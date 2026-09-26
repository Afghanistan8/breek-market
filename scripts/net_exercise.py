#!/usr/bin/env python3
"""
Breek -- drive a deployed contract from the command line.

The ``genlayer`` CLI (0.39.2) cannot attach native GEN to a call, so
``commit_forecast`` is unreachable from it. This script does that through
``genlayer-py``. It never prices a round by supplying a number --
``score_round`` takes a round id and the contract fetches its own feeds.

Entering is a two-step commit-reveal. ``enter`` seals a forecast and prints the
salt; ``reveal`` opens it once entries have closed. The salt is written to
``.breek-reveal.json`` beside the repo as well as printed, because a lost salt
means a commitment that can never be opened and a fee that is forfeited.

The signing key comes from the ``BREEK_PRIVATE_KEY`` environment variable. It is
never written to disk, echoed, or sent anywhere except to sign a transaction for
the network you selected.

Usage::

    export BREEK_PRIVATE_KEY=0x...
    python scripts/net_exercise.py --address 0x2b5c... catalog
    python scripts/net_exercise.py --address 0x2b5c... open CRYPTO SOL DAILY 2026-09-29
    python scripts/net_exercise.py --address 0x2b5c... enter 1 118.40
    python scripts/net_exercise.py --address 0x2b5c... revise 1 117.95
    python scripts/net_exercise.py --address 0x2b5c... reveal 1
    python scripts/net_exercise.py --address 0x2b5c... score 1
    python scripts/net_exercise.py --address 0x2b5c... board 1
    python scripts/net_exercise.py --address 0x2b5c... collect 1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys

GEN = 10**18
PRICE_SCALE = 10**8
REVEAL_STORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".breek-reveal.json")


def scaled_of(text: str) -> int:
    """Decimal string to a PRICE_SCALE integer, matching the contract exactly."""
    t = text.strip().lstrip("+")
    whole, _, frac = t.partition(".")
    if whole == "":
        whole = "0"
    if not whole.isdigit() or (frac != "" and not frac.isdigit()):
        raise SystemExit("not a plain decimal price: %r" % text)
    frac = (frac + "0" * 8)[:8]
    return int(whole) * PRICE_SCALE + int(frac)


def commit_hash(round_id: int, who: str, forecast: str, salt: str) -> str:
    """The commitment. Preimage is published by ``get_catalog``."""
    pre = "c1|%d|%s|%d|%s" % (round_id, who.lower(), scaled_of(forecast), salt)
    return hashlib.sha256(pre.encode("utf-8")).hexdigest()


def remember(round_id: int, who: str, forecast: str, salt: str) -> None:
    store = {}
    if os.path.exists(REVEAL_STORE):
        try:
            with open(REVEAL_STORE, encoding="utf-8") as fh:
                store = json.load(fh)
        except Exception:  # noqa: BLE001
            store = {}
    store["%d:%s" % (round_id, who.lower())] = {"forecast": forecast, "salt": salt}
    with open(REVEAL_STORE, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)


def recall(round_id: int, who: str):
    if not os.path.exists(REVEAL_STORE):
        return None
    try:
        with open(REVEAL_STORE, encoding="utf-8") as fh:
            return json.load(fh).get("%d:%s" % (round_id, who.lower()))
    except Exception:  # noqa: BLE001
        return None


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

    p = sub.add_parser("enter", help="seal a forecast and pay the entry fee")
    p.add_argument("round_id", type=int)
    p.add_argument("forecast", help="price as a decimal string, e.g. 118.40")
    p.add_argument("--salt", help="hex salt; generated if omitted")

    p = sub.add_parser("revise", help="reseal with a different number, free")
    p.add_argument("round_id", type=int)
    p.add_argument("forecast")
    p.add_argument("--salt")

    p = sub.add_parser("reveal", help="open a commitment after entries close")
    p.add_argument("round_id", type=int)
    p.add_argument("forecast", nargs="?", help="omit to use the saved reveal key")
    p.add_argument("--salt")

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
        catalog = client.read_contract(address=addr, function_name="get_catalog", args=[])
        fee = int(catalog["entry_fee_wei"])
        if catalog.get("commit_version") not in (None, "c1"):
            print("contract speaks commitment scheme %s, this script speaks c1"
                  % catalog["commit_version"])
            return 2

        salt = args.salt or secrets.token_hex(16)
        digest = commit_hash(args.round_id, account.address, args.forecast, salt)

        # Written before the transaction is sent, never after. If the send
        # succeeds and the process then dies, an unrecorded salt means a
        # commitment nobody can open and a fee forfeited for nothing.
        remember(args.round_id, account.address, args.forecast, salt)
        print("sealed %s with salt %s" % (args.forecast, salt))
        print("saved to %s -- keep it, you cannot reveal without it" % REVEAL_STORE)
        print("commit_forecast(%d, %s) with %d wei" % (args.round_id, digest, fee))

        wait(client, client.write_contract(
            address=addr, function_name="commit_forecast",
            args=[args.round_id, digest], value=fee))
        show("entry", client.read_contract(
            address=addr, function_name="get_entry",
            args=[args.round_id, account.address]))
        return 0

    if args.cmd == "revise":
        salt = args.salt or secrets.token_hex(16)
        digest = commit_hash(args.round_id, account.address, args.forecast, salt)
        remember(args.round_id, account.address, args.forecast, salt)
        print("resealed %s with salt %s" % (args.forecast, salt))
        wait(client, client.write_contract(
            address=addr, function_name="revise_commitment",
            args=[args.round_id, digest], value=0))
        return 0

    if args.cmd == "reveal":
        saved = recall(args.round_id, account.address)
        forecast = args.forecast or (saved or {}).get("forecast")
        salt = args.salt or (saved or {}).get("salt")
        if not forecast or not salt:
            print("no saved reveal key for round %d and %s."
                  % (args.round_id, account.address))
            print("pass the forecast and --salt explicitly.")
            return 2
        print("reveal_forecast(%d, %s, %s)" % (args.round_id, forecast, salt))
        wait(client, client.write_contract(
            address=addr, function_name="reveal_forecast",
            args=[args.round_id, forecast, salt], value=0))
        show("entry", client.read_contract(
            address=addr, function_name="get_entry",
            args=[args.round_id, account.address]))
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
