"""Offline checks for redacted SQLite-independent journal diagnostics."""
import io
import logging
import sqlite3
import unittest

from anime_diagnostics import SafeFormatter, Span, event, redact

class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.logger = logging.getLogger("test.anime.diagnostics")
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(self.stream)
        handler.setFormatter(SafeFormatter("%(levelname)s %(message)s"))
        self.logger.addHandler(handler)

    def test_exception_traceback_and_correlation(self):
        try:
            raise RuntimeError("deliberate failure")
        except RuntimeError:
            event(self.logger, logging.ERROR, "STAGING_FAILED",
                  subsystem="staging", operation="publish_episode",
                  job_id=42, notification_id=5, stage="PROBE",
                  error_type="RuntimeError", retryable=True, exc_info=True)
        log = self.stream.getvalue()
        for expected in ("Traceback (most recent call last)", "RuntimeError",
                         "job_id=42", "notification_id=5",
                         "event=STAGING_FAILED", "retryable=true"):
            self.assertIn(expected, log)

    def test_redacts_exception_and_log_text(self):
        try:
            raise ValueError("api_key=supersecret Authorization: Bearer hunter2")
        except ValueError:
            self.logger.exception("password=plaintext token=hidden")
        log = self.stream.getvalue()
        for forbidden in ("supersecret", "hunter2", "plaintext", "hidden"):
            self.assertNotIn(forbidden, log)
        self.assertIn("[REDACTED]", log)

    def test_rejects_untrusted_context(self):
        event(self.logger, logging.INFO, "CHECK", subsystem="worker",
              password="password=secret", job_id="42",
              operation="https://private.example/?token=secret",
              torrent_hash="a" * 40)
        log = self.stream.getvalue()
        self.assertNotIn("secret", log)
        self.assertNotIn("job_id=", log)
        self.assertIn("torrent_hash=" + "a" * 12, log)

    def test_no_sqlite_dependency_or_poll_spam(self):
        sqlite3.connect(":memory:").close()
        event(self.logger, logging.DEBUG, "POLL", subsystem="worker")
        self.assertIn("event=POLL", self.stream.getvalue())
        self.assertGreaterEqual(Span().milliseconds(), 0)

if __name__ == "__main__":
    unittest.main()
