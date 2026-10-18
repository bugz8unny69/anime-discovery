import copy
import unittest
from identity_evidence_assembly import assemble, AssemblyError

class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.kw = dict(release_title='[Group] Example - 27 [1080p].mkv', series_id=7, anilist_id=11061,
            binding={'series_id':7,'provider':'anilist','provider_id':11061,'state':'ACTIVE','binding_id':4},
            cross_reference={'series_id':7,'anilist_id':11061,'binding_id':4,'sonarr_series_id':12,
                             'anidb_anime_id':99,'status':'ADMIN_REVIEWED','audit_ref':'admin-audit-1'},
            anilist_snapshot={'id':11061,'identity_only':True,'canonical_mapping_authorized':False},
            sonarr_snapshot={'sonarr_series_id':12,'canonical_mapping_authorized':False,
                'normalized_entries':[{'release_season':None,'release_episode':27,'canonical_season':1,'canonical_episode':3,'kind':'REGULAR'}]},
            anidb_snapshot={'anidb_anime_id':99,'canonical_mapping_authorized':False,
                'normalized_entries':[{'release_season':None,'release_episode':27,'canonical_season':1,'canonical_episode':3,'kind':'REGULAR'}]})
    def test_candidate(self):
        result=assemble(**self.kw)
        self.assertEqual(result['candidate']['canonical_episode'],3)
        self.assertFalse(result['canonical_mapping_authorized'])
        self.assertEqual(len(result['evidence_sha256']),64)
    def test_determinism(self):
        self.assertEqual(assemble(**self.kw)['evidence_sha256'],assemble(**self.kw)['evidence_sha256'])
    def test_evidence_changes_fingerprint(self):
        other=copy.deepcopy(self.kw); other['anilist_snapshot']['title']='new title'
        self.assertNotEqual(assemble(**self.kw)['evidence_sha256'],assemble(**other)['evidence_sha256'])
    def test_fail_closed_cases(self):
        cases=[
            ('series_id',8),('anilist_id',0),('release_title','[Group] Example - 27-28.mkv'),
            ('binding.state','REVOKED'),('binding.provider_id',9),('binding.binding_id',0),
            ('cross_reference.status','PENDING'),('cross_reference.audit_ref',''),
            ('cross_reference.binding_id',8),('cross_reference.series_id',8),
            ('cross_reference.anilist_id',99),('cross_reference.sonarr_series_id',0),
            ('cross_reference.anidb_anime_id',0),('anilist_snapshot.id',1),
            ('anilist_snapshot.identity_only',False),
            ('anilist_snapshot.canonical_mapping_authorized',True),
            ('sonarr_snapshot.sonarr_series_id',999),
            ('sonarr_snapshot.canonical_mapping_authorized',True),
            ('anidb_snapshot.anidb_anime_id',999),
            ('anidb_snapshot.canonical_mapping_authorized',True),
            ('sonarr_snapshot.normalized_entries',None),
            ('anidb_snapshot.normalized_entries',None),
            ('sonarr_snapshot.normalized_entries.0.canonical_episode',4),
            ('anidb_snapshot.normalized_entries.0.kind','SPECIAL'),
            ('sonarr_snapshot.normalized_entries.0.canonical_season',2),
            ('sonarr_snapshot.normalized_entries.0.canonical_episode',7),
            ('sonarr_snapshot.normalized_entries.0.release_episode',28),
        ]
        for path,value in cases:
            with self.subTest(path=path):
                data=copy.deepcopy(self.kw); parts=path.split('.'); obj=data
                for p in parts[:-1]: obj=obj[int(p)] if p.isdigit() else obj[p]
                obj[parts[-1]]=value
                with self.assertRaises(AssemblyError): assemble(**data)

if __name__=='__main__':
    unittest.main(verbosity=2)
