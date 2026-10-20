"""Fail-closed ffprobe language regression tests.

Exercise the actual JP+EN parser and both the source and staged-file gates.
No media downloads or external ffprobe invocation: subprocess runner is injected.
"""
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from anime_audio_verification import audio_languages, confirmed_jp_en
from anime_source_retention import retain_recovery_record


def probe_runner(streams, *, error=None, observed=None):
    def run(args, **kwargs):
        if observed is not None:
            observed.append((args,kwargs))
        if error is not None:
            raise error
        return SimpleNamespace(stdout=json.dumps({"streams":streams}))
    return run


def streams(*languages):
    return [{"index":i,"tags":({"language":lang} if lang is not None else {})}
            for i,lang in enumerate(languages)]


class FFprobeAudioGateTests(unittest.TestCase):
    def test_dual_audio_accepts_iso_639_variants(self):
        for japanese,english in (("jpn","eng"),("ja","en"),
                                 ("JPN","ENG"),("ja","eng")):
            with self.subTest(japanese=japanese,english=english):
                observed=[]
                self.assertTrue(confirmed_jp_en("/tmp/source.mkv",
                    runner=probe_runner(streams(japanese,english),observed=observed)))
                args,options=observed[0]
                self.assertEqual(args[0],"ffprobe")
                self.assertEqual(args[args.index("-select_streams")+1],"a")
                self.assertIn("stream_tags=language",args)
                self.assertEqual(args[-1],"/tmp/source.mkv")
                self.assertTrue(options["check"])
                self.assertEqual(options["timeout"],30)

    def test_one_language_only_or_missing_tags_is_rejected(self):
        for languages in (("jpn",),("eng",),("jpn","und"),
                          ("en",None),(None,None),()):
            with self.subTest(languages=languages):
                self.assertFalse(confirmed_jp_en("episode.mkv",
                    runner=probe_runner(streams(*languages))))

    def test_subtitle_languages_cannot_satisfy_audio_requirement(self):
        # -select_streams a restricts ffprobe to audio; irrelevant subtitle
        # metadata never enters the returned audio streams.
        self.assertFalse(confirmed_jp_en("episode.mkv",
            runner=probe_runner(streams("jpn"))))

    def test_probe_failure_or_invalid_json_never_approves(self):
        with self.assertRaises(subprocess.CalledProcessError):
            confirmed_jp_en("episode.mkv",runner=probe_runner([],
                error=subprocess.CalledProcessError(1,["ffprobe"])))
        with self.assertRaises(subprocess.TimeoutExpired):
            confirmed_jp_en("episode.mkv",runner=probe_runner([],
                error=subprocess.TimeoutExpired(["ffprobe"],30)))
        with self.assertRaises(ValueError):
            audio_languages("episode.mkv",runner=lambda *a,**kw:
                SimpleNamespace(stdout='{"streams": null}'))
        with self.assertRaises(json.JSONDecodeError):
            confirmed_jp_en("episode.mkv",runner=lambda *a,**kw:
                SimpleNamespace(stdout="corrupt JSON"))

    def test_staged_copy_is_reprobed_before_recovery_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"source.mkv"
            staged=root/"staged.mkv"
            source.write_bytes(b"identical bytes")
            staged.write_bytes(source.read_bytes())
            db=sqlite3.connect(":memory:",isolation_level=None)
            self.addCleanup(db.close)
            # Refuse a source/staged pair whose staged audio check fails.
            with patch("anime_source_retention.confirmed_jp_en",
                       side_effect=lambda path:path==source) as checker:
                with self.assertRaisesRegex(ValueError,"Japanese and English"):
                    retain_recovery_record(db,infohash="a"*40,
                        magnet_uri="magnet:?xt=urn:btih:"+"a"*40,
                        source=source,staged=staged,notification_id=1)
                checker.assert_called_once_with(staged)
            self.assertFalse(db.execute("""SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='torrent_recovery_records'""").fetchone())

if __name__=="__main__":
    unittest.main()
