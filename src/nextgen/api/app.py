"""Small versioned ASGI application. No worker execution or provider logic."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import logging
import re
import uuid
from urllib.parse import parse_qs, urlsplit

from src.nextgen.async_io import blocking
from src.nextgen.api.auth import (ApiError, COOKIE, Sessions, bearer, matches, public_origin, check_origin, webhook_key)
from src.nextgen.configuration import ConfigurationStore
from src.nextgen.configuration_schema import ConfigurationError, ConfigurationConflict, ConfigurationSnapshot, for_operation, field_definitions
from src.nextgen.cancellation import CancellationError
from src.nextgen.diagnostics import configure_logging, event, log_history
from src.nextgen.history import encode_details
from src.nextgen.maintenance import MaintenanceGate, MaintenanceError, MaintenancePending, MaintenanceBusy
from src.nextgen.messages import MessageCatalog
from src.nextgen.dashboard.assets import load_assets, CSP as DASHBOARD_CSP
from src.nextgen.dashboard.presentation import HANDLERS
from src.nextgen.secrets import SecretStore
from src.nextgen.storage.job_queue import JobQueue, QueueUnavailable
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable, ActionNotFound
from src.nextgen.storage.migrations import LATEST_VERSION
from src.nextgen.storage.sqlite import accept_event_and_job

PREFIX='/api/v1'
MAX_BODY=65536
CATALOG=MessageCatalog(handlers=HANDLERS)


def object_json(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ApiError(400,'API_REQUEST_INVALID')
            result[k]=v
        return result
    try:
        result=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
                          parse_constant=lambda value:(_ for _ in ()).throw(ValueError()))
        if type(result) is not dict:raise ValueError()
        return result
    except (UnicodeError,ValueError,TypeError,RecursionError):raise ApiError(400,'API_REQUEST_INVALID') from None


def exact(body,keys):
    if set(body)!=set(keys):raise ApiError(400,'API_REQUEST_INVALID')


def page_number(query,key,default,lower,upper):
    values=query.get(key,[str(default)])
    if len(values)!=1 or not re.fullmatch('[0-9]{1,19}',values[0]):raise ApiError(400,'API_REQUEST_INVALID')
    value=int(values[0])
    if not lower<=value<=upper:raise ApiError(400,'API_REQUEST_INVALID')
    return value


def validate_secret_fields(kind,body,fields):
    if any(type(body[k]) is not str or len(body[k])>4096 for k in fields):raise ApiError(400,'API_REQUEST_INVALID')
    try:
        if kind=='access':
            from src.nextgen.secrets import _access_values
            _access_values(body['webhook_token'],body['management_token'])
        elif kind=='qbittorrent':
            from src.nextgen.acquisition.settings import DownloadCredentials
            if body['username'] or body['password']:DownloadCredentials(body['username'],body['password'])
        elif body['api_key']:
            from src.nextgen.providers.http import Credentials
            Credentials(body['api_key'])
    except (ValueError,RuntimeError):raise ApiError(400,'API_REQUEST_INVALID') from None


def normalize_webhook(body):
    def one(keys,*,lower=False):
        values=[body[k] for k in keys if k in body]
        if not values or any(type(v) is not str or not v.strip() for v in values):raise ApiError(400,'API_WEBHOOK_INVALID')
        values=[v.strip().lower() if lower else v.strip() for v in values]
        if len(set(values))!=1:raise ApiError(400,'API_WEBHOOK_INVALID')
        return values[0]
    title=one(('release_name','torrentName','name'))
    digest=one(('torrent_infohash','info_hash','torrentHash','hash'),lower=True)
    if (len(title.encode('utf-8'))>1024 or any(ord(c)<32 or ord(c)==127 for c in title)
            or not re.fullmatch('[a-f0-9]{40}',digest)):raise ApiError(400,'API_WEBHOOK_INVALID')
    # Persist ONLY the normalized release declaration; no credential, URL,
    # source label, raw payload or self-declared verified identity is forwarded.
    return json.dumps({'release_name':title,'torrent_infohash':digest},sort_keys=True).encode()


class Application:
    def __init__(self,directory,*,origin=None,secrets=None,sessions=None):
        self.store=ConfigurationStore(directory);self.startup=self.store.read()
        self.secrets=SecretStore(directory) if secrets is None else secrets
        host=self.startup.value('api.host');port=self.startup.value('api.port')
        authority=('['+host+']' if ':' in host else host)+':'+str(port)
        self.origin=public_origin(origin or 'http://'+authority)
        self.authorities={urlsplit(self.origin).netloc,authority.lower()}
        self.sessions=sessions or Sessions()
        self.assets=load_assets()
        self.pool=ThreadPoolExecutor(max_workers=8,thread_name_prefix='nextgen-api')
        self.slots=asyncio.Semaphore(8)
        self.logger=configure_logging(self.startup.logging_settings(),'api',logger=logging.Logger('nextgen.api.requests'))
        self.closed=False

    def close(self):
        self.closed=True
        self.pool.shutdown(wait=True,cancel_futures=False)

    async def _body(self,receive):
        chunks=[];size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':raise ApiError(400,'API_REQUEST_INVALID')
            if message['type']!='http.request':raise ApiError(400,'API_REQUEST_INVALID')
            chunk=message.get('body',b'')
            if type(chunk) is not bytes:raise ApiError(400,'API_REQUEST_INVALID')
            size+=len(chunk)
            if size>MAX_BODY:raise ApiError(413,'API_BODY_TOO_LARGE')
            if chunk:chunks.append(chunk)
            if not message.get('more_body',False):return b''.join(chunks)

    async def __call__(self,scope,receive,send):
        if scope['type']=='lifespan':
            while True:
                message=await receive()
                if message['type']=='lifespan.startup':await send({'type':'lifespan.startup.complete'})
                elif message['type']=='lifespan.shutdown':
                    await blocking(self.close)
                    await send({'type':'lifespan.shutdown.complete'});return
            return
        if scope['type']=='websocket':
            await send({'type':'websocket.close','code':1008});return
        if scope['type']!='http':return
        request_id=uuid.uuid4().hex;extra=[]
        try:
            if self.closed:raise ApiError(503,'API_UNAVAILABLE')
            headers={}
            raw_headers=scope.get('headers',[])
            if len(raw_headers)>100 or sum(len(k)+len(v) for k,v in raw_headers)>16384:raise ApiError(400,'API_REQUEST_INVALID')
            for raw_key,raw_value in raw_headers:
                key=raw_key.decode('ascii').lower();value=raw_value.decode('latin-1')
                if key in headers or any(ord(c)<32 or ord(c)==127 for c in value):raise ApiError(400,'API_REQUEST_INVALID')
                headers[key]=value
            if headers.get('host','').lower() not in self.authorities:raise ApiError(400,'API_ORIGIN_INVALID')
            if 'content-encoding' in headers:raise ApiError(415,'API_MEDIA_TYPE_INVALID')
            if headers.get('transfer-encoding') not in (None,'chunked') or 'transfer-encoding' in headers and 'content-length' in headers:raise ApiError(400,'API_REQUEST_INVALID')
            length=headers.get('content-length')
            if length is not None and (not re.fullmatch('[0-9]{1,8}',length) or int(length)>MAX_BODY):raise ApiError(413,'API_BODY_TOO_LARGE')
            raw_query=scope.get('query_string',b'')
            path=scope.get('path','')
            if len(raw_query)>2048 or len(path)>512 or '%' in path or not (path.startswith(PREFIX+'/') or path in self.assets):raise ApiError(404,'API_ROUTE_NOT_FOUND')
            if scope.get('raw_path',path.encode('utf-8'))!=path.encode('utf-8'):raise ApiError(400,'API_REQUEST_INVALID')
            query=parse_qs(raw_query.decode('ascii'),keep_blank_values=True,max_num_fields=16,strict_parsing=True) if raw_query else {}
            raw=await asyncio.wait_for(self._body(receive),timeout=15)
            if length is not None and len(raw)!=int(length):raise ApiError(400,'API_REQUEST_INVALID')
            if raw and headers.get('content-type','').lower() not in ('application/json','application/json; charset=utf-8'):raise ApiError(415,'API_MEDIA_TYPE_INVALID')
            body=object_json(raw) if raw else {}
            if scope['method']=='GET' and raw:raise ApiError(400,'API_REQUEST_INVALID')
            if path in self.assets:
                if scope['method']!='GET':raise ApiError(405,'API_METHOD_INVALID')
                if query or raw:raise ApiError(400,'API_REQUEST_INVALID')
                mime,content=self.assets[path]
                await send({'type':'http.response.start','status':200,'headers':[
                    (b'content-type',mime.encode()),(b'content-length',str(len(content)).encode()),
                    (b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff'),
                    (b'referrer-policy',b'no-referrer'),(b'content-security-policy',DASHBOARD_CSP.encode()),
                    (b'x-request-id',request_id.encode())]})
                await send({'type':'http.response.body','body':content})
                return
            peer=str((scope.get('client') or ('local',0))[0])
            async with self.slots:
                status,data,extra=await blocking(self._dispatch,scope['method'],path,headers,query,body,peer,executor=self.pool)
            result={'api_version':'v1','request_id':request_id,'data':data}
        except asyncio.TimeoutError:
            status=408;result={'api_version':'v1','request_id':request_id,'error':CATALOG.reason('API_REQUEST_INVALID')}
        except ApiError as exc:
            status=exc.status;result={'api_version':'v1','request_id':request_id,'error':CATALOG.reason(exc.reason_code)}
            event(self.logger,logging.WARNING,'API_REQUEST_REJECTED',component='api',reason_code=exc.reason_code)
        except (UnicodeError,ValueError):
            status=400;result={'api_version':'v1','request_id':request_id,'error':CATALOG.reason('API_REQUEST_INVALID')}
        except Exception:
            # No request URL, header, body, exception text or ASGI scope is logged.
            status=503;result={'api_version':'v1','request_id':request_id,'error':CATALOG.reason('API_UNAVAILABLE')}
            event(self.logger,logging.ERROR,'API_REQUEST_REJECTED',component='api',reason_code='API_UNAVAILABLE')
        encoded=json.dumps(result,allow_nan=False,separators=(',',':')).encode()
        response_headers=[(b'content-type',b'application/json; charset=utf-8'),(b'cache-control',b'no-store'),
            (b'x-content-type-options',b'nosniff'),(b'referrer-policy',b'no-referrer'),
            (b'content-security-policy',b"default-src 'none'; frame-ancestors 'none'"),
            (b'x-request-id',request_id.encode()),(b'content-length',str(len(encoded)).encode()),*extra]
        if status==401:response_headers.append((b'www-authenticate',b'Bearer realm="anime-discovery"'))
        if status in (429,503):response_headers.append((b'retry-after',b'60'))
        await send({'type':'http.response.start','status':status,'headers':response_headers})
        await send({'type':'http.response.body','body':encoded})

    def _dispatch(self,method,path,headers,query,body,peer):
        try:return self._route(method,path,headers,query,body,peer)
        except ApiError:raise
        except ActionNotFound as exc:raise ApiError(404,exc.reason_code) from None
        except ActionUnavailable as exc:raise ApiError(409,exc.reason_code) from None
        except ConfigurationConflict as exc:raise ApiError(409,exc.reason_code) from None
        except ConfigurationError as exc:raise ApiError(503,exc.reason_code) from None
        except (MaintenancePending,MaintenanceBusy,MaintenanceError) as exc:raise ApiError(503,exc.reason_code) from None
        except QueueUnavailable as exc:raise ApiError(503,exc.reason_code) from None
        except CancellationError as exc:raise ApiError(409,exc.reason_code) from None

    def _route(self,method,path,headers,query,body,peer):
        access=self.secrets.access_credentials()  # Fresh, fail closed. No fallback.
        if path==PREFIX+'/webhook':
            if method!='POST':raise ApiError(405,'API_METHOD_INVALID')
            if set(query)-{'token'}:raise ApiError(400,'API_REQUEST_INVALID')
            webhook_key(headers,query,body,access.webhook_token)
            normalized=normalize_webhook(body)
            if any(key and key.encode() in normalized for key in (access.webhook_token,access.management_token)):raise ApiError(400,'API_WEBHOOK_INVALID')
            desired=self.store.read();configuration=for_operation(desired,self.startup,component='api')
            configure_logging(configuration.logging_settings(),'api',logger=self.logger)
            with MaintenanceGate(configuration.value('storage.database_path')).operation():
                with JobQueue(configuration.value('storage.database_path')).connection() as db:
                    event_id,job_id=accept_event_and_job(db,'autobrr',normalized,kind='IDENTIFY_ANIME',payload={},component='api',logger=self.logger)
            return 202,{'event_id':event_id,'job_id':job_id},[]
        check_origin(headers,self.origin)
        if not access.management_token:raise ApiError(503,'API_AUTH_UNCONFIGURED')
        if path==PREFIX+'/auth/session' and method=='POST':
            if query:raise ApiError(400,'API_REQUEST_INVALID')
            check_origin(headers,self.origin,required=True)
            self.sessions.attempt(peer);exact(body,('token',))
            if not matches(body['token'],access.management_token):raise ApiError(401,'API_AUTH_REQUIRED')
            if 'authorization' in headers and not matches(bearer(headers),access.management_token):raise ApiError(401,'API_AUTH_REQUIRED')
            token,csrf=self.sessions.create(access.management_token)
            event(self.logger,logging.INFO,'API_SESSION_CREATED',component='api')
            return 201,{'csrf_token':csrf,'expires_in':self.sessions.ttl},[(b'set-cookie',self._cookie(token).encode())]
        supplied=bearer(headers)
        digest=session=None
        if supplied is not None:
            if not matches(supplied,access.management_token):raise ApiError(401,'API_AUTH_REQUIRED')
        else:
            check_origin(headers,self.origin,required=method!='GET')
            digest,session=self.sessions.require(headers,access.management_token,mutation=method!='GET')
        if path==PREFIX+'/auth/session':
            if query:raise ApiError(400,'API_REQUEST_INVALID')
            if method=='GET':return 200,{'authenticated':True,'csrf_token':None if session is None else session.csrf},[]
            if method=='DELETE':
                exact(body,())
                if digest is not None:self.sessions.remove(digest)
                event(self.logger,logging.INFO,'API_SESSION_CLOSED',component='api')
                return 200,{'signed_out':True},[(b'set-cookie',self._cookie('',clear=True).encode())]
            raise ApiError(405,'API_METHOD_INVALID')
        if 'token' in query:raise ApiError(400,'API_REQUEST_INVALID')
        desired=self.store.read();configuration=for_operation(desired,self.startup,component='api')
        configure_logging(configuration.logging_settings(),'api',logger=self.logger)
        # Authentication and CSRF above apply equally to all explicit actions.
        # HTTP performs local admission only; network/filesystem cleanup is queued.
        with MaintenanceGate(configuration.value('storage.database_path')).operation():
            match=re.fullmatch(PREFIX+r'/jobs/([1-9][0-9]{0,18})/(keep|reject|cancel|cleanup|cancellation)',path)
            if match:
                if query:raise ApiError(400,'API_REQUEST_INVALID')
                job=int(match[1]);action=match[2]
                if job>(1<<63)-1:raise ApiError(400,'API_REQUEST_INVALID')
                actions=ManagementActions(configuration.value('storage.database_path'))
                if action=='cancellation' and method=='GET':
                    with actions.queue.connection() as db:
                        db.execute('BEGIN')
                        row=db.execute('SELECT job_id,event_id,created_by_job_id,kind,state,activity_code,attempt_count,last_reason_code FROM jobs WHERE job_id=?',(job,)).fetchone()
                        if row is None:raise ApiError(404,'API_ROUTE_NOT_FOUND')
                        data=self._job(actions.queue,db,row)
                        return 200,{**data['cancellation'],'actions':data['actions']},[]
                if action in ('keep','reject','cancel','cleanup') and method=='POST':
                    exact(body,())
                    status,data,records=actions.submit(job,action)
                    for record in records:log_history(self.logger,record)
                    return status,data,([] if 'status_url' not in data else [(b'location',data['status_url'].encode())])
                raise ApiError(405,'API_METHOD_INVALID')
            single=re.fullmatch(PREFIX+r'/jobs/([1-9][0-9]{0,18})',path)
            if single:
                if method!='GET':raise ApiError(405,'API_METHOD_INVALID')
                if query:raise ApiError(400,'API_REQUEST_INVALID')
                job=int(single[1])
                if job>(1<<63)-1:raise ApiError(400,'API_REQUEST_INVALID')
                queue=JobQueue(configuration.value('storage.database_path'))
                with queue.connection() as db:
                    db.execute('BEGIN')
                    row=db.execute('SELECT job_id,event_id,created_by_job_id,kind,state,activity_code,attempt_count,last_reason_code FROM jobs WHERE job_id=?',(job,)).fetchone()
                    if row is None:raise ApiError(404,'API_ROUTE_NOT_FOUND')
                    return 200,self._job(queue,db,row),[]
            if path==PREFIX+'/' and method=='GET':
                if query:raise ApiError(400,'API_REQUEST_INVALID')
                return 200,{'version':'v1','resources':['health','settings','credentials','intake','jobs','auth/session','webhook','missing-episodes']},[]

            if path==PREFIX+'/missing-episodes':
                if method!='GET':raise ApiError(405,'API_METHOD_INVALID')
                if set(query) not in (set(),{'plan_id'}):raise ApiError(400,'API_REQUEST_INVALID')
                plan_id=page_number(query,'plan_id',None,1,(1<<63)-1) if query else None
                with JobQueue(configuration.value('storage.database_path')).connection() as db:
                    db.execute('BEGIN')
                    if plan_id is None:
                        plans=db.execute('SELECT p.plan_id,p.anidb_id,p.tvdb_series_id,p.tvdb_season,'
                            'p.anchor_episode,p.backfill_count,p.following_count,a.title '
                            'FROM trial_plans p JOIN identified_anime a ON a.anidb_id=p.anidb_id '
                            'ORDER BY p.plan_id DESC LIMIT 50').fetchall()
                        return 200,{'plans':[{'plan_id':p[0],'anidb_id':p[1],
                            'tvdb_series_id':p[2],'tvdb_season':p[3],'anchor_episode':p[4],
                            'backfill_count':p[5],'following_count':p[6],'anime_title':p[7]}
                            for p in plans],'plan_limit':50},[]
                    plan=db.execute('SELECT anidb_id,tvdb_series_id,tvdb_season,anchor_episode,backfill_count,following_count '
                                    'FROM trial_plans WHERE plan_id=?',(plan_id,)).fetchone()
                    if plan is None:raise ApiError(404,'API_ROUTE_NOT_FOUND')
                    from src.nextgen.trial_policy import Window
                    positions=Window(plan[4],plan[5]).episodes(plan[3])
                    reserved={x[0] for x in db.execute('SELECT tvdb_episode FROM episode_reservations WHERE '
                                "tvdb_series_id=? AND tvdb_season=? AND tvdb_order='official'",(plan[1],plan[2]))}
                    recorded={x[0]:(x[1],x[2],x[3]) for x in db.execute(
                        'SELECT tvdb_episode,status,candidate_count,searched_at_ms FROM missing_episode_searches '
                        'WHERE plan_id=?',(plan_id,))}
                    rows=[{'tvdb_episode':n,'status':'RESERVED' if n in reserved else
                           recorded[n][0] if n in recorded else 'NOT_SEARCHED',
                           'candidate_count':recorded[n][1] if n in recorded else 0}
                          for n in positions]
                    candidates=[{'tvdb_episode':e,'info_hash':h,'release_name':title} for e,h,title in db.execute(
                        'SELECT tvdb_episode,info_hash,release_name FROM missing_episode_candidates '
                        'WHERE plan_id=? ORDER BY tvdb_episode,info_hash LIMIT 100',(plan_id,))]
                    return 200,{'plan_id':plan_id,'anidb_id':plan[0],'tvdb_series_id':plan[1],
                        'tvdb_season':plan[2],'positions':rows,'candidates':candidates,
                        'candidate_limit':100,'candidate_note':'Unverified search hints; no automatic download'},[]
            if path==PREFIX+'/intake':
                if method!='GET':raise ApiError(405,'API_METHOD_INVALID')
                return 200,self._intake(configuration,query),[]
            if path==PREFIX+'/health' and method=='GET':
                if query:raise ApiError(400,'API_REQUEST_INVALID')
                with JobQueue(configuration.value('storage.database_path')).connection():pass
                return 200,{'ready':True,'database_schema_version':LATEST_VERSION},[]
            if path==PREFIX+'/settings':
                if query:raise ApiError(400,'API_REQUEST_INVALID')
                if method=='GET':return 200,{'desired':desired.to_document(),
                    'effective':ConfigurationSnapshot(configuration.desired_revision,configuration.values).to_document(),
                    'pending_restart_fields':configuration.pending_restart_fields,'fields':field_definitions()},[]
                if method=='PATCH':
                    exact(body,('expected_revision','settings'))
                    try:result=self.store.update(body['settings'],expected_revision=body['expected_revision'])
                    except ConfigurationConflict:raise
                    except ConfigurationError as exc:raise ApiError(400,exc.reason_code) from None
                    return 200,{'configuration':result.snapshot.to_document(),'saved':result.saved,
                        'durability_confirmed':result.durability_confirmed,'reason_code':result.reason_code,
                        'restart_fields':result.restart_fields,'restart_components':result.restart_components},[]
                raise ApiError(405,'API_METHOD_INVALID')
            if path==PREFIX+'/credentials' and method=='GET':
                if query:raise ApiError(400,'API_REQUEST_INVALID')
                return 200,asdict(self.secrets.status()),[]
            secret_match=re.fullmatch(PREFIX+r'/credentials/(tvdb|qbittorrent|access|sonarr|jellyfin|prowlarr)',path)
            if secret_match:
                if query:raise ApiError(400,'API_REQUEST_INVALID')
                if method!='PATCH':raise ApiError(405,'API_METHOD_INVALID')
                kind=secret_match[1]
                fields={'tvdb':('api_key',),'qbittorrent':('username','password'),'access':('webhook_token','management_token'),'sonarr':('api_key',),'jellyfin':('api_key',),'prowlarr':('api_key',)}[kind]
                exact(body,('expected_revision',*fields))
                validate_secret_fields(kind,body,fields)
                callback={'tvdb':self.secrets.update_tvdb_api_key,'qbittorrent':self.secrets.update_qbittorrent_credentials,'access':self.secrets.update_access_tokens,'sonarr':self.secrets.update_sonarr_api_key,'jellyfin':self.secrets.update_jellyfin_api_key,'prowlarr':self.secrets.update_prowlarr_api_key}[kind]
                result=callback(*(body[k] for k in fields),expected_revision=body['expected_revision'])
                if result.saved:event(self.logger,logging.INFO,'API_CREDENTIALS_UPDATED',component='api')
                return 200,{'status':asdict(result.status),'saved':result.saved,'durability_confirmed':result.durability_confirmed,'reason_code':result.reason_code},[]
            if method=='GET' and (path==PREFIX+'/jobs' or re.fullmatch(PREFIX+r'/jobs/[1-9][0-9]{0,18}/history',path)):
                return 200,self._jobs(configuration,path,query),[]
        if path in (PREFIX+'/',PREFIX+'/health',PREFIX+'/credentials',PREFIX+'/jobs',PREFIX+'/missing-episodes') or re.fullmatch(PREFIX+r'/jobs/[1-9][0-9]{0,18}/history',path):raise ApiError(405,'API_METHOD_INVALID')
        raise ApiError(404,'API_ROUTE_NOT_FOUND')

    def _cookie(self,token,*,clear=False):
        return COOKIE+'='+token+'; Path=/; HttpOnly; SameSite=Strict; Max-Age='+('0' if clear else str(self.sessions.ttl))+('; Secure' if self.origin.startswith('https://') else '')

    def _jobs(self,configuration,path,query):
        if set(query)-{'after_id','before_id','limit'} or 'after_id' in query and 'before_id' in query:raise ApiError(400,'API_REQUEST_INVALID')
        after=page_number(query,'after_id',0,0,(1<<63)-1);limit=page_number(query,'limit',50,1,100)
        queue=JobQueue(configuration.value('storage.database_path'))
        history=path.endswith('/history')
        with queue.connection() as db:
            db.execute('BEGIN')
            if history:
                if 'before_id' in query:raise ApiError(400,'API_REQUEST_INVALID')
                job=int(path.split('/')[-2])
                if job>(1<<63)-1:raise ApiError(400,'API_REQUEST_INVALID')
                if db.execute('SELECT 1 FROM jobs WHERE job_id=?',(job,)).fetchone() is None:raise ApiError(404,'API_ROUTE_NOT_FOUND')
                rows=db.execute('SELECT history_id,occurred_at_ms,event_code,reason_code,component,details_json,handler_code,handler_label,invocation_id '
                    'FROM job_history WHERE job_id=? AND history_id>? ORDER BY history_id LIMIT ?',(job,after,limit+1)).fetchall()
                items=[]
                for row in rows[:limit]:
                    try:details=json.loads(encode_details(json.loads(row[5] or '{}')))
                    except (ValueError,TypeError):details={}
                    items.append({'history_id':row[0],'occurred_at_ms':row[1],'event':CATALOG.event(row[2]),
                        'reason':None if row[3] is None else CATALOG.reason(row[3]),'component':row[4],'details':details,
                        'handler':None if row[6] is None else CATALOG.handler(row[6],recorded_label=row[7]),'invocation_id':row[8]})
            else:
                newest='before_id' in query
                cursor=page_number(query,'before_id',(1<<63)-1,1,(1<<63)-1) if newest else after
                ordering='job_id<? ORDER BY job_id DESC' if newest else 'job_id>? ORDER BY job_id'
                rows=db.execute('SELECT job_id,event_id,created_by_job_id,kind,state,activity_code,attempt_count,last_reason_code '
                                'FROM jobs WHERE '+ordering+' LIMIT ?',(cursor,limit+1)).fetchall()
                items=[self._job(queue,db,r) for r in rows[:limit]]
                if newest:return {'items':items,'next_before_id':rows[limit-1][0] if len(rows)>limit else None}
        return {'items':items,'next_after_id':rows[limit-1][0] if len(rows)>limit else None}

    def _intake(self,configuration,query):
        if set(query)-{'before_id','limit'}:raise ApiError(400,'API_REQUEST_INVALID')
        before=page_number(query,'before_id',(1<<63)-1,1,(1<<63)-1)
        limit=page_number(query,'limit',50,1,100)
        queue=JobQueue(configuration.value('storage.database_path'))
        with queue.connection() as db:
            db.execute('BEGIN')
            rows=db.execute('SELECT o.operation_id,j.job_id,j.event_id,j.created_by_job_id,j.kind,j.state,'
                'j.activity_code,j.attempt_count,j.last_reason_code FROM job_operations o '
                'JOIN jobs j ON j.job_id=(SELECT MAX(m.job_id) FROM job_operation_members m WHERE m.operation_id=o.operation_id) '
                'WHERE o.operation_id<? AND NOT EXISTS (SELECT 1 FROM management_actions a WHERE a.job_id=j.job_id) '
                'ORDER BY o.operation_id DESC LIMIT ?',(before,limit+1)).fetchall()
            items=[self._job(queue,db,row[1:]) for row in rows[:limit]]
        return {'items':items,'next_before_id':rows[limit-1][0] if len(rows)>limit else None}

    def _job(self,queue,db,row):
        op=db.execute('SELECT o.operation_id,o.state,o.cleanup_state,o.reason_code FROM job_operations o JOIN job_operation_members m USING(operation_id) WHERE m.job_id=?',(row[0],)).fetchone()
        actions=ManagementActions(queue.database).capabilities(db,row[0])
        context=db.execute('SELECT j.created_at_ms,e.received_at_ms,CASE WHEN length(e.raw_body)<=65536 THEN e.raw_body ELSE NULL END '
                           'FROM jobs j LEFT JOIN incoming_events e ON e.event_id=j.event_id WHERE j.job_id=?',(row[0],)).fetchone()
        release=None
        try:
            declaration=json.loads(context[2] or b'{}')
            value=declaration.get('release_name') if type(declaration) is dict else None
            if type(value) is str and len(value.encode('utf-8'))<=1024:release=value
        except (ValueError,UnicodeError,TypeError,RecursionError):pass
        titles=db.execute('SELECT CASE WHEN length(CAST(a.title AS BLOB))<=1024 THEN a.title ELSE NULL END '
                          'FROM identity_results r JOIN identified_anime a USING(anidb_id) WHERE r.event_id=? LIMIT 2',(row[1],)).fetchall()
        return {'job_id':row[0],'event_id':row[1],'created_by_job_id':row[2],'kind':row[3],'state':row[4],
                'is_management_action':db.execute('SELECT 1 FROM management_actions WHERE job_id=?',(row[0],)).fetchone() is not None,
                'label':CATALOG.handler(row[3]),'created_at_ms':context[0],'received_at_ms':context[1],
                'release_name':release,'anime_title':titles[0][0] if len(titles)==1 else None,
                'acquisition_status':CATALOG.state('acquisition',op[1]),
                'status':CATALOG.job_status(row[4],row[5]),'attempt_count':row[6],
                'reason':None if row[7] is None else CATALOG.reason(row[7]),'actions':actions,
                'cancellation':{'operation_id':op[0],'state':op[1],'cleanup_state':op[2],'reason_code':op[3],
                                'can_cancel':actions['cancel']['enabled'],'can_cleanup':actions['cleanup']['enabled']}}
