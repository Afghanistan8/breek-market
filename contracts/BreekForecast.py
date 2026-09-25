# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Breek -- a forecast accuracy contest that scores itself.

You are not picking a side. You are naming a number.

Each round asks one question: what will this asset's price be at the end of a
GMT+1 window? Entrants pay one flat fee and submit a price. When the window
closes, the contract fetches two independent public feeds itself, inside a
GenLayer equivalence-principle block, and derives a single consensus price. Every
entrant is then scored on how far their number sat from it, and the pot is split
in proportion to accuracy.

How this differs from a prediction market, deliberately:

* **There are no sides.** No up/down, no field of competing assets, no
  counterparty. You submit a point forecast and are graded on a continuum.
* **The pot is not won, it is earned in proportion.** A closer forecast takes a
  larger share; everyone inside the scoring band is paid something. Nothing is
  "split among the winning side", because there is no winning side.
* **Settlement produces a number, not a verdict.** The two feeds must agree
  within a tolerance band; the consensus price is their midpoint. A verdict was
  never computed, so there is nothing for two sources to vote on.
* **Your forecast is revisable, free, until the window opens.** Conviction is
  not locked; precision is what is rewarded.

A single feed can never price a round: if the two disagree by more than the
tolerance the round is VOID and every entry fee is returned. There is no owner,
no pause, no admin score, no upgrade hook and no privileged address anywhere in
this file. ``score_round`` takes a round id and nothing else.

All lifecycle time comes from consensus time (``gl.message_raw['datetime']``),
never a host clock. All scoring and payout maths is integer only.
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

#: One flat fee per entrant. Everybody buys in at the same price, so the only
#: thing that separates a large payout from a small one is accuracy.
ENTRY_FEE = 1 * GEN

#: Scoring iterates entrants once, at scoring time, so the round is bounded.
MAX_ENTRIES = 200

#: The two feeds must land within this many basis points of each other for the
#: round to be priceable at all. Wider than this and there is no single honest
#: number to score against, so the round voids.
TOLERANCE_BPS = 50

#: A forecast this far from the consensus price scores zero. It bounds how much
#: a wild guess can dilute the people who were actually close.
SCORE_CUTOFF_BPS = 1000

MAX_FORWARD_DAYS = 366
EXPIRY_DELAY = 5 * DAY
MAX_PAGE = 50
MAX_SOURCE_BYTES = 60000
PRICE_SCALE = 10**8
BPS_SCALE = 10000

PAYLOAD_VERSION = "f1"
PAYLOAD_FIELDS = 11

# Round outcomes.
STATUS_SCORED = "SCORED"
STATUS_VOID_SPREAD = "VOID_SPREAD"
STATUS_VOID_EXPIRED = "VOID_EXPIRED"
STATUS_VOID_NO_SCORES = "VOID_NO_SCORES"

# Phases are derived from consensus time, never stored.
PHASE_ACCEPTING = "ACCEPTING"
PHASE_LOCKED = "LOCKED"
PHASE_AWAITING_SCORE = "AWAITING_SCORE"
PHASE_SCORED = "SCORED"
PHASE_VOID = "VOID"

TIMEFRAME_DAILY = "DAILY"
TIMEFRAME_WEEKLY = "WEEKLY"
TIMEFRAMES = (TIMEFRAME_DAILY, TIMEFRAME_WEEKLY)

CAT_CRYPTO = "CRYPTO"
CAT_DOMINANCE = "DOMINANCE"

CRYPTO_ASSETS = ("SOL", "ETH", "NEAR")
DOMINANCE_ASSETS = ("BTC.D", "ETH.D", "OTHERS.D")

#: DOMINANCE is listed but cannot be priced: no second keyless feed publishes
#: historical total market cap, and the feeds that do exist disagree by whole
#: percentage points because they aggregate different coin universes. A round
#: that cannot be priced twice is a round that cannot open. See docs/SPEC.md.
PRICEABLE_CATEGORIES = (CAT_CRYPTO,)

SOURCE_A = "gate.io"
SOURCE_B = "coingecko"

# Compile-time URL templates. Never caller-supplied, never carrying an API key.
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
#   [0] open time (unix s)  [1] quote volume  [2] close  [3] high
#   [4] low  [5] open  [6] base volume  [7] "true" iff the window has closed
GATE_TS = 0
GATE_CLOSE = 2
GATE_CLOSED_FLAG = 7

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

E_EXPECTED = "EXPECTED:"
E_TRANSIENT = "TRANSIENT:"
E_EXTERNAL = "EXTERNAL:"
E_INVARIANT = "INVARIANT:"


# ===========================================================================
# Civil calendar maths, hand-rolled
# ===========================================================================


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


def _parse_consensus_datetime(text: str) -> int:
    """Parse the GenVM consensus datetime, e.g. 2026-09-25T13:43:54.996120Z."""
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
    if s == 60:
        s = 59
    return _days_from_civil(y, m, d) * DAY + h * HOUR + mi * 60 + s


def _now() -> int:
    """Consensus time in Unix seconds. The only clock this contract trusts."""
    return _parse_consensus_datetime(gl.message_raw["datetime"])


def _window_bounds(timeframe: str, window_id: str) -> tuple[int, int]:
    """A GMT+1 day D starts at ``day_index(D) * 86400 - 3600`` -- 23:00 UTC on D-1."""
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
# Fixed point. No float ever touches a price or a payout.
# ===========================================================================

_PRICE_DIGITS = 8


def _dec_to_scaled(text: str) -> int:
    """Decimal string to a PRICE_SCALE integer. '80494.31' == '80494.31000000'."""
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
    """Scale a JSON number decoded with ``parse_float=str``, so no IEEE-754."""
    if isinstance(value, bool):
        raise gl.vm.UserError(E_EXTERNAL + "NOT_A_NUMBER")
    if isinstance(value, int):
        return value * PRICE_SCALE
    if isinstance(value, str):
        return _dec_to_scaled(value)
    raise gl.vm.UserError(E_EXTERNAL + "NOT_A_NUMBER")


def _scaled_to_dec(value: int) -> str:
    whole = value // PRICE_SCALE
    frac = value % PRICE_SCALE
    return "%d.%0*d" % (whole, _PRICE_DIGITS, frac)


# ===========================================================================
# The contest maths
# ===========================================================================


def _spread_bps(a: int, b: int) -> int:
    """How far apart the two feeds are, relative to the lower of the two."""
    if a <= 0 or b <= 0:
        raise gl.vm.UserError(E_EXTERNAL + "NON_POSITIVE_PRICE")
    low = a if a < b else b
    diff = a - b if a > b else b - a
    return (diff * BPS_SCALE) // low


def _consensus_of(a: int, b: int) -> int:
    """The number the round is scored against: the midpoint of two feeds.

    Deliberately not a verdict. Two sources that merely *agree on a direction*
    would be useless here -- a forecast needs an actual price, so the feeds have
    to converge numerically or the round cannot be scored at all.
    """
    return (a + b) // 2


def _error_bps(forecast: int, consensus: int) -> int:
    """Absolute distance from the consensus price, in basis points."""
    if consensus <= 0:
        raise gl.vm.UserError(E_INVARIANT + "NON_POSITIVE_CONSENSUS")
    diff = forecast - consensus if forecast > consensus else consensus - forecast
    return (diff * BPS_SCALE) // consensus


def _accuracy_weight(error: int) -> int:
    """Score for one entry: linear from SCORE_CUTOFF_BPS at a perfect call to
    zero at the cutoff.

    This is the heart of the contest, and the reason there is no winning side to
    split a pool between. A payout is a *share of accuracy*, not a share of a
    side. Being closer than someone else pays more than they get; being wilder
    than the cutoff pays nothing and stops a careless guess from diluting people
    who did the work.
    """
    if error >= SCORE_CUTOFF_BPS:
        return 0
    return SCORE_CUTOFF_BPS - error


# ===========================================================================
# Storage
# ===========================================================================


@allow_storage
@dataclass
class Round:
    round_id: u256
    category: str
    asset: str
    timeframe: str
    window_id: str
    window_start: u64
    window_end: u64
    locks_at: u64          # entries close when the window opens
    scoreable_at: u64      # scoring opens when the window closes
    expires_at: u64
    opener: Address
    opened_at: u64
    pot: u256
    entrants: u64
    status: str            # "", SCORED, VOID_SPREAD, VOID_EXPIRED, VOID_NO_SCORES
    consensus: u256        # the scaled price the round was graded against
    total_weight: u256     # sum of every entry's accuracy weight
    scored_at: u64
    evidence: str


@allow_storage
@dataclass
class Entry:
    forecast: u256         # scaled price
    submitted_at: u64
    revisions: u64
    claimed: bool


# ===========================================================================
# Contract
# ===========================================================================


class BreekForecast(gl.Contract):
    """A self-scoring forecast accuracy contest on GenLayer."""

    rounds: TreeMap[u256, Round]
    round_order: DynArray[u256]
    dedupe: TreeMap[str, u256]

    entries: TreeMap[u256, TreeMap[Address, Entry]]
    roster: TreeMap[u256, DynArray[Address]]
    participation: TreeMap[Address, DynArray[u256]]

    next_id: u256
    total_entries: u256
    total_paid: u256
    rounds_scored: u256
    rounds_void: u256

    def __init__(self) -> None:
        self.next_id = u256(1)
        self.total_entries = u256(0)
        self.total_paid = u256(0)
        self.rounds_scored = u256(0)
        self.rounds_void = u256(0)

    # -- helpers ------------------------------------------------------------

    def _catalog(self, category: str) -> tuple:
        if category == CAT_CRYPTO:
            return CRYPTO_ASSETS
        if category == CAT_DOMINANCE:
            return DOMINANCE_ASSETS
        raise gl.vm.UserError(E_EXPECTED + "UNKNOWN_CATEGORY")

    def _round(self, round_id: int) -> Round:
        r = self.rounds.get(u256(round_id))
        if r is None:
            raise gl.vm.UserError(E_EXPECTED + "NO_SUCH_ROUND")
        return r

    def _phase(self, r: Round, now: int) -> str:
        if r.status != "":
            return PHASE_SCORED if r.status == STATUS_SCORED else PHASE_VOID
        if now < int(r.locks_at):
            return PHASE_ACCEPTING
        if now < int(r.scoreable_at):
            return PHASE_LOCKED
        return PHASE_AWAITING_SCORE

    def _pay(self, to: Address, amount: int) -> None:
        if amount > 0:
            gl.get_contract_at(to).emit_transfer(value=u256(amount), on="finalized")

    # -- open a round -------------------------------------------------------

    @gl.public.write
    def open_round(
        self,
        category: str,
        asset: str,
        timeframe: str,
        window_id: str,
    ) -> str:
        """Put a question up for forecasting. Anyone may call this.

        Nothing here is privileged and nothing is caller-configurable beyond a
        catalog key and a window: no URLs, no prices, no fee, no scorer.
        """
        now = _now()

        if timeframe not in TIMEFRAMES:
            raise gl.vm.UserError(E_EXPECTED + "UNKNOWN_TIMEFRAME")

        catalog = self._catalog(category)
        if category not in PRICEABLE_CATEGORIES:
            raise gl.vm.UserError(E_EXPECTED + "CATEGORY_NOT_PRICEABLE")
        if asset not in catalog:
            raise gl.vm.UserError(E_EXPECTED + "UNKNOWN_ASSET")

        window_start, window_end = _window_bounds(timeframe, window_id)
        if window_start <= now:
            raise gl.vm.UserError(E_EXPECTED + "WINDOW_NOT_IN_FUTURE")
        if window_start - now > MAX_FORWARD_DAYS * DAY:
            raise gl.vm.UserError(E_EXPECTED + "WINDOW_TOO_FAR_AHEAD")

        key = category + "|" + asset + "|" + timeframe + "|" + window_id
        if key in self.dedupe:
            raise gl.vm.UserError(E_EXPECTED + "DUPLICATE_ROUND")

        round_id = self.next_id
        self.next_id = u256(int(self.next_id) + 1)

        self.rounds[round_id] = Round(
            round_id=round_id,
            category=category,
            asset=asset,
            timeframe=timeframe,
            window_id=window_id,
            window_start=u64(window_start),
            window_end=u64(window_end),
            locks_at=u64(window_start),
            scoreable_at=u64(window_end),
            expires_at=u64(window_end + EXPIRY_DELAY),
            opener=gl.message.sender_address,
            opened_at=u64(now),
            pot=u256(0),
            entrants=u64(0),
            status="",
            consensus=u256(0),
            total_weight=u256(0),
            scored_at=u64(0),
            evidence="",
        )
        self.round_order.append(round_id)
        self.dedupe[key] = round_id
        return "OPENED:" + str(int(round_id))

    # -- enter --------------------------------------------------------------

    @gl.public.write.payable
    def submit_forecast(self, round_id: int, forecast: str) -> str:
        """Enter a round with a price, for a flat fee.

        One entry per wallet. The fee is identical for everyone, so nothing but
        accuracy separates a large payout from a small one.

        Anything invalid refunds the attached GEN inside this same call. It must
        never revert once value has been credited, because a revert after credit
        would strand the fee with no path out.
        """
        value = int(gl.message.value)
        if value == 0:
            raise gl.vm.UserError(E_EXPECTED + "NO_FEE_ATTACHED")

        sender = gl.message.sender_address
        now = _now()

        r = self.rounds.get(u256(round_id))
        if r is None:
            self._pay(sender, value)
            return "REFUNDED:NO_SUCH_ROUND"

        if now >= int(r.locks_at):
            self._pay(sender, value)
            return "REFUNDED:ROUND_LOCKED"

        if value != ENTRY_FEE:
            self._pay(sender, value)
            return "REFUNDED:WRONG_FEE"

        book = self.entries.get_or_insert_default(u256(round_id))
        if sender in book:
            # Already in. Revising is free, so charging again would be wrong.
            self._pay(sender, value)
            return "REFUNDED:ALREADY_ENTERED"

        if int(r.entrants) >= MAX_ENTRIES:
            self._pay(sender, value)
            return "REFUNDED:ROUND_FULL"

        try:
            scaled = _dec_to_scaled(forecast)
        except Exception:
            self._pay(sender, value)
            return "REFUNDED:BAD_FORECAST"
        if scaled <= 0:
            self._pay(sender, value)
            return "REFUNDED:BAD_FORECAST"

        book[sender] = Entry(
            forecast=u256(scaled),
            submitted_at=u64(now),
            revisions=u64(0),
            claimed=False,
        )
        self.roster.get_or_insert_default(u256(round_id)).append(sender)
        self.participation.get_or_insert_default(sender).append(u256(round_id))

        r.entrants = u64(int(r.entrants) + 1)
        r.pot = u256(int(r.pot) + value)
        self.total_entries = u256(int(self.total_entries) + 1)
        return "ENTERED:" + _scaled_to_dec(scaled)

    @gl.public.write
    def revise_forecast(self, round_id: int, forecast: str) -> str:
        """Change your number, free, any time before the window opens.

        A prediction market locks you to a side because the side is the bet.
        Here the bet is precision, so there is no reason to punish someone for
        sharpening their estimate as the window approaches.
        """
        sender = gl.message.sender_address
        now = _now()
        r = self._round(round_id)

        if now >= int(r.locks_at):
            raise gl.vm.UserError(E_EXPECTED + "ROUND_LOCKED")

        book = self.entries.get(u256(round_id))
        entry = book.get(sender) if book is not None else None
        if entry is None:
            raise gl.vm.UserError(E_EXPECTED + "NOT_ENTERED")

        scaled = _dec_to_scaled(forecast)
        if scaled <= 0:
            raise gl.vm.UserError(E_EXPECTED + "BAD_FORECAST")

        entry.forecast = u256(scaled)
        entry.revisions = u64(int(entry.revisions) + 1)
        return "REVISED:" + _scaled_to_dec(scaled)

    # -- score --------------------------------------------------------------

    @gl.public.write
    def score_round(self, round_id: int) -> str:
        """Price the round from two independent live feeds and grade everyone.

        The only argument is the round id. Everything that decides the result is
        either already stored on the round or fetched by the contract itself.
        """
        now = _now()
        r = self._round(round_id)

        if r.status != "":
            raise gl.vm.UserError(E_EXPECTED + "ALREADY_SCORED")
        if now < int(r.scoreable_at):
            raise gl.vm.UserError(E_EXPECTED + "WINDOW_NOT_CLOSED")

        # Past the expiry the contract must settle with zero HTTP. It never
        # invents a price, so an unscoreable round becomes a full refund.
        if now >= int(r.expires_at):
            r.status = STATUS_VOID_EXPIRED
            r.scored_at = u64(now)
            r.evidence = PAYLOAD_VERSION + "|EXPIRED|" + str(int(r.expires_at))
            self.rounds_void = u256(int(self.rounds_void) + 1)
            return "VOID:EXPIRED"

        asset = r.asset
        category = r.category
        timeframe = r.timeframe
        window_id = r.window_id
        window_start = int(r.window_start)
        window_end = int(r.window_end)

        def price_block() -> str:
            a_close = _fetch_gate_close(asset, window_start, window_end)
            b_close = _fetch_coingecko_close(asset, window_start, window_end)
            spread = _spread_bps(a_close, b_close)
            if spread > TOLERANCE_BPS:
                consensus = 0
                status = STATUS_VOID_SPREAD
            else:
                consensus = _consensus_of(a_close, b_close)
                status = STATUS_SCORED
            return "|".join(
                (
                    PAYLOAD_VERSION,
                    category,
                    asset,
                    timeframe,
                    window_id,
                    SOURCE_A,
                    SOURCE_B,
                    _scaled_to_dec(a_close),
                    _scaled_to_dec(b_close),
                    str(spread),
                    _scaled_to_dec(consensus) if consensus else status,
                )
            )

        # Every web request lives inside the equivalence block. Nothing below
        # this line touches the network.
        agreed = gl.eq_principle.strict_eq(price_block)

        consensus, status = self._parse_agreed(agreed, r)

        r.evidence = agreed
        r.scored_at = u64(now)

        if status != STATUS_SCORED:
            r.status = status
            self.rounds_void = u256(int(self.rounds_void) + 1)
            return "VOID:SPREAD"

        total_weight = self._tally(round_id, consensus)
        if int(r.entrants) > 0 and total_weight == 0:
            # Entrants existed but none landed inside the scoring band. Refund
            # rather than keep a pot that no accuracy earned. An *empty* round
            # is not this case: it still prices correctly, there is simply
            # nobody to pay.
            r.status = STATUS_VOID_NO_SCORES
            r.consensus = u256(consensus)
            self.rounds_void = u256(int(self.rounds_void) + 1)
            return "VOID:NO_SCORES"

        r.status = STATUS_SCORED
        r.consensus = u256(consensus)
        r.total_weight = u256(total_weight)
        self.rounds_scored = u256(int(self.rounds_scored) + 1)
        return "SCORED:" + _scaled_to_dec(consensus)

    def _tally(self, round_id: int, consensus: int) -> int:
        """Sum every entry's accuracy weight. Bounded by MAX_ENTRIES."""
        roster = self.roster.get(u256(round_id))
        book = self.entries.get(u256(round_id))
        if roster is None or book is None:
            return 0
        total = 0
        for i in range(len(roster)):
            entry = book.get(roster[i])
            if entry is None:
                continue
            total += _accuracy_weight(_error_bps(int(entry.forecast), consensus))
        return total

    def _parse_agreed(self, agreed: str, r: Round) -> tuple:
        """Re-derive the price offline. The payload is data, never an instruction."""
        parts = agreed.split("|")
        if len(parts) != PAYLOAD_FIELDS:
            raise gl.vm.UserError(E_INVARIANT + "FIELD_COUNT")
        (
            version,
            category,
            asset,
            timeframe,
            window_id,
            source_a,
            source_b,
            a_raw,
            b_raw,
            spread_raw,
            final_raw,
        ) = parts

        if version != PAYLOAD_VERSION:
            raise gl.vm.UserError(E_INVARIANT + "VERSION")
        if category != r.category or asset != r.asset:
            raise gl.vm.UserError(E_INVARIANT + "ROUND_BINDING")
        if timeframe != r.timeframe or window_id != r.window_id:
            raise gl.vm.UserError(E_INVARIANT + "WINDOW_BINDING")
        if source_a != SOURCE_A or source_b != SOURCE_B:
            raise gl.vm.UserError(E_INVARIANT + "SOURCE_BINDING")

        a_close = _dec_to_scaled(a_raw)
        b_close = _dec_to_scaled(b_raw)
        if a_close <= 0 or b_close <= 0:
            raise gl.vm.UserError(E_INVARIANT + "NON_POSITIVE_PRICE")

        if not spread_raw.isdigit():
            raise gl.vm.UserError(E_INVARIANT + "SPREAD_FORMAT")
        if _spread_bps(a_close, b_close) != int(spread_raw):
            raise gl.vm.UserError(E_INVARIANT + "SPREAD")

        if int(spread_raw) > TOLERANCE_BPS:
            if final_raw != STATUS_VOID_SPREAD:
                raise gl.vm.UserError(E_INVARIANT + "EXPECTED_VOID")
            return 0, STATUS_VOID_SPREAD

        consensus = _dec_to_scaled(final_raw)
        if consensus != _consensus_of(a_close, b_close):
            raise gl.vm.UserError(E_INVARIANT + "CONSENSUS")
        if consensus <= 0:
            raise gl.vm.UserError(E_INVARIANT + "NON_POSITIVE_CONSENSUS")
        return consensus, STATUS_SCORED

    # -- collect ------------------------------------------------------------

    @gl.public.write
    def collect(self, round_id: int) -> str:
        """Take your share of the pot, sized by how close you were.

        After a scored round your share is your accuracy weight over the sum of
        everyone's. After any void, your entry fee comes back untouched.
        """
        sender = gl.message.sender_address
        r = self._round(round_id)
        if r.status == "":
            raise gl.vm.UserError(E_EXPECTED + "NOT_SCORED")

        book = self.entries.get(u256(round_id))
        entry = book.get(sender) if book is not None else None
        if entry is None:
            raise gl.vm.UserError(E_EXPECTED + "NO_ENTRY")
        if entry.claimed:
            raise gl.vm.UserError(E_EXPECTED + "ALREADY_COLLECTED")

        entry.claimed = True

        if r.status != STATUS_SCORED:
            self.total_paid = u256(int(self.total_paid) + ENTRY_FEE)
            self._pay(sender, ENTRY_FEE)
            return "COLLECTED:" + str(ENTRY_FEE) + ":REFUND_" + r.status

        weight = _accuracy_weight(_error_bps(int(entry.forecast), int(r.consensus)))
        if weight == 0 or int(r.total_weight) == 0:
            return "COLLECTED:0:OUTSIDE_BAND"

        payout = (int(r.pot) * weight) // int(r.total_weight)
        self.total_paid = u256(int(self.total_paid) + payout)
        self._pay(sender, payout)
        return "COLLECTED:" + str(payout) + ":SCORED"

    # -- views --------------------------------------------------------------

    @gl.public.view
    def get_catalog(self) -> dict:
        return {
            "timeframes": list(TIMEFRAMES),
            "categories": [
                {
                    "key": CAT_CRYPTO,
                    "assets": list(CRYPTO_ASSETS),
                    "priceable": True,
                    "basis": "closing USD/USDT price at the end of the GMT+1 window",
                    "note": "",
                },
                {
                    "key": CAT_DOMINANCE,
                    "assets": list(DOMINANCE_ASSETS),
                    "priceable": False,
                    "basis": "market-cap dominance percentage",
                    "note": (
                        "Listed but not priceable: no second independent keyless "
                        "feed publishes historical total market cap, so a "
                        "consensus price cannot be formed. Breek will not price a "
                        "round from one feed."
                    ),
                },
            ],
            "entry_fee_wei": str(ENTRY_FEE),
            "gen_wei": str(GEN),
            "tolerance_bps": str(TOLERANCE_BPS),
            "score_cutoff_bps": str(SCORE_CUTOFF_BPS),
            "max_entries": str(MAX_ENTRIES),
            "sources": {"a": SOURCE_A, "b": SOURCE_B},
            "timezone": "GMT+1 (fixed +3600, no DST)",
            "price_scale": str(PRICE_SCALE),
            "expiry_delay_s": str(EXPIRY_DELAY),
        }

    @gl.public.view
    def get_round(self, round_id: int) -> dict:
        return self._round_dict(self._round(round_id), _now())

    @gl.public.view
    def get_phase(self, round_id: int) -> str:
        return self._phase(self._round(round_id), _now())

    @gl.public.view
    def get_evidence(self, round_id: int) -> dict:
        r = self._round(round_id)
        out = {
            "round_id": str(int(r.round_id)),
            "status": r.status,
            "scored_at": str(int(r.scored_at)),
            "payload": r.evidence,
            "source_a": SOURCE_A,
            "source_b": SOURCE_B,
            "tolerance_bps": str(TOLERANCE_BPS),
        }
        parts = r.evidence.split("|")
        if len(parts) == PAYLOAD_FIELDS:
            out["a_close"] = parts[7]
            out["b_close"] = parts[8]
            out["spread_bps"] = parts[9]
            out["consensus"] = parts[10]
        return out

    @gl.public.view
    def get_entry(self, round_id: int, who: str) -> dict:
        r = self._round(round_id)
        addr = Address(who)
        book = self.entries.get(u256(round_id))
        entry = book.get(addr) if book is not None else None
        out = {
            "round_id": str(round_id),
            "who": _lower_hex(addr),
            "entered": entry is not None,
            "forecast": _scaled_to_dec(int(entry.forecast)) if entry is not None else "",
            "revisions": str(int(entry.revisions)) if entry is not None else "0",
            "collected": entry.claimed if entry is not None else False,
            "error_bps": "",
            "weight": "",
            "collectable_wei": "0",
            "outcome": "",
        }
        if entry is None or r.status == "":
            return out
        if r.status != STATUS_SCORED:
            out["outcome"] = "REFUND_" + r.status
            if not entry.claimed:
                out["collectable_wei"] = str(ENTRY_FEE)
            return out
        error = _error_bps(int(entry.forecast), int(r.consensus))
        weight = _accuracy_weight(error)
        out["error_bps"] = str(error)
        out["weight"] = str(weight)
        if weight == 0:
            out["outcome"] = "OUTSIDE_BAND"
        else:
            out["outcome"] = "SCORED"
            if not entry.claimed:
                out["collectable_wei"] = str(
                    (int(r.pot) * weight) // int(r.total_weight)
                )
        return out

    @gl.public.view
    def get_leaderboard(self, round_id: int, limit: int) -> dict:
        """Everyone in the round, ordered by accuracy once it has been scored.

        Before scoring this returns entrants without their numbers: publishing
        live forecasts would let a late entrant simply copy the crowd.
        """
        r = self._round(round_id)
        if limit <= 0 or limit > MAX_PAGE:
            limit = MAX_PAGE
        roster = self.roster.get(u256(round_id))
        book = self.entries.get(u256(round_id))
        rows = []
        if roster is not None and book is not None:
            scored = r.status == STATUS_SCORED
            for i in range(len(roster)):
                addr = roster[i]
                entry = book.get(addr)
                if entry is None:
                    continue
                row = {
                    "who": _lower_hex(addr),
                    "revisions": str(int(entry.revisions)),
                    "collected": entry.claimed,
                    "forecast": "",
                    "error_bps": "",
                    "weight": "",
                    "share_wei": "0",
                }
                if r.status != "":
                    row["forecast"] = _scaled_to_dec(int(entry.forecast))
                if scored:
                    error = _error_bps(int(entry.forecast), int(r.consensus))
                    weight = _accuracy_weight(error)
                    row["error_bps"] = str(error)
                    row["weight"] = str(weight)
                    if weight > 0:
                        row["share_wei"] = str(
                            (int(r.pot) * weight) // int(r.total_weight)
                        )
                rows.append(row)
            if scored:
                rows.sort(key=lambda row: int(row["error_bps"]))
        return {
            "round_id": str(int(r.round_id)),
            "status": r.status,
            "consensus": _scaled_to_dec(int(r.consensus)) if r.status == STATUS_SCORED else "",
            "entries": rows[:limit],
        }

    @gl.public.view
    def list_rounds(self, offset: int, limit: int) -> dict:
        now = _now()
        total = len(self.round_order)
        if limit <= 0 or limit > MAX_PAGE:
            limit = MAX_PAGE
        if offset < 0:
            offset = 0
        rows = []
        idx = total - 1 - offset
        while idx >= 0 and len(rows) < limit:
            r = self.rounds.get(self.round_order[idx])
            if r is not None:
                rows.append(self._round_dict(r, now))
            idx -= 1
        return {
            "total": str(total),
            "offset": str(offset),
            "limit": str(limit),
            "now": str(now),
            "rounds": rows,
        }

    @gl.public.view
    def list_scoreable(self, limit: int) -> dict:
        now = _now()
        if limit <= 0 or limit > MAX_PAGE:
            limit = MAX_PAGE
        rows = []
        idx = len(self.round_order) - 1
        while idx >= 0 and len(rows) < limit:
            r = self.rounds.get(self.round_order[idx])
            if r is not None and r.status == "" and now >= int(r.scoreable_at):
                rows.append(self._round_dict(r, now))
            idx -= 1
        return {"now": str(now), "rounds": rows}

    @gl.public.view
    def list_entries(self, who: str, limit: int) -> dict:
        now = _now()
        addr = Address(who)
        if limit <= 0 or limit > MAX_PAGE:
            limit = MAX_PAGE
        ids = self.participation.get(addr)
        rows = []
        if ids is not None:
            idx = len(ids) - 1
            while idx >= 0 and len(rows) < limit:
                rid = int(ids[idx])
                r = self.rounds.get(u256(rid))
                if r is not None:
                    rows.append(
                        {"round": self._round_dict(r, now), "entry": self.get_entry(rid, who)}
                    )
                idx -= 1
        return {"who": _lower_hex(addr), "now": str(now), "entries": rows}

    @gl.public.view
    def get_stats(self) -> dict:
        return {
            "rounds": str(len(self.round_order)),
            "scored": str(int(self.rounds_scored)),
            "void": str(int(self.rounds_void)),
            "entries": str(int(self.total_entries)),
            "total_paid_wei": str(int(self.total_paid)),
            "contract_balance_wei": str(int(self.balance)),
            "now": str(_now()),
        }

    def _round_dict(self, r: Round, now: int) -> dict:
        return {
            "round_id": str(int(r.round_id)),
            "category": r.category,
            "asset": r.asset,
            "timeframe": r.timeframe,
            "window_id": r.window_id,
            "window_start": str(int(r.window_start)),
            "window_end": str(int(r.window_end)),
            "locks_at": str(int(r.locks_at)),
            "scoreable_at": str(int(r.scoreable_at)),
            "expires_at": str(int(r.expires_at)),
            "opener": _lower_hex(r.opener),
            "opened_at": str(int(r.opened_at)),
            "pot_wei": str(int(r.pot)),
            "entrants": str(int(r.entrants)),
            "status": r.status,
            "consensus": _scaled_to_dec(int(r.consensus)) if int(r.consensus) > 0 else "",
            "total_weight": str(int(r.total_weight)),
            "scored_at": str(int(r.scored_at)),
            "phase": self._phase(r, now),
            "entry_fee_wei": str(ENTRY_FEE),
            "seconds_to_lock": str(max(0, int(r.locks_at) - now)),
            "seconds_to_score": str(max(0, int(r.scoreable_at) - now)),
        }


def _lower_hex(addr: Address) -> str:
    return "0x" + addr.as_bytes.hex()


# ===========================================================================
# Source fetchers -- only ever called from inside an equivalence block
# ===========================================================================


def _http_get_json(url: str):
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
        # parse_float=str keeps every price as exact decimal text, so no
        # IEEE-754 value ever reaches the scoring maths.
        return json.loads(text, parse_float=str)
    except Exception:
        raise gl.vm.UserError(E_EXTERNAL + "BAD_JSON")


def _fetch_gate_close(symbol: str, window_start: int, window_end: int) -> int:
    """Source A: the close of the last hourly candle inside the GMT+1 window.

    The window is rebuilt from candle OPEN TIMES because Gate.io's daily bars
    are UTC-aligned, which is exactly one hour off a GMT+1 day.
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
    close = _dec_to_scaled(str(by_ts[window_end - HOUR][GATE_CLOSE]))
    if close <= 0:
        raise gl.vm.UserError(E_EXTERNAL + "GATE_NON_POSITIVE")
    return close


def _fetch_coingecko_close(symbol: str, window_start: int, window_end: int) -> int:
    """Source B: the sample at exactly the window's closing instant.

    The range is padded by an hour either side so the boundary is an interior
    point, then the sample is selected by timestamp rather than by position.
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
    close = None
    for point in prices:
        if not isinstance(point, list) or len(point) < 2:
            raise gl.vm.UserError(E_EXTERNAL + "CG_POINT_SHAPE")
        ms = int(point[0])
        if ms % 1000 != 0:
            raise gl.vm.UserError(E_EXTERNAL + "CG_SUBSECOND_TS")
        if ms // 1000 == window_end:
            close = _json_number_to_scaled(point[1])
    if close is None:
        raise gl.vm.UserError(E_EXTERNAL + "CG_NO_SAMPLE_AT_END")
    if close <= 0:
        raise gl.vm.UserError(E_EXTERNAL + "CG_NON_POSITIVE")
    return close
