"""Offline archive-upgrade tests with fake systemd and fresh SQLite."""
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from anime_admin_archive_upgrade import upgrade_archive
from anime_fresh_database import initialize


def create_archive(path,*,bad=False):
    with tarfile.open(path,"w:gz") as archive:
        entries={
            "anime-discovery/deploy/install-homelab.py":b"new installer",
            "anime-discovery/src/legacy/anime-discovery-live.py":b"new runtime",
            "anime-discovery/README.md":b"new release"
        }
        if bad:
            entries["anime-discovery/../../unsafe.txt"]=b"bad"
        for name,body in entries.items():
            entry=tarfile.TarInfo(name)
            entry.size=len(body)
            entry.mode=0o644
            archive.addfile(entry,io.BytesIO(body))


class ArchiveUpgradeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.root=self.base/"anime-discovery"
        (self.root/"src"/"legacy").mkdir(parents=True)
        (self.root/"src"/"legacy"/"anime-discovery-live.py").write_text("old runtime")
        self.database=self.base/"anime.sqlite"
        initialize(self.database)
        self.archive=self.base/"release.tar.gz"
        create_archive(self.archive)
        self.calls=[]

    def runner(self,*args,cwd=None):
        self.calls.append(args)
        return ""

    def test_archive_upgrade_replaces_only_code_and_backs_up_database(self):
        result=upgrade_archive(self.root,self.archive,db_path=self.database,runner=self.runner)
        self.assertTrue(result["updated"])
        self.assertEqual((self.root/"src"/"legacy"/"anime-discovery-live.py").read_text(),"new runtime")
        self.assertEqual((Path(result["backup_code"])/"src"/"legacy"/"anime-discovery-live.py").read_text(),"old runtime")
        self.assertTrue(Path(result["backup_database"]).is_file())
        self.assertTrue(self.database.is_file())
        self.assertIn(("systemctl","stop","anime-discovery.service"),self.calls)
        self.assertIn(("systemctl","start","anime-discovery.service"),self.calls)

    def test_restart_failure_restores_old_code(self):
        def runner(*args,cwd=None):
            self.calls.append(args)
            if args==("systemctl","is-active","--quiet","anime-discovery.service"):
                raise RuntimeError("failed startup")
        with self.assertRaisesRegex(RuntimeError,"Service not active after 3 readiness checks"):
            upgrade_archive(self.root,self.archive,db_path=self.database,runner=runner,
                            readiness_attempts=3,sleep=lambda seconds: None)
        self.assertEqual((self.root/"src"/"legacy"/"anime-discovery-live.py").read_text(),"old runtime")
        self.assertEqual(self.calls.count(("systemctl","start","anime-discovery.service")),2)

    def test_transient_service_startup_passes_and_verbose_reports_steps(self):
        attempts=[0]
        progress=[]
        def runner(*args,cwd=None):
            self.calls.append(args)
            if args==("systemctl","is-active","--quiet","anime-discovery.service"):
                attempts[0]+=1
                if attempts[0]<3:
                    raise RuntimeError("activating")
            return ""
        result=upgrade_archive(self.root,self.archive,db_path=self.database,
            runner=runner,verbose=True,log=progress.append,sleep=lambda _:None)
        self.assertTrue(result["updated"])
        self.assertEqual(attempts[0],3)
        self.assertTrue(any("Extracting release" in m for m in progress))
        self.assertTrue(any("Service active" in m for m in progress))
        self.assertTrue((self.root/"src"/"legacy"/"anime-discovery-live.py").is_file())

    def test_unsafe_archive_never_stops_service(self):
        create_archive(self.archive,bad=True)
        with self.assertRaisesRegex(ValueError,"unsafe"):
            upgrade_archive(self.root,self.archive,db_path=self.database,runner=self.runner)
        self.assertFalse(self.calls)
        self.assertEqual((self.root/"src"/"legacy"/"anime-discovery-live.py").read_text(),"old runtime")

    def test_refuses_git_checkout_or_missing_database(self):
        (self.root/".git").mkdir()
        with self.assertRaisesRegex(ValueError,"archive directory"):
            upgrade_archive(self.root,self.archive,db_path=self.database,runner=self.runner)
        (self.root/".git").rmdir()
        with self.assertRaisesRegex(ValueError,"regular file"):
            upgrade_archive(self.root,self.archive,db_path=self.base/"missing.db",runner=self.runner)


if __name__=="__main__":
    unittest.main()
