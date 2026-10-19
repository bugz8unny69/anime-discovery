#!/usr/bin/env python3
"""Single-user dashboard authentication. No third-party dependencies."""
import argparse, base64, getpass, hashlib, hmac, json, os, secrets, time
from pathlib import Path

AUTH_FILE=Path(os.environ.get('ANIME_DASHBOARD_AUTH_FILE','/var/lib/anime-discovery/dashboard-auth.json'))
ITERATIONS=600000

def _write(data):
    AUTH_FILE.parent.mkdir(parents=True,exist_ok=True)
    temp=AUTH_FILE.with_name(AUTH_FILE.name+'.'+secrets.token_hex(8)+'.tmp')
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(data,out);out.flush();os.fsync(out.fileno())
        os.replace(temp,AUTH_FILE)
        AUTH_FILE.chmod(0o600)
    finally:
        if temp.exists():temp.unlink()

def read():
    try:return json.loads(AUTH_FILE.read_text())
    except FileNotFoundError:return None

def hash_password(password,salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),ITERATIONS).hex()

def set_password(password):
    if len(password)<12:raise ValueError('Password must be at least 12 characters')
    salt=secrets.token_hex(16)
    _write({'version':1,'username':'admin','salt':salt,'iterations':ITERATIONS,
            'password_hash':hash_password(password,salt),'session_secret':secrets.token_hex(32)})

def initialize_legacy(password):
    """One-time migration: preserve an existing admin password without weakening
    password requirements for newly configured passwords."""
    if read() is not None:
        return False
    if not isinstance(password,str) or not password:
        raise ValueError("A configured administrator password is required")
    salt=secrets.token_hex(16)
    _write({'version':1,'username':'admin','salt':salt,'iterations':ITERATIONS,
            'password_hash':hash_password(password,salt),
            'session_secret':secrets.token_hex(32)})
    return True

def verify(username,password):
    data=read()
    if not data or not hmac.compare_digest(username,'admin'):return False
    derived=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(data['salt']),int(data['iterations'])).hex()
    return hmac.compare_digest(derived,data['password_hash'])

def session_token(ttl=7*86400):
    data=read()
    expiry=int(time.time())+ttl
    nonce=secrets.token_hex(16)
    payload=f'{expiry}.{nonce}'
    signature=hmac.new(bytes.fromhex(data['session_secret']),payload.encode(),'sha256').hexdigest()
    return payload+'.'+signature

def valid_session(token):
    data=read()
    if not data or not token or len(token)>300:return False
    try:
        expiry,nonce,signature=token.split('.')
        if not expiry.isascii() or not expiry.isdecimal() or int(expiry)<time.time() or int(expiry)>time.time()+8*86400:return False
        if len(nonce)!=32 or len(signature)!=64:return False
        expected=hmac.new(bytes.fromhex(data['session_secret']),f'{expiry}.{nonce}'.encode(),'sha256').hexdigest()
        return hmac.compare_digest(signature,expected)
    except (ValueError,KeyError,TypeError):return False

def revoke_all():
    data=read()
    if not data:raise ValueError('Authentication is not initialized')
    data['session_secret']=secrets.token_hex(32)
    _write(data)

def main():
    parser=argparse.ArgumentParser(description='Anime Discovery dashboard admin password and session manager')
    parser.add_argument('command',choices=['passwd','revoke-all','status'])
    args=parser.parse_args()
    if args.command=='status':print('Initialized' if read() else 'Not initialized');return
    if args.command=='revoke-all':revoke_all();print('All sessions revoked');return
    p1=getpass.getpass('New admin password (12+ characters): ')
    p2=getpass.getpass('Confirm password: ')
    if p1!=p2:parser.error('Passwords do not match')
    try:set_password(p1)
    except ValueError as exc:parser.error(str(exc))
    print('Password updated; existing sessions revoked. No dashboard restart required.')

if __name__=='__main__':main()
