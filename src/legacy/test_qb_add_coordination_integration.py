import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from controller_add_coordinator import install, coordinate, AddBlocked
from qb_trial_add_adapter import QBTrialAdd
from anime_service_adapters import Torrent
H='c'*40
M='magnet:?xt=urn:btih:'+H
class IntegrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.dbpath=str(Path(self.tmp.name)/'fixture.db')
  self.db=sqlite3.connect(self.dbpath,isolation_level=None)
  self.db.execute('CREATE TABLE download_attempts (id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT)')
  self.db.execute('INSERT INTO download_attempts VALUES (22,3,1,1,?,?)',(H,'QUEUED'))
  install(self.dbpath,self.db)
  self.q=QBTrialAdd('http://127.0.0.1:8080','user','pass')
  self.q._authenticated=True
  self.items=[]
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def run_coordinator(self):
  return coordinate(self.dbpath,self.db,attempt_id=22,series_id=3,episode=1,generation=1,torrent_hash=H,
   inventory=lambda:self.q.torrents(),add=lambda h:self.q.add_trial_magnet(M,h,allow_external_write=True),
   lock_path=str(Path(self.tmp.name)/'lock'),allow_external_add=True)
 def test_integrated_confirmed_no_cancellation(self):
  def mock_request(path,*,form=None):
   if path.endswith('/torrents/info'):
    import json
    return json.dumps(self.items)
   self.assertEqual(path,'/api/v2/torrents/add')
   self.items.append({'hash':H,'name':'test','state':'pausedDL','save_path':'/mnt/media/Torrents/anime-trial','progress':0})
   return 'Ok.'
  with patch.object(self.q,'_request',side_effect=mock_request):
   result=self.run_coordinator()
  self.assertEqual(result['state'],'CONFIRMED')
  self.assertFalse(result['cancellation_authorized'])
 def test_preexisting_hash_does_not_call_add(self):
  self.items.append({'hash':H,'name':'existing','state':'downloading','save_path':'/elsewhere','progress':0})
  with patch.object(self.q,'_request',return_value=__import__('json').dumps(self.items)) as request:
   with self.assertRaises(AddBlocked):self.run_coordinator()
   self.assertEqual(request.call_count,1)
if __name__=='__main__':unittest.main()
