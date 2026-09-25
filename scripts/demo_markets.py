#!/usr/bin/env python3
"""
Breek Market -- end-to-end walkthrough.

Two modes.

``--mode local`` (default) runs the real contract file in-process through the
py-genlayer runner and walks the whole lifecycle for every shipped kind:

    create -> stake -> warp past the GMT+1 window -> resolve -> claim

Crucially it does NOT mock the feeds. Every ``resolve_market`` call reaches out
to the live Gate.io and CoinGecko endpoints, so the settlement you see is derived
from real bytes for a real closed GMT+1 window. Consensus time is warped rather
than slept through, which is the only reason a full lifecycle fits in one run.

``--mode net --address 0x...`` exercises a deployed contract on the live network:
it creates a market and stakes on it. It deliberately does NOT resolve, because a
live market can only be resolved once its real window has closed, and faking that
with injected prices would defeat the entire point of the design.

Usage::

    python scripts/demo_markets.py
    python scripts/demo_markets.py --day 2026-09-23 --week 2026-09-14
    python scripts/demo_markets.py --mode net --address 0xabc... --kind DIR_DAILY
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.check_sources import (  # noqa: E402
    DAY,
    GMT_PLUS_ONE,
    HOUR,
    WEEK,
    civil_from_days,
    days_from_civil,
    fmt_ts,
    last_closed_day,
    last_closed_week,
    weekday_from_days,
)

GEN = 10**18
CONTRACT = REPO_ROOT / "contracts" / "BreekMarket.py"
MAX_BODY = 60000


# ---------------------------------------------------------------------------
# Live web handler for the in-process runner
# ---------------------------------------------------------------------------


class LiveWeb:
    """Serve the contract's ``gl.nondet.web.get`` calls from the real internet."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.calls: list[tuple[str, int, int]] = []

    def __call__(self, data):
        url = data.get("url", "")
        headers = {}
        for key, value in (data.get("headers") or {}).items():
            headers[key] = value.decode("utf-8") if isinstance(value, bytes) else value
        req = urllib.request.Request(url, headers=headers, method=data.get("method", "GET"))

        # A single laptop IP trips CoinGecko's keyless rate limit long before a
        # validator would, so back off and retry here. This is demo plumbing
        # outside the contract: on chain a 429 simply becomes a TRANSIENT revert
        # and whoever wants the market settled calls resolve_market again.
        body, status = b"", 0
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body, status = resp.read(MAX_BODY + 1), resp.status
            except urllib.error.HTTPError as exc:
                body, status = exc.read(), exc.code
            except Exception as exc:  # noqa: BLE001
                print("      ! %s -> %s: %s" % (short(url), type(exc).__name__, exc))
                raise
            if status != 429:
                break
            wait = 8 * (attempt + 1)
            print("      .. %s rate-limited, retrying in %ds" % (short(url), wait))
            time.sleep(wait)

        self.calls.append((url, status, len(body)))
        if self.verbose:
            print("      fetched %-52s %d  %5d bytes" % (short(url), status, len(body)))
        return {"ok": {"response": {"status": status, "headers": {}, "body": body}}}

    def reset(self):
        self.calls = []


def short(url: str) -> str:
    host = url.split("/")[2] if "://" in url else url
    tail = url.split("?")[0].rsplit("/", 1)[-1]
    q = ""
    if "currency_pair=" in url:
        q = url.split("currency_pair=")[1].split("&")[0]
    elif "/coins/" in url:
        q = url.split("/coins/")[1].split("/")[0]
    return "%s %s %s" % (host, tail, q)


# ---------------------------------------------------------------------------
# Local walkthrough
# ---------------------------------------------------------------------------


def iso(unix: int) -> str:
    days, rem = divmod(unix, DAY)
    h, rem = divmod(rem, HOUR)
    mi, s = divmod(rem, 60)
    y, m, d = civil_from_days(days)
    return "%04d-%02d-%02dT%02d:%02d:%02d.000000Z" % (y, m, d, h, mi, s)


def warp(vm, unix: int) -> None:
    """Move consensus time, including the copy the contract actually reads."""
    stamp = iso(unix)
    vm.warp(stamp)
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and getattr(gl, "message_raw", None) is not None:
        gl.message_raw["datetime"] = stamp


def banner(text: str) -> None:
    print()
    print("=" * 78)
    print(text)
    print("=" * 78)


def step(text: str) -> None:
    print("  -> %s" % text)


def run_local(day: str, week: str) -> int:
    from gltest.direct import VMContext, create_address, deploy_contract

    live = LiveWeb()
    alice = create_address("breek-demo-alice")
    bob = create_address("breek-demo-bob")
    carol = create_address("breek-demo-carol")

    vm = VMContext()
    vm.sender = alice
    vm.origin = alice
    vm.warp(iso(int(time.time())))
    vm._live_web_handler = live

    banner("Breek Market -- local walkthrough against LIVE feeds")
    print("  contract : %s" % CONTRACT.relative_to(REPO_ROOT))
    print("  day      : %s (GMT+1)" % day)
    print("  week     : %s (GMT+1 Monday)" % week)
    print("  feeds    : gate.io + coingecko, fetched for real, no mocks")

    failures = 0
    with vm.activate():
        contract = deploy_contract(CONTRACT, vm)
        warp(vm, int(time.time()))
        step("deployed; stake band is %s-%s GEN" % (
            int(contract.get_catalog()["stake"]["min_wei"]) // GEN,
            int(contract.get_catalog()["stake"]["max_wei"]) // GEN,
        ))

        scenarios = [
            ("DIR_DAILY", "CRYPTO", "SOL", "DAILY", day, ["UP", "DOWN"]),
            ("REL_DAILY", "CRYPTO", "", "DAILY", day, ["SOL", "ETH", "NEAR"]),
            ("REL_WEEKLY", "CRYPTO", "", "WEEKLY", week, ["SOL", "ETH", "NEAR"]),
            ("DIR_WEEKLY", "CRYPTO", "NEAR", "WEEKLY", week, ["UP", "DOWN"]),
        ]

        for kind, category, asset, timeframe, window_id, sides in scenarios:
            label = kind + (" " + asset if asset else "") + " " + window_id
            banner(label)
            live.reset()

            bounds = window_bounds(timeframe, window_id)
            if bounds is None:
                print("  !! bad window id, skipping")
                failures += 1
                continue
            window_start, window_end = bounds
            print("  window  %s -> %s" % (fmt_ts(window_start), fmt_ts(window_end)))

            # 1. create, before the candle opens
            warp(vm, window_start - 2 * DAY)
            vm.sender = alice
            try:
                created = contract.create_market(kind, category, asset, timeframe, window_id)
            except Exception as exc:  # noqa: BLE001
                print("  !! create failed: %s" % exc)
                failures += 1
                continue
            mid = int(created.split(":")[1])
            step("created market %d, phase=%s" % (mid, contract.get_phase(mid)))

            # 2. stake, still before the cutoff
            stakers = [(alice, sides[0], 2 * GEN), (bob, sides[0], 4 * GEN),
                       (carol, sides[-1], 3 * GEN)]
            for who, side, amount in stakers:
                vm.sender = who
                vm.value = amount
                result = contract.take_position(mid, side)
                vm.value = 0
                step("%s staked %d GEN on %s -> %s" % (
                    nick(who), amount // GEN, side, result))

            # a couple of rules, demonstrated rather than asserted
            vm.sender = alice
            vm.value = 2 * GEN
            step("alice tries to switch side  -> %s" % contract.take_position(mid, sides[-1]))
            vm.value = 5 * GEN
            step("alice tries a 5 GEN stake   -> %s" % contract.take_position(mid, sides[0]))
            vm.value = 0

            market = contract.get_market(mid)
            step("pool %s GEN across %s stakers, sides %s" % (
                int(market["pool_wei"]) // GEN, market["stakers"], market["sides"]))

            # 3. the window opens -- staking is closed
            warp(vm, window_start + HOUR)
            vm.sender = alice
            vm.value = 2 * GEN
            step("phase=%s, late stake -> %s" % (
                contract.get_phase(mid), contract.take_position(mid, sides[0])))
            vm.value = 0

            # 4. the window closes -- anyone may resolve
            warp(vm, window_end + HOUR)
            step("phase=%s, resolving with live data..." % contract.get_phase(mid))
            try:
                outcome = contract.resolve_market(mid)
            except Exception as exc:  # noqa: BLE001
                print("  !! resolve failed: %s" % exc)
                print("     (a TRANSIENT error is retryable; the market stays open)")
                failures += 1
                continue
            step("resolve_market(%d) -> %s   [%d live fetches]" % (
                mid, outcome, len(live.calls)))

            evidence = contract.get_evidence(mid)
            print("     source A (%s): %s -> %s" % (
                evidence["source_a"], evidence.get("a_series"), evidence.get("a_verdict")))
            print("     source B (%s): %s -> %s" % (
                evidence["source_b"], evidence.get("b_series"), evidence.get("b_verdict")))
            print("     final: %s" % evidence.get("final"))

            # 5. claim
            pool = int(contract.get_market(mid)["pool_wei"])
            paid = 0
            for who, _side, _amount in stakers:
                vm.sender = who
                claimed = contract.claim(mid)
                paid += int(claimed.split(":")[1])
                step("%s claim -> %s" % (nick(who), claimed))
            step("paid %s of %s wei (integer division leaves at most a few wei of dust)"
                 % (paid, pool))
            if paid > pool:
                print("  !! PAID MORE THAN THE POOL")
                failures += 1

            vm.sender = alice
            try:
                contract.claim(mid)
                print("  !! double claim succeeded")
                failures += 1
            except Exception as exc:  # noqa: BLE001
                step("double claim rejected -> %s" % exc)

            running = contract.get_stats()
            step("running totals: settled=%s inconclusive=%s staked=%s paid=%s"
                 % (running["settled"], running["inconclusive"],
                    running["total_staked_wei"], running["total_paid_wei"]))

        # DOMINANCE: listed, deliberately not settlable
        banner("DOMINANCE -- catalog only")
        warp(vm, int(time.time()))
        cat = {c["key"]: c for c in contract.get_catalog()["categories"]}["DOMINANCE"]
        print("  assets     : %s" % cat["assets"])
        print("  settlable  : %s" % cat["settlable"])
        print("  reason     : %s" % cat["note"])
        future = future_day(int(time.time()))
        try:
            contract.create_market("DIR_DAILY", "DOMINANCE", "BTC.D", "DAILY", future)
            print("  !! a DOMINANCE market was created; it should be refused")
            failures += 1
        except Exception as exc:  # noqa: BLE001
            step("create_market refused -> %s" % exc)

        # Terminal refund, with no network access at all
        banner("Terminal refund -- five days unresolved, zero HTTP")
        future = future_day(int(time.time()))
        warp(vm, int(time.time()))
        mid = int(contract.create_market(
            "DIR_DAILY", "CRYPTO", "ETH", "DAILY", future).split(":")[1])
        market = contract.get_market(mid)
        vm.sender = bob
        vm.value = 3 * GEN
        contract.take_position(mid, "UP")
        vm.value = 0
        step("market %d created for %s, bob staked 3 GEN" % (mid, future))
        live.reset()
        vm.strict_mocks = True  # any web request now raises
        warp(vm, int(market["terminal_refund_at"]) + HOUR)
        step("resolve_market -> %s" % contract.resolve_market(mid))
        step("live fetches during terminal refund: %d" % len(live.calls))
        if live.calls:
            print("  !! the terminal path touched the network")
            failures += 1
        vm.sender = bob
        step("bob claim -> %s" % contract.claim(mid))
        vm.strict_mocks = False

        banner("Stats")
        for key, value in contract.get_stats().items():
            print("  %-22s %s" % (key, value))

    banner("DONE -- %s" % ("all scenarios passed" if failures == 0
                           else "%d problem(s)" % failures))
    return 1 if failures else 0


def nick(addr) -> str:
    raw = addr.as_bytes if hasattr(addr, "as_bytes") else bytes(addr)
    return "0x" + raw.hex()[:6]


def window_bounds(timeframe: str, window_id: str):
    try:
        y, m, d = int(window_id[0:4]), int(window_id[5:7]), int(window_id[8:10])
    except Exception:  # noqa: BLE001
        return None
    z = days_from_civil(y, m, d)
    start = z * DAY - GMT_PLUS_ONE
    if timeframe == "DAILY":
        return start, start + DAY
    if timeframe == "WEEKLY":
        if weekday_from_days(z) != 0:
            return None
        return start, start + WEEK
    return None


def future_day(now: int) -> str:
    """A GMT+1 day comfortably in the future, so create_market accepts it."""
    z = (now + GMT_PLUS_ONE) // DAY + 30
    y, m, d = civil_from_days(z)
    return "%04d-%02d-%02d" % (y, m, d)


def next_monday(now: int) -> str:
    z = (now + GMT_PLUS_ONE) // DAY
    z = z + (7 - weekday_from_days(z)) + 7
    y, m, d = civil_from_days(z)
    return "%04d-%02d-%02d" % (y, m, d)


# ---------------------------------------------------------------------------
# Live-network walkthrough
# ---------------------------------------------------------------------------


def run_net(address: str, kind: str, side: str, stake_gen: int) -> int:
    """Create and stake on a deployed contract. Never resolves; see the docstring."""
    from gltest import get_contract_factory  # noqa: F401  (import proves the env works)
    from genlayer_py import create_client  # type: ignore
    from genlayer_py.chains import studionet  # type: ignore

    banner("Breek Market -- live network walkthrough")
    print("  contract : %s" % address)
    print("  note     : this mode never resolves. A live market resolves only")
    print("             once its real GMT+1 window has closed, and injecting")
    print("             prices to fake that would defeat the design.")

    client = create_client(chain=studionet)
    now = int(time.time())
    timeframe = "WEEKLY" if kind.endswith("WEEKLY") else "DAILY"
    window_id = next_monday(now) if timeframe == "WEEKLY" else future_day(now)
    asset = "" if kind.startswith("REL") else "SOL"

    print("  kind     : %s  window %s (%s)" % (kind, window_id, timeframe))
    print()
    print("  Run these with the genlayer CLI:")
    print()
    print("    genlayer write %s create_market \\" % address)
    print("      --args %s CRYPTO %s %s %s" % (
        kind, '""' if asset == "" else asset, timeframe, window_id))
    print()
    print("    genlayer write %s take_position --args <market_id> %s \\" % (address, side))
    print("      --value %d" % (stake_gen * GEN))
    print()
    print("    genlayer call %s get_market --args <market_id>" % address)
    print()
    print("  Once the window has closed, anyone can settle it:")
    print()
    print("    genlayer call  %s list_resolvable --args 10" % address)
    print("    genlayer write %s resolve_market --args <market_id>" % address)
    print("    genlayer call  %s get_evidence --args <market_id>" % address)
    print("    genlayer write %s claim --args <market_id>" % address)
    print()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Breek Market walkthrough")
    ap.add_argument("--mode", choices=["local", "net"], default="local")
    ap.add_argument("--day", help="GMT+1 day YYYY-MM-DD (default: last closed day)")
    ap.add_argument("--week", help="GMT+1 Monday YYYY-MM-DD (default: last closed week)")
    ap.add_argument("--address", help="deployed contract address (net mode)")
    ap.add_argument("--kind", default="DIR_DAILY")
    ap.add_argument("--side", default="UP")
    ap.add_argument("--stake", type=int, default=2, help="GEN to stake, 2-4")
    args = ap.parse_args()

    if args.mode == "net":
        if not args.address:
            print("net mode needs --address")
            return 2
        return run_net(args.address, args.kind, args.side, args.stake)

    now = int(time.time())
    return run_local(args.day or last_closed_day(now), args.week or last_closed_week(now))


if __name__ == "__main__":
    sys.exit(main())
