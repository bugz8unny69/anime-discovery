import importlib, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

class NtfyConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ, {'ANIME_CONFIG_DIR':self.tmp.name}, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        import review_notifications
        self.mod=importlib.reload(review_notifications)

    def write(self, name, data):
        Path(self.tmp.name, name).write_text(json.dumps(data))

    def test_dynamic_reminder(self):
        self.write('config.json', {'ntfy.reminder_hours':2})
        self.assertEqual(self.mod.reminder_interval(),7200)
        self.write('config.json', {'ntfy.reminder_hours':3})
        self.assertEqual(self.mod.reminder_interval(),10800)

    def test_notification_live_credentials_and_link(self):
        self.write('config.json', {'ntfy.server':'https://ntfy.example', 'ntfy.topic':'testtopic', 'dashboard.public_url':'https://animeds.example'})
        self.write('secrets.json', {'ntfy.token':'test-secret'})
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
        requests=[]
        def urlopen(req, timeout):
            requests.append(req)
            return Response()
        with patch.object(self.mod.urllib.request,'urlopen',side_effect=urlopen):
            self.mod.notify('Demo','42',False)
            self.write('secrets.json', {'ntfy.token':'new-secret'})
            self.mod.notify('Demo','42',True)
        self.assertEqual(requests[0].get_header('Authorization'),'Bearer test-secret')
        self.assertEqual(requests[1].get_header('Authorization'),'Bearer new-secret')
        self.assertEqual(requests[0].get_header('Click'),'https://animeds.example/?tab=needs-review&item=42')

    def test_no_default_public_ntfy_destination(self):
        with self.assertRaises(RuntimeError): self.mod.notify('Demo','42',False)

if __name__=='__main__': unittest.main()
