#!/usr/bin/env python3
"""Collect public, read-only mining data; never publish raw upstream responses."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "Mozilla/5.0 (compatible; PersonalMiningMonitor/1.0)"
PRICE_URL = ("https://api.coingecko.com/api/v3/simple/price?ids=pearl-2,nockchain"
             "&vs_currencies=usd,cny&include_24hr_change=true&include_last_updated_at=true")


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def amount(value, divisor=1):
    if isinstance(value, bool):
        raise ValueError("Invalid numeric value")
    try:
        number = Decimal(str(value)) / Decimal(divisor)
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid numeric value") from None
    if not number.is_finite():
        raise ValueError("Non-finite numeric value")
    return float(number)


def total(values):
    return float(sum((Decimal(str(v)) for v in values), Decimal(0)))


def stamp(value):
    return datetime.fromtimestamp(amount(value) / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def load_config():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"prl1[a-z0-9]{20,100}", config["prl_address"]):
        raise ValueError("Invalid PRL address")
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{30,100}", config["nock_address"]):
        raise ValueError("Invalid NOCK address")
    return config


def request_json(url, allow_empty_address=False):
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=18) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise ValueError("Unexpected response schema")
            return result
        except urllib.error.HTTPError as exc:
            if allow_empty_address and exc.code == 404:
                try:
                    body = json.loads(exc.read())
                except (ValueError, UnicodeError):
                    body = {}
                if body.get("error") == "Address not found":
                    return {"_address_not_found": True}
            if exc.code < 500 and exc.code != 429:
                raise
            if attempt:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt:
                raise
        time.sleep(1)


def ledger_summary(data, coin):
    rows = data["balance_transactions"]
    if not isinstance(rows, list):
        raise ValueError("Invalid ledger")
    rows = [r for r in rows if r.get("coin_type", coin) == coin]
    payments = []
    credits = []
    for row in rows:
        value = amount(row["amount"])
        reason = str(row.get("reason", "")).lower()
        if value < 0 and ("payment" in reason or "payout" in reason):
            payments.append({"amount": -value, "time": stamp(row["timestamp"])})
        if value > 0:
            credits.append({"amount": value, "time": stamp(row["timestamp"])})
    return {
        "balance": amount(data["balance"]) if coin == "nock" else total(amount(r["amount"]) for r in rows),
        "paid_total": total(p["amount"] for p in payments),
        "payments": sorted(payments, key=lambda r: r["time"], reverse=True)[:12],
        "last_credit_at": max((r["time"] for r in credits), default=None),
    }


def parse_prl_pool(data):
    result = ledger_summary(data, "pearl")
    result["pending"] = amount(data["pending_rewards"]["total_pending_prl"])
    result["nock_payout_address"] = data.get("nock_payout_address")
    workers = data["connected_workers"]
    if not isinstance(workers, list):
        raise ValueError("Invalid workers")
    result["workers"] = [{
        "name": str(w.get("worker_name", "未命名矿工"))[:80],
        "version": str(w.get("version", "未知"))[:80],
        "gpus": [{"name": str(g.get("name", "未知显卡"))[:80], "hashrate": amount(g["hashrate"])}
                 for g in w.get("gpu_info", [])],
    } for w in workers]
    result["hashrate"] = total(g["hashrate"] for w in result["workers"] for g in w["gpus"])
    return result


def parse_nock_pool(data):
    result = ledger_summary(data, "nock")
    result["pending"] = amount(data["pending_rewards"]["total_pending"])
    return result


def parse_prl_chain(data):
    return {
        "balance": amount(data["balance_grains"], 100_000_000),
        "received_total": amount(data["external_received_grains"], 100_000_000),
        "sent_total": amount(data["external_sent_grains"], 100_000_000),
        "last_activity_at": data.get("last_seen_at"),
        "transaction_count": int(data["tx_count"]),
    }


def parse_prl_txs(data):
    rows = []
    for row in data["items"]:
        # Exclude outgoing/self-change and non-canonical transactions.
        if amount(row["sent_grains"]) != 0 or amount(row["received_grains"]) <= 0:
            continue
        if row.get("canonical") is not True or row.get("status") != "confirmed":
            continue
        txid = row["txid"]
        if not re.fullmatch(r"[0-9a-f]{64}", txid):
            raise ValueError("Invalid transaction id")
        rows.append({"amount": amount(row["received_grains"], 100_000_000), "time": row["time"],
                     "txid": txid, "label": "矿池付款" if "payout" in str(row.get("type_label", "")).lower() else "链上转入",
                     "url": "https://www.prlscan.com/tx/" + txid})
    return {"transactions": sorted(rows, key=lambda r: r["time"], reverse=True)[:12], "window": "最近 50 笔交易中的转入"}


def parse_nock_chain(data):
    if data.get("_address_not_found"):
        return {"balance": None, "received_total": None, "sent_total": None,
                "transactions": [], "address_not_found": True}
    rows = []
    for row in data.get("transactions", []):
        if row.get("type") != "received":
            continue
        txid = str(row.get("txId", ""))
        entry = {"amount": amount(row["amount"], 65536), "time": stamp(amount(row["timestamp"]) * 1000),
                 "txid": txid, "label": "链上转入"}
        # Link the documented address page; synthetic coinbase IDs aren't tx IDs.
        rows.append(entry)
    return {"balance": amount(data["currentBalance"], 65536),
            "received_total": amount(data["totalReceived"], 65536),
            "sent_total": amount(data["totalSent"], 65536),
            "transactions": sorted(rows, key=lambda r: r["time"], reverse=True)[:12],
            "address_not_found": False}


def parse_prices(data):
    quotes = {}
    for coin, coin_id in (("PRL", "pearl-2"), ("NOCK", "nockchain")):
        row = data.get(coin_id)
        if not row:
            quotes[coin] = None
            continue
        usd, cny = amount(row["usd"]), amount(row["cny"])
        updated = amount(row["last_updated_at"])
        if usd <= 0 or cny <= 0 or updated <= 0 or updated > time.time() + 300:
            raise ValueError("Invalid price or quote timestamp")
        quotes[coin] = {"usd": usd, "cny": cny,
                        "change_24h": amount(row["usd_24h_change"]) if row.get("usd_24h_change") is not None else None,
                        "updated_at": stamp(updated * 1000)}
    if not any(quotes.values()):
        raise ValueError("No supported coin prices returned")
    return {"provider": "CoinGecko", "quotes": quotes}


def source_specs(config):
    prl, nock = config["prl_address"], config["nock_address"]
    return {
        "prl_pool": (f"https://pearlhash.xyz/api/account/{prl}", parse_prl_pool),
        "nock_pool": (f"https://pearlhash.xyz/api/nock-balance/{prl}", parse_nock_pool),
        "prl_chain": (f"https://api.prlscan.com/v1/addresses/{prl}", parse_prl_chain),
        "prl_txs": (f"https://api.prlscan.com/v1/addresses/{prl}/txs?limit=50", parse_prl_txs),
        "nock_chain": (f"https://nockscan.com/api/v1/address/{nock}?limit=50", parse_nock_chain),
        "prices": (PRICE_URL, parse_prices),
    }


def collect_source(key, url, parser, previous=None):
    checked = utcnow()
    try:
        data = parser(request_json(url, allow_empty_address=(key == "nock_chain")))
        if key == "prices":
            updated = min(q["updated_at"] for q in data["quotes"].values() if q)
            stale = time.time() - datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp() > 900
            return {"state": "stale" if stale else "ok", "data": data, "updated_at": updated,
                    "checked_at": checked, "error": "Quote is over 15 minutes old" if stale else None}
        return {"state": "empty" if data.get("address_not_found") else "ok", "data": data,
                "updated_at": checked, "checked_at": checked, "error": None}
    except Exception as exc:
        message = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
        previous = previous or {}
        return {"state": "stale" if previous.get("data") is not None else "unavailable",
                "data": previous.get("data"), "updated_at": previous.get("updated_at"),
                "checked_at": checked, "error": message}


def build_snapshot(config, previous=None):
    previous = previous or {}
    # Never reuse a previous wallet's balances after configuration changes.
    old_sources = previous.get("sources", {}) if previous.get("config") == config else {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        tasks = {k: executor.submit(collect_source, k, url, parser, old_sources.get(k))
                 for k, (url, parser) in source_specs(config).items()}
        sources = {k: task.result() for k, task in tasks.items()}
    return {"schema_version": 1, "generated_at": utcnow(), "config": config, "sources": sources}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "site/data/status.json")
    parser.add_argument("--previous-url")
    args = parser.parse_args()
    config = load_config()
    previous = None
    if args.output.exists():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if args.previous_url:
        try:
            previous = request_json(args.previous_url)
        except Exception:
            pass
    snapshot = build_snapshot(config, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({k: v["state"] for k, v in snapshot["sources"].items()}))


if __name__ == "__main__":
    main()
