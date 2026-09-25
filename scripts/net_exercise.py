#!/usr/bin/env python3
"""
Breek Market -- drive a deployed contract from the command line.

The ``genlayer`` CLI (0.39.2) cannot do two things this contract needs:

* attach native GEN to a call, so ``take_position`` is unreachable from it;
* encode an empty string, so ``create_market`` for the REL kinds is unreachable.

This script does both through ``genlayer-py``. It never resolves a market for
you by injecting anything -- ``resolve_market`` takes only a market id, and the
contract fetches its own prices.

The signing key comes from the ``BREEK_PRIVATE_KEY`` environment variable. It is
never written to disk, echoed, or sent anywhere except to sign a transaction for
the network you selected.

Usage::

    export BREEK_PRIVATE_KEY=0x...
    python scripts/net_exercise.py --address 0xC69e... catalog
    python scripts/net_exercise.py --address 0xC69e... create REL_DAILY CRYPTO "" DAILY 2026-09-28
    python scripts/net_exercise.py --address 0xC69e... stake 1 UP 2
    python scripts/net_exercise.py --address 0xC69e... resolve 1
    python scripts/net_exercise.py --address 0xC69e... claim 1
    python scripts/net_exercise.py --address 0xC69e... queue
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
        result = first.get("result") or {}
        payload = result.get("payload")
        if isinstance(payload, dict):
            print("  returned : %s" % payload.get("readable"))
    print("  status   : %s" % receipt.get("status_name", receipt.get("status")))
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description="Drive a deployed Breek Market contract")
    ap.add_argument("--address", required=True, help="deployed contract address")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog")
    sub.add_parser("stats")
    sub.add_parser("queue", help="markets that are ready to settle")

    p = sub.add_parser("list")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("market")
    p.add_argument("market_id", type=int)

    p = sub.add_parser("evidence")
    p.add_argument("market_id", type=int)

    p = sub.add_parser("create")
    p.add_argument("kind")
    p.add_argument("category")
    p.add_argument("asset", help='catalog symbol, or "" for the REL kinds')
    p.add_argument("timeframe")
    p.add_argument("window_id")

    p = sub.add_parser("stake")
    p.add_argument("market_id", type=int)
    p.add_argument("side")
    p.add_argument("gen", type=int, help="whole GEN, 2 to 4")

    p = sub.add_parser("resolve")
    p.add_argument("market_id", type=int)

    p = sub.add_parser("claim")
    p.add_argument("market_id", type=int)

    p = sub.add_parser("position")
    p.add_argument("market_id", type=int)
    p.add_argument("--who")

    args = ap.parse_args()
    client, account = build_client()
    addr = args.address

    read_only = {
        "catalog": ("get_catalog", []),
        "stats": ("get_stats", []),
        "queue": ("list_resolvable", [10]),
    }
    if args.cmd in read_only:
        fn, fn_args = read_only[args.cmd]
        show(args.cmd, client.read_contract(address=addr, function_name=fn, args=fn_args))
        return 0

    if args.cmd == "list":
        show("markets", client.read_contract(
            address=addr, function_name="list_markets", args=[args.offset, args.limit]))
        return 0

    if args.cmd == "market":
        show("market %d" % args.market_id, client.read_contract(
            address=addr, function_name="get_market", args=[args.market_id]))
        return 0

    if args.cmd == "evidence":
        show("evidence %d" % args.market_id, client.read_contract(
            address=addr, function_name="get_evidence", args=[args.market_id]))
        return 0

    if args.cmd == "position":
        who = args.who or account.address
        show("position", client.read_contract(
            address=addr, function_name="get_position", args=[args.market_id, who]))
        return 0

    if args.cmd == "create":
        print("create_market(%s, %s, %r, %s, %s)" % (
            args.kind, args.category, args.asset, args.timeframe, args.window_id))
        wait(client, client.write_contract(
            address=addr,
            function_name="create_market",
            args=[args.kind, args.category, args.asset, args.timeframe, args.window_id],
            value=0,
        ))
        return 0

    if args.cmd == "stake":
        if not 2 <= args.gen <= 4:
            print("stake must be 2, 3 or 4 GEN -- anything else is refunded on chain")
        value = args.gen * GEN
        print("take_position(%d, %s) with %d wei" % (args.market_id, args.side, value))
        wait(client, client.write_contract(
            address=addr,
            function_name="take_position",
            args=[args.market_id, args.side],
            value=value,
        ))
        show("position", client.read_contract(
            address=addr, function_name="get_position",
            args=[args.market_id, account.address]))
        return 0

    if args.cmd == "resolve":
        print("resolve_market(%d) -- the contract fetches its own prices" % args.market_id)
        wait(client, client.write_contract(
            address=addr, function_name="resolve_market",
            args=[args.market_id], value=0))
        show("evidence", client.read_contract(
            address=addr, function_name="get_evidence", args=[args.market_id]))
        return 0

    if args.cmd == "claim":
        wait(client, client.write_contract(
            address=addr, function_name="claim", args=[args.market_id], value=0))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
