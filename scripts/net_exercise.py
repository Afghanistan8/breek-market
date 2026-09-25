#!/usr/bin/env python3
"""
Breek -- drive a deployed contract from the command line.

The ``genlayer`` CLI (0.39.2) cannot attach native GEN to a call, so
``submit_forecast`` is unreachable from it. This script does that through
``genlayer-py``. It never prices a round by supplying a number --
``score_round`` takes a round id and the contract fetches its own feeds.

The signing key comes from the ``BREEK_PRIVATE_KEY`` environment variable. It is
never written to disk, echoed, or sent anywhere except to sign a transaction for
the network you selected.

Usage::

    export BREEK_PRIVATE_KEY=0x...
    python scripts/net_exercise.py --address 0x2b5c... catalog
    python scripts/net_exercise.py --address 0x2b5c... open CRYPTO SOL DAILY 2026-09-29
    python scripts/net_exercise.py --address 0x2b5c... enter 1 118.40
    python scripts/net_exercise.py --address 0x2b5c... revise 1 117.95
    python scripts/net_exercise.py --address 0x2b5c... score 1
    python scripts/net_exercise.py --address 0x2b5c... board 1
    python scripts/net_exercise.py --address 0x2b5c... collect 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys

GEN = 10**18


def build_client():
    from genlayer_py import create_client
    from genlayer_py.chains import studionet

    key = os.environ.get("BREEK_PRIVATE_KEY", "").strip()
    if not key:
        print("BREEK_PRIVATE_KEY is not set.")
        print("Export the key for the account you want to sign with, then retry.")
        sys.exit(2)

    from eth_account import Account

    account = Account.from_key(key)
    print("signing as %s" % account.address.lower())
    return create_client(chain=studionet, account=account), account


def show(label, value):
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def wait(client, tx_hash):
    print("tx %s" % tx_hash)
    receipt = client.wait_for_transaction_receipt(
        transaction_hash=tx_hash, status="FINALIZED", retries=200, interval=5000
    )
    leader = (receipt.get("consensus_data") or {}).get("leader_receipt") or []
    if leader:
        first = leader[0]
        print("  execution: %s" % first.get("execution_result"))
        payload = (first.get("result") or {}).get("payload")
        if isinstance(payload, dict):
            print("  returned : %s" % payload.get("readable"))
    print("  status   : %s" % receipt.get("status_name", receipt.get("status")))
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description="Drive a deployed Breek contract")
    ap.add_argument("--address", required=True, help="deployed contract address")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog")
    sub.add_parser("stats")
    sub.add_parser("queue", help="rounds whose window has closed but are unscored")

    p = sub.add_parser("list")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=10)

    for name in ("round", "evidence", "board", "score", "collect"):
        p = sub.add_parser(name)
        p.add_argument("round_id", type=int)

    p = sub.add_parser("open")
    p.add_argument("category")
    p.add_argument("asset")
    p.add_argument("timeframe")
    p.add_argument("window_id")

    p = sub.add_parser("enter")
    p.add_argument("round_id", type=int)
    p.add_argument("forecast", help="price as a decimal string, e.g. 118.40")

    p = sub.add_parser("revise")
    p.add_argument("round_id", type=int)
    p.add_argument("forecast")

    p = sub.add_parser("entry")
    p.add_argument("round_id", type=int)
    p.add_argument("--who")

    args = ap.parse_args()
    client, account = build_client()
    addr = args.address

    reads = {
        "catalog": ("get_catalog", []),
        "stats": ("get_stats", []),
        "queue": ("list_scoreable", [10]),
    }
    if args.cmd in reads:
        fn, fn_args = reads[args.cmd]
        show(args.cmd, client.read_contract(address=addr, function_name=fn, args=fn_args))
        return 0

    if args.cmd == "list":
        show("rounds", client.read_contract(
            address=addr, function_name="list_rounds", args=[args.offset, args.limit]))
        return 0

    if args.cmd in ("round", "evidence"):
        fn = "get_round" if args.cmd == "round" else "get_evidence"
        show("%s %d" % (args.cmd, args.round_id), client.read_contract(
            address=addr, function_name=fn, args=[args.round_id]))
        return 0

    if args.cmd == "board":
        show("leaderboard %d" % args.round_id, client.read_contract(
            address=addr, function_name="get_leaderboard", args=[args.round_id, 50]))
        return 0

    if args.cmd == "entry":
        who = args.who or account.address
        show("entry", client.read_contract(
            address=addr, function_name="get_entry", args=[args.round_id, who]))
        return 0

    if args.cmd == "open":
        print("open_round(%s, %s, %s, %s)" % (
            args.category, args.asset, args.timeframe, args.window_id))
        wait(client, client.write_contract(
            address=addr, function_name="open_round",
            args=[args.category, args.asset, args.timeframe, args.window_id], value=0))
        return 0

    if args.cmd == "enter":
        fee = int(client.read_contract(
            address=addr, function_name="get_catalog", args=[])["entry_fee_wei"])
        print("submit_forecast(%d, %s) with %d wei" % (args.round_id, args.forecast, fee))
        wait(client, client.write_contract(
            address=addr, function_name="submit_forecast",
            args=[args.round_id, args.forecast], value=fee))
        show("entry", client.read_contract(
            address=addr, function_name="get_entry",
            args=[args.round_id, account.address]))
        return 0

    if args.cmd == "revise":
        wait(client, client.write_contract(
            address=addr, function_name="revise_forecast",
            args=[args.round_id, args.forecast], value=0))
        return 0

    if args.cmd == "score":
        print("score_round(%d) -- the contract fetches its own feeds" % args.round_id)
        wait(client, client.write_contract(
            address=addr, function_name="score_round", args=[args.round_id], value=0))
        show("evidence", client.read_contract(
            address=addr, function_name="get_evidence", args=[args.round_id]))
        return 0

    if args.cmd == "collect":
        wait(client, client.write_contract(
            address=addr, function_name="collect", args=[args.round_id], value=0))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
