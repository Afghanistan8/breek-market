#!/usr/bin/env python3
"""
Breek -- end-to-end walkthrough of a scoring round.

Runs the real contract file in-process through the py-genlayer runner and walks
a whole round:

    open -> enter -> revise -> warp past the GMT+1 window -> score -> collect

It does NOT mock the feeds. Every ``score_round`` call reaches out to the live
Gate.io and CoinGecko endpoints, so the price you see graded against is derived
from real bytes for a real closed GMT+1 window. Consensus time is warped rather
than slept through, which is the only reason a full round fits in one run.

Usage::

    python scripts/demo_rounds.py
    python scripts/demo_rounds.py --day 2026-09-23 --week 2026-09-14
"""

from __future__ import annotations

import argparse
import hashlib
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
CONTRACT = REPO_ROOT / "contracts" / "BreekForecast.py"
MAX_BODY = 60000


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
        # validator would, so back off here. On chain a 429 is simply a
        # TRANSIENT revert and whoever wants the round scored tries again.
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
            print("      fetched %-46s %d  %5d bytes" % (short(url), status, len(body)))
        return {"ok": {"response": {"status": status, "headers": {}, "body": body}}}

    def reset(self):
        self.calls = []


def short(url: str) -> str:
    host = url.split("/")[2] if "://" in url else url
    q = ""
    if "currency_pair=" in url:
        q = url.split("currency_pair=")[1].split("&")[0]
    elif "/coins/" in url:
        q = url.split("/coins/")[1].split("/")[0]
    return "%s %s" % (host, q)


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
    print("=" * 76)
    print(text)
    print("=" * 76)


def step(text: str) -> None:
    print("  -> %s" % text)


def addr_hex(addr) -> str:
    raw = addr.as_bytes if hasattr(addr, "as_bytes") else bytes(addr)
    return "0x" + raw.hex()


def commit_hash(round_id: int, who, forecast: str, salt: str) -> str:
    """The commitment, as any client must compute it. See docs/SPEC.md."""
    scaled_whole, _, scaled_frac = forecast.partition(".")
    scaled = int(scaled_whole or "0") * 10**8 + int((scaled_frac + "0" * 8)[:8] or "0")
    pre = "c1|%d|%s|%d|%s" % (round_id, addr_hex(who), scaled, salt)
    return hashlib.sha256(pre.encode("utf-8")).hexdigest()


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
    z = (now + GMT_PLUS_ONE) // DAY + 30
    y, m, d = civil_from_days(z)
    return "%04d-%02d-%02d" % (y, m, d)


def run(day: str, week: str) -> int:
    from gltest.direct import VMContext, create_address, deploy_contract

    live = LiveWeb()
    players = [
        ("sharp", create_address("breek-sharp")),
        ("close", create_address("breek-close")),
        ("loose", create_address("breek-loose")),
        ("wild", create_address("breek-wild")),
    ]

    vm = VMContext()
    vm.sender = players[0][1]
    vm.origin = players[0][1]
    vm.warp(iso(int(time.time())))
    vm._live_web_handler = live

    banner("Breek -- forecast round walkthrough against LIVE feeds")
    print("  contract : %s" % CONTRACT.relative_to(REPO_ROOT))
    print("  day      : %s (GMT+1)" % day)
    print("  week     : %s (GMT+1 Monday)" % week)
    print("  feeds    : gate.io + coingecko, fetched for real, no mocks")

    failures = 0
    with vm.activate():
        contract = deploy_contract(CONTRACT, vm)
        warp(vm, int(time.time()))
        cat = contract.get_catalog()
        fee = int(cat["entry_fee_wei"])
        step("deployed; entry fee %d GEN, tolerance %s bp, cutoff %s bp" % (
            fee // GEN, cat["tolerance_bps"], cat["score_cutoff_bps"]))

        for asset, timeframe, window_id in (
            ("SOL", "DAILY", day),
            ("NEAR", "WEEKLY", week),
        ):
            label = "%s %s %s" % (asset, timeframe, window_id)
            banner(label)
            live.reset()

            bounds = window_bounds(timeframe, window_id)
            if bounds is None:
                print("  !! bad window id, skipping")
                failures += 1
                continue
            start, end = bounds
            print("  window  %s -> %s" % (fmt_ts(start), fmt_ts(end)))

            # 1. open, before the window starts
            warp(vm, start - 2 * DAY)
            vm.sender = players[0][1]
            rid = int(contract.open_round("CRYPTO", asset, timeframe, window_id).split(":")[1])
            step("opened round %d, phase=%s" % (rid, contract.get_phase(rid)))

            # 2. everyone enters with a guess. We do not know the answer yet, so
            #    these are seeded around a plausible number and then one of them
            #    sharpens after the fact -- see the revise step.
            base = {"SOL": 115.0, "ETH": 2700.0, "NEAR": 4.3}[asset]
            guesses = [base * k for k in (1.001, 1.02, 1.06, 2.5)]
            sealed = {}
            for i, ((name, who), guess) in enumerate(zip(players, guesses)):
                number = "%.4f" % guess
                salt = "%016x" % (0xDE0BEEF0000 + i)
                vm.sender = who
                vm.origin = who
                vm.value = fee
                result = contract.commit_forecast(rid, commit_hash(rid, who, number, salt))
                vm.value = 0
                sealed[name] = (who, number, salt)
                step("%s (%s) sealed a number -> %s" % (name, nick(who), result[:22] + "..."))

            step("nothing is readable yet: %s" % (
                "all forecasts empty"
                if all(
                    contract.get_entry(rid, addr_hex(who))["forecast"] == ""
                    for _n, (who, _f, _s) in sealed.items()
                )
                else "!! A FORECAST LEAKED"
            ))

            # a couple of rules, demonstrated rather than asserted
            vm.sender = players[0][1]
            vm.origin = players[0][1]
            vm.value = fee
            step("entering twice        -> %s" % contract.commit_forecast(rid, "a" * 64))
            vm.value = fee * 3
            step("paying the wrong fee  -> %s" % contract.commit_forecast(rid, "b" * 64))
            vm.value = 0

            # 3. resealing is free and unlimited before the lock
            who0, _old, salt0 = sealed[players[0][0]]
            sharper = "%.4f" % (base * 1.0005)
            vm.sender = who0
            vm.origin = who0
            step("sharp reseals         -> %s" % (
                contract.revise_commitment(rid, commit_hash(rid, who0, sharper, salt0))[:22] + "..."
            ))
            sealed[players[0][0]] = (who0, sharper, salt0)
            r = contract.get_round(rid)
            step("field: %s entries, %s GEN pot" % (r["entrants"], int(r["pot_wei"]) // GEN))

            # 4. window opens -- entries close and reveals begin
            warp(vm, start + HOUR)
            vm.sender = players[0][1]
            vm.origin = players[0][1]
            step("phase=%s, resealing now -> refused" % contract.get_phase(rid))
            try:
                contract.revise_commitment(rid, "c" * 64)
                print("  !! revision after lock succeeded")
                failures += 1
            except Exception as exc:  # noqa: BLE001
                step("  %s" % exc)

            # 4b. everyone opens their commitment
            for name, (who, number, salt) in sealed.items():
                vm.sender = who
                vm.origin = who
                step("%s reveals -> %s" % (name, contract.reveal_forecast(rid, number, salt)))

            # 5. window closes -- anyone may price it
            warp(vm, end + HOUR)
            step("phase=%s, pricing with live data..." % contract.get_phase(rid))
            try:
                outcome = contract.score_round(rid)
            except Exception as exc:  # noqa: BLE001
                print("  !! scoring failed: %s" % exc)
                print("     (a TRANSIENT error is retryable; the round stays open)")
                failures += 1
                continue
            step("score_round(%d) -> %s   [%d live fetches]" % (rid, outcome, len(live.calls)))

            ev = contract.get_evidence(rid)
            print("     feed A (%s): %s" % (ev["source_a"], ev.get("a_close")))
            print("     feed B (%s): %s" % (ev["source_b"], ev.get("b_close")))
            print("     gap %s bp (tolerance %s) -> %s"
                  % (ev.get("spread_bps"), ev["tolerance_bps"], ev.get("consensus")))

            # 6. the leaderboard, ordered by accuracy
            board = contract.get_leaderboard(rid, 50)
            if board["status"] == "SCORED":
                print("     %-8s %-14s %-10s %-8s %s"
                      % ("who", "called", "off by", "weight", "share"))
                for row in board["entries"]:
                    print("     %-8s %-14s %-10s %-8s %s GEN"
                          % (row["who"][:8], row["forecast"][:14],
                             "%.2f%%" % (int(row["error_bps"]) / 100),
                             row["weight"], int(row["share_wei"]) / GEN))

            # 7. collect
            pot = int(contract.get_round(rid)["pot_wei"])
            paid = 0
            for name, who in players:
                vm.sender = who
                claimed = contract.collect(rid)
                paid += int(claimed.split(":")[1])
                step("%s collect -> %s" % (name, claimed))
            step("paid %d of %d wei" % (paid, pot))
            if paid > pot:
                print("  !! PAID MORE THAN THE POT")
                failures += 1

            vm.sender = players[0][1]
            try:
                contract.collect(rid)
                print("  !! double collect succeeded")
                failures += 1
            except Exception as exc:  # noqa: BLE001
                step("double collect refused -> %s" % exc)

        # DOMINANCE: listed, deliberately not priceable
        banner("DOMINANCE -- listed, not priceable")
        warp(vm, int(time.time()))
        dom = {c["key"]: c for c in contract.get_catalog()["categories"]}["DOMINANCE"]
        print("  assets    : %s" % dom["assets"])
        print("  priceable : %s" % dom["priceable"])
        print("  reason    : %s" % dom["note"])
        try:
            contract.open_round("DOMINANCE", "BTC.D", "DAILY", future_day(int(time.time())))
            print("  !! a DOMINANCE round opened; it should be refused")
            failures += 1
        except Exception as exc:  # noqa: BLE001
            step("open_round refused -> %s" % exc)

        # Expiry, with no network access at all
        banner("Expiry -- five days unscored, zero HTTP")
        nxt = future_day(int(time.time()))
        warp(vm, int(time.time()))
        rid = int(contract.open_round("CRYPTO", "ETH", "DAILY", nxt).split(":")[1])
        r = contract.get_round(rid)
        vm.sender = players[1][1]
        vm.value = fee
        contract.commit_forecast(rid, commit_hash(rid, vm.sender, "2700.0", "0" * 16))
        vm.value = 0
        step("round %d opened for %s, one entry" % (rid, nxt))
        live.reset()
        vm.strict_mocks = True
        warp(vm, int(r["expires_at"]) + HOUR)
        step("score_round -> %s" % contract.score_round(rid))
        step("live fetches during expiry: %d" % len(live.calls))
        if live.calls:
            print("  !! the expiry path touched the network")
            failures += 1
        vm.sender = players[1][1]
        step("collect -> %s" % contract.collect(rid))
        vm.strict_mocks = False

        banner("Stats")
        for key, value in contract.get_stats().items():
            print("  %-22s %s" % (key, value))

    banner("DONE -- %s" % ("all scenarios passed" if failures == 0
                           else "%d problem(s)" % failures))
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Breek forecast round walkthrough")
    ap.add_argument("--day", help="GMT+1 day YYYY-MM-DD (default: last closed day)")
    ap.add_argument("--week", help="GMT+1 Monday YYYY-MM-DD (default: last closed week)")
    args = ap.parse_args()
    now = int(time.time())
    return run(args.day or last_closed_day(now), args.week or last_closed_week(now))


if __name__ == "__main__":
    sys.exit(main())
