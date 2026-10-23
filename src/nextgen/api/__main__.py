"""Explicit API entry point; no auto-initialize, migrate, provider or worker start."""
import argparse
import getpass
import ipaddress
import logging

from src.nextgen.api.app import Application
from src.nextgen.api.auth import ApiError
from src.nextgen.secrets import SecretStore


class TransportFilter(logging.Filter):
    def filter(self,record):
        # Third-party parser/transport errors must not emit a URL/query/header.
        record.msg='API_TRANSPORT_NOTICE: The API transport needs attention.'
        record.args=();record.exc_info=None;record.exc_text=None;record.stack_info=None
        return True


def main():
    parser=argparse.ArgumentParser(description='Anime Discovery NextGen API')
    parser.add_argument('command',choices=('serve','init-access'))
    parser.add_argument('--config-dir',required=True)
    parser.add_argument('--public-origin',help='Exact browser origin; HTTPS behind a trusted proxy, or local loopback HTTP.')
    args=parser.parse_args()
    if args.command=='init-access':
        store=SecretStore(args.config_dir)
        management=getpass.getpass('Management access key (32–256 URL-safe characters): ')
        webhook=getpass.getpass('Separate webhook key (32–256 URL-safe characters): ')
        if not management or not webhook:parser.error('Both distinct keys are required.')
        status=store.status()
        result=store.initialize(management_token=management,webhook_token=webhook) if status.revision==0 else store.update_access_tokens(webhook,management,expected_revision=status.revision)
        print('Access keys saved.' if result.durability_confirmed else 'Access keys saved; storage durability needs review.')
        return
    app=Application(args.config_dir,origin=args.public_origin)
    host=app.startup.value('api.host')
    try:
        if host!='localhost' and not ipaddress.ip_address(host).is_loopback:raise ValueError()
    except ValueError:
        app.close();parser.error('Bind the API to loopback and publish it through a TLS reverse proxy.')
    try:
        import uvicorn
    except ImportError:
        app.close();parser.error('Install requirements-nextgen-api.txt before serving the API.')
    transport=logging.getLogger('uvicorn.error')
    transport.addFilter(TransportFilter())
    try:
        uvicorn.run(app,host=host,port=app.startup.value('api.port'),workers=1,interface='asgi3',
            http='h11',ws='none',lifespan='on',proxy_headers=False,forwarded_allow_ips='',
            access_log=False,log_level='warning',log_config=None,limit_concurrency=32,
            timeout_keep_alive=5,h11_max_incomplete_event_size=16384,server_header=False)
    finally:app.close()


if __name__=='__main__':main()
