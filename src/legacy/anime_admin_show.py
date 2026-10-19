"""Human-readable grouped settings with credential presence only."""
import json
from anime_flat_config import DEFAULT_SETTINGS, ALLOWED_SECRET_KEYS, load_config

def report(directory):
    cfg=load_config(directory)
    from anime_dashboard_auth import read
    secrets=cfg["secrets"]
    credentials={key:("Set" if secrets.get(key) else "Not set")
                 for key in sorted(ALLOWED_SECRET_KEYS) if key!="admin_password"}
    credentials["admin_password"]="Set" if read() or secrets.get("admin_password") else "Not set"
    return {"settings":cfg["settings"],"credentials":credentials,
            "source":"persisted settings.json and secrets.json",
            "apply_status":"Restart required for service settings changed since last start; runtime state not inspected"}

def render(directory,*,as_json=False):
    data=report(directory)
    if as_json:
        return json.dumps(data,indent=2,sort_keys=True)
    lines=["Anime Discovery — persisted configuration",
           "Source: settings.json / secrets.json (not running-state verification)"]
    for section,values in data["settings"].items():
        lines.append("\n["+section.upper()+"]")
        for key,val in values.items():
            displayed=json.dumps(val,sort_keys=True)
            lines.append("  "+key.ljust(25)+displayed)
    lines.append("\n[CREDENTIAL STATUS]")
    for key,value in data["credentials"].items():
        lines.append("  "+key.ljust(25)+value)
    lines.append("\nService settings may require restart; this report does not verify hot reload.")
    return "\n".join(lines)
