"""Offline configuration/diagnostics tests; no systemd, network or CI."""
import io
import logging
import unittest

from src.nextgen.settings import Settings, parse_settings
from src.nextgen.diagnostics import TRACE, SafeFormatter, configure_logging, event, redact, Span

class FoundationTests(unittest.TestCase):
    def test_defaults_and_override(self):
        config = parse_settings({"logging": {"level": "INFO",
                          "components": {"coordinator": "TRACE"}}})
        self.assertEqual(config.logging.level_for("coordinator"), "TRACE")
        self.assertEqual(config.logging.level_for("intake"), "INFO")
        self.assertEqual(Settings().logging.level, "INFO")

    def test_reject_unrecognized_settings(self):
        for config in ({"logging": {"level": "verbose"}},
                       {"logging": {"components": {"unknown": "TRACE"}}},
                       {"logging": {"components": {"intake": "oops"}}},
                       {"logging": {"quietly_disable_redaction": True}},
                       {"unexpected": {}}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                parse_settings(config)

    def test_redaction_even_at_trace(self):
        stream = io.StringIO()
        logger = logging.Logger("nextgen.coordinator.test")
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        configure_logging(parse_settings({"logging": {"level": "TRACE"}}),
                          "coordinator", logger=logger)
        self.assertEqual(logger.level, TRACE)
        logger.log(TRACE, "authorization: abc123 password=hidden https://alice:pass@example.org")
        content = stream.getvalue()
        self.assertNotIn("abc123", content)
        self.assertNotIn("hidden", content)
        self.assertNotIn("alice:pass", content)

    def test_metadata_allowlist(self):
        stream = io.StringIO()
        logger = logging.Logger("nextgen.safe.test")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(SafeFormatter("%(message)s"))
        logger.addHandler(handler)
        event(logger, logging.INFO, "JOB_RETRY", job_id=42, attempt=2,
              retryable=True, raw_body="never log this")
        output = stream.getvalue()
        self.assertIn("job_id=42", output)
        self.assertNotIn("never log this", output)

    def test_span(self):
        self.assertGreaterEqual(Span().milliseconds(), 0)

if __name__ == "__main__":
    unittest.main()
