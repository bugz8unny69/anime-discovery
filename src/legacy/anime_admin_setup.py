"""Local interactive first-run setup wizard."""
from anime_flat_config import load_config
import anime_dashboard_auth as dashboard_auth

def initialized(directory):
    cfg=load_config(directory)
    return dashboard_auth.read() is not None and bool(cfg["secrets"].get("web_token"))

def setup(directory, *, reconfigure=False, ask=input, password_prompt=None, integration_configurer=None):
    """Bootstrap credentials locally; an interrupted run is safe to repeat."""
    import getpass
    import secrets
    from anime_admin_secret_editor import set_secret
    from anime_shared_settings import apply_settings
    password_prompt=password_prompt or getpass.getpass
    cfg=load_config(directory)
    if initialized(directory) and not reconfigure:
        return {"configured":True,"unchanged":True}
    current=cfg["settings"]["web"]
    host=ask("Dashboard host ["+current["host"]+"]: ").strip() or current["host"]
    raw=ask("Dashboard port ["+str(current["port"])+"]: ").strip()
    port=int(raw) if raw else current["port"]
    from anime_flat_config import validate_config
    candidate={key:dict(values) for key,values in cfg["settings"].items()}
    candidate["web"].update(host=host,port=port)
    validate_config(candidate,cfg["secrets"])
    if dashboard_auth.read() is None:
        password=password_prompt("New dashboard admin password: ")
        confirmation=password_prompt("Confirm dashboard admin password: ")
        if password!=confirmation or len(password)<12:
            raise ValueError("Password confirmation failed or password too short")
    else:
        password=None
    if not cfg["secrets"].get("web_token"):
        generated=secrets.token_urlsafe(32)
        set_secret(directory,"web_token",prompt=lambda _:generated)
    if password is not None:
        dashboard_auth.set_password(password)
    changed=apply_settings(directory,{"web":{"host":host,"port":port}})
    from anime_admin_integrations import configure
    from anime_admin_jellyfin import configure_jellyfin
    integration_configurer=integration_configurer or configure
    configured=[]
    for service in ("jellyfin","sonarr","shoko","ntfy"):
        if ask("Configure "+service+" now? [y/N]: ").strip().lower() in ("y","yes"):
            if service=="jellyfin":
                configure_jellyfin(directory,ask=ask,secret_prompt=password_prompt)
            else:
                integration_configurer(directory,service,ask=ask,secret_prompt=password_prompt)
            configured.append(service)
    return {"configured":True,"unchanged":False,
            "administrator":"Set","webhook_token":"Set",
            "restart_required":changed["restart_required"] or password is not None or bool(configured),
            "configured_integrations":configured,"autobrr":"Webhook token configured"}
