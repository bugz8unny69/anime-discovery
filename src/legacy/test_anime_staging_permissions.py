"""Offline ownership policy regressions for the real staging path."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_trial_staging import stage_verified
from anime_staging_permissions import resolve_policy


class StagingPermissionsTests(unittest.TestCase):
    def stage(self, **kwargs):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        trial=root/"trial";trial.mkdir()
        source=root/"video.mkv";source.write_bytes(b"verified media")
        path=stage_verified(source,trial,title="Solo Leveling",tvdb_id=389597,
            season=1,episode=1,series_id=1,**kwargs)
        return path

    def test_default_mkstemp_mode_is_replaced_and_nfo_group_readable(self):
        path=self.stage()
        for file in (path,path.with_suffix(".nfo"),path.parent.parent/"tvshow.nfo"):
            self.assertTrue(file.is_file())
            self.assertEqual(stat.S_IMODE(file.stat().st_mode),0o640)
        self.assertEqual(path.read_bytes(),b"verified media")

    def test_optional_numeric_group_applies_to_files_and_directories(self):
        gid=os.getegid()
        path=self.stage(staged_group=str(gid))
        self.assertEqual(path.stat().st_gid,gid)
        self.assertEqual(path.with_suffix(".nfo").stat().st_gid,gid)
        self.assertEqual((path.parent.parent/"tvshow.nfo").stat().st_gid,gid)
        for folder in (path.parent,path.parent.parent):
            self.assertEqual(folder.stat().st_gid,gid)
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode)&0o050,0o050)

    def test_optional_user_may_be_current_owner(self):
        path=self.stage(staged_owner=str(os.geteuid()))
        self.assertEqual(path.stat().st_uid,os.geteuid())

    def test_foreign_owner_is_rejected_without_elevation(self):
        if os.geteuid()==0:
            self.skipTest("Root can deliberately change ownership")
        with self.assertRaises(PermissionError):
            resolve_policy(str(os.geteuid()+1),"")

    def test_unknown_group_fails_before_any_copy(self):
        with self.assertRaises(ValueError):
            self.stage(staged_group="not_a_real_group_999999")

    def test_permission_failure_cannot_mark_media_as_published(self):
        with patch("anime_trial_staging.apply_file",side_effect=PermissionError("NFS denies mode")):
            with self.assertRaises(PermissionError):
                self.stage(staged_group=str(os.getegid()))

if __name__=="__main__":
    unittest.main()
