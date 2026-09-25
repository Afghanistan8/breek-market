# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Breek Market -- a permissionless prediction market that settles itself.

Most markets resolve through an admin key or a single oracle. Breek removes that
party. When anyone calls ``resolve_market``, the contract itself fetches two
independent public feeds inside a GenLayer equivalence-principle block,
reconstructs the target GMT+1 window from each source separately, and derives a
verdict from each source's own open and close.

    UP + UP                       -> settle UP
    DOWN + DOWN                   -> settle DOWN
    same winner + same winner     -> settle that winner
    any disagreement / TIE / gap  -> INCONCLUSIVE, every stake refunded

A single source can never produce a direction or a winner. There is no owner, no
pause, no admin resolve, no upgrade hook and no privileged address anywhere in
this file. ``resolve_market`` takes a market id and nothing else -- callers
cannot supply prices, URLs, slugs, winners or results.

Every settlement instant is derived from consensus time
(``gl.message_raw['datetime']``), never a host clock. All money maths is integer
only; prices are fixed-point integers scaled by ``PRICE_SCALE``.
"""

import json
from dataclasses import dataclass

from genlayer import *

# ===========================================================================
# Constants
# ===========================================================================

DAY = 86400
HOUR = 3600
WEEK = 7 * DAY

#: GMT+1 is a fixed +3600 offset from Unix UTC. No DST, no tz database, ever.
GMT_PLUS_ONE = 3600

GEN = 10**18
MIN_STAKE = 2 * GEN
MAX_STAKE = 4 * GEN

MAX_FORWARD_DAYS = 366
TERMINAL_REFUND_DELAY = 5 * DAY
MAX_PAGE = 50
MAX_SOURCE_BYTES = 60000
PRICE_SCALE = 10**8
BPS_SCALE = 10000

PAYLOAD_VERSION = "v1"
PAYLOAD_FIELDS = 13

UP = "UP"
DOWN = "DOWN"
TIE = "TIE"
INCONCLUSIVE = "INCONCLUSIVE"

# Phases are derived from consensus time, never stored.
PHASE_OPEN = "OPEN"
PHASE_WINDOW_LIVE = "WINDOW_LIVE"
PHASE_READY = "READY_TO_SETTLE"
PHASE_SETTLED_UP = "SETTLED_UP"
PHASE_SETTLED_DOWN = "SETTLED_DOWN"
PHASE_SETTLED_WINNER = "SETTLED_WINNER"
PHASE_INCONCLUSIVE = "INCONCLUSIVE"

KIND_DIR_DAILY = "DIR_DAILY"
KIND_DIR_WEEKLY = "DIR_WEEKLY"
KIND_REL_DAILY = "REL_DAILY"
KIND_REL_WEEKLY = "REL_WEEKLY"

#: REL_HOURLY / DIR_HOURLY are deliberately absent. scripts/check_sources.py
#: could not prove that both sources reconstruct an exact GMT+1 hour, so hourly
#: is not shipped. The two-source rule is never weakened to enable a timeframe.
KINDS = (KIND_DIR_DAILY, KIND_DIR_WEEKLY, KIND_REL_DAILY, KIND_REL_WEEKLY)

TIMEFRAME_DAILY = "DAILY"
TIMEFRAME_WEEKLY = "WEEKLY"

CAT_CRYPTO = "CRYPTO"
CAT_DOMINANCE = "DOMINANCE"

#: Catalog order is part of the consensus payload. Never reorder these without
#: bumping PAYLOAD_VERSION.
CRYPTO_ASSETS = ("SOL", "ETH", "NEAR")
DOMINANCE_ASSETS = ("BTC.D", "ETH.D", "OTHERS.D")

#: DOMINANCE is a catalog entry only. Settling it needs BTC and ETH market cap
#: plus TOTAL crypto market cap at two PAST GMT+1 instants from two independent
#: keyless feeds. No such second feed exists: every keyless dominance endpoint we
#: probed publishes current values only, and they disagree by several percentage
#: points because they aggregate different coin universes. Rather than settle
#: from one source, Breek refuses to create the market. See docs/SPEC.md.
SETTLABLE_CATEGORIES = (CAT_CRYPTO,)

SOURCE_A = "gate.io"
SOURCE_B = "coingecko"

# Compile-time URL templates. Never caller-supplied, never contain an API key.
GATE_URL = (
    "https://api.gateio.ws/api/v4/spot/candlesticks"
    "?currency_pair={pair}&interval=1h&from={frm}&to={to}"
)
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/{cid}/market_chart/range"
    "?vs_currency=usd&from={frm}&to={to}"
)

GATE_PAIRS = {"SOL": "SOL_USDT", "ETH": "ETH_USDT", "NEAR": "NEAR_USDT"}
COINGECKO_IDS = {"SOL": "solana", "ETH": "ethereum", "NEAR": "near"}

# Gate.io v4 spot candlestick row layout:
#   [0] window open time (unix s)  [1] quote volume  [2] close  [3] high
#   [4] low  [5] open  [6] base volume  [7] "true" iff the window has closed
GATE_TS = 0
GATE_CLOSE = 2
GATE_OPEN = 5
GATE_CLOSED_FLAG = 7

# Some feeds gate non-browser clients; pin a stable browser-like identity so
# every validator sends byte-identical request headers.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Error prefixes.
#   EXPECTED:  bad user input or wrong phase
#   TRANSIENT: retryable fetch failure; the market stays resolvable
#   EXTERNAL:  a source is unusable for this window
#   INVARIANT: the agreed payload failed deterministic re-derivation
E_EXPECTED = "EXPECTED:"
E_TRANSIENT = "TRANSIENT:"
E_EXTERNAL = "EXTERNAL:"
E_INVARIANT = "INVARIANT:"


# ===========================================================================
# Civil calendar maths, hand-rolled
# ===========================================================================
# The contract must not depend on host timezone data, so days are converted with
# Howard Hinnant's proleptic Gregorian algorithms and GMT+1 is applied as a bare
# -3600 second shift.


def _is_leap(y: int) -> bool:
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0


def _days_in_month(y: int, m: int) -> int:
    if m == 2:
        return 29 if _is_leap(y) else 28
    if m in (4, 6, 9, 11):
        return 30
    return 31


def _days_from_civil(y: int, m: int, d: int) -> int:
    """Days since 1970-01-01."""
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> tuple[int, int, int]:
    """Inverse of :func:`_days_from_civil`."""
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


def _weekday_from_days(z: int) -> int:
    """0 = Monday .. 6 = Sunday. 1970-01-01 was a Thursday."""
    return (z + 3) % 7


def _parse_iso_date(text: str) -> tuple[int, int, int]:
    """Strict ``YYYY-MM-DD``. No slop, no alternative separators."""
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise gl.vm.UserError(E_EXPECTED + "WINDOW_ID_FORMAT")
    ys, ms, ds = text[0:4], text[5:7], text[8:10]
    if not (ys.isdigit() and ms.isdigit() and ds.isdigit()):
        raise gl.vm.UserError(E_EXPECTED + "WINDOW_ID_FORMAT")
    y, m, d = int(ys), int(ms), int(ds)
    if y < 1970 or y > 9999 or m < 1 or m > 12:
        raise gl.vm.UserError(E_EXPECTED + "WINDOW_ID_RANGE")
    if d < 1 or d > _days_in_month(y, m):
        raise gl.vm.UserError(E_EXPECTED + "WINDOW_ID_RANGE")
    return y, m, d


def _format_iso_date(z: int) -> str:
    y, m, d = _civil_from_days(z)
    return "%04d-%02d-%02d" % (y, m, d)


def _parse_consensus_datetime(text: str) -> int:
    """Parse the GenVM consensus datetime into Unix seconds.

    The runtime hands us an ISO-8601 instant such as
    ``2026-09-25T13:43:54.996120Z``. Fractional seconds are truncated, not
    rounded, so the value is monotone with the string.
    """
    if len(text) < 19 or text[4] != "-" or text[7] != "-":
        raise gl.vm.UserError(E_INVARIANT + "CONSENSUS_TIME_FORMAT")
    if text[10] not in ("T", " ") or text[13] != ":" or text[16] != ":":
        raise gl.vm.UserError(E_INVARIANT + "CONSENSUS_TIME_FORMAT")
    y, m, d = _parse_iso_date(text[0:10])
    hh, mm, ss = text[11:13], text[14:16], text[17:19]
    if not (hh.isdigit() and mm.isdigit() and ss.isdigit()):
        raise gl.vm.UserError(E_INVARIANT + "CONSENSUS_TIME_FORMAT")
    h, mi, s = int(hh), int(mm), int(ss)
    if h > 23 or mi > 59 or s > 60:
        raise gl.vm.UserError(E_INVARIANT + "CONSENSUS_TIME_RANGE")
    if s == 60:  # tolerate a leap-second spelling by clamping
        s = 59
    return _days_from_civil(y, m, d) * DAY + h * HOUR + mi * 60 + s


def _now() -> int:
    """Consensus time in Unix seconds. The only clock this contract trusts."""
    return _parse_consensus_datetime(gl.message_raw["datetime"])


def _window_bounds(timeframe: str, window_id: str) -> tuple[int, int]:
    """Resolve a GMT+1 window id to ``(window_start, window_end)`` in Unix time.

    A GMT+1 calendar day D starts at ``day_index(D) * 86400 - 3600``: midnight in
    GMT+1 is 23:00 UTC on the preceding day.
    """
    y, m, d = _parse_iso_date(window_id)
    z = _days_from_civil(y, m, d)
    start = z * DAY - GMT_PLUS_ONE
    if timeframe == TIMEFRAME_DAILY:
        return start, start + DAY
    if timeframe == TIMEFRAME_WEEKLY:
        if _weekday_from_days(z) != 0:
            raise gl.vm.UserError(E_EXPECTED + "WEEK_MUST_START_MONDAY")
        return start, start + WEEK
    raise gl.vm.UserError(E_EXPECTED + "UNKNOWN_TIMEFRAME")


# ===========================================================================
# Fixed-point helpers. No floats anywhere in a money or settlement path.
# ===========================================================================

_PRICE_DIGITS = 8  # len(str(PRICE_SCALE)) - 1


def _dec_to_scaled(text: str) -> int:
    """Convert a decimal string to a ``PRICE_SCALE`` integer.

    ``"80494.31000000"`` and ``"80494.31"`` must land on the same integer, so the
    fraction is padded then truncated rather than rounded. Exponent notation is
    rejected outright: silently mis-scaling a price is worse than not settling.
    """
    s = text.strip()
    if s == "":
        raise gl.vm.UserError(E_EXTERNAL + "EMPTY_NUMBER")
    if s[0] == "+":
        s = s[1:]
    if s[:1] == "-":
        raise gl.vm.UserError(E_EXTERNAL + "NEGATIVE_PRICE")
    if "e" in s or "E" in s:
        raise gl.vm.UserError(E_EXTERNAL + "EXPONENT_NOTATION")
    dot = s.find(".")
    if dot == -1:
        whole, frac = s, ""
    else:
        whole, frac = s[:dot], s[dot + 1:]
        if "." in frac:
            raise gl.vm.UserError(E_EXTERNAL + "MALFORMED_NUMBER")
    if whole == "":
        whole = "0"
    if not whole.isdigit():
        raise gl.vm.UserError(E_EXTERNAL + "MALFORMED_NUMBER")
    if frac != "" and not frac.isdigit():
        raise gl.vm.UserError(E_EXTERNAL + "MALFORMED_NUMBER")
    frac = (frac + "0" * _PRICE_DIGITS)[:_PRICE_DIGITS]
    return int(whole) * PRICE_SCALE + int(frac)


def _json_number_to_scaled(value) -> int:
    """Scale a JSON number that was decoded with ``parse_float=str``.

    Decoding floats as strings is what keeps this path integer-only: the raw
    decimal text from the feed is converted directly, so no IEEE-754 value ever
    touches a price.
    """
    if isinstance(value, bool):
        raise gl.vm.UserError(E_EXTERNAL + "NOT_A_NUMBER")
    if isinstance(value, int):
        return value * PRICE_SCALE
    if isinstance(value, str):
        return _dec_to_scaled(value)
    raise gl.vm.UserError(E_EXTERNAL + "NOT_A_NUMBER")


def _scaled_to_dec(value: int) -> str:
    """Render a scaled integer back to a decimal string, for the payload."""
    whole = value // PRICE_SCALE
    frac = value % PRICE_SCALE
    return "%d.%0*d" % (whole, _PRICE_DIGITS, frac)


def _bps(open_: int, close: int) -> int:
    """Return over the window, in basis points, floor-divided."""
    if open_ <= 0:
        raise gl.vm.UserError(E_EXTERNAL + "NON_POSITIVE_OPEN")
    return ((close - open_) * BPS_SCALE) // open_


# ===========================================================================
# Verdict maths
# ===========================================================================


def _direction_verdict(open_: int, close: int) -> str:
    """Flat is DOWN, by design: a Breek market never settles 'unchanged'."""
    return UP if close > open_ else DOWN


def _relative_verdict(symbols: tuple, series: dict) -> str:
    """Strictly greatest bps wins. Any joint best is a TIE."""
    best = None
    winner = ""
    tied = False
    for sym in symbols:
        o, c = series[sym]
        score = _bps(o, c)
        if best is None or score > best:
            best = score
            winner = sym
            tied = False
        elif score == best:
            tied = True
    if best is None or tied:
        return TIE
    return winner


def _combine(a_verdict: str, b_verdict: str) -> str:
    """One source can never settle. A TIE can never produce a winner."""
    if a_verdict == "" or b_verdict == "":
        return INCONCLUSIVE
    if a_verdict == TIE or b_verdict == TIE:
        return INCONCLUSIVE
    if a_verdict == INCONCLUSIVE or b_verdict == INCONCLUSIVE:
        return INCONCLUSIVE
    if a_verdict != b_verdict:
        return INCONCLUSIVE
    return a_verdict


# ===========================================================================
# Storage records
# ===========================================================================


@allow_storage
@dataclass
class Market:
    market_id: u256
    kind: str
    category: str
    asset: str          # the single asset for DIR kinds, "" for REL kinds
    timeframe: str
    window_id: str      # GMT+1 day, or the Monday of a GMT+1 week
    window_start: u64
    window_end: u64
    cutoff_at: u64      # staking closes when the candle opens
    settles_at: u64     # resolve opens once the candle has closed
    terminal_refund_at: u64
    creator: Address
    created_at: u64
    pool: u256
    stakers: u64
    settled: bool
    outcome: str        # "", UP, DOWN, a catalog symbol, or INCONCLUSIVE
    settled_at: u64
    evidence: str       # the agreed consensus payload, verbatim


@allow_storage
@dataclass
class Position:
    side: str
    amount: u256
    claimed: bool


# ===========================================================================
# Contract
# ===========================================================================


class BreekMarket(gl.Contract):
    """Permissionless GMT+1 prediction markets with two-source self-settlement."""

    markets: TreeMap[u256, Market]
    market_order: DynArray[u256]
    dedupe: TreeMap[str, u256]

    positions: TreeMap[u256, TreeMap[Address, Position]]
    side_totals: TreeMap[u256, TreeMap[str, u256]]
    participation: TreeMap[Address, DynArray[u256]]

    next_id: u256
    total_staked: u256
    total_paid: u256
    markets_settled: u256
    markets_inconclusive: u256

    def __init__(self) -> None:
        self.next_id = u256(1)
        self.total_staked = u256(0)
        self.total_paid = u256(0)
        self.markets_settled = u256(0)
        self.markets_inconclusive = u256(0)

    # -- internal helpers ---------------------------------------------------

    def _catalog(self, category: str) -> tuple:
        if category == CAT_CRYPTO:
            return CRYPTO_ASSETS
        if category == CAT_DOMINANCE:
            return DOMINANCE_ASSETS
        raise gl.vm.UserError(E_EXPECTED + "UNKNOWN_CATEGORY")

    def _market(self, market_id: int) -> Market:
        m = self.markets.get(u256(market_id))
        if m is None:
            raise gl.vm.UserError(E_EXPECTED + "NO_SUCH_MARKET")
        return m

    def _phase(self, m: Market, now: int) -> str:
        if m.settled:
            if m.outcome == UP:
                return PHASE_SETTLED_UP
            if m.outcome == DOWN:
                return PHASE_SETTLED_DOWN
            if m.outcome == INCONCLUSIVE:
                return PHASE_INCONCLUSIVE
            return PHASE_SETTLED_WINNER
        if now < m.cutoff_at:
            return PHASE_OPEN
        if now < m.settles_at:
            return PHASE_WINDOW_LIVE
        return PHASE_READY

    def _is_relative(self, kind: str) -> bool:
        return kind == KIND_REL_DAILY or kind == KIND_REL_WEEKLY

    def _valid_sides(self, m: Market) -> tuple:
        if self._is_relative(m.kind):
            return self._catalog(m.category)
        return (UP, DOWN)

    def _refund(self, to: Address, amount: int) -> None:
        if amount > 0:
            gl.get_contract_at(to).emit_transfer(value=u256(amount), on="finalized")

    # -- create -------------------------------------------------------------

    @gl.public.write
    def create_market(
        self,
        kind: str,
        category: str,
        asset: str,
        timeframe: str,
        window_id: str,
    ) -> str:
        """Create a market on a listed asset or category. Anyone may call this.

        Nothing here is privileged and nothing is caller-configurable beyond
        catalog keys and the window: no URLs, no prices, no fee, no resolver.
        """
        now = _now()

        if kind not in KINDS:
            raise gl.vm.UserError(E_EXPECTED + "UNKNOWN_KIND")
        if timeframe not in (TIMEFRAME_DAILY, TIMEFRAME_WEEKLY):
            raise gl.vm.UserError(E_EXPECTED + "UNKNOWN_TIMEFRAME")
        if not kind.endswith("_" + timeframe):
            raise gl.vm.UserError(E_EXPECTED + "KIND_TIMEFRAME_MISMATCH")

        catalog = self._catalog(category)
        if category not in SETTLABLE_CATEGORIES:
            # Refusing beats settling from one source. See docs/SPEC.md.
            raise gl.vm.UserError(E_EXPECTED + "CATEGORY_NOT_SETTLABLE")

        if self._is_relative(kind):
            if asset != "":
                raise gl.vm.UserError(E_EXPECTED + "REL_TAKES_NO_ASSET")
        else:
            if asset not in catalog:
                raise gl.vm.UserError(E_EXPECTED + "UNKNOWN_ASSET")

        window_start, window_end = _window_bounds(timeframe, window_id)

        if window_start <= now:
            raise gl.vm.UserError(E_EXPECTED + "WINDOW_NOT_IN_FUTURE")
        if window_start - now > MAX_FORWARD_DAYS * DAY:
            raise gl.vm.UserError(E_EXPECTED + "WINDOW_TOO_FAR_AHEAD")

        key = kind + "|" + category + "|" + asset + "|" + window_id
        if key in self.dedupe:
            raise gl.vm.UserError(E_EXPECTED + "DUPLICATE_MARKET")

        market_id = self.next_id
        self.next_id = u256(int(self.next_id) + 1)

        self.markets[market_id] = Market(
            market_id=market_id,
            kind=kind,
            category=category,
            asset=asset,
            timeframe=timeframe,
            window_id=window_id,
            window_start=u64(window_start),
            window_end=u64(window_end),
            cutoff_at=u64(window_start),
            settles_at=u64(window_end),
            terminal_refund_at=u64(window_end + TERMINAL_REFUND_DELAY),
            creator=gl.message.sender_address,
            created_at=u64(now),
            pool=u256(0),
            stakers=u64(0),
            settled=False,
            outcome="",
            settled_at=u64(0),
            evidence="",
        )
        self.market_order.append(market_id)
        self.dedupe[key] = market_id
        return "CREATED:" + str(int(market_id))

    # -- stake --------------------------------------------------------------

    @gl.public.write.payable
    def take_position(self, market_id: int, side: str) -> str:
        """Stake 2-4 GEN on a side before the window opens.

        Anything invalid refunds the attached GEN inside this same call. It must
        never revert once value has been credited to the contract, because a
        revert after credit would strand the stake with no claim path.
        """
        value = int(gl.message.value)
        if value == 0:
            raise gl.vm.UserError(E_EXPECTED + "NO_VALUE_ATTACHED")

        sender = gl.message.sender_address
        now = _now()

        m = self.markets.get(u256(market_id))
        if m is None:
            self._refund(sender, value)
            return "REFUNDED:NO_SUCH_MARKET"

        if now >= int(m.cutoff_at):
            self._refund(sender, value)
            return "REFUNDED:WINDOW_ALREADY_OPEN"

        if side not in self._valid_sides(m):
            self._refund(sender, value)
            return "REFUNDED:INVALID_SIDE"

        book = self.positions.get_or_insert_default(u256(market_id))
        existing = book.get(sender)
        prior = int(existing.amount) if existing is not None else 0

        if existing is not None and existing.side != side:
            self._refund(sender, value)
            return "REFUNDED:SIDE_SWITCH_FORBIDDEN"

        total = prior + value
        if total < MIN_STAKE:
            self._refund(sender, value)
            return "REFUNDED:BELOW_MIN_STAKE"
        if total > MAX_STAKE:
            self._refund(sender, value)
            return "REFUNDED:ABOVE_MAX_STAKE"

        if existing is None:
            book[sender] = Position(side=side, amount=u256(total), claimed=False)
            m.stakers = u64(int(m.stakers) + 1)
            self.participation.get_or_insert_default(sender).append(u256(market_id))
        else:
            existing.amount = u256(total)

        totals = self.side_totals.get_or_insert_default(u256(market_id))
        totals[side] = u256(int(totals.get(side, u256(0))) + value)

        m.pool = u256(int(m.pool) + value)
        self.total_staked = u256(int(self.total_staked) + value)
        return "STAKED:" + str(total)

    # -- resolve ------------------------------------------------------------

    @gl.public.write
    def resolve_market(self, market_id: int) -> str:
        """Settle a market from two independent live feeds. Anyone may call this.

        The only argument is the market id. Everything that decides the outcome
        is either already stored on the market or fetched by the contract itself.
        """
        now = _now()
        m = self._market(market_id)

        if m.settled:
            raise gl.vm.UserError(E_EXPECTED + "ALREADY_SETTLED")
        if now < int(m.settles_at):
            raise gl.vm.UserError(E_EXPECTED + "WINDOW_NOT_CLOSED")

        # After the terminal delay the market must settle with zero HTTP. The
        # contract never invents a price, so an unresolvable window becomes a
        # full refund instead of a guess.
        if now >= int(m.terminal_refund_at):
            m.settled = True
            m.outcome = INCONCLUSIVE
            m.settled_at = u64(now)
            m.evidence = PAYLOAD_VERSION + "|TERMINAL_REFUND|" + str(int(m.terminal_refund_at))
            self.markets_inconclusive = u256(int(self.markets_inconclusive) + 1)
            return "INCONCLUSIVE:TERMINAL_REFUND"

        # Capture everything the closure needs as plain locals: a non-deterministic
        # block cannot touch storage.
        kind = m.kind
        category = m.category
        asset = m.asset
        timeframe = m.timeframe
        window_id = m.window_id
        window_start = int(m.window_start)
        window_end = int(m.window_end)
        symbols = (asset,) if not self._is_relative(kind) else self._catalog(category)
        relative = self._is_relative(kind)

        def settle_block() -> str:
            a_series = {}
            b_series = {}
            for sym in symbols:
                a_series[sym] = _fetch_gate(sym, window_start, window_end)
                b_series[sym] = _fetch_coingecko(sym, window_start, window_end)

            if relative:
                a_verdict = _relative_verdict(symbols, a_series)
                b_verdict = _relative_verdict(symbols, b_series)
            else:
                ao, ac = a_series[asset]
                bo, bc = b_series[asset]
                a_verdict = _direction_verdict(ao, ac)
                b_verdict = _direction_verdict(bo, bc)

            final = _combine(a_verdict, b_verdict)
            return "|".join(
                (
                    PAYLOAD_VERSION,
                    kind,
                    category,
                    asset,
                    timeframe,
                    SOURCE_A,
                    SOURCE_B,
                    window_id,
                    _encode_series(symbols, a_series),
                    a_verdict,
                    _encode_series(symbols, b_series),
                    b_verdict,
                    final,
                )
            )

        # Every web request lives inside the equivalence block. Nothing below
        # this line touches the network.
        agreed = gl.eq_principle.strict_eq(settle_block)

        outcome = self._parse_agreed(agreed, m, symbols)

        m.settled = True
        m.outcome = outcome
        m.settled_at = u64(now)
        m.evidence = agreed
        if outcome == INCONCLUSIVE:
            self.markets_inconclusive = u256(int(self.markets_inconclusive) + 1)
            return "INCONCLUSIVE:SOURCES_DISAGREE"
        self.markets_settled = u256(int(self.markets_settled) + 1)
        return "SETTLED:" + outcome

    def _parse_agreed(self, agreed: str, m: Market, symbols: tuple) -> str:
        """Re-derive the whole verdict from the agreed payload, offline.

        The payload is data, not an instruction. Every field is re-checked
        against this market and both verdicts plus the final result are
        recomputed from the series. A forged winner cannot survive this.
        """
        parts = agreed.split("|")
        if len(parts) != PAYLOAD_FIELDS:
            raise gl.vm.UserError(E_INVARIANT + "FIELD_COUNT")
        (
            version,
            kind,
            category,
            asset,
            timeframe,
            source_a,
            source_b,
            window_id,
            a_raw,
            a_verdict,
            b_raw,
            b_verdict,
            final,
        ) = parts

        if version != PAYLOAD_VERSION:
            raise gl.vm.UserError(E_INVARIANT + "VERSION")
        if kind != m.kind or category != m.category or asset != m.asset:
            raise gl.vm.UserError(E_INVARIANT + "MARKET_BINDING")
        if timeframe != m.timeframe or window_id != m.window_id:
            raise gl.vm.UserError(E_INVARIANT + "WINDOW_BINDING")
        if source_a != SOURCE_A or source_b != SOURCE_B:
            raise gl.vm.UserError(E_INVARIANT + "SOURCE_BINDING")

        a_series = _decode_series(symbols, a_raw)
        b_series = _decode_series(symbols, b_raw)

        if self._is_relative(m.kind):
            if _relative_verdict(symbols, a_series) != a_verdict:
                raise gl.vm.UserError(E_INVARIANT + "A_VERDICT")
            if _relative_verdict(symbols, b_series) != b_verdict:
                raise gl.vm.UserError(E_INVARIANT + "B_VERDICT")
        else:
            ao, ac = a_series[m.asset]
            bo, bc = b_series[m.asset]
            if _direction_verdict(ao, ac) != a_verdict:
                raise gl.vm.UserError(E_INVARIANT + "A_VERDICT")
            if _direction_verdict(bo, bc) != b_verdict:
                raise gl.vm.UserError(E_INVARIANT + "B_VERDICT")

        if _combine(a_verdict, b_verdict) != final:
            raise gl.vm.UserError(E_INVARIANT + "FINAL")

        if final == INCONCLUSIVE:
            return INCONCLUSIVE
        if self._is_relative(m.kind):
            if final not in symbols:
                raise gl.vm.UserError(E_INVARIANT + "WINNER_NOT_IN_CATALOG")
        else:
            if final not in (UP, DOWN):
                raise gl.vm.UserError(E_INVARIANT + "NOT_A_DIRECTION")
        return final

    # -- claim --------------------------------------------------------------

    @gl.public.write
    def claim(self, market_id: int) -> str:
        """Withdraw a payout or a refund. Idempotent per wallet.

        After a settled result, holders of the winning side split the whole pool
        pro-rata by stake. After INCONCLUSIVE -- or when nobody held the winning
        side -- every wallet withdraws exactly its own stake.
        """
        sender = gl.message.sender_address
        m = self._market(market_id)
        if not m.settled:
            raise gl.vm.UserError(E_EXPECTED + "NOT_SETTLED")

        book = self.positions.get(u256(market_id))
        if book is None:
            raise gl.vm.UserError(E_EXPECTED + "NO_POSITION")
        pos = book.get(sender)
        if pos is None:
            raise gl.vm.UserError(E_EXPECTED + "NO_POSITION")
        if pos.claimed:
            raise gl.vm.UserError(E_EXPECTED + "ALREADY_CLAIMED")

        stake = int(pos.amount)
        pool = int(m.pool)

        if m.outcome == INCONCLUSIVE:
            payout = stake
            reason = "REFUND_INCONCLUSIVE"
        else:
            totals = self.side_totals.get(u256(market_id))
            winning_total = 0
            if totals is not None:
                winning_total = int(totals.get(m.outcome, u256(0)))
            if winning_total == 0:
                # Settled, but nobody backed the winning side. Refunding beats
                # stranding the pool with no claimant.
                payout = stake
                reason = "REFUND_NO_WINNERS"
            elif pos.side != m.outcome:
                pos.claimed = True
                return "CLAIMED:0:LOST"
            else:
                payout = (pool * stake) // winning_total
                reason = "PAYOUT"

        pos.claimed = True
        self.total_paid = u256(int(self.total_paid) + payout)
        self._refund(sender, payout)
        return "CLAIMED:" + str(payout) + ":" + reason

    # -- views --------------------------------------------------------------

    @gl.public.view
    def get_catalog(self) -> dict:
        """Everything the UI needs to build a create form, with settlability."""
        return {
            "kinds": list(KINDS),
            "timeframes": [TIMEFRAME_DAILY, TIMEFRAME_WEEKLY],
            "categories": [
                {
                    "key": CAT_CRYPTO,
                    "assets": list(CRYPTO_ASSETS),
                    "settlable": True,
                    "return_basis": "(close-open)/open on the quoted USD/USDT price",
                    "note": "",
                },
                {
                    "key": CAT_DOMINANCE,
                    "assets": list(DOMINANCE_ASSETS),
                    "settlable": False,
                    "return_basis": "change in market-cap dominance percentage",
                    "note": (
                        "Listed but not settlable: no second independent keyless "
                        "feed publishes historical total market cap, so dominance "
                        "cannot be reconstructed twice. Breek refuses to settle "
                        "from one source."
                    ),
                },
            ],
            "stake": {
                "min_wei": str(MIN_STAKE),
                "max_wei": str(MAX_STAKE),
                "gen_wei": str(GEN),
            },
            "sources": {"a": SOURCE_A, "b": SOURCE_B},
            "timezone": "GMT+1 (fixed +3600, no DST)",
            "price_scale": str(PRICE_SCALE),
            "terminal_refund_delay_s": str(TERMINAL_REFUND_DELAY),
        }

    @gl.public.view
    def get_market(self, market_id: int) -> dict:
        m = self._market(market_id)
        return self._market_dict(m, _now())

    @gl.public.view
    def get_phase(self, market_id: int) -> str:
        return self._phase(self._market(market_id), _now())

    @gl.public.view
    def get_evidence(self, market_id: int) -> dict:
        """The agreed payload, verbatim, plus a decoded view of both series."""
        m = self._market(market_id)
        out = {
            "market_id": str(int(m.market_id)),
            "settled": m.settled,
            "outcome": m.outcome,
            "settled_at": str(int(m.settled_at)),
            "payload": m.evidence,
            "source_a": SOURCE_A,
            "source_b": SOURCE_B,
        }
        parts = m.evidence.split("|")
        if len(parts) == PAYLOAD_FIELDS:
            out["a_series"] = parts[8]
            out["a_verdict"] = parts[9]
            out["b_series"] = parts[10]
            out["b_verdict"] = parts[11]
            out["final"] = parts[12]
        return out

    @gl.public.view
    def list_markets(self, offset: int, limit: int) -> dict:
        """Newest first, paginated. ``limit`` is clamped to ``MAX_PAGE``."""
        now = _now()
        total = len(self.market_order)
        if limit <= 0:
            limit = MAX_PAGE
        if limit > MAX_PAGE:
            limit = MAX_PAGE
        if offset < 0:
            offset = 0
        rows = []
        idx = total - 1 - offset
        while idx >= 0 and len(rows) < limit:
            m = self.markets.get(self.market_order[idx])
            if m is not None:
                rows.append(self._market_dict(m, now))
            idx -= 1
        return {
            "total": str(total),
            "offset": str(offset),
            "limit": str(limit),
            "now": str(now),
            "markets": rows,
        }

    @gl.public.view
    def list_resolvable(self, limit: int) -> dict:
        """The resolve queue: everything a caller could settle right now."""
        now = _now()
        if limit <= 0 or limit > MAX_PAGE:
            limit = MAX_PAGE
        rows = []
        idx = len(self.market_order) - 1
        while idx >= 0 and len(rows) < limit:
            m = self.markets.get(self.market_order[idx])
            if m is not None and not m.settled and now >= int(m.settles_at):
                rows.append(self._market_dict(m, now))
            idx -= 1
        return {"now": str(now), "markets": rows}

    @gl.public.view
    def get_position(self, market_id: int, who: str) -> dict:
        m = self._market(market_id)
        addr = Address(who)
        book = self.positions.get(u256(market_id))
        pos = book.get(addr) if book is not None else None
        totals = self.side_totals.get(u256(market_id))
        winning_total = 0
        if totals is not None and m.settled and m.outcome != INCONCLUSIVE:
            winning_total = int(totals.get(m.outcome, u256(0)))
        out = {
            "market_id": str(market_id),
            "who": _lower_hex(addr),
            "has_position": pos is not None,
            "side": pos.side if pos is not None else "",
            "amount_wei": str(int(pos.amount)) if pos is not None else "0",
            "claimed": pos.claimed if pos is not None else False,
            "claimable_wei": "0",
            "claim_kind": "",
        }
        if pos is not None and m.settled and not pos.claimed:
            if m.outcome == INCONCLUSIVE:
                out["claimable_wei"] = str(int(pos.amount))
                out["claim_kind"] = "REFUND_INCONCLUSIVE"
            elif winning_total == 0:
                out["claimable_wei"] = str(int(pos.amount))
                out["claim_kind"] = "REFUND_NO_WINNERS"
            elif pos.side == m.outcome:
                out["claimable_wei"] = str((int(m.pool) * int(pos.amount)) // winning_total)
                out["claim_kind"] = "PAYOUT"
            else:
                out["claim_kind"] = "LOST"
        return out

    @gl.public.view
    def list_positions(self, who: str, limit: int) -> dict:
        """Every market this wallet has staked in, newest first."""
        now = _now()
        addr = Address(who)
        if limit <= 0 or limit > MAX_PAGE:
            limit = MAX_PAGE
        ids = self.participation.get(addr)
        rows = []
        if ids is not None:
            idx = len(ids) - 1
            while idx >= 0 and len(rows) < limit:
                mid = int(ids[idx])
                m = self.markets.get(u256(mid))
                if m is not None:
                    rows.append(
                        {
                            "market": self._market_dict(m, now),
                            "position": self.get_position(mid, who),
                        }
                    )
                idx -= 1
        return {"who": _lower_hex(addr), "now": str(now), "positions": rows}

    @gl.public.view
    def get_stats(self) -> dict:
        return {
            "markets": str(len(self.market_order)),
            "settled": str(int(self.markets_settled)),
            "inconclusive": str(int(self.markets_inconclusive)),
            "total_staked_wei": str(int(self.total_staked)),
            "total_paid_wei": str(int(self.total_paid)),
            "contract_balance_wei": str(int(self.balance)),
            "now": str(_now()),
        }

    def _market_dict(self, m: Market, now: int) -> dict:
        totals = self.side_totals.get(m.market_id)
        sides = {}
        for side in self._valid_sides(m):
            amount = 0
            if totals is not None:
                amount = int(totals.get(side, u256(0)))
            sides[side] = str(amount)
        return {
            "market_id": str(int(m.market_id)),
            "kind": m.kind,
            "category": m.category,
            "asset": m.asset,
            "timeframe": m.timeframe,
            "window_id": m.window_id,
            "window_start": str(int(m.window_start)),
            "window_end": str(int(m.window_end)),
            "cutoff_at": str(int(m.cutoff_at)),
            "settles_at": str(int(m.settles_at)),
            "terminal_refund_at": str(int(m.terminal_refund_at)),
            "creator": _lower_hex(m.creator),
            "created_at": str(int(m.created_at)),
            "pool_wei": str(int(m.pool)),
            "stakers": str(int(m.stakers)),
            "settled": m.settled,
            "outcome": m.outcome,
            "settled_at": str(int(m.settled_at)),
            "phase": self._phase(m, now),
            "sides": sides,
            "valid_sides": list(self._valid_sides(m)),
            "seconds_to_cutoff": str(max(0, int(m.cutoff_at) - now)),
            "seconds_to_settle": str(max(0, int(m.settles_at) - now)),
        }


# ===========================================================================
# Series encoding
# ===========================================================================


def _encode_series(symbols: tuple, series: dict) -> str:
    """``SYMBOL:open:close`` joined by commas, in catalog order."""
    return ",".join(
        sym + ":" + _scaled_to_dec(series[sym][0]) + ":" + _scaled_to_dec(series[sym][1])
        for sym in symbols
    )


def _decode_series(symbols: tuple, raw: str) -> dict:
    """Decode a series and assert it matches the catalog, in order."""
    entries = raw.split(",")
    if len(entries) != len(symbols):
        raise gl.vm.UserError(E_INVARIANT + "SERIES_LENGTH")
    out = {}
    for i in range(len(symbols)):
        bits = entries[i].split(":")
        if len(bits) != 3:
            raise gl.vm.UserError(E_INVARIANT + "SERIES_SHAPE")
        if bits[0] != symbols[i]:
            raise gl.vm.UserError(E_INVARIANT + "SERIES_SYMBOL_ORDER")
        open_ = _dec_to_scaled(bits[1])
        close = _dec_to_scaled(bits[2])
        if open_ <= 0:
            raise gl.vm.UserError(E_INVARIANT + "NON_POSITIVE_OPEN")
        if close <= 0:
            raise gl.vm.UserError(E_INVARIANT + "NON_POSITIVE_CLOSE")
        out[symbols[i]] = (open_, close)
    return out


def _lower_hex(addr: Address) -> str:
    """Addresses are normalised to lowercase 0x hex everywhere in views."""
    return "0x" + addr.as_bytes.hex()


# ===========================================================================
# Source fetchers -- only ever called from inside an equivalence block
# ===========================================================================


def _http_get_json(url: str):
    """Fetch and decode one source. Status maps onto the retry taxonomy."""
    res = gl.nondet.web.get(url, headers=HTTP_HEADERS)
    status = int(res.status)
    if status in (408, 425, 429) or status >= 500:
        raise gl.vm.UserError(E_TRANSIENT + "HTTP_" + str(status))
    if status != 200:
        raise gl.vm.UserError(E_EXTERNAL + "HTTP_" + str(status))
    body = res.body
    if body is None:
        raise gl.vm.UserError(E_TRANSIENT + "EMPTY_BODY")
    if len(body) > MAX_SOURCE_BYTES:
        raise gl.vm.UserError(E_EXTERNAL + "BODY_TOO_LARGE")
    try:
        text = body.decode("utf-8")
    except Exception:
        raise gl.vm.UserError(E_EXTERNAL + "NOT_UTF8")
    try:
        # parse_float=str keeps every price as its exact decimal text, so no
        # IEEE-754 value ever reaches the settlement maths.
        return json.loads(text, parse_float=str)
    except Exception:
        raise gl.vm.UserError(E_EXTERNAL + "BAD_JSON")


def _fetch_gate(symbol: str, window_start: int, window_end: int) -> tuple:
    """Source A. Rebuild the GMT+1 window from hourly candle OPEN TIMES.

    Gate.io daily bars are UTC-aligned, which is one hour off a GMT+1 day, so the
    window is always reconstructed from hourly candles -- 24 for a day, 168 for a
    week -- and the first and last open times are asserted exactly.
    """
    pair = GATE_PAIRS.get(symbol)
    if pair is None:
        raise gl.vm.UserError(E_EXTERNAL + "NO_GATE_PAIR_" + symbol)
    url = GATE_URL.format(pair=pair, frm=window_start, to=window_end - 1)
    rows = _http_get_json(url)
    expected = (window_end - window_start) // HOUR
    if not isinstance(rows, list) or len(rows) != expected:
        raise gl.vm.UserError(E_EXTERNAL + "GATE_CANDLE_COUNT")
    by_ts = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            raise gl.vm.UserError(E_EXTERNAL + "GATE_ROW_SHAPE")
        ts = int(row[GATE_TS])
        if ts % HOUR != 0:
            raise gl.vm.UserError(E_EXTERNAL + "GATE_TS_UNALIGNED")
        if row[GATE_CLOSED_FLAG] != "true":
            raise gl.vm.UserError(E_EXTERNAL + "GATE_CANDLE_OPEN")
        by_ts[ts] = row
    ts = window_start
    while ts < window_end:
        if ts not in by_ts:
            raise gl.vm.UserError(E_EXTERNAL + "GATE_MISSING_HOUR")
        ts += HOUR
    open_ = _dec_to_scaled(str(by_ts[window_start][GATE_OPEN]))
    close = _dec_to_scaled(str(by_ts[window_end - HOUR][GATE_CLOSE]))
    if open_ <= 0 or close <= 0:
        raise gl.vm.UserError(E_EXTERNAL + "GATE_NON_POSITIVE")
    return (open_, close)


def _fetch_coingecko(symbol: str, window_start: int, window_end: int) -> tuple:
    """Source B. Select the samples at EXACTLY the two window instants.

    The range is padded by an hour either side so both boundaries are interior
    points, then the samples are picked by timestamp rather than by position.
    CoinGecko serves hourly samples for a historical range longer than a day and
    5-minutely for shorter ones; both contain the exact :00 instants, so
    timestamp selection is correct under either granularity and can never
    compare a 23h sample against a 24h close.
    """
    cid = COINGECKO_IDS.get(symbol)
    if cid is None:
        raise gl.vm.UserError(E_EXTERNAL + "NO_COINGECKO_ID_" + symbol)
    url = COINGECKO_URL.format(cid=cid, frm=window_start - HOUR, to=window_end + HOUR)
    doc = _http_get_json(url)
    if not isinstance(doc, dict):
        raise gl.vm.UserError(E_EXTERNAL + "CG_SHAPE")
    prices = doc.get("prices")
    if not isinstance(prices, list) or len(prices) == 0:
        raise gl.vm.UserError(E_EXTERNAL + "CG_NO_SERIES")
    open_ = None
    close = None
    for point in prices:
        if not isinstance(point, list) or len(point) < 2:
            raise gl.vm.UserError(E_EXTERNAL + "CG_POINT_SHAPE")
        ms = int(point[0])
        if ms % 1000 != 0:
            raise gl.vm.UserError(E_EXTERNAL + "CG_SUBSECOND_TS")
        secs = ms // 1000
        if secs == window_start:
            open_ = _json_number_to_scaled(point[1])
        elif secs == window_end:
            close = _json_number_to_scaled(point[1])
    if open_ is None:
        raise gl.vm.UserError(E_EXTERNAL + "CG_NO_SAMPLE_AT_START")
    if close is None:
        raise gl.vm.UserError(E_EXTERNAL + "CG_NO_SAMPLE_AT_END")
    if open_ <= 0 or close <= 0:
        raise gl.vm.UserError(E_EXTERNAL + "CG_NON_POSITIVE")
    return (open_, close)
