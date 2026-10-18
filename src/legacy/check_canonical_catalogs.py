"""Read-only catalog check; no credentials printed and no controller writes."""
import getpass
import json
import os
from anime_service_adapters import SonarrReadOnly
from canonical_provider_integration import TVmazeReadOnly, compare_season_one, MappingBlocked

def main():
    key=os.environ.get('SONARR_API_KEY') or getpass.getpass('Sonarr API key (hidden): ')
    client=SonarrReadOnly('https://sonarr.arr.internal',key)
    series=client.series()
    print('Available Sonarr series (ID, title, TVDB ID):')
    for s in series:
        if isinstance(s,dict):
            print('{} | {} | {}'.format(s.get('id'),s.get('title'),s.get('tvdbId')))
    choice=int(input('Sonarr series ID to audit (read-only): ').strip())
    matches=[s for s in series if s.get('id')==choice]
    if len(matches)!=1: raise MappingBlocked('SERIES_NOT_FOUND')
    target=matches[0]
    provider=TVmazeReadOnly()
    show=provider.show_by_tvdb(target['tvdbId'])
    result=compare_season_one(target,client.episodes(choice),show,provider.episodes(show['id']))
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    main()
