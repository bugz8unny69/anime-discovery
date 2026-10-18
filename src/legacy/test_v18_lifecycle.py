import unittest
from dataclasses import replace
from v18_lifecycle import Trial, transition, LifecycleError
class LifecycleTests(unittest.TestCase):
 def setUp(self): self.t=Trial('a'*40,'AUTO_VERIFIED_CANDIDATE',100,completed_data_available=True)
 def test_approve(self): self.assertEqual(transition(self.t,'AUTO_APPROVE'),'APPROVED_PAUSED')
 def test_unverified(self):
  with self.assertRaises(LifecycleError): transition(replace(self.t,verification='AWAITING_MAPPING_EVIDENCE'),'AUTO_APPROVE')
 def test_replay_block(self): self.assertEqual(transition(replace(self.t,state='REJECTED_BLOCKED'),'WEBHOOK_REPLAY'),'REJECTED_BLOCKED')
 def test_restore(self): self.assertEqual(transition(replace(self.t,state='REJECTED_BLOCKED'),'RESTORE_FOR_TRIAL'),'RESTORE_REQUESTED_PAUSED')
 def test_no_download_restore(self):
  with self.assertRaises(LifecycleError): transition(replace(self.t,state='REJECTED_BLOCKED',completed_data_available=False),'RESTORE_FOR_TRIAL')
 def test_delete_requires_ownership(self):
  with self.assertRaises(LifecycleError): transition(replace(self.t,state='REJECTED_BLOCKED'),'DELETE_TRIAL_COPY')
 def test_keep(self): self.assertEqual(transition(replace(self.t,state='TRIAL_READY'),'KEEP'),'PROMOTION_REQUESTED')
 def test_staging(self): self.assertEqual(transition(replace(self.t,state='APPROVED_PAUSED'),'STAGE_TRIAL'),'TRIAL_READY')
if __name__=='__main__': unittest.main()
