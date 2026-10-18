import tempfile,sqlite3,unittest
from pathlib import Path
from anime_identity_worker_v10 import init,pending,record
class TestQueue(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup)
  self.db=Path(self.t.name)/'state.db'; self.inbox=Path(self.t.name)/'inbox.db'
  with sqlite3.connect(self.inbox) as c:
   c.execute('CREATE TABLE notifications(id INTEGER PRIMARY KEY,status TEXT)')
   c.executemany('INSERT INTO notifications VALUES (?,?)',[(1,'UNTRUSTED'),(2,'UNTRUSTED'),(3,'NEEDS_REVIEW')])
  init(self.db)
 def test_initial(self):self.assertEqual(pending(self.db,self.inbox,100,5),[1,2])
 def test_done(self):
  record(self.db,1,'UNCHANGED',100)
  self.assertEqual(pending(self.db,self.inbox,100,5),[2])
 def test_retry(self):
  record(self.db,1,'NEW_IDENTITY_LOOKUP_PENDING_RATE_LIMIT_INTEGRATION',100)
  self.assertEqual(pending(self.db,self.inbox,200,5),[2])
  self.assertEqual(pending(self.db,self.inbox,401,5),[1,2])
 def test_status(self):self.assertNotIn(3,pending(self.db,self.inbox,100,5))
if __name__=='__main__':unittest.main()
