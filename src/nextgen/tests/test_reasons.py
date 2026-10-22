"""Standalone offline reason registry tests."""
import unittest
from src.nextgen.reasons import REGISTRY, display_reason, safe_details

class ReasonTests(unittest.TestCase):
    def test_catalog_is_consistent(self):
        for key, reason in REGISTRY.items():
            self.assertEqual(key, reason.code)
            self.assertIn(reason.severity, {"WARNING", "ERROR", "INFO", "CRITICAL"})
            self.assertTrue(reason.description and reason.message and reason.action)
            self.assertIs(type(reason.retryable), bool)

    def test_plain_language_and_unknown_fallback(self):
        view = display_reason("IDENTITY_INCOMPLETE")
        self.assertIn("identification", view["message"])
        self.assertEqual(display_reason("FUTURE_CODE")["retryable"], None)

    def test_details_are_safe_and_bounded(self):
        result = safe_details(missing_fields=["anime.title", "anime.title"],
                              retry_at_ms=1234)
        self.assertEqual(result["missing_fields"], ["anime.title"])
        for field in ("password", "webhook.body", "token"):
            with self.assertRaises(ValueError):
                safe_details(missing_fields=[field])
        with self.assertRaises(ValueError):
            safe_details(missing_fields=["anime.title"] * 21)

if __name__ == "__main__":
    unittest.main()
