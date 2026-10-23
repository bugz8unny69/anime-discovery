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
        if path not in ('auth/login','app/version','app/webapiVersion','torrents/info','torrents/files','torrents/add'):raise ValueError('unsupported client operation')
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
