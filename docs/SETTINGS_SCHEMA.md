# Settings schema and generated dashboard

Ordinary application settings are defined in one registry:
`src/legacy/anime_settings_schema.py` (`SCHEMA`). The configuration loader
derives `DEFAULT_SETTINGS` from that registry. The dashboard uses the same
registry to render every visible scalar field.

## Adding a setting

Add the field to the appropriate section under `SCHEMA`:

```python
"new_option": field(5, label="New option", minimum=1, maximum=20)
```

For dashboard-enabled sections, an integer input will automatically appear on
the Settings page and be submitted to the existing `/api/settings` endpoint.
Backend schema validation enforces integer/string/boolean type, numeric bounds
and enumerated choices. Existing complex cross-field validators still run in
`anime_flat_config.validate_config`.

For sensitive or complex/internal fields, set `visible=False`. Dictionaries
such as `identity.episode_map` must use a custom editor and cannot appear
as automatically generated inputs. A new section must be deliberately marked
`dashboard=True` to be exposed. A plain client name, such as
`anidb.client`, is ordinary configuration. API keys and passwords are
**never** added as regular setting fields: they use the separate secrets
system and a section's `credential` key.

Only configured integrations with existing safe probe logic have a
`test_connection=True` control. AniDB does not expose that control: a test
button should not consume the API's scarce request budget. Register your
AniDB HTTP API client outside Anime Discovery, then enter the client name
and version in the AniDB section of the dashboard.

Saving is atomic, validates the full settings file, and reports whether a
service restart is required. Saving does **not** restart background workers
automatically. The original Keep→Sonarr→Shoko pipeline is unchanged.
