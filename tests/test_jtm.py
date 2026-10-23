import importlib.util
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("collector", Path(__file__).resolve().parents[1] / "scripts/collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)


class JtmTests(unittest.TestCase):
    def mining(self, **changes):
        row = {"adapter": "jetsam", "available": True, "stale": False, "error": None,
               "updatedAt": time.time() * 1000, "address": collect.load_config()["jtm_address"],
               "hashrate": 12340, "displayHashrate": 12340, "averages": {"m10": 11000},
               "onlineWorkers": 1, "accepted": 14, "rejected": None, "lastShare": time.time() * 1000,
               "workers": [{"name": "jtm-computer", "online": True, "status": "active",
                            "displayHashrate": 12340, "deviceModel": "Xeon 8360Y", "platform": "towerminer",
                            "id": "private-session", "ip": "192.0.2.9", "key": "secret"}]}
        return dict(row, **changes)

    def test_units_and_nullable_reject_count(self):
        result = collect.parse_jtm_balance({"adapter": "jetsam", "symbol": "JTM", "updatedAt": time.time()*1000,
                     "balance": {"available": "1234567", "immature": "5", "reserved": "123", "paid": "2000000"}})
        self.assertEqual(result["balance"], 1.234567)
        self.assertEqual(result["pending"], 0.000005)
        self.assertEqual(result["reserved"], 0.000123)
        self.assertEqual(result["paid_total"], 2)
        self.assertIsNone(collect.parse_jtm_mining(self.mining())["rejected"])

    def test_public_fields_and_offline_status(self):
        row = self.mining()
        row["workers"][0]["online"] = False
        row["workers"][0]["status"] = "offline"
        result = collect.parse_jtm_mining(row)
        self.assertFalse(result["workers"][0]["online"])
        for secret in ("private-session", "192.0.2.9", '"key"', '"ip"'):
            self.assertNotIn(secret, json.dumps(result))

    def test_invalid_or_stale_responses_are_not_healthy(self):
        for changes in ({"available": False}, {"stale": True}, {"error": "backend"}, {"workers": None},
                        {"updatedAt": 0}, {"updatedAt": (time.time()+600)*1000}, {"hashrate": -1}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                collect.parse_jtm_mining(self.mining(**changes))
        with self.assertRaises(ValueError):
            collect.parse_jtm_balance({"adapter": "jetsam", "symbol": "JTM", "updatedAt": time.time()*1000,
                                      "balance": {"available": "0", "paid": "0"}})

    def test_upstream_time_and_stale_fallback(self):
        row = self.mining(updatedAt=(time.time()-1800)*1000)
        with patch.object(collect, "request_json", return_value=row):
            result = collect.collect_source("jtm_mining", "https://example.invalid", collect.parse_jtm_mining)
        self.assertEqual(result["state"], "stale")
        self.assertLess(result["updated_at"], result["checked_at"])

    def test_wrong_address_is_not_accepted(self):
        config = collect.load_config()
        url, parser = collect.source_specs(config)["jtm_mining"]
        self.assertIn(config["jtm_address"], url)
        with self.assertRaises(ValueError):
            parser(self.mining(address="j1someoneelse"))


if __name__ == "__main__":
    unittest.main()
