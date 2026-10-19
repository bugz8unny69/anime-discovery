"""Interactive supported-secret editor. Does not accept password values in command arguments."""
import getpass
from anime_flat_config import ALLOWED_SECRET_KEYS

def prompt_secret(key, prompt=getpass.getpass):
    if key not in ALLOWED_SECRET_KEYS:
        raise ValueError("Unsupported credential")
    return prompt(key+" (blank keeps existing): ")
