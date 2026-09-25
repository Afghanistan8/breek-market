"""Market lifecycle: create, stake, refund, resolve, claim.

These drive the public methods exactly as a wallet would, including the value
attached to ``take_position``, so the refund-instead-of-revert rule is exercised
for real rather than asserted about.
"""

import pytest

from tests.conftest import (
    DAY,
    GEN,
    HOUR,
    WEEK,
    day_window,
    hexaddr,
    mock_asset,
    warp_to,
    week_window,
)

DAY_ID = "2026-09-24"
DAY_START, DAY_END = day_window(2026, 9, 24)
WEEK_ID = "2026-09-14"
WEEK_START, WEEK_END = week_window(2026, 9, 14)

BEFORE = DAY_START - 2 * DAY          # staking is open
AFTER_CLOSE = DAY_END + HOUR          # resolvable
TERMINAL = DAY_END + 5 * DAY + HOUR   # past the terminal refund delay


def open_dir_market(breek, vm, asset="SOL", window=DAY_ID, timeframe="DAILY"):
    contract, _ = breek
    warp_to(vm, BEFORE if timeframe == "DAILY" else WEEK_START - 2 * DAY)
    kind = "DIR_DAILY" if timeframe == "DAILY" else "DIR_WEEKLY"
    res = contract.create_market(kind, "CRYPTO", asset, timeframe, window)
    return int(res.split(":")[1])


def open_rel_market(breek, vm, window=DAY_ID, timeframe="DAILY"):
    contract, _ = breek
    warp_to(vm, BEFORE if timeframe == "DAILY" else WEEK_START - 2 * DAY)
    kind = "REL_DAILY" if timeframe == "DAILY" else "REL_WEEKLY"
    res = contract.create_market(kind, "CRYPTO", "", timeframe, window)
    return int(res.split(":")[1])


def stake(contract, vm, who, market_id, side, amount):
    vm.sender = who
    vm.value = amount
    try:
        return contract.take_position(market_id, side)
    finally:
        vm.value = 0


# --- create ----------------------------------------------------------------


def test_create_sets_derived_schedule(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    m = contract.get_market(mid)
    assert m["kind"] == "DIR_DAILY"
    assert m["asset"] == "SOL"
    assert m["window_start"] == str(DAY_START)
    assert m["window_end"] == str(DAY_END)
    assert m["cutoff_at"] == str(DAY_START)
    assert m["settles_at"] == str(DAY_END)
    assert m["terminal_refund_at"] == str(DAY_END + 5 * DAY)
    assert m["phase"] == "OPEN"
    assert m["valid_sides"] == ["UP", "DOWN"]


def test_create_relative_market_has_catalog_sides(breek, vm):
    contract, _ = breek
    mid = open_rel_market(breek, vm)
    m = contract.get_market(mid)
    assert m["asset"] == ""
    assert m["valid_sides"] == ["SOL", "ETH", "NEAR"]


def test_create_rejects_dominance(breek, vm):
    """No second keyless historical dominance feed exists, so refuse the market."""
    contract, _ = breek
    warp_to(vm, BEFORE)
    with pytest.raises(Exception, match="CATEGORY_NOT_SETTLABLE"):
        contract.create_market("DIR_DAILY", "DOMINANCE", "BTC.D", "DAILY", DAY_ID)
    with pytest.raises(Exception, match="CATEGORY_NOT_SETTLABLE"):
        contract.create_market("REL_DAILY", "DOMINANCE", "", "DAILY", DAY_ID)


def test_create_rejects_unknown_keys(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    with pytest.raises(Exception, match="UNKNOWN_KIND"):
        contract.create_market("DIR_HOURLY", "CRYPTO", "SOL", "DAILY", DAY_ID)
    with pytest.raises(Exception, match="UNKNOWN_CATEGORY"):
        contract.create_market("DIR_DAILY", "STOCKS", "SOL", "DAILY", DAY_ID)
    with pytest.raises(Exception, match="UNKNOWN_ASSET"):
        contract.create_market("DIR_DAILY", "CRYPTO", "BTC", "DAILY", DAY_ID)
    with pytest.raises(Exception, match="UNKNOWN_TIMEFRAME"):
        contract.create_market("DIR_DAILY", "CRYPTO", "SOL", "HOURLY", DAY_ID)


def test_create_requires_kind_and_timeframe_to_agree(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    with pytest.raises(Exception, match="KIND_TIMEFRAME_MISMATCH"):
        contract.create_market("DIR_DAILY", "CRYPTO", "SOL", "WEEKLY", WEEK_ID)


def test_relative_market_takes_no_asset(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    with pytest.raises(Exception, match="REL_TAKES_NO_ASSET"):
        contract.create_market("REL_DAILY", "CRYPTO", "SOL", "DAILY", DAY_ID)


def test_create_rejects_past_and_in_progress_windows(breek, vm):
    contract, _ = breek
    warp_to(vm, DAY_START + HOUR)  # window already running
    with pytest.raises(Exception, match="WINDOW_NOT_IN_FUTURE"):
        contract.create_market("DIR_DAILY", "CRYPTO", "SOL", "DAILY", DAY_ID)
    warp_to(vm, DAY_END + DAY)  # window long gone
    with pytest.raises(Exception, match="WINDOW_NOT_IN_FUTURE"):
        contract.create_market("DIR_DAILY", "CRYPTO", "SOL", "DAILY", DAY_ID)


def test_create_rejects_window_exactly_at_cutoff(breek, vm):
    """Creating at the instant the candle opens is already too late."""
    contract, _ = breek
    warp_to(vm, DAY_START)
    with pytest.raises(Exception, match="WINDOW_NOT_IN_FUTURE"):
        contract.create_market("DIR_DAILY", "CRYPTO", "SOL", "DAILY", DAY_ID)


def test_create_rejects_too_far_ahead(breek, vm):
    contract, _ = breek
    warp_to(vm, DAY_START - 400 * DAY)
    with pytest.raises(Exception, match="WINDOW_TOO_FAR_AHEAD"):
        contract.create_market("DIR_DAILY", "CRYPTO", "SOL", "DAILY", DAY_ID)


def test_create_rejects_duplicates_but_allows_sibling_markets(breek, vm):
    contract, _ = breek
    open_dir_market(breek, vm, asset="SOL")
    with pytest.raises(Exception, match="DUPLICATE_MARKET"):
        contract.create_market("DIR_DAILY", "CRYPTO", "SOL", "DAILY", DAY_ID)
    # different asset, different kind and different window are all distinct
    contract.create_market("DIR_DAILY", "CRYPTO", "ETH", "DAILY", DAY_ID)
    contract.create_market("REL_DAILY", "CRYPTO", "", "DAILY", DAY_ID)
    contract.create_market("DIR_DAILY", "CRYPTO", "SOL", "DAILY", "2026-09-25")


def test_weekly_market_requires_monday(breek, vm):
    contract, _ = breek
    warp_to(vm, WEEK_START - 2 * DAY)
    with pytest.raises(Exception, match="WEEK_MUST_START_MONDAY"):
        contract.create_market("DIR_WEEKLY", "CRYPTO", "SOL", "WEEKLY", "2026-09-15")


def test_anyone_can_create(breek, vm, bob):
    """There is no privileged creator."""
    contract, _ = breek
    vm.sender = bob
    warp_to(vm, BEFORE)
    res = contract.create_market("DIR_DAILY", "CRYPTO", "NEAR", "DAILY", DAY_ID)
    mid = int(res.split(":")[1])
    assert contract.get_market(mid)["creator"] == hexaddr(bob)


# --- staking ---------------------------------------------------------------


def test_stake_accepts_2_to_4_gen(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    for amount in (2 * GEN, 3 * GEN, 4 * GEN):
        vm.sender = bob
        snap = vm.snapshot()
        assert stake(contract, vm, bob, mid, "UP", amount) == "STAKED:%d" % amount
        vm.revert(snap)


def test_stake_below_min_is_refunded(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    assert stake(contract, vm, bob, mid, "UP", GEN) == "REFUNDED:BELOW_MIN_STAKE"
    assert contract.get_market(mid)["pool_wei"] == "0"
    assert contract.get_position(mid, hexaddr(bob))["has_position"] is False


def test_stake_above_max_is_refunded(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    assert stake(contract, vm, bob, mid, "UP", 5 * GEN) == "REFUNDED:ABOVE_MAX_STAKE"
    assert contract.get_market(mid)["pool_wei"] == "0"


def test_topup_on_same_side_accumulates(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    assert stake(contract, vm, bob, mid, "UP", 2 * GEN) == "STAKED:%d" % (2 * GEN)
    assert stake(contract, vm, bob, mid, "UP", GEN) == "STAKED:%d" % (3 * GEN)
    pos = contract.get_position(mid, hexaddr(bob))
    assert pos["amount_wei"] == str(3 * GEN)
    assert contract.get_market(mid)["pool_wei"] == str(3 * GEN)


def test_topup_past_max_is_refunded_and_leaves_position_intact(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, bob, mid, "UP", 3 * GEN)
    assert stake(contract, vm, bob, mid, "UP", 2 * GEN) == "REFUNDED:ABOVE_MAX_STAKE"
    assert contract.get_position(mid, hexaddr(bob))["amount_wei"] == str(3 * GEN)
    assert contract.get_market(mid)["pool_wei"] == str(3 * GEN)


def test_side_switch_is_refunded(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, bob, mid, "UP", 2 * GEN)
    assert stake(contract, vm, bob, mid, "DOWN", 2 * GEN) == "REFUNDED:SIDE_SWITCH_FORBIDDEN"
    pos = contract.get_position(mid, hexaddr(bob))
    assert pos["side"] == "UP"
    assert pos["amount_wei"] == str(2 * GEN)


def test_invalid_side_is_refunded(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    assert stake(contract, vm, bob, mid, "SIDEWAYS", 2 * GEN) == "REFUNDED:INVALID_SIDE"
    # a catalog symbol is not a valid side on a direction market
    assert stake(contract, vm, bob, mid, "SOL", 2 * GEN) == "REFUNDED:INVALID_SIDE"


def test_relative_market_sides_are_catalog_symbols(breek, vm, bob):
    contract, _ = breek
    mid = open_rel_market(breek, vm)
    assert stake(contract, vm, bob, mid, "NEAR", 2 * GEN) == "STAKED:%d" % (2 * GEN)
    assert stake(contract, vm, bob, mid, "UP", 2 * GEN) == "REFUNDED:INVALID_SIDE"


def test_late_stake_is_refunded(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    warp_to(vm, DAY_START)  # exactly at cutoff -- already too late
    assert stake(contract, vm, bob, mid, "UP", 2 * GEN) == "REFUNDED:WINDOW_ALREADY_OPEN"
    warp_to(vm, DAY_START + HOUR)
    assert stake(contract, vm, bob, mid, "UP", 2 * GEN) == "REFUNDED:WINDOW_ALREADY_OPEN"


def test_stake_on_missing_market_is_refunded(breek, vm, bob):
    contract, _ = breek
    open_dir_market(breek, vm)
    assert stake(contract, vm, bob, 999, "UP", 2 * GEN) == "REFUNDED:NO_SUCH_MARKET"


def test_stake_with_no_value_reverts(breek, vm, bob):
    """Nothing is at risk, so a plain revert is safe here."""
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    vm.sender = bob
    with pytest.raises(Exception, match="NO_VALUE_ATTACHED"):
        contract.take_position(mid, "UP")


def test_side_totals_and_pool_track_stakes(breek, vm, alice, bob, carol):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    stake(contract, vm, bob, mid, "UP", 4 * GEN)
    stake(contract, vm, carol, mid, "DOWN", 3 * GEN)
    m = contract.get_market(mid)
    assert m["sides"] == {"UP": str(6 * GEN), "DOWN": str(3 * GEN)}
    assert m["pool_wei"] == str(9 * GEN)
    assert m["stakers"] == "3"


# --- phases ----------------------------------------------------------------


def test_phase_progression(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    assert contract.get_phase(mid) == "OPEN"
    warp_to(vm, DAY_START)
    assert contract.get_phase(mid) == "WINDOW_LIVE"
    warp_to(vm, DAY_END - 1)
    assert contract.get_phase(mid) == "WINDOW_LIVE"
    warp_to(vm, DAY_END)
    assert contract.get_phase(mid) == "READY_TO_SETTLE"


def test_resolve_before_window_closes_is_rejected(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    warp_to(vm, DAY_END - 1)
    with pytest.raises(Exception, match="WINDOW_NOT_CLOSED"):
        contract.resolve_market(mid)


# --- resolve + claim -------------------------------------------------------


def settle_dir(breek, vm, mid, *, a=("115.15", "116.61"), b=None, asset="SOL"):
    contract, _ = breek
    b = a if b is None else b
    vm.clear_mocks()
    mock_asset(
        vm, asset, DAY_START, DAY_END,
        a_open=a[0], a_close=a[1], b_open=b[0], b_close=b[1],
    )
    warp_to(vm, AFTER_CLOSE)
    return contract.resolve_market(mid)


def test_resolve_up_when_both_sources_agree(breek, vm, alice, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    stake(contract, vm, bob, mid, "DOWN", 2 * GEN)
    assert settle_dir(breek, vm, mid) == "SETTLED:UP"
    m = contract.get_market(mid)
    assert m["outcome"] == "UP"
    assert m["phase"] == "SETTLED_UP"


def test_resolve_down_on_flat_candle(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    assert settle_dir(breek, vm, mid, a=("100.0", "100.0")) == "SETTLED:DOWN"
    assert contract.get_market(mid)["phase"] == "SETTLED_DOWN"


def test_sources_disagreeing_on_direction_is_inconclusive(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    res = settle_dir(breek, vm, mid, a=("100.0", "110.0"), b=("100.0", "90.0"))
    assert res == "INCONCLUSIVE:SOURCES_DISAGREE"
    m = contract.get_market(mid)
    assert m["outcome"] == "INCONCLUSIVE"
    assert m["phase"] == "INCONCLUSIVE"


def test_evidence_records_both_series_and_verdicts(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    settle_dir(breek, vm, mid, a=("115.15", "116.61"))
    ev = contract.get_evidence(mid)
    assert ev["source_a"] == "gate.io" and ev["source_b"] == "coingecko"
    assert ev["a_verdict"] == "UP" and ev["b_verdict"] == "UP"
    assert ev["final"] == "UP"
    assert ev["a_series"] == "SOL:115.15000000:116.61000000"
    assert ev["payload"].startswith("v1|DIR_DAILY|CRYPTO|SOL|DAILY|gate.io|coingecko|2026-09-24|")


def test_resolve_is_idempotent(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    settle_dir(breek, vm, mid)
    with pytest.raises(Exception, match="ALREADY_SETTLED"):
        contract.resolve_market(mid)


def test_transient_failure_leaves_market_resolvable(breek, vm):
    """A 429 must not settle anything and must not consume the market."""
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    vm.clear_mocks()
    from tests.conftest import GATE_URL_RE
    vm.mock_web(GATE_URL_RE % "SOL", {"method": "GET", "status": 429, "body": "{}"})
    warp_to(vm, AFTER_CLOSE)
    with pytest.raises(Exception, match="TRANSIENT:HTTP_429"):
        contract.resolve_market(mid)
    assert contract.get_market(mid)["settled"] is False
    assert contract.get_phase(mid) == "READY_TO_SETTLE"
    # and it settles once the feed recovers
    assert settle_dir(breek, vm, mid) == "SETTLED:UP"


def test_winners_split_pool_pro_rata(breek, vm, alice, bob, carol):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    stake(contract, vm, bob, mid, "UP", 4 * GEN)     # twice alice's stake
    stake(contract, vm, carol, mid, "DOWN", 3 * GEN)
    settle_dir(breek, vm, mid)  # UP wins; pool is 9 GEN, winning side 6 GEN

    vm.sender = alice
    assert contract.claim(mid) == "CLAIMED:%d:PAYOUT" % (9 * GEN * 2 // 6)
    vm.sender = bob
    assert contract.claim(mid) == "CLAIMED:%d:PAYOUT" % (9 * GEN * 4 // 6)
    vm.sender = carol
    assert contract.claim(mid) == "CLAIMED:0:LOST"


def test_payouts_never_exceed_the_pool(breek, vm, alice, bob, carol):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 3 * GEN)
    stake(contract, vm, bob, mid, "UP", 3 * GEN)
    stake(contract, vm, carol, mid, "DOWN", 2 * GEN)
    settle_dir(breek, vm, mid)
    pool = int(contract.get_market(mid)["pool_wei"])
    paid = 0
    for who in (alice, bob, carol):
        vm.sender = who
        paid += int(contract.claim(mid).split(":")[1])
    assert paid <= pool


def test_double_claim_is_rejected(breek, vm, alice):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    settle_dir(breek, vm, mid)
    vm.sender = alice
    contract.claim(mid)
    with pytest.raises(Exception, match="ALREADY_CLAIMED"):
        contract.claim(mid)


def test_claim_before_settlement_is_rejected(breek, vm, alice):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    vm.sender = alice
    with pytest.raises(Exception, match="NOT_SETTLED"):
        contract.claim(mid)


def test_claim_without_a_position_is_rejected(breek, vm, alice, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    settle_dir(breek, vm, mid)
    vm.sender = bob
    with pytest.raises(Exception, match="NO_POSITION"):
        contract.claim(mid)


def test_inconclusive_refunds_every_stake_exactly(breek, vm, alice, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    stake(contract, vm, bob, mid, "DOWN", 4 * GEN)
    settle_dir(breek, vm, mid, a=("100.0", "110.0"), b=("100.0", "90.0"))
    vm.sender = alice
    assert contract.claim(mid) == "CLAIMED:%d:REFUND_INCONCLUSIVE" % (2 * GEN)
    vm.sender = bob
    assert contract.claim(mid) == "CLAIMED:%d:REFUND_INCONCLUSIVE" % (4 * GEN)


def test_settled_with_no_winners_refunds_everyone(breek, vm, alice):
    """Nobody backed the winning side, so the pool must not be stranded."""
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "DOWN", 2 * GEN)
    assert settle_dir(breek, vm, mid) == "SETTLED:UP"
    assert contract.get_position(mid, hexaddr(alice))["claim_kind"] == (
        "REFUND_NO_WINNERS"
    )
    vm.sender = alice
    assert contract.claim(mid) == "CLAIMED:%d:REFUND_NO_WINNERS" % (2 * GEN)


# --- relative markets ------------------------------------------------------


def mock_all_three(vm, window_start, window_end, a_map, b_map=None):
    b_map = a_map if b_map is None else b_map
    vm.clear_mocks()
    for sym in ("SOL", "ETH", "NEAR"):
        mock_asset(
            vm, sym, window_start, window_end,
            a_open=a_map[sym][0], a_close=a_map[sym][1],
            b_open=b_map[sym][0], b_close=b_map[sym][1],
        )


def test_relative_daily_settles_the_strongest_asset(breek, vm, alice, bob):
    contract, _ = breek
    mid = open_rel_market(breek, vm)
    stake(contract, vm, alice, mid, "NEAR", 2 * GEN)
    stake(contract, vm, bob, mid, "SOL", 2 * GEN)
    mock_all_three(
        vm, DAY_START, DAY_END,
        {"SOL": ("115.15", "116.61"), "ETH": ("2690.25", "2685.52"), "NEAR": ("4.325", "4.583")},
    )
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "SETTLED:NEAR"
    assert contract.get_market(mid)["phase"] == "SETTLED_WINNER"
    vm.sender = alice
    assert contract.claim(mid).endswith(":PAYOUT")


def test_relative_tie_on_one_source_is_inconclusive(breek, vm):
    contract, _ = breek
    mid = open_rel_market(breek, vm)
    mock_all_three(
        vm, DAY_START, DAY_END,
        # SOL and ETH both +1000 bps on source A -> TIE
        {"SOL": ("100.0", "110.0"), "ETH": ("200.0", "220.0"), "NEAR": ("4.0", "4.1")},
    )
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "INCONCLUSIVE:SOURCES_DISAGREE"


def test_relative_different_winners_is_inconclusive(breek, vm):
    contract, _ = breek
    mid = open_rel_market(breek, vm)
    mock_all_three(
        vm, DAY_START, DAY_END,
        {"SOL": ("100.0", "120.0"), "ETH": ("100.0", "101.0"), "NEAR": ("100.0", "102.0")},
        {"SOL": ("100.0", "101.0"), "ETH": ("100.0", "101.5"), "NEAR": ("100.0", "130.0")},
    )
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "INCONCLUSIVE:SOURCES_DISAGREE"


def test_relative_weekly_settles_over_168_hours(breek, vm):
    contract, _ = breek
    mid = open_rel_market(breek, vm, window=WEEK_ID, timeframe="WEEKLY")
    mock_all_three(
        vm, WEEK_START, WEEK_END,
        {"SOL": ("99.73", "111.04"), "ETH": ("2475.57", "2639.61"), "NEAR": ("2.309", "4.066")},
    )
    warp_to(vm, WEEK_END + HOUR)
    assert contract.resolve_market(mid) == "SETTLED:NEAR"


def test_direction_weekly_settles(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm, window=WEEK_ID, timeframe="WEEKLY")
    vm.clear_mocks()
    mock_asset(vm, "SOL", WEEK_START, WEEK_END, a_open="99.73", a_close="111.04")
    warp_to(vm, WEEK_END + HOUR)
    assert contract.resolve_market(mid) == "SETTLED:UP"


# --- terminal refund -------------------------------------------------------


def test_terminal_refund_makes_zero_http_calls(breek, vm, alice, bob):
    """Past the terminal delay the contract must not touch the network at all.

    No web mocks are registered, and ``strict_mocks`` makes any unmocked request
    an error -- so if resolve_market reached out, this test would fail.
    """
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    stake(contract, vm, bob, mid, "DOWN", 3 * GEN)

    vm.clear_mocks()
    vm.strict_mocks = True
    warp_to(vm, TERMINAL)
    assert contract.resolve_market(mid) == "INCONCLUSIVE:TERMINAL_REFUND"

    m = contract.get_market(mid)
    assert m["outcome"] == "INCONCLUSIVE"
    assert m["phase"] == "INCONCLUSIVE"
    assert contract.get_evidence(mid)["payload"].startswith("v1|TERMINAL_REFUND|")

    vm.sender = alice
    assert contract.claim(mid) == "CLAIMED:%d:REFUND_INCONCLUSIVE" % (2 * GEN)
    vm.sender = bob
    assert contract.claim(mid) == "CLAIMED:%d:REFUND_INCONCLUSIVE" % (3 * GEN)


def test_terminal_boundary_is_exact(breek, vm):
    """One second before the terminal delay the contract still tries the feeds."""
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    vm.clear_mocks()
    vm.strict_mocks = True
    warp_to(vm, DAY_END + 5 * DAY - 1)
    with pytest.raises(Exception):
        contract.resolve_market(mid)
    assert contract.get_market(mid)["settled"] is False


# --- views -----------------------------------------------------------------


def test_catalog_marks_dominance_unsettlable(breek, vm):
    contract, _ = breek
    cat = contract.get_catalog()
    by_key = {c["key"]: c for c in cat["categories"]}
    assert by_key["CRYPTO"]["settlable"] is True
    assert by_key["CRYPTO"]["assets"] == ["SOL", "ETH", "NEAR"]
    assert by_key["DOMINANCE"]["settlable"] is False
    assert by_key["DOMINANCE"]["assets"] == ["BTC.D", "ETH.D", "OTHERS.D"]
    assert cat["stake"]["min_wei"] == str(2 * GEN)
    assert cat["stake"]["max_wei"] == str(4 * GEN)
    assert "DIR_HOURLY" not in cat["kinds"] and "REL_HOURLY" not in cat["kinds"]


def test_list_markets_is_newest_first_and_paginated(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    ids = []
    for day in ("2026-09-24", "2026-09-25", "2026-09-26"):
        ids.append(int(contract.create_market(
            "DIR_DAILY", "CRYPTO", "SOL", "DAILY", day).split(":")[1]))
    page = contract.list_markets(0, 2)
    assert page["total"] == "3"
    assert [m["market_id"] for m in page["markets"]] == [str(ids[2]), str(ids[1])]
    page2 = contract.list_markets(2, 2)
    assert [m["market_id"] for m in page2["markets"]] == [str(ids[0])]


def test_list_markets_clamps_limit(breek, vm):
    contract, _ = breek
    open_dir_market(breek, vm)
    assert contract.list_markets(0, 9999)["limit"] == "50"
    assert contract.list_markets(0, 0)["limit"] == "50"


def test_list_resolvable_only_shows_ready_markets(breek, vm):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    assert contract.list_resolvable(10)["markets"] == []
    warp_to(vm, AFTER_CLOSE)
    assert [m["market_id"] for m in contract.list_resolvable(10)["markets"]] == [str(mid)]
    settle_dir(breek, vm, mid)
    assert contract.list_resolvable(10)["markets"] == []


def test_list_positions_returns_my_markets(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, bob, mid, "UP", 2 * GEN)
    out = contract.list_positions(hexaddr(bob), 10)
    assert len(out["positions"]) == 1
    assert out["positions"][0]["position"]["side"] == "UP"
    assert out["positions"][0]["market"]["market_id"] == str(mid)


def test_stats_track_totals(breek, vm, alice, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, alice, mid, "UP", 2 * GEN)
    stake(contract, vm, bob, mid, "DOWN", 2 * GEN)
    settle_dir(breek, vm, mid)
    stats = contract.get_stats()
    assert stats["markets"] == "1"
    assert stats["settled"] == "1"
    assert stats["inconclusive"] == "0"
    assert stats["total_staked_wei"] == str(4 * GEN)


def test_addresses_are_lowercase_hex(breek, vm, bob):
    contract, _ = breek
    mid = open_dir_market(breek, vm)
    stake(contract, vm, bob, mid, "UP", 2 * GEN)
    creator = contract.get_market(mid)["creator"]
    assert creator == creator.lower() and creator.startswith("0x") and len(creator) == 42
    who = contract.get_position(mid, hexaddr(bob))["who"]
    assert who == who.lower()


def test_unknown_market_views_reject(breek, vm):
    contract, _ = breek
    with pytest.raises(Exception, match="NO_SUCH_MARKET"):
        contract.get_market(4242)
    with pytest.raises(Exception, match="NO_SUCH_MARKET"):
        contract.get_phase(4242)
