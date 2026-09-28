import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("collect", Path(__file__).resolve().parents[1] / "scripts/collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)


class AccountingTests(unittest.TestCase):
    def test_prl_excludes_other_coin_and_manual_debits_from_payouts(self):
        result = collect.parse_prl_pool({"balance_transactions": [
            {"coin_type":"pearl", "amount":4.5, "timestamp":1000, "reason":"Epoch credit"},
            {"coin_type":"pearl", "amount":-2, "timestamp":2000, "reason":"Auto Payment"},
            {"coin_type":"pearl", "amount":-0.5, "timestamp":3000, "reason":"Manual adjustment"},
            {"coin_type":"mdl", "amount":900, "timestamp":4000, "reason":"Epoch credit"}],
            "pending_rewards":{"total_pending_prl":0.7}, "connected_workers":[]})
        self.assertEqual(result["balance"], 2)
        self.assertEqual(result["paid_total"], 2)
        self.assertEqual(result["pending"], 0.7)

    def test_chain_uses_external_receipts_not_change(self):
        result = collect.parse_prl_chain({"balance_grains":22038089717, "received_grains":54520736667,
            "external_received_grains":54267227941, "external_sent_grains":32229138224, "tx_count":418})
        self.assertAlmostEqual(result["balance"], 220.38089717)
        self.assertAlmostEqual(result["received_total"], 542.67227941)

    def test_nock_units_and_not_found_are_not_zero(self):
        result = collect.parse_nock_chain({"currentBalance":65536, "totalReceived":131072, "totalSent":65536})
        self.assertEqual(result["balance"],1)
        self.assertEqual(result["received_total"],2)
        empty=collect.parse_nock_chain({"_address_not_found":True})
        self.assertIsNone(empty["balance"])
        self.assertTrue(empty["address_not_found"])

    def test_worker_public_fields_exclude_ip_and_ids(self):
        result=collect.parse_prl_pool({"balance_transactions":[], "pending_rewards":{"total_pending_prl":0},
            "connected_workers":[{"ip":"192.0.2.42", "worker_id":1234, "worker_name":"mine", "version":"v1",
                                  "gpu_info":[{"name":"A100", "hashrate":2e14}]}]})
        self.assertEqual(result["hashrate"],2e14)
        encoded=json.dumps(result)
        self.assertNotIn("192.0.2.42",encoded)
        self.assertNotIn("worker_id",encoded)

    def test_bad_schema_does_not_show_zero_or_healthy(self):
        with patch.object(collect,"request_json",return_value={"error":"temporarily unavailable"}):
            result=collect.collect_source("prl_pool","https://example.invalid",collect.parse_prl_pool)
        self.assertEqual(result["state"],"unavailable")
        self.assertIsNone(result["data"])

    def test_failed_request_retains_last_success_timestamp(self):
        old={"data":{"balance":4},"updated_at":"2026-09-27T00:00:00Z"}
        with patch.object(collect,"request_json",side_effect=TimeoutError):
            result=collect.collect_source("prl_chain","https://example.invalid",collect.parse_prl_chain,old)
        self.assertEqual(result["state"],"stale")
        self.assertEqual(result["updated_at"],old["updated_at"])
        self.assertEqual(result["data"]["balance"],4)

    def test_transactions_exclude_change_and_orphaned_blocks(self):
        row={"txid":"a"*64,"received_grains":200000000,"sent_grains":0,"time":"2026-09-28T00:00:00Z",
             "canonical":True,"status":"confirmed","type_label":"PearlHash payout"}
        result=collect.parse_prl_txs({"items":[row,dict(row,sent_grains=300000000),dict(row,canonical=False)]})
        self.assertEqual(len(result["transactions"]),1)
        self.assertEqual(result["transactions"][0]["amount"],2)

    def test_changed_wallet_cannot_reuse_old_balances(self):
        config=collect.load_config()
        previous={"config":dict(config,nock_address="different"),"sources":{"prl_chain":{"data":{"balance":99}}}}
        with patch.object(collect,"request_json",side_effect=TimeoutError):
            result=collect.build_snapshot(config,previous)
        self.assertIsNone(result["sources"]["prl_chain"]["data"])

    def test_nan_is_rejected(self):
        for value in ("nan", "Infinity", None, True):
            with self.assertRaises(ValueError):collect.amount(value)

    def test_price_ids_currency_and_timestamp(self):
        row={"usd":1.39,"cny":9.3,"usd_24h_change":-4.8,"last_updated_at":1700000000}
        result=collect.parse_prices({"pearl-2":row,"nockchain":dict(row,usd=0.024,cny=0.16),
                                     "pearl":{"usd":100000}})
        self.assertEqual(result["quotes"]["PRL"]["usd"],1.39)
        self.assertEqual(result["quotes"]["NOCK"]["cny"],0.16)
        self.assertEqual(result["quotes"]["PRL"]["change_24h"],-4.8)
        self.assertEqual(result["quotes"]["PRL"]["updated_at"],"2023-11-14T22:13:20Z")

    def test_missing_quote_is_unknown_not_zero(self):
        result=collect.parse_prices({"pearl-2":{"usd":2,"cny":14,"last_updated_at":1700000000,"usd_24h_change":None}})
        self.assertIsNone(result["quotes"]["NOCK"])
        self.assertIsNone(result["quotes"]["PRL"]["change_24h"])
        for value in (-1,0,None,"nan"):
            with self.assertRaises(ValueError):
                collect.parse_prices({"pearl-2":{"usd":value,"cny":14,"last_updated_at":1700000000}})

    def test_price_freshness_uses_quote_timestamp_not_request_time(self):
        body={"pearl-2":{"usd":2,"cny":14,"last_updated_at":1700000000}}
        with patch.object(collect,"request_json",return_value=body):
            result=collect.collect_source("prices","https://example.invalid",collect.parse_prices)
        self.assertEqual(result["state"],"stale")
        self.assertEqual(result["updated_at"],"2023-11-14T22:13:20Z")


if __name__ == "__main__":
    unittest.main()
