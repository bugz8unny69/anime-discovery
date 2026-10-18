import unittest
from unittest.mock import patch
from qb_trial_add_adapter import QBTrialAdd, TrialAddDisabled, validate_magnet
from anime_service_adapters import AdapterError
H='a'*40
M='magnet:?xt=urn:btih:'+H
class TrialAddTests(unittest.TestCase):
 def setUp(self):
  self.q=QBTrialAdd('http://127.0.0.1:8080','user','pass')
  self.q._authenticated=True
 def test_disabled_no_network(self):
  with patch.object(self.q,'_request') as req:
   with self.assertRaises(TrialAddDisabled):self.q.add_trial_magnet(M,H)
   req.assert_not_called()
 def test_payload(self):
  with patch.object(self.q,'_request',return_value='Ok.') as req:
   self.assertTrue(self.q.add_trial_magnet(M,H,allow_external_write=True))
   args,kwargs=req.call_args
   self.assertEqual(args[0],'/api/v2/torrents/add')
   self.assertEqual(kwargs['form']['category'],'anime-trial')
   self.assertEqual(kwargs['form']['savepath'],'/mnt/media/Torrents/anime-trial')
   self.assertEqual(kwargs['form']['paused'],'true')
   self.assertEqual(kwargs['form']['autoTMM'],'false')
 def test_login_required(self):
  self.q._authenticated=False
  with self.assertRaises(AdapterError):self.q.add_trial_magnet(M,H,allow_external_write=True)
 def test_response_uncertain(self):
  with patch.object(self.q,'_request',return_value='Fails.'):
   with self.assertRaises(AdapterError):self.q.add_trial_magnet(M,H,allow_external_write=True)
 def test_wrong_hash(self):
  with self.assertRaises(ValueError):validate_magnet(M,'b'*40)
 def test_two_xt(self):
  with self.assertRaises(ValueError):validate_magnet(M+'&xt=urn:btih:'+H,H)
 def test_source_parameters(self):
  with self.assertRaises(ValueError):validate_magnet(M+'&xs=https%3A%2F%2Fexample.com',H)
 def test_invalid_hash(self):
  with self.assertRaises(ValueError):validate_magnet(M,'x'*40)
 def test_no_fragment(self):
  with self.assertRaises(ValueError):validate_magnet(M+'#fragment',H)
 def test_bad_scheme(self):
  with self.assertRaises(ValueError):validate_magnet('http://example.com',H)
 def test_no_auth_network(self):
  self.q._authenticated=False
  with patch.object(self.q,'_request') as req:
   with self.assertRaises(AdapterError):self.q.add_trial_magnet(M,H,allow_external_write=True)
   req.assert_not_called()
if __name__=='__main__':unittest.main()
