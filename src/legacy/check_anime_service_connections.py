"""Opt-in, read-only connectivity check; requires credentials in environment."""
import getpass
import os
from anime_service_adapters import QBittorrentReadOnly, SonarrReadOnly, AdapterError


def main():
    user = os.environ.get('QBITTORRENT_USERNAME') or input('qBittorrent username: ')
    password = os.environ.get('QBITTORRENT_PASSWORD') or getpass.getpass('qBittorrent password: ')
    qb = QBittorrentReadOnly(os.environ.get('QBITTORRENT_URL', 'http://127.0.0.1:8080'), user, password)
    qb.login()
    print('qBittorrent version:', qb.version())
    print('qBittorrent inventory entries:', len(qb.torrents()))
    print('No torrent hashes or paths displayed.')
    key = os.environ.get('SONARR_API_KEY')
    if not key:
        print('Sonarr API check skipped: SONARR_API_KEY not configured.')
        return
    sonarr = SonarrReadOnly(os.environ.get('SONARR_URL', 'https://sonarr.arr.internal'), key,
                            ca_bundle=os.environ.get('SONARR_CA_BUNDLE') or None)
    print('Sonarr version:', sonarr.status()['version'])
    print('Sonarr series entries:', len(sonarr.series()))


if __name__ == '__main__':
    try:
        main()
    except (AdapterError, ValueError) as exc:
        raise SystemExit('Connection check failed: {}'.format(exc))
