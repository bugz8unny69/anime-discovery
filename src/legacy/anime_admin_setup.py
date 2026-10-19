"""Local interactive first-run setup wizard."""
from anime_flat_config import load_config
import anime_dashboard_auth as dashboard_auth

def initialized(directory):
    cfg=load_config(directory)
    return dashboard_auth.read() is not None and bool(cfg["secrets"].get("web_token"))
