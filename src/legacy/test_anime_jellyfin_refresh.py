import unittest
from unittest.mock import patch
from anime_jellyfin_refresh import refresh_library
from anime_flat_config import validate_config

class JellyfinRefreshTests(unittest.TestCase):
    def test_scan_request_uses_private_header_and_post(self):
        class Response:
            status=204
            def __enter__(self): return self
            def __exit__(self,*args): pass
        calls=[]
        def fake_open(request,timeout):
            calls.append((request.full_url,request.get_method(),request.get_header("X-emby-token"),timeout))
            return Response()
        with patch("anime_jellyfin_refresh.urlopen",side_effect=fake_open):
            self.assertTrue(refresh_library("https://jellyfin.example.test/base/","PRIVATE_KEY"))
        self.assertEqual(calls,[("https://jellyfin.example.test/base/Library/Refresh","POST","PRIVATE_KEY",8)])
    def test_invalid_url_rejected(self):
        for url in ("file:///tmp","https://user:pass@host","https://host/?key=hidden"):
            with self.assertRaises(ValueError):
                refresh_library(url,"key")
    def test_enabled_scan_requires_credentials(self):
        with self.assertRaisesRegex(ValueError,"jellyfin_api_key"):
            validate_config({"jellyfin":{"enabled":True,"base_url":"https://jellyfin.example.test"}},{})
        cfg=validate_config({"jellyfin":{"enabled":True,"base_url":"https://jellyfin.example.test"}},
            {"jellyfin_api_key":"key"})
        self.assertTrue(cfg["settings"]["jellyfin"]["enabled"])

if __name__=="__main__":
    unittest.main()
