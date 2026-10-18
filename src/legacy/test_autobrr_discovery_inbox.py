import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from autobrr_discovery_inbox import Inbox, InboxError, make_handler, validate

TOKEN = 'a'*48
DATA = dict(source='nyaa',release_name='Solo Leveling S01E01 [Dual Audio]',source_guid='nyaa:123',info_hash='a'*40)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inbox=Inbox(Path(self.tmp.name)/'inbox.db')
    def test_queue_and_dedupe(self):
        self.assertEqual(self.inbox.receive(DATA),'queued_untrusted')
        self.assertEqual(self.inbox.receive(DATA),'duplicate')
    def test_guid_conflict(self):
        self.inbox.receive(DATA)
        with self.assertRaises(InboxError): self.inbox.receive(dict(DATA,info_hash='b'*40))
    def test_invalid(self):
        for data in [dict(DATA,source='unknown'),dict(DATA,info_hash='bad'),dict(DATA,release_name='x\n'),dict(DATA,unexpected=True),dict(DATA,source_guid='')]:
            with self.subTest(data=data), self.assertRaises(InboxError): validate(data)
    def test_http(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.inbox,TOKEN))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def request(data=DATA,token=TOKEN,content_type='application/json',path='/v1/release'):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            conn.request('POST',path,json.dumps(data),{'Authorization':'Bearer '+token,'Content-Type':content_type})
            r=conn.getresponse(); status=r.status;body=json.loads(r.read());conn.close();return status,body
        self.assertEqual(request(token='wrong')[0],401)
        self.assertEqual(request(content_type='text/plain')[0],415)
        self.assertEqual(request(path='/other')[0],404)
        self.assertEqual(request()[0],202)
        self.assertEqual(request()[0],200)
        self.assertEqual(request(dict(DATA,info_hash='b'*40))[0],422)
    def test_auth_length(self):
        with self.assertRaises(InboxError):make_handler(self.inbox,'short')
    def test_capacity(self):
        import autobrr_discovery_inbox as mod
        old=mod.MAX_ITEMS
        try:
            mod.MAX_ITEMS=1
            self.inbox.receive(DATA)
            with self.assertRaises(InboxError):self.inbox.receive(dict(DATA,source_guid='other'))
        finally:mod.MAX_ITEMS=old

if __name__=='__main__':unittest.main()
