import os
import sys
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from services.integration_runtime import IntegrationRuntime, HISTORY_MAX_ENTRIES  # noqa: E402


class TestIntegrationRuntimePaused(unittest.TestCase):
    def test_paused_defaults_to_false(self):
        runtime = IntegrationRuntime()
        snapshot = runtime.snapshot()
        self.assertFalse(snapshot["providers"]["massive"]["paused"])

    def test_paused_provider_is_not_enabled_for_fetches(self):
        runtime = IntegrationRuntime()
        self.assertTrue(runtime.is_enabled("massive"))

        runtime.update_provider("massive", paused=True)
        self.assertFalse(runtime.is_enabled("massive"))

        snapshot = runtime.snapshot()
        self.assertTrue(snapshot["providers"]["massive"]["enabled"])
        self.assertTrue(snapshot["providers"]["massive"]["paused"])

    def test_unpausing_restores_enabled_fetches(self):
        runtime = IntegrationRuntime()
        runtime.update_provider("massive", paused=True)
        self.assertFalse(runtime.is_enabled("massive"))

        runtime.update_provider("massive", paused=False)
        self.assertTrue(runtime.is_enabled("massive"))

    def test_paused_is_independent_of_enabled(self):
        runtime = IntegrationRuntime()
        runtime.update_provider("massive", enabled=False, paused=True)
        snapshot = runtime.snapshot()
        self.assertFalse(snapshot["providers"]["massive"]["enabled"])
        self.assertTrue(snapshot["providers"]["massive"]["paused"])

        runtime.update_provider("massive", enabled=True)
        snapshot = runtime.snapshot()
        self.assertTrue(snapshot["providers"]["massive"]["enabled"])
        self.assertTrue(snapshot["providers"]["massive"]["paused"])
        self.assertFalse(runtime.is_enabled("massive"))

    def test_paused_respects_provider_aliases(self):
        runtime = IntegrationRuntime()
        runtime.update_provider("polygon", paused=True)
        self.assertFalse(runtime.is_enabled("massive"))
        self.assertTrue(runtime.snapshot()["providers"]["massive"]["paused"])

    def test_unknown_provider_update_returns_false(self):
        runtime = IntegrationRuntime()
        self.assertFalse(runtime.update_provider("not_a_real_provider", paused=True))


class TestIntegrationRuntimeHistory(unittest.TestCase):
    def test_history_starts_empty(self):
        runtime = IntegrationRuntime()
        history = runtime.get_history("massive")
        self.assertEqual(history["errors"], [])
        self.assertEqual(history["response_times"], [])

    def test_unknown_provider_history_returns_none(self):
        runtime = IntegrationRuntime()
        self.assertIsNone(runtime.get_history("not_a_real_provider"))

    def test_record_response_time_appends_entry(self):
        runtime = IntegrationRuntime()
        runtime.record_response_time("massive", 123.456)
        history = runtime.get_history("massive")
        self.assertEqual(len(history["response_times"]), 1)
        entry = history["response_times"][0]
        self.assertEqual(entry["elapsed_ms"], 123.46)
        self.assertIn("timestamp", entry)

    def test_record_error_appends_entry(self):
        runtime = IntegrationRuntime()
        runtime.record_error("massive", "boom")
        history = runtime.get_history("massive")
        self.assertEqual(len(history["errors"]), 1)
        self.assertEqual(history["errors"][0]["message"], "boom")
        self.assertIn("timestamp", history["errors"][0])

    def test_history_is_bounded_and_keeps_most_recent(self):
        runtime = IntegrationRuntime()
        total = HISTORY_MAX_ENTRIES + 5
        for i in range(total):
            runtime.record_response_time("massive", float(i))
            runtime.record_error("massive", f"error-{i}")

        history = runtime.get_history("massive")
        self.assertEqual(len(history["response_times"]), HISTORY_MAX_ENTRIES)
        self.assertEqual(len(history["errors"]), HISTORY_MAX_ENTRIES)

        # Oldest entries should have been evicted; the tail should be the most recent ones.
        self.assertEqual(history["response_times"][-1]["elapsed_ms"], float(total - 1))
        self.assertEqual(history["errors"][-1]["message"], f"error-{total - 1}")
        self.assertEqual(history["response_times"][0]["elapsed_ms"], float(total - HISTORY_MAX_ENTRIES))

    def test_history_is_isolated_per_provider(self):
        runtime = IntegrationRuntime()
        runtime.record_error("massive", "massive failed")
        runtime.record_response_time("binance", 50.0)

        massive_history = runtime.get_history("massive")
        binance_history = runtime.get_history("binance")

        self.assertEqual(len(massive_history["errors"]), 1)
        self.assertEqual(len(massive_history["response_times"]), 0)
        self.assertEqual(len(binance_history["errors"]), 0)
        self.assertEqual(len(binance_history["response_times"]), 1)


if __name__ == "__main__":
    unittest.main()
