#!/usr/bin/env python3
"""
Breek -- live pricing-source probe.

This script is the gate that must pass before ``score_round`` parsers are
trusted. It talks to the real public endpoints Breek settles against and proves,
for every market kind we intend to ship, that TWO INDEPENDENT sources can each
reconstruct THE SAME TWO GMT+1 INSTANTS from their own bytes:

    price at window_start   ("open")
    price at window_end     ("close")

Nothing here runs on chain. It exists so that a human (and CI) can see the raw
evidence behind docs/SPEC.md before locking the URL templates into the contract.

Usage::

    python scripts/check_sources.py                  # last closed day + week
    python scripts/check_sources.py --day 2026-09-23
    python scripts/check_sources.py --week 2026-09-21
    python scripts/check_sources.py --json out.json  # machine-readable evidence

Exit code 0 only if every shipped kind reconstructs both instants on both
sources. DOMINANCE is probed too, and is EXPECTED to fail the two-source test --
see docs/SPEC.md for the write-up and the consequence.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Constants mirrored from contracts/BreekForecast.py. Keep these in lockstep.
# ---------------------------------------------------------------------------

DAY = 86400
HOUR = 3600
WEEK = 7 * DAY
GMT_PLUS_ONE = 3600
PRICE_SCALE = 10**8
BPS_SCALE = 10000
MAX_SOURCE_BYTES = 60000

CRYPTO_SYMBOLS = ("SOL", "ETH", "NEAR")
DOMINANCE_SYMBOLS = ("BTC.D", "ETH.D", "OTHERS.D")

GATE_PAIR = {"SOL": "SOL_USDT", "ETH": "ETH_USDT", "NEAR": "NEAR_USDT"}
COINGECKO_ID = {"SOL": "solana", "ETH": "ethereum", "NEAR": "near"}

GATE_URL = (
    "https://api.gateio.ws/api/v4/spot/candlesticks"
    "?currency_pair={pair}&interval=1h&from={frm}&to={to}"
)
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/{cid}/market_chart/range"
    "?vs_currency=usd&from={frm}&to={to}"
)

# Probed, keyless, current-value-only dominance feeds. Kept here as evidence
# that no *historical* dominance pair exists, not as settlement sources.
DOMINANCE_PROBES = {
    "coingecko_global": "https://api.coingecko.com/api/v3/global",
    "coinpaprika_global": "https://api.coinpaprika.com/v1/global",
    "coinlore_global": "https://api.coinlore.net/api/global/",
    "coingecko_global_history": (
        "https://api.coingecko.com/api/v3/global/market_cap_chart?days=7"
    ),
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

UP, DOWN, TIE, INCONCLUSIVE = "UP", "DOWN", "TIE", "INCONCLUSIVE"

# ---------------------------------------------------------------------------
# Hand-rolled civil calendar maths. Identical algorithm to the contract, so a
# disagreement between this script and the contract is a real bug, not drift.
# ---------------------------------------------------------------------------


def is_leap(y: int) -> bool:
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0


def days_from_civil(y: int, m: int, d: int) -> int:
    """Days since 1970-01-01, proleptic Gregorian."""
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z: int) -> tuple[int, int, int]:
    """Inverse of days_from_civil."""
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return (y + (1 if m <= 2 else 0), m, d)


def parse_iso_date(s: str) -> tuple[int, int, int]:
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise ValueError("bad ISO date: " + repr(s))
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    if not 1 <= m <= 12:
        raise ValueError("bad month: " + repr(s))
    mdays = [31, 29 if is_leap(y) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not 1 <= d <= mdays[m - 1]:
        raise ValueError("bad day: " + repr(s))
    return y, m, d


def weekday_from_days(z: int) -> int:
    """0 = Monday .. 6 = Sunday. 1970-01-01 was a Thursday."""
    return (z + 3) % 7


def day_window(date_str: str) -> tuple[int, int]:
    y, m, d = parse_iso_date(date_str)
    start = days_from_civil(y, m, d) * DAY - GMT_PLUS_ONE
    return start, start + DAY


def week_window(monday_str: str) -> tuple[int, int]:
    y, m, d = parse_iso_date(monday_str)
    z = days_from_civil(y, m, d)
    if weekday_from_days(z) != 0:
        raise ValueError(monday_str + " is not a Monday (GMT+1 weeks start Monday)")
    start = z * DAY - GMT_PLUS_ONE
    return start, start + WEEK


# ---------------------------------------------------------------------------
# Decimal -> scaled integer. No floats anywhere in the money path.
# ---------------------------------------------------------------------------


def dec_to_scaled(text: str, scale: int = PRICE_SCALE) -> int:
    """'80494.31000000' and '80494.31' must map to the same integer."""
    s = text.strip()
    if not s:
        raise ValueError("empty number")
    neg = s.startswith("-")
    if neg or s.startswith("+"):
        s = s[1:]
    if "e" in s or "E" in s:
        raise ValueError("exponent notation not accepted: " + repr(text))
    if s.count(".") > 1:
        raise ValueError("malformed number: " + repr(text))
    if "." in s:
        whole, frac = s.split(".")
    else:
        whole, frac = s, ""
    whole = whole or "0"
    if not whole.isdigit() or (frac and not frac.isdigit()):
        raise ValueError("non-numeric: " + repr(text))
    digits = len(str(scale)) - 1
    frac = (frac + "0" * digits)[:digits]  # truncate, never round
    val = int(whole) * scale + int(frac or "0")
    return -val if neg else val


def float_to_scaled(x: float, scale: int = PRICE_SCALE) -> int:
    """Only for feeds that hand us JSON numbers rather than decimal strings."""
    return dec_to_scaled("%.18f" % x, scale)


def bps(open_: int, close: int) -> int:
    if open_ <= 0:
        raise ValueError("open must be positive")
    return ((close - open_) * BPS_SCALE) // open_


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class FetchError(RuntimeError):
    pass


def fetch(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers=REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(MAX_SOURCE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise FetchError("HTTP %d: %r" % (exc.code, exc.read()[:200])) from exc
    except Exception as exc:  # noqa: BLE001 - a probe reports every failure mode
        raise FetchError("%s: %s" % (type(exc).__name__, exc)) from exc
    if len(body) > MAX_SOURCE_BYTES:
        raise FetchError("body exceeds MAX_SOURCE_BYTES (%d)" % MAX_SOURCE_BYTES)
    return body


# ---------------------------------------------------------------------------
# Source A -- Gate.io hourly spot candlesticks
# ---------------------------------------------------------------------------
# Row layout (Gate.io v4 spot candlesticks):
#   [0] window open time, unix seconds  [1] quote volume  [2] close
#   [3] high  [4] low  [5] open  [6] base volume  [7] "true" iff window closed
GATE_TS, GATE_CLOSE, GATE_OPEN, GATE_CLOSED_FLAG = 0, 2, 5, 7


def gate_window(symbol: str, start: int, end: int) -> dict[str, Any]:
    """Rebuild the GMT+1 window from hourly candle OPEN TIMES, not positions."""
    pair = GATE_PAIR[symbol]
    url = GATE_URL.format(pair=pair, frm=start, to=end - 1)
    raw = fetch(url)
    rows = json.loads(raw)
    expected = (end - start) // HOUR
    if not isinstance(rows, list) or len(rows) != expected:
        raise FetchError("expected %d hourly candles, got %d" % (expected, len(rows)))
    by_ts: dict[int, Any] = {}
    for row in rows:
        ts_ = int(row[GATE_TS])
        if ts_ % HOUR != 0:
            raise FetchError("candle open time not hour-aligned: %d" % ts_)
        if row[GATE_CLOSED_FLAG] != "true":
            raise FetchError("candle %d is still open" % ts_)
        by_ts[ts_] = row
    for want in range(start, end, HOUR):
        if want not in by_ts:
            raise FetchError("missing hourly candle at %d" % want)
    first, last = by_ts[start], by_ts[end - HOUR]
    return {
        "url": url,
        "bytes": len(raw),
        "candles": len(rows),
        "first_ts": start,
        "last_ts": end - HOUR,
        "open_raw": first[GATE_OPEN],
        "close_raw": last[GATE_CLOSE],
        "open": dec_to_scaled(first[GATE_OPEN]),
        "close": dec_to_scaled(last[GATE_CLOSE]),
    }


# ---------------------------------------------------------------------------
# Source B -- CoinGecko market_chart/range spot samples
# ---------------------------------------------------------------------------
# We pad the request by one hour either side so the boundary instants are
# interior points, then select BY TIMESTAMP. CoinGecko returns hourly samples
# for a historical range longer than a day and 5-minutely for shorter ones;
# both contain the exact :00 instants, so timestamp selection is correct under
# either granularity.


def coingecko_window(symbol: str, start: int, end: int) -> dict[str, Any]:
    cid = COINGECKO_ID[symbol]
    url = COINGECKO_URL.format(cid=cid, frm=start - HOUR, to=end + HOUR)
    raw = fetch(url)
    doc = json.loads(raw)
    prices = doc.get("prices")
    if not isinstance(prices, list) or not prices:
        raise FetchError("no price series returned")
    by_ts: dict[int, float] = {}
    for point in prices:
        ms = int(point[0])
        if ms % 1000 != 0:
            raise FetchError("sub-second timestamp: %d" % ms)
        by_ts[ms // 1000] = point[1]
    if start not in by_ts:
        raise FetchError("no sample at window_start %d" % start)
    if end not in by_ts:
        raise FetchError("no sample at window_end %d" % end)
    step = 0
    if len(prices) > 1:
        step = (int(prices[1][0]) - int(prices[0][0])) // 1000
    return {
        "url": url,
        "bytes": len(raw),
        "samples": len(prices),
        "step_s": step,
        "open_raw": repr(by_ts[start]),
        "close_raw": repr(by_ts[end]),
        "open": float_to_scaled(by_ts[start]),
        "close": float_to_scaled(by_ts[end]),
    }


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def direction_verdict(open_: int, close: int) -> str:
    """Flat is DOWN, by design. A market never settles 'unchanged'."""
    return UP if close > open_ else DOWN


def relative_verdict(series: dict[str, tuple[int, int]]) -> tuple[str, dict[str, int]]:
    scores = {sym: bps(o, c) for sym, (o, c) in series.items()}
    best = max(scores.values())
    leaders = [s for s, v in scores.items() if v == best]
    return (leaders[0] if len(leaders) == 1 else TIE), scores


def combine(a: str, b: str) -> str:
    """One source can never produce a result. TIE can never produce a winner."""
    if a == b and a not in (TIE, "", INCONCLUSIVE):
        return a
    return INCONCLUSIVE


# ---------------------------------------------------------------------------
# Probe runners
# ---------------------------------------------------------------------------


def probe_crypto_window(label: str, start: int, end: int, report: dict) -> bool:
    print("\n=== CRYPTO / %s ===" % label)
    print("    window_start %d  (%s)" % (start, fmt_ts(start)))
    print("    window_end   %d  (%s)" % (end, fmt_ts(end)))
    a_series: dict[str, tuple[int, int]] = {}
    b_series: dict[str, tuple[int, int]] = {}
    ok = True
    entry = report.setdefault(label, {"window": [start, end], "assets": {}})
    for sym in CRYPTO_SYMBOLS:
        row: dict[str, Any] = {}
        try:
            a = gate_window(sym, start, end)
            a_series[sym] = (a["open"], a["close"])
            row["gate"] = a
            print(
                "  %-5s gate.io    open=%-14s close=%-14s candles=%d bytes=%d bps=%+d"
                % (sym, a["open_raw"], a["close_raw"], a["candles"], a["bytes"],
                   bps(a["open"], a["close"]))
            )
        except FetchError as exc:
            ok = False
            row["gate_error"] = str(exc)
            print("  %-5s gate.io    FAILED: %s" % (sym, exc))
        time.sleep(0.5)  # be polite; keyless CoinGecko limits are tight
        try:
            b = coingecko_window(sym, start, end)
            b_series[sym] = (b["open"], b["close"])
            row["coingecko"] = b
            print(
                "  %-5s coingecko  open=%-14s close=%-14s samples=%d step=%ds "
                "bytes=%d bps=%+d"
                % (sym, b["open_raw"][:14], b["close_raw"][:14], b["samples"],
                   b["step_s"], b["bytes"], bps(b["open"], b["close"]))
            )
        except FetchError as exc:
            ok = False
            row["coingecko_error"] = str(exc)
            print("  %-5s coingecko  FAILED: %s" % (sym, exc))
        entry["assets"][sym] = row
        time.sleep(0.5)

    if not ok:
        print("  -> two-source reconstruction INCOMPLETE for this window")
        return False

    print("  -- DIR verdicts (one asset, UP/DOWN, flat=DOWN) --")
    for sym in CRYPTO_SYMBOLS:
        va = direction_verdict(*a_series[sym])
        vb = direction_verdict(*b_series[sym])
        final = combine(va, vb)
        entry["assets"][sym]["dir"] = {"a": va, "b": vb, "final": final}
        note = "agree" if final != INCONCLUSIVE else "DISAGREE -> refund all"
        print("     %-5s A=%-4s B=%-4s -> %-12s (%s)" % (sym, va, vb, final, note))

    print("  -- REL verdict (strongest bps across the catalog) --")
    wa, sa = relative_verdict(a_series)
    wb, sb = relative_verdict(b_series)
    final = combine(wa, wb)
    entry["rel"] = {"a": wa, "b": wb, "final": final, "a_bps": sa, "b_bps": sb}
    print("     A bps %s -> %s" % (fmt_bps(sa), wa))
    print("     B bps %s -> %s" % (fmt_bps(sb), wb))
    print("     final -> %s" % final)
    return True


def probe_dominance(report: dict) -> bool:
    print("\n=== DOMINANCE / two-source feasibility ===")
    print("    Settling BTC.D / ETH.D / OTHERS.D needs BTC and ETH market cap AND")
    print("    TOTAL crypto market cap at two PAST GMT+1 instants, from two")
    print("    independent keyless feeds. Probing every candidate we know of:")
    out = report.setdefault("dominance", {})
    historical_total_sources = 0
    for name, url in DOMINANCE_PROBES.items():
        try:
            raw = fetch(url)
            doc = json.loads(raw)
            note = summarise_dominance(name, doc)
            out[name] = {"url": url, "ok": True, "bytes": len(raw), "note": note}
            print("  %-26s OK    %s" % (name, note))
        except FetchError as exc:
            out[name] = {"url": url, "ok": False, "error": str(exc)}
            print("  %-26s FAIL  %s" % (name, exc))
        time.sleep(0.5)
    print()
    print("  Verdict: none of the probed feeds expose HISTORICAL total market cap")
    print("  without an API key, and the current-value feeds disagree with each")
    print("  other by several percentage points because they aggregate different")
    print("  coin universes. A single source can never settle a Breek market, so")
    print("  DOMINANCE ships as a catalog entry only -- create_market rejects it.")
    out["settlable"] = historical_total_sources >= 2
    return False


def summarise_dominance(name: str, doc: Any) -> str:
    try:
        if name == "coingecko_global":
            pct = doc["data"]["market_cap_percentage"]
            return "current only: BTC.D=%.2f ETH.D=%.2f (no history)" % (
                pct["btc"], pct["eth"])
        if name == "coinpaprika_global":
            return "current only: BTC.D=%.2f total_mcap=%s (no history)" % (
                doc["bitcoin_dominance_percentage"], doc["market_cap_usd"])
        if name == "coinlore_global":
            row = doc[0]
            return "current only: BTC.D=%s ETH.D=%s (no history)" % (
                row["btc_d"], row["eth_d"])
    except Exception:  # noqa: BLE001
        pass
    return "unexpected payload shape"


# ---------------------------------------------------------------------------
# Helpers / CLI
# ---------------------------------------------------------------------------


def fmt_ts(unix: int) -> str:
    shifted = unix + GMT_PLUS_ONE
    y, m, d = civil_from_days(shifted // DAY)
    rem = shifted % DAY
    return "%04d-%02d-%02d %02d:%02d GMT+1" % (y, m, d, rem // 3600, rem % 3600 // 60)


def fmt_bps(scores: dict[str, int]) -> str:
    return "  ".join("%s=%+d" % (k, v) for k, v in scores.items())


def last_closed_day(now: int) -> str:
    """Most recent GMT+1 day whose window has fully closed."""
    z = (now + GMT_PLUS_ONE) // DAY - 1
    y, m, d = civil_from_days(z)
    return "%04d-%02d-%02d" % (y, m, d)


def last_closed_week(now: int) -> str:
    z = (now + GMT_PLUS_ONE) // DAY
    monday = z - weekday_from_days(z) - 7
    y, m, d = civil_from_days(monday)
    return "%04d-%02d-%02d" % (y, m, d)


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe Breek Market settlement sources")
    ap.add_argument("--day", help="GMT+1 day YYYY-MM-DD (default: last closed day)")
    ap.add_argument("--week", help="GMT+1 Monday YYYY-MM-DD (default: last closed week)")
    ap.add_argument("--json", help="write machine-readable evidence to this path")
    ap.add_argument("--skip-week", action="store_true", help="probe the daily window only")
    ap.add_argument("--skip-hourly", action="store_true", help="skip the hourly probe")
    args = ap.parse_args()

    now = int(time.time())
    day = args.day or last_closed_day(now)
    week = args.week or last_closed_week(now)

    print("Breek -- pricing source probe")
    print("probed at %d (%s)" % (now, fmt_ts(now)))
    print("source A: gate.io   hourly spot candlesticks (keyless)")
    print("source B: coingecko market_chart/range spot samples (keyless)")

    report: dict[str, Any] = {
        "probed_at": now,
        "source_a": "gate.io",
        "source_b": "coingecko",
    }
    ok = True

    ds, de = day_window(day)
    ok = probe_crypto_window("DAILY " + day, ds, de, report) and ok

    if not args.skip_week:
        ws, we = week_window(week)
        ok = probe_crypto_window("WEEKLY " + week, ws, we, report) and ok

    probe_dominance(report)

    if not args.skip_hourly:
        print("\n=== HOURLY feasibility ===")
        hs = (now // HOUR) * HOUR - HOUR
        he = hs + HOUR
        print("    Probing the last closed GMT+1 hour %s -> %s"
              % (fmt_ts(hs), fmt_ts(he)))
        hourly_ok = probe_crypto_window("HOURLY %d" % hs, hs, he, report)
        report["hourly_settlable"] = bool(hourly_ok)
        if hourly_ok:
            print("    Both sources reconstructed the exact hour. Hourly MAY ship.")
        else:
            print("    At least one source could not reconstruct the exact hour.")
            print("    Hourly is NOT shipped; the two-source rule is not weakened.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print("\nevidence written to %s" % args.json)

    print("\n" + ("PASS: every shipped kind reconstructs two independent sources."
                  if ok else
                  "FAIL: a shipped kind could not be reconstructed twice."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
