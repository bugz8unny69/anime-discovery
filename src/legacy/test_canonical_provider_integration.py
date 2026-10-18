import unittest
import json
import io
from canonical_provider_integration import compare_season_one, MappingBlocked, TVmazeReadOnly

S={'id':12,'tvdbId':100}
T={'id':22,'externals':{'thetvdb':100}}
def rows(kind, n=6):
    return ([{'seasonNumber':1,'episodeNumber':i,'title':'Episode {}'.format(i)} for i in range(1,n+1)] if kind=='s' else [{'season':1,'number':i,'name':'Episode {}'.format(i),'type':'regular'} for i in range(1,n+1)])
class MappingTests(unittest.TestCase):
    def test_candidate_never_approval(self):
        result=compare_season_one(S,rows('s'),T,rows('t'))
        self.assertEqual(len(result['prefix']),6)
        self.assertFalse(result['canonical_mapping_authorized'])
        self.assertFalse(result['release_mapping_verified'])
    def test_prefix_short(self):
        self.assertEqual(len(compare_season_one(S,rows('s',3),T,rows('t',3))['prefix']),3)
    def test_identity_mismatch(self):
        with self.assertRaises(MappingBlocked): compare_season_one(S,rows('s'),{'id':22,'externals':{'thetvdb':101}},rows('t'))
    def test_missing_ep1(self):
        with self.assertRaises(MappingBlocked): compare_season_one(S,rows('s')[1:],T,rows('t'))
    def test_gap(self):
        with self.assertRaises(MappingBlocked): compare_season_one(S,[x for x in rows('s') if x['episodeNumber']!=3],T,rows('t'))
    def test_duplicate(self):
        with self.assertRaises(MappingBlocked): compare_season_one(S,rows('s')+[rows('s')[0]],T,rows('t'))
    def test_nonregular(self):
        r=rows('t');r[0]['type']='special'
        with self.assertRaises(MappingBlocked): compare_season_one(S,rows('s'),T,r)
    def test_bad_limit(self):
        with self.assertRaises(MappingBlocked): compare_season_one(S,rows('s'),T,rows('t'),limit=7)
    def test_no_episodes(self):
        with self.assertRaises(MappingBlocked): compare_season_one(S,[],T,[])
    def test_tvmaze_rejects_bad_id(self):
        with self.assertRaises(MappingBlocked): TVmazeReadOnly().show_by_tvdb('100')
    def test_tvmaze_rejects_bad_show_id(self):
        with self.assertRaises(MappingBlocked): TVmazeReadOnly().episodes(0)
if __name__=='__main__': unittest.main()

class RedirectTests(unittest.TestCase):
    class Response:
        status=200
        def __init__(self, url, data): self.url=url; self.data=data
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def geturl(self): return self.url
        def read(self,n): return json.dumps(self.data).encode()
    class Opener:
        def __init__(self,url,data): self.url=url; self.data=data
        def open(self,req,timeout=None): return RedirectTests.Response(self.url,self.data)
    def test_canonical_https_redirect_allowed(self):
        p=TVmazeReadOnly(opener=self.Opener('https://api.tvmaze.com/shows/55', {'id':55,'externals':{'thetvdb':389597}}))
        self.assertEqual(p.show_by_tvdb(389597)['id'],55)
    def test_cross_origin_redirect_blocked(self):
        p=TVmazeReadOnly(opener=self.Opener('https://evil.example/shows/55', {'id':55,'externals':{'thetvdb':389597}}))
        with self.assertRaisesRegex(MappingBlocked,'PROVIDER_REDIRECT_OR_STATUS'): p.show_by_tvdb(389597)
    def test_http_redirect_blocked(self):
        p=TVmazeReadOnly(opener=self.Opener('http://api.tvmaze.com/shows/55', {'id':55,'externals':{'thetvdb':389597}}))
        with self.assertRaises(MappingBlocked): p.show_by_tvdb(389597)
    def test_redirect_id_mismatch_blocked(self):
        p=TVmazeReadOnly(opener=self.Opener('https://api.tvmaze.com/shows/55', {'id':56,'externals':{'thetvdb':389597}}))
        with self.assertRaisesRegex(MappingBlocked,'REDIRECT_SHOW_ID_MISMATCH'): p.show_by_tvdb(389597)
    def test_tvdb_cross_reference_mismatch_blocked(self):
        p=TVmazeReadOnly(opener=self.Opener('https://api.tvmaze.com/shows/55', {'id':55,'externals':{'thetvdb':999}}))
        with self.assertRaisesRegex(MappingBlocked,'TVDB_CROSS_REFERENCE_MISMATCH'): p.show_by_tvdb(389597)
