import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_flat_config import DEFAULT_SETTINGS
from anime_dashboard_settings_page import settings_page
import anime_dashboard_auth as auth

class DashboardSettingsTests(unittest.TestCase):
    def test_five_integrations_render_without_returning_credentials(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            (folder/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
            (folder/"secrets.json").write_text(json.dumps({
                "web_token":"private-value-here","jellyfin_api_key":"other-private-value"}))
            os.chmod(folder/"secrets.json",0o600)
            with patch.object(auth,"AUTH_FILE",folder/"auth.json"):
                html=settings_page(folder)
            for name in ("jellyfin","sonarr","shoko","autobrr","ntfy","tvdb"):
                self.assertIn('data-name="'+name+'"',html)
            self.assertIn('data-key="web_token" data-stored="true"',html)
            self.assertIn("API Key",html)
            self.assertIn("AniDB",html)
            self.assertIn("no API key required",html)
            self.assertIn("Save &amp; Apply",html)
            self.assertIn("Test Connection",html)
            self.assertIn('class="toggle-secret"',html)
            self.assertNotIn('name="reveal_password"',html)
            self.assertNotIn('class="toggle-token"',html)
            self.assertIn('type="password" name="credential"',html)
            self.assertNotIn("private-value-here",html)
            self.assertNotIn("other-private-value",html)
            self.assertIn("Refresh",html)
            self.assertIn("Save &amp; Apply",html)

if __name__=="__main__": unittest.main()
