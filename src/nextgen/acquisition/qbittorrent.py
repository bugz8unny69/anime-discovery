"""Bounded session-local qBittorrent 4.5/4.6 and 5.x transport. No automatic retries."""
from http.cookies import SimpleCookie
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from src.nextgen.acquisition.metadata import TorrentFile, parse_metainfo
from src.nextgen.acquisition.settings import DownloadOptions, DownloadCredentials
from src.nextgen.acquisition.submission import (Observation, SendPermit, ClientUnavailable, ClientInvalid,
                                               ClientAuthenticationFailed, ClientUnsupported)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


def _json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ClientInvalid()
            result[key]=value
        return result
    try:return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
                          parse_constant=lambda value:(_ for _ in ()).throw(ClientInvalid()))
    except (ValueError,UnicodeError,RecursionError):raise ClientInvalid() from None


def _text(value,limit):
    if type(value) is not str or len(value)>limit or any(ord(c)<32 or ord(c)==127 for c in value):raise ClientInvalid()
    return value


class Client:
    def __init__(self,options,credentials,*,transport=None):
        if type(options) is not DownloadOptions or type(credentials) is not DownloadCredentials:raise ValueError('validated client context required')
        self.options,self._credentials=options,credentials
        self._sid=None
        self.major=None
        opener=urllib.request.build_opener(_NoRedirect(),urllib.request.ProxyHandler({}))
        self._transport=transport or (lambda request,timeout:opener.open(request,timeout=timeout))

    def _request(self,path,*,query=None,form=None,body=None,content_type=None,limit=3145728):
        if path not in ('auth/login','app/version','app/webapiVersion','torrents/info','torrents/files','torrents/add','torrents/properties','torrents/filePrio','torrents/start','torrents/resume','torrents/stop','torrents/pause','torrents/delete'):raise ValueError('unsupported client operation')
        url=self.options.base_url+'/api/v2/'+path
        if query:url+='?'+urllib.parse.urlencode(query)
        headers={'User-Agent':'AnimeDiscoveryNextGen/1','Referer':self.options.base_url+'/','Accept':'application/json'}
        if self._sid:headers['Cookie']='SID='+self._sid
        if form is not None:
            body=urllib.parse.urlencode(form).encode()
            content_type='application/x-www-form-urlencoded'
        if content_type:headers['Content-Type']=content_type
        request=urllib.request.Request(url,data=body,headers=headers,method='POST' if body is not None else 'GET')
        try:
            with self._transport(request,self.options.timeout_seconds) as response:
                if response.getcode() in (401,403):raise ClientAuthenticationFailed()
                if response.getcode()!=200:raise ClientUnavailable()
                raw=response.read(limit+1)
                if type(raw) is not bytes or len(raw)>limit:raise ClientInvalid()
                return raw,response.headers
        except urllib.error.HTTPError as exc:
            code=exc.code
            exc.close()
            if code in (401,403):raise ClientAuthenticationFailed() from None
            raise ClientUnavailable() from None
        except (OSError,TimeoutError,urllib.error.URLError):raise ClientUnavailable() from None

    def login(self):
        self._sid=None
        self.major=None
        raw,headers=self._request('auth/login',form={'username':self._credentials.username,'password':self._credentials.password},limit=4096)
        if raw.strip()!=b'Ok.':raise ClientAuthenticationFailed()
        cookies=headers.get_all('Set-Cookie',[])
        if len(cookies)>10 or any(len(v)>4096 for v in cookies):raise ClientInvalid()
        found=[]
        for value in cookies:
            try:
                parsed=SimpleCookie();parsed.load(value)
                if 'SID' in parsed:found.append(parsed['SID'].value)
            except Exception:raise ClientInvalid() from None
        if len(found)!=1 or not re.fullmatch('[A-Za-z0-9_-]{8,256}',found[0]):raise ClientAuthenticationFailed()
        self._sid=found[0]
        version,_=self._request('app/version',limit=128)
        api,_=self._request('app/webapiVersion',limit=128)
        try:
            match=re.fullmatch(r'v?(4|5)\.([0-9]+)\.[0-9]+',version.decode().strip())
            api_match=re.fullmatch(r'2\.([0-9]+)(?:\.[0-9]+)?',api.decode().strip())
            if not match or not api_match or int(api_match[1])<8:raise ClientUnsupported()
            if match[1]=='4' and int(match[2]) not in (5,6):raise ClientUnsupported()
            self.major=int(match[1])
        except UnicodeError:raise ClientUnsupported() from None

    def inspect(self,expected_hash):
        if not self._sid or self.major is None:raise ClientAuthenticationFailed()
        from src.nextgen.acquisition.metadata import infohash
        expected_hash=infohash(expected_hash)
        raw,_=self._request('torrents/info',query={'hashes':expected_hash,'limit':2})
        rows=_json(raw)
        if type(rows) is not list or len(rows)>1:raise ClientInvalid()
        if not rows:return None
        row=rows[0]
        if type(row) is not dict or row.get('hash')!=expected_hash or type(row.get('auto_tmm')) is not bool:raise ClientInvalid()
        tags=_text(row.get('tags'),8192).split(',') if row.get('tags') else []
        tags=tuple(t.strip() for t in tags if t.strip())
        if len(tags)>128 or any(len(t)>128 for t in tags):raise ClientInvalid()
        state=_text(row.get('state'),64)
        save_path=_text(row.get('save_path'),4096)
        category=_text(row.get('category'),256)
        raw,_=self._request('torrents/files',query={'hash':expected_hash})
        files=_json(raw)
        if type(files) is not list or len(files)>10000:raise ClientInvalid()
        result=[]
        try:
            for item in files:
                if type(item) is not dict:raise ClientInvalid()
                result.append(TorrentFile(item.get('index'),item.get('name'),item.get('size')))
            result.sort(key=lambda f:f.index)
            if [f.index for f in result]!=list(range(len(result))):raise ClientInvalid()
        except ValueError:raise ClientInvalid() from None
        return Observation(expected_hash,state,save_path,category,tags,row['auto_tmm'],tuple(result))

    def add_stopped(self,raw,intent,permit):
        if not self._sid or self.major is None:raise ClientAuthenticationFailed()
        if type(permit) is not SendPermit or intent.options!=self.options or intent.api_major!=self.major:raise ClientInvalid()
        manifest=parse_metainfo(raw,intent.plan.manifest.info_hash)
        if manifest!=intent.plan.manifest:raise ClientInvalid()
        boundary='ad'+uuid.uuid4().hex
        while boundary.encode() in raw:boundary='ad'+uuid.uuid4().hex
        fields={'savepath':self.options.download_root,'category':self.options.category,'tags':'ad-'+intent.plan.marker,
                'stopped' if self.major==5 else 'paused':'true','autoTMM':'false','useDownloadPath':'false',
                'skip_checking':'false','contentLayout':'Original'}
        chunks=[]
        for key,value in fields.items():
            chunks.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
        chunks.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="torrents"; filename="source.torrent"\r\nContent-Type: application/x-bittorrent\r\n\r\n').encode()+raw+b'\r\n')
        chunks.append(('--'+boundary+'--\r\n').encode())
        # Consume before the single transport call. Never retry, even on HTTP error.
        permit.take(intent)
        self._request('torrents/add',body=b''.join(chunks),content_type='multipart/form-data; boundary='+boundary,limit=4096)

    def inspect_transfer(self,expected_hash):
        from src.nextgen.acquisition.transfers import TransferSnapshot, SnapshotChanged
        before=self.inspect(expected_hash)
        if before is None:return None
        raw,_=self._request('torrents/files',query={'hash':expected_hash})
        files=_json(raw)
        if type(files) is not list or len(files)!=len(before.files):raise ClientInvalid()
        rows=[]
        try:
            for row in files:
                if type(row) is not dict:raise ClientInvalid()
                item=TorrentFile(row.get('index'),row.get('name'),row.get('size'))
                ranges=row.get('piece_range')
                if type(ranges) is not list or len(ranges)!=2:raise ClientInvalid()
                rows.append((item,row.get('priority'),row.get('progress'),tuple(ranges)))
            rows.sort(key=lambda r:r[0].index)
        except ValueError:raise ClientInvalid() from None
        if tuple(r[0] for r in rows)!=before.files:raise SnapshotChanged()
        raw,_=self._request('torrents/properties',query={'hash':expected_hash})
        properties=_json(raw)
        if type(properties) is not dict:raise ClientInvalid()
        after=self.inspect(expected_hash)
        if before!=after:raise SnapshotChanged()
        return TransferSnapshot(after,tuple(r[1] for r in rows),tuple(r[2] for r in rows),
                                properties.get('piece_size'),tuple(r[3] for r in rows))

    def apply_selection(self,intent,fingerprint,permit,action):
        if not self._sid or self.major not in (4,5):raise ClientAuthenticationFailed()
        from src.nextgen.acquisition.transfers import (TransferPermit, TransferConflict, STOPPED, verify_snapshot, selection_fingerprint)
        if type(permit) is not TransferPermit or self.options!=intent.options:raise ClientInvalid()
        snapshot=self.inspect_transfer(intent.plan.manifest.info_hash)
        if snapshot is None:raise TransferConflict()
        verify_snapshot(intent,snapshot)
        if selection_fingerprint(intent,snapshot.piece_size)!=fingerprint:raise TransferConflict()
        if snapshot.observation.state not in STOPPED:raise TransferConflict()
        selected=intent.plan.manifest.selected_index
        if action=='skip':indices=[i for i in range(len(snapshot.priorities)) if i!=selected];priority=0
        elif action=='wanted':indices=[selected];priority=1
        else:raise TransferConflict()
        permit.take(fingerprint,action)
        if indices:self._request('torrents/filePrio',form={'hash':intent.plan.manifest.info_hash,
            'id':'|'.join(map(str,indices)),'priority':priority},limit=4096)

    def start_selected(self,intent,fingerprint,permit):
        if not self._sid or self.major not in (4,5):raise ClientAuthenticationFailed()
        from src.nextgen.acquisition.transfers import (TransferPermit, TransferConflict, STOPPED, verify_snapshot, exact_selection, selection_fingerprint)
        if type(permit) is not TransferPermit or self.options!=intent.options:raise ClientInvalid()
        snapshot=self.inspect_transfer(intent.plan.manifest.info_hash)
        if snapshot is None:raise TransferConflict()
        verify_snapshot(intent,snapshot)
        if selection_fingerprint(intent,snapshot.piece_size)!=fingerprint:raise TransferConflict()
        if snapshot.observation.state not in STOPPED or not exact_selection(intent,snapshot):raise TransferConflict()
        permit.take(fingerprint,'start')
        self._request('torrents/start' if self.major==5 else 'torrents/resume',
                      form={'hashes':intent.plan.manifest.info_hash},limit=4096)

    def cleanup_control(self,intent,fingerprint,permit,action):
        from src.nextgen.acquisition.cleanup import CleanupPermit, owned
        from src.nextgen.acquisition.transfers import STOPPED
        if not self._sid or self.major not in (4,5):raise ClientAuthenticationFailed()
        if type(permit) is not CleanupPermit or self.options!=intent.options or fingerprint!=intent.fingerprint:raise ClientInvalid()
        current=owned(intent,self.inspect(intent.plan.manifest.info_hash))
        if action=='remove' and current.state not in STOPPED:raise ClientInvalid()
        if action not in ('stop','remove'):raise ClientInvalid()
        permit.take(fingerprint,action)
        if action=='stop':
            self._request('torrents/stop' if self.major==5 else 'torrents/pause',
                          form={'hashes':intent.plan.manifest.info_hash},limit=4096)
        else:
            # Local files are deleted separately with a persisted exact manifest.
            self._request('torrents/delete',form={'hashes':intent.plan.manifest.info_hash,'deleteFiles':'false'},limit=4096)
