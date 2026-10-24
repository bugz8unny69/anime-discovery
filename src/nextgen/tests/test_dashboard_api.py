"""Offline dashboard assets, authenticated views and operation pagination; unrun."""
import json
import unittest

from src.nextgen.api.auth import COOKIE
from src.nextgen.storage.sqlite import connect, transaction
from src.nextgen.tests.test_api_v1 import ApiV1Tests, ADMIN, WEB, ORIGIN
from src.nextgen.tests.test_management_actions import reserve_without_metadata


class DashboardApiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=ApiV1Tests.asyncSetUp
    rows=ApiV1Tests.rows
    request=ApiV1Tests.request
    release=ApiV1Tests.release

    async def asset(self,path,*,method='GET',host='anime.example'):
        route,_,query=path.partition('?')
        scope={'type':'http','method':method,'path':route,'raw_path':route.encode(),
               'query_string':query.encode(),'headers':[(b'host',host.encode()),(b'content-length',b'0')]}
        output=[]
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        async def send(message):output.append(message)
        await self.app(scope,receive,send)
        return output[0]['status'],output[1]['body'],dict(output[0]['headers'])

    async def test_public_shell_and_assets_contain_no_private_data_and_have_strict_csp(self):
        await self.request('POST','/api/v1/webhook',self.release(),token=WEB)
        for route,mime in [('/','text/html'),('/jobs','text/html'),('/settings','text/html'),
                           ('/assets/dashboard.css','text/css'),('/assets/dashboard.js','text/javascript')]:
            status,body,headers=await self.asset(route)
            self.assertEqual(status,200)
            self.assertTrue(headers[b'content-type'].decode().startswith(mime))
            self.assertEqual(headers[b'cache-control'],b'no-store')
            csp=headers[b'content-security-policy'].decode()
            self.assertIn("script-src 'self'",csp)
            self.assertIn("frame-ancestors 'none'",csp)
            self.assertNotIn('unsafe-inline',csp)
            for private in (ADMIN,WEB,'Test Anime - 10'):
                self.assertNotIn(private.encode(),body)
        self.assertEqual(self.rows('SELECT count(*) FROM jobs'),[(1,)])

    async def test_asset_allowlist_rejects_mutation_query_paths_and_untrusted_host(self):
        for route,method,host,expected in [('/assets/../secrets.json','GET','anime.example',404),
                ('/assets/secrets.json','GET','anime.example',404),('/','POST','anime.example',405),
                ('/?token=secret','GET','anime.example',400),('/','GET','evil.example',400)]:
            status,_,_=await self.asset(route,method=method,host=host)
            self.assertEqual(status,expected)

    async def test_intake_uses_management_session_and_presents_one_row_per_explicit_scope(self):
        evaluation,target=await reserve_without_metadata(self)
        for credential in (None,WEB):
            status,_,_=await self.request('GET','/api/v1/intake',token=credential)
            self.assertEqual(status,401)
        status,session,headers=await self.request('POST','/api/v1/auth/session',{'password':ADMIN},headers={'Origin':ORIGIN})
        self.assertEqual(status,201)
        cookie=headers[b'set-cookie'].decode().split(';',1)[0]
        self.assertTrue(cookie.startswith(COOKIE+'='))
        status,result,_=await self.request('GET','/api/v1/intake',headers={'Cookie':cookie})
        self.assertEqual(status,200)
        matching=[item for item in result['data']['items'] if item['job_id']==target]
        self.assertEqual(len(matching),1)
        self.assertNotIn(evaluation,[item['job_id'] for item in result['data']['items']])
        item=matching[0]
        self.assertEqual(item['release_name'],'Test Anime - 10')
        self.assertEqual(item['anime_title'],'Test Anime')
        self.assertEqual(item['acquisition_status']['message'],'Not staged')
        self.assertTrue(item['actions']['cancel']['enabled'])
        self.assertEqual(item['label']['message_key'],'handler.RESERVE_EPISODE.label')
        for private in ('raw_body','payload_json','lease_token','torrent_infohash',ADMIN,WEB):
            self.assertNotIn(private,json.dumps(item))
        status,_,_=await self.request('POST',f'/api/v1/jobs/{target}/cancel',{},headers={'Cookie':cookie,'Origin':ORIGIN})
        self.assertEqual(status,403)
        status,_,_=await self.request('POST',f'/api/v1/jobs/{target}/cancel',{},headers={
            'Cookie':cookie,'Origin':ORIGIN,'X-CSRF-Token':session['data']['csrf_token']})
        self.assertEqual(status,200)

    async def test_intake_newest_pagination_preserves_deliveries_and_excludes_control_scopes(self):
        targets=[]
        for _ in range(3):
            _,result,_=await self.request('POST','/api/v1/webhook',self.release(),token=WEB)
            targets.append(result['data']['job_id'])
        from src.nextgen.storage.job_queue import JobQueue
        JobQueue(self.database).claim()
        _,control,_=await self.request('POST',f'/api/v1/jobs/{targets[0]}/cancel',{},token=ADMIN)
        control_id=control['data']['job_id']
        status,page,_=await self.request('GET','/api/v1/intake?limit=2',token=ADMIN)
        self.assertEqual(status,200)
        self.assertEqual([r['job_id'] for r in page['data']['items']],list(reversed(targets[1:])))
        cursor=page['data']['next_before_id']
        _,last,_=await self.request('GET',f'/api/v1/intake?limit=2&before_id={cursor}',token=ADMIN)
        self.assertEqual([r['job_id'] for r in last['data']['items']],[targets[0]])
        self.assertIsNone(last['data']['next_before_id'])
        _,job,_=await self.request('GET',f'/api/v1/jobs/{control_id}',token=ADMIN)
        self.assertTrue(job['data']['is_management_action'])

    async def test_reverse_job_pagination_is_additive_and_rejects_mixed_cursors(self):
        for _ in range(3):await self.request('POST','/api/v1/webhook',self.release(),token=WEB)
        _,old,_=await self.request('GET','/api/v1/jobs?limit=2',token=ADMIN)
        self.assertEqual([r['job_id'] for r in old['data']['items']],[1,2])
        self.assertEqual(old['data']['next_after_id'],2)
        _,new,_=await self.request('GET','/api/v1/jobs?before_id=9223372036854775807&limit=2',token=ADMIN)
        self.assertEqual([r['job_id'] for r in new['data']['items']],[3,2])
        self.assertEqual(new['data']['next_before_id'],2)
        for route in ('/api/v1/jobs?before_id=3&after_id=0','/api/v1/jobs/1/history?before_id=3',
                      '/api/v1/intake?after_id=0','/api/v1/intake?before_id=0'):
            status,_,_=await self.request('GET',route,token=ADMIN)
            self.assertEqual(status,400)

    async def test_display_context_ignores_unknown_and_malformed_stored_declarations(self):
        _,result,_=await self.request('POST','/api/v1/webhook',self.release(),token=WEB)
        job=result['data']['job_id'];db=connect(self.database)
        try:
            for raw in (b'{broken',b'[]',b'{"token":"private-value","unknown":"private-value"}'):
                with transaction(db):db.execute('UPDATE incoming_events SET raw_body=?',(raw,))
                status,result,_=await self.request('GET',f'/api/v1/jobs/{job}',token=ADMIN)
                self.assertEqual(status,200)
                self.assertIsNone(result['data']['release_name'])
                self.assertNotIn('private-value',json.dumps(result))
        finally:db.close()
