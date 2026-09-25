"""Shared fixtures for the Breek Market test suite.

Everything here runs the real contract file through ``gltest.direct``, which
loads the actual py-genlayer runner in-process. There is no re-implementation of
contract logic in the tests: pure helpers are imported from the loaded module so
a test can only pass if the shipped code is correct.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from gltest.direct import VMContext, create_address, deploy_contract

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "contracts" / "BreekMarket.py"
MODULE_NAME = "_contract_BreekMarket"

DAY = 86400
HOUR = 3600
WEEK = 7 * DAY
GEN = 10**18


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def iso(unix: int, micros: int = 0) -> str:
    """Render Unix seconds the way GenVM hands us consensus time."""
    days, rem = divmod(unix, DAY)
    h, rem = divmod(rem, HOUR)
    mi, s = divmod(rem, 60)
    y, m, d = civil_from_days(days)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%06dZ" % (y, m, d, h, mi, s, micros)


def hexaddr(addr) -> str:
    """Lowercase 0x hex for an address, matching what the contract's views return.

    ``create_address`` hands back an ``Address`` or raw 20 bytes depending on how
    the value has travelled, so accept either.
    """
    raw = addr.as_bytes if hasattr(addr, "as_bytes") else bytes(addr)
    return "0x" + raw.hex()


def warp_to(vm: VMContext, unix: int) -> None:
    """Set consensus time to ``unix`` seconds and make the contract see it.

    ``VMContext.warp`` updates the VM's own datetime and refreshes ``gl.message``,
    but gltest 0.29.2 does not copy the new datetime into the already-imported
    ``gl.message_raw`` dict -- only sender, origin and value. The contract reads
    its clock from ``gl.message_raw['datetime']``, so we set that too, otherwise
    every warp would silently leave the contract frozen at deploy time.
    """
    stamp = iso(unix)
    vm.warp(stamp)
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and getattr(gl, "message_raw", None) is not None:
        gl.message_raw["datetime"] = stamp


def civil_from_days(z: int) -> tuple[int, int, int]:
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


def days_from_civil(y: int, m: int, d: int) -> int:
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def day_window(y: int, m: int, d: int) -> tuple[int, int]:
    """GMT+1 calendar day -> (window_start, window_end) in Unix seconds."""
    start = days_from_civil(y, m, d) * DAY - HOUR
    return start, start + DAY


def week_window(y: int, m: int, d: int) -> tuple[int, int]:
    start = days_from_civil(y, m, d) * DAY - HOUR
    return start, start + WEEK


# ---------------------------------------------------------------------------
# Source body builders -- shaped exactly like the live feeds
# ---------------------------------------------------------------------------

GATE_URL_RE = r"api\.gateio\.ws.*currency_pair=%s_USDT"
CG_URL_RE = r"api\.coingecko\.com.*/coins/%s/market_chart/range"

CG_SLUG = {"SOL": "solana", "ETH": "ethereum", "NEAR": "near"}


def gate_body(
    window_start: int,
    window_end: int,
    open_px: str,
    close_px: str,
    *,
    all_closed: bool = True,
    drop_hour: int | None = None,
    reverse: bool = False,
    unaligned: bool = False,
) -> str:
    """Build a Gate.io hourly candlestick array.

    Row layout mirrors the live feed: ``[ts, quote_vol, close, high, low, open,
    base_vol, closed_flag]``. Only the first candle's open and the last candle's
    close matter to the contract; the filler values in between exist to prove
    the parser selects by timestamp rather than by position.
    """
    n = (window_end - window_start) // HOUR
    rows = []
    for i in range(n):
        ts = window_start + i * HOUR
        if drop_hour is not None and i == drop_hour:
            continue
        o = open_px if i == 0 else "50.00000000"
        c = close_px if i == n - 1 else "50.00000000"
        rows.append(
            [
                str(ts + (1 if unaligned and i == 0 else 0)),
                "123456.789",
                c,
                "999999.0",
                "0.00000001",
                o,
                "1000.0",
                "true" if all_closed else ("false" if i == n - 1 else "true"),
            ]
        )
    if reverse:
        rows.reverse()
    return json.dumps(rows)


def cg_body(
    window_start: int,
    window_end: int,
    open_px: str,
    close_px: str,
    *,
    omit_start: bool = False,
    omit_end: bool = False,
    numeric: bool = False,
) -> str:
    """Build a CoinGecko market_chart/range document.

    The contract asks for the window padded by an hour either side, so the
    series here spans ``window_start - HOUR`` to ``window_end + HOUR`` and the
    boundary instants are interior points.
    """
    prices = []
    ts = window_start - HOUR
    while ts <= window_end + HOUR:
        if ts == window_start:
            if not omit_start:
                prices.append([ts * 1000, _num(open_px, numeric)])
        elif ts == window_end:
            if not omit_end:
                prices.append([ts * 1000, _num(close_px, numeric)])
        else:
            prices.append([ts * 1000, _num("50.5", numeric)])
        ts += HOUR
    return json.dumps(
        {"prices": prices, "market_caps": [], "total_volumes": []}
    )


def _num(text: str, numeric: bool):
    """Emit the price as a JSON number (default) or as an integer."""
    if numeric:
        return int(float(text))
    return float(text)


def mock_asset(
    vm: VMContext,
    symbol: str,
    window_start: int,
    window_end: int,
    *,
    a_open: str,
    a_close: str,
    b_open: str | None = None,
    b_close: str | None = None,
    gate_kwargs: dict | None = None,
    cg_kwargs: dict | None = None,
) -> None:
    """Mock both settlement sources for one asset over one window."""
    b_open = a_open if b_open is None else b_open
    b_close = a_close if b_close is None else b_close
    vm.mock_web(
        GATE_URL_RE % symbol,
        {
            "method": "GET",
            "status": 200,
            "body": gate_body(
                window_start, window_end, a_open, a_close, **(gate_kwargs or {})
            ),
        },
    )
    vm.mock_web(
        CG_URL_RE % CG_SLUG[symbol],
        {
            "method": "GET",
            "status": 200,
            "body": cg_body(
                window_start, window_end, b_open, b_close, **(cg_kwargs or {})
            ),
        },
    )


# ---------------------------------------------------------------------------
# Equivalence-principle helpers
# ---------------------------------------------------------------------------
# gl.eq_principle.strict_eq votes AGREE exactly when a validator's own run of the
# non-deterministic block returns a value equal to the leader's. Its real
# validator path goes through gl.vm.spawn_sandbox, which gltest 0.29.2 does not
# implement in direct mode (it returns an undecodable result code), so we drive
# the captured leader closure ourselves and apply the same equality rule. The
# closure is the contract's own settle block, so nothing about the settlement
# logic is stubbed -- only the sandbox plumbing around it.

LEADER_ERRORED = object()


def leader_payload(vm: VMContext) -> str:
    """The payload the leader produced in the most recent resolve."""
    stored, _leader_fn, _validator_fn = vm._captured_validators[-1]
    return stored


def validator_payload(vm: VMContext) -> str:
    """Re-run the non-deterministic block as an independent validator would.

    Whatever web mocks are registered right now stand in for that validator's own
    view of the world.
    """
    _stored, leader_fn, _validator_fn = vm._captured_validators[-1]
    return leader_fn()


def strict_eq_agrees(vm: VMContext, leader_result=None) -> bool:
    """Would a validator vote AGREE on this round?

    Pass ``leader_result`` to test a leader that reported something other than
    what an honest fetch produces, or ``LEADER_ERRORED`` for a leader that failed.
    """
    stored, leader_fn, _validator_fn = vm._captured_validators[-1]
    leader = stored if leader_result is None else leader_result
    try:
        mine = leader_fn()
    except Exception:
        # Our own fetch failed. We cannot confirm the leader either way.
        return leader is LEADER_ERRORED
    if leader is LEADER_ERRORED:
        # The leader errored but we succeeded: vote against.
        return False
    return mine == leader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vm() -> VMContext:
    return VMContext()


@pytest.fixture
def alice():
    return create_address("breek-alice")


@pytest.fixture
def bob():
    return create_address("breek-bob")


@pytest.fixture
def carol():
    return create_address("breek-carol")


@pytest.fixture
def breek(vm, alice):
    """Deploy the contract and yield ``(contract, module)`` inside an active VM.

    The module is handed back so tests can exercise the contract's own pure
    helpers -- calendar maths, decimal scaling, verdicts -- rather than a copy.
    """
    vm.sender = alice
    vm.origin = alice
    vm.warp(iso(1_700_000_000))
    with vm.activate():
        contract = deploy_contract(CONTRACT, vm)
        module = sys.modules[MODULE_NAME]
        warp_to(vm, 1_700_000_000)
        yield contract, module


@pytest.fixture
def mod(breek):
    return breek[1]


@pytest.fixture
def clock(vm, breek):
    """Warp consensus time: ``clock(unix_seconds)``."""

    def _warp(unix: int) -> None:
        warp_to(vm, unix)

    return _warp
