"""Shared fixtures for the Breek test suite.

Everything here runs the real contract file through ``gltest.direct``, which
loads the actual py-genlayer runner in-process. There is no re-implementation of
contract logic in the tests: pure helpers are imported from the loaded module so
a test can only pass if the shipped code is correct.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from gltest.direct import VMContext, create_address, deploy_contract

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "contracts" / "BreekForecast.py"
MODULE_NAME = "_contract_BreekForecast"

DAY = 86400
HOUR = 3600
WEEK = 7 * DAY
GEN = 10**18
ENTRY_FEE = 1 * GEN


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
    """Lowercase 0x hex, matching what the contract's views return."""
    raw = addr.as_bytes if hasattr(addr, "as_bytes") else bytes(addr)
    return "0x" + raw.hex()


def warp_to(vm: VMContext, unix: int) -> None:
    """Set consensus time and make the contract see it.

    ``VMContext.warp`` refreshes sender, origin and value but gltest 0.29.2 does
    not copy the new datetime into the already-imported ``gl.message_raw``. The
    contract reads its clock from there, so set it too -- otherwise every warp
    silently leaves the contract frozen at deploy time.
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
    close_px: str,
    *,
    all_closed: bool = True,
    drop_hour: int | None = None,
    reverse: bool = False,
    unaligned: bool = False,
) -> str:
    """Build a Gate.io hourly candlestick array.

    Row layout mirrors the live feed: ``[ts, quote_vol, close, high, low, open,
    base_vol, closed_flag]``. Only the LAST candle's close matters here; the
    filler values prove the parser selects by timestamp, not by position.
    """
    n = (window_end - window_start) // HOUR
    rows = []
    for i in range(n):
        ts = window_start + i * HOUR
        if drop_hour is not None and i == drop_hour:
            continue
        c = close_px if i == n - 1 else "50.00000000"
        rows.append(
            [
                str(ts + (1 if unaligned and i == 0 else 0)),
                "123456.789",
                c,
                "999999.0",
                "0.00000001",
                "50.00000000",
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
    close_px: str,
    *,
    omit_end: bool = False,
    numeric: bool = False,
) -> str:
    """Build a CoinGecko market_chart/range document.

    The contract asks for the window padded by an hour either side, so the
    closing instant is an interior point of this series.
    """
    prices = []
    ts = window_start - HOUR
    while ts <= window_end + HOUR:
        if ts == window_end:
            if not omit_end:
                prices.append([ts * 1000, _num(close_px, numeric)])
        else:
            prices.append([ts * 1000, _num("50.5", numeric)])
        ts += HOUR
    return json.dumps({"prices": prices, "market_caps": [], "total_volumes": []})


def _num(text: str, numeric: bool):
    if numeric:
        return int(float(text))
    return float(text)


def mock_feeds(
    vm: VMContext,
    symbol: str,
    window_start: int,
    window_end: int,
    *,
    a_close: str,
    b_close: str | None = None,
    gate_kwargs: dict | None = None,
    cg_kwargs: dict | None = None,
) -> None:
    """Mock both pricing sources for one asset over one window."""
    b_close = a_close if b_close is None else b_close
    vm.mock_web(
        GATE_URL_RE % symbol,
        {
            "method": "GET",
            "status": 200,
            "body": gate_body(window_start, window_end, a_close, **(gate_kwargs or {})),
        },
    )
    vm.mock_web(
        CG_URL_RE % CG_SLUG[symbol],
        {
            "method": "GET",
            "status": 200,
            "body": cg_body(window_start, window_end, b_close, **(cg_kwargs or {})),
        },
    )


# ---------------------------------------------------------------------------
# Commit-reveal helpers
# ---------------------------------------------------------------------------
# The digest below is written out independently rather than imported from the
# contract. If it were imported, a bug in the contract's own hashing would be
# invisible -- both sides would be wrong in the same way and every test would
# still pass. This is the scheme as a third-party client must implement it,
# from the documented preimage, so the contract has to agree with something
# outside itself.

PRICE_SCALE = 10**8
COMMIT_VERSION = "c1"

#: Any hex string long enough to satisfy the contract's minimum.
SALT_A = "a1b2c3d4e5f60718"
SALT_B = "00ff00ff00ff00ff"
SALT_C = "dead0000beef1111"
SALT_D = "9876543210abcdef"


def scale_price(text: str) -> int:
    """Decimal string -> PRICE_SCALE integer, without touching a float."""
    neg = text.startswith("-")
    if neg:
        text = text[1:]
    if "." in text:
        whole, frac = text.split(".", 1)
    else:
        whole, frac = text, ""
    frac = (frac + "0" * 8)[:8]
    value = int(whole or "0") * PRICE_SCALE + int(frac or "0")
    return -value if neg else value


def commitment(round_id: int, who, forecast: str, salt: str) -> str:
    """Reproduce the contract's commitment from the published preimage."""
    addr = who if isinstance(who, str) else hexaddr(who)
    preimage = "%s|%d|%s|%d|%s" % (
        COMMIT_VERSION,
        round_id,
        addr.lower(),
        scale_price(forecast),
        salt,
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def commit(contract, vm, who, round_id: int, forecast: str, salt: str, *, value=ENTRY_FEE):
    """Enter a round with a sealed forecast, as ``who``."""
    vm.sender = who
    vm.origin = who
    vm.value = value
    return contract.commit_forecast(round_id, commitment(round_id, who, forecast, salt))


def reveal(contract, vm, who, round_id: int, forecast: str, salt: str):
    """Open a commitment, as ``who``."""
    vm.sender = who
    vm.origin = who
    vm.value = 0
    return contract.reveal_forecast(round_id, forecast, salt)


# ---------------------------------------------------------------------------
# Equivalence-principle helpers
# ---------------------------------------------------------------------------
# gl.eq_principle.strict_eq votes AGREE exactly when a validator's own run of
# the non-deterministic block equals the leader's. Its real validator path uses
# gl.vm.spawn_sandbox, which gltest 0.29.2 does not implement in direct mode, so
# we drive the captured leader closure and apply the same equality rule. The
# closure is the contract's own pricing block; only the sandbox plumbing is
# bypassed.

LEADER_ERRORED = object()


def leader_payload(vm: VMContext) -> str:
    stored, _leader_fn, _validator_fn = vm._captured_validators[-1]
    return stored


def validator_payload(vm: VMContext) -> str:
    _stored, leader_fn, _validator_fn = vm._captured_validators[-1]
    return leader_fn()


def strict_eq_agrees(vm: VMContext, leader_result=None) -> bool:
    stored, leader_fn, _validator_fn = vm._captured_validators[-1]
    leader = stored if leader_result is None else leader_result
    try:
        mine = leader_fn()
    except Exception:
        return leader is LEADER_ERRORED
    if leader is LEADER_ERRORED:
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
def dave():
    return create_address("breek-dave")


@pytest.fixture
def breek(vm, alice):
    """Deploy the contract and yield ``(contract, module)`` inside an active VM.

    The module is handed back so tests can exercise the contract's own pure
    helpers -- calendar maths, scaling, scoring -- rather than a copy.
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
