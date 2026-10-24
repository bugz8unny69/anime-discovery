"""Offline authenticated durable HTTP submissions; no live requests; unexecuted."""
import unittest
from unittest.mock import patch
from src.nextgen.api.app import Application
from src.nextgen.storage.management_actions import disabled_reason
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import connect, transaction
from src.nextgen.tests.test_api_v1 import ApiV1Tests, ADMIN, WEB


class ApiManagementActionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=ApiV1Tests.asyncSetUp
    rows=ApiV1Tests.rows
    request=ApiV1Tests.request
    release=ApiV1Tests.release

    async def running(self):
        _,result,_=await self.request('POST','/api/v1/webhook',self.release(),token=WEB)
        target=result['data']['job_id']
        JobQueue(self.database).claim()
        return target

    async def test_running_cancel_receipt_polling_and_button_state_survive_api_restart(self):
        target=await self.running()
        with patch('src.nextgen.cancellation_service.CancellationService.cleanup',side_effect=AssertionError('HTTP must not run cleanup')):
            status,result,headers=await self.request('POST',f'/api/v1/jobs/{target}/cancel',{},token=ADMIN)
        self.assertEqual(status,202);data=result['data']
        self.assertEqual(data['notification']['message'],'Job submitted.')
        self.assertTrue(data['disable_action']);self.assertEqual(data['state'],'PENDING')
        self.assertEqual(data['disabled_reason']['message'],'A job is already queued.')
        self.assertEqual(data['disabled_reason']['message_key'],'reason.MANAGEMENT_JOB_QUEUED.message')
        self.assertEqual(headers[b'location'].decode(),data['status_url'])
        self.app.close();self.app=Application(self.root,origin='https://anime.example');self.addCleanup(self.app.close)
        _,duplicate,_=await self.request('POST',f'/api/v1/jobs/{target}/cleanup',{},token=ADMIN)
        self.assertEqual(duplicate['data']['job_id'],data['job_id']);self.assertTrue(duplicate['data']['reused'])
        status,job,_=await self.request('GET',data['status_url'],token=ADMIN)
        self.assertEqual(status,200);self.assertEqual(job['data']['kind'],'CLEANUP_CANCELED_OPERATION')
        self.assertNotIn('payload',job['data']);self.assertNotIn('lease_token',job['data'])
        status,original,_=await self.request('GET',f'/api/v1/jobs/{target}',token=ADMIN)
        self.assertFalse(original['data']['actions']['cancel']['enabled'])
        self.assertFalse(original['data']['actions']['cleanup']['enabled'])
        self.assertEqual(original['data']['actions']['cleanup']['job']['job_id'],data['job_id'])
        for name in ('keep','cancel','cleanup'):
            action=original['data']['actions'][name]
            self.assertFalse(action['enabled'])
            self.assertEqual(action['disabled_reason']['code'],'MANAGEMENT_JOB_QUEUED')
        claim,_=JobQueue(self.database).claim()
        self.assertEqual(claim.job_id,data['job_id'])
        _,running,_=await self.request('GET',f'/api/v1/jobs/{target}',token=ADMIN)
        for name in ('keep','cancel','cleanup'):
            action=running['data']['actions'][name]
            self.assertFalse(action['enabled'])
            self.assertEqual(action['disabled_reason']['message'],'A job is already in progress.')
            self.assertEqual(action['disabled_reason']['message_key'],'reason.MANAGEMENT_JOB_RUNNING.message')
        _,history,_=await self.request('GET',data['history_url'],token=ADMIN)
        self.assertEqual(history['data']['items'][0]['event']['code'],'CREATED')

    async def test_pending_cancel_is_immediate_and_invalid_or_unauthorized_actions_do_not_enqueue(self):
        _,result,_=await self.request('POST','/api/v1/webhook',self.release(),token=WEB)
        target=result['data']['job_id']
        for path,body,token,expected in ((f'/api/v1/jobs/{target}/keep',{},ADMIN,409),
            (f'/api/v1/jobs/{target}/cancel',{},WEB,401),(f'/api/v1/jobs/{target}/cancel',{'kind':'ARBITRARY'},ADMIN,400),
            ('/api/v1/jobs/9999/cleanup',{},ADMIN,404)):
            status,_,_=await self.request('POST',path,body,token=token);self.assertEqual(status,expected)
        self.assertEqual(self.rows('SELECT * FROM management_actions'),[])
        status,result,_=await self.request('POST',f'/api/v1/jobs/{target}/cancel',{},token=ADMIN)
        self.assertEqual(status,200);self.assertTrue(result['data']['completed'])
        self.assertEqual(self.rows('SELECT count(*) FROM jobs'),[(1,)])

    async def test_staged_keep_is_a_single_durable_request_not_a_claim_of_completion(self):
        _,result,_=await self.request('POST','/api/v1/webhook',self.release(),token=WEB)
        target=result['data']['job_id'];db=connect(self.database)
        try:
            with transaction(db):
                db.execute("UPDATE jobs SET state='DONE' WHERE job_id=?",(target,))
                db.execute("UPDATE job_operations SET state='STAGED' WHERE operation_id=(SELECT operation_id FROM job_operation_members WHERE job_id=?)",(target,))
        finally:db.close()
        status,result,_=await self.request('POST',f'/api/v1/jobs/{target}/keep',{},token=ADMIN)
        self.assertEqual(status,202);control=result['data']['job_id']
        _,again,_=await self.request('POST',f'/api/v1/jobs/{target}/keep',{},token=ADMIN)
        self.assertEqual(again['data']['job_id'],control)
        self.assertEqual(self.rows('SELECT kind,state FROM jobs WHERE job_id=?',(control,)),[('KEEP_MEDIA','PENDING')])
        _,original,_=await self.request('GET',f'/api/v1/jobs/{target}',token=ADMIN)
        self.assertFalse(original['data']['actions']['keep']['enabled'])
        self.assertFalse(original['data']['actions']['cancel']['enabled'])


class ActionMessageTests(unittest.TestCase):
    def test_disabled_explanations_follow_state_not_stale_progress_reason(self):
        expected={'PENDING':'A job is already queued.',
                  'RUNNING':'A job is already in progress.',
                  'RETRY_WAIT':'A job is waiting to continue.',
                  'DONE':'This job is already complete.',
                  'CANCELED':'This job was canceled.'}
        for state,message in expected.items():
            with self.subTest(state=state):
                reason=disabled_reason(state,'CANCELLATION_DRAINING')
                self.assertEqual(reason['message'],message)
                self.assertEqual(reason['message_key'],f"reason.{reason['code']}.message")
        for state in ('ON_HOLD','BLOCKED','NEEDS_REVIEW'):
            with self.subTest(state=state):
                self.assertEqual(disabled_reason(state)['code'],'MANAGEMENT_JOB_ATTENTION')
        self.assertEqual(disabled_reason('BLOCKED','KEEP_NOT_READY')['code'],'KEEP_NOT_READY')
