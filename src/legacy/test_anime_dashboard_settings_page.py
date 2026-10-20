import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_flat_config import DEFAULT_SETTINGS
from anime_dashboard_settings_page import settings_page, render_field
from anime_settings_schema import SCHEMA, field, defaults
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
            self.assertIn('id="anidb-public"',html)
            self.assertNotIn("anidb_api_key",html)
            self.assertIn("no API key required",html)
            self.assertIn("Save &amp; Apply",html)
            self.assertIn("Test Connection",html)
            self.assertIn('class="toggle-secret"',html)
            self.assertNotIn('name="reveal_password"',html)
            self.assertNotIn('class="toggle-token"',html)
            self.assertIn('type="password" name="credential"',html)
            self.assertNotIn("private-value-here",html)
            self.assertNotIn("other-private-value",html)
            self.assertNotIn('id="refresh"',html)
            self.assertNotIn("Complex and internal settings",html)
            self.assertIn("Saved and applied automatically",html)
            self.assertIn("api/credential-reveal",html)
            self.assertIn("Save &amp; Apply",html)

    def test_anidb_client_and_version_are_generated_without_credentials(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            settings=defaults()
            settings["anidb"]["client"]="registeredclient"
            settings["anidb"]["clientver"]=3
            (folder/"settings.json").write_text(json.dumps(settings))
            (folder/"secrets.json").write_text("{}")
            with patch.object(auth,"AUTH_FILE",folder/"auth.json"):
                page=settings_page(folder)
        form=page.split('id="anidb-public"',1)[1].split("</form>",1)[0]
        self.assertIn('name="client" value="registeredclient"',form)
        self.assertIn('name="clientver" value="3"',form)
        self.assertIn("HTTP API Client Name",form)
        self.assertNotIn('name="http_api_url"',form)
        self.assertNotIn('name="credential"',form)
        self.assertNotIn("Test Connection",form)
        self.assertNotIn('name="anidb_api_key"',form)

    def test_new_schema_field_needs_no_renderer_or_default_updates(self):
        new=field("safe-default",label="Future Preference")
        self.assertIn('name="future_preference"',render_field("future_preference",new,"safe-default"))
        with patch.dict(SCHEMA["anidb"]["fields"],{"future_preference":new}):
            self.assertEqual(defaults()["anidb"]["future_preference"],"safe-default")
            with patch("anime_dashboard_settings_page.snapshot",
                       return_value={"settings":defaults(),"credential_status":{}}):
                page=settings_page(Path("/unused-in-patched-snapshot"))
            self.assertIn('name="future_preference" value="safe-default"',page)
            self.assertIn("Future Preference",page)

    def test_complex_or_hidden_schema_fields_are_not_rendered(self):
        self.assertEqual(render_field("episode_map",SCHEMA["identity"]["fields"]["episode_map"],{}),"")
        self.assertEqual(render_field("http_api_url",SCHEMA["anidb"]["fields"]["http_api_url"],""),"")
        with self.assertRaises(ValueError):
            field({},visible=True)

    def test_rendered_values_are_html_escaped(self):
        spec=field("",label="User Supplied")
        self.assertIn('&lt;script&gt;',render_field("test",spec,'<script>'))
        self.assertNotIn('value="<script>"',render_field("test",spec,'<script>'))

if __name__=="__main__": unittest.main()
