import unittest
from anime_shoko_link_plan import plan_episode_link

class ShokoLinkPlanTests(unittest.TestCase):
    def test_only_unrecognized_exact_episode_is_reviewable(self):
        options=dict(contract={"validated":True},
                     file_observation={"file_id":21,"recognized":False,"existing_episode_ids":[]},
                     anidb_episode_id=54321,identity_verified=True,episode_order_verified=True)
        result=plan_episode_link(**options)
        self.assertEqual(result["action"],"ELIGIBLE_FOR_SEPARATE_REVIEW")
        self.assertFalse(result["writes_enabled"])
        options["file_observation"]["recognized"]=True
        self.assertEqual(plan_episode_link(**options)["action"],"NO_WRITE")
        options["file_observation"]["recognized"]=False
        options["file_observation"]["existing_episode_ids"]=[3]
        self.assertEqual(plan_episode_link(**options)["action"],"NO_WRITE")
        options["file_observation"]["existing_episode_ids"]=[]
        options["episode_order_verified"]=False
        self.assertEqual(plan_episode_link(**options)["action"],"NO_WRITE")

if __name__=="__main__":
    unittest.main()
