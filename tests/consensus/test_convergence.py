"""Leader / validator convergence under the equivalence principle.

``resolve_market`` runs its fetches inside ``gl.eq_principle.strict_eq``, so a
validator only agrees when its own independent fetch reproduces the leader's
payload byte for byte. These tests capture the validator closure from a real
``resolve_market`` call and then re-run it against deliberately different
external data, using snapshots to rewind state between scenarios.
"""

import pytest

from tests.conftest import (
    DAY,
    GATE_URL_RE,
    GEN,
    HOUR,
    LEADER_ERRORED,
    day_window,
    leader_payload,
    mock_asset,
    strict_eq_agrees,
    validator_payload,
    warp_to,
)

pytestmark = pytest.mark.consensus

DAY_ID = "2026-09-24"
DAY_START, DAY_END = day_window(2026, 9, 24)
BEFORE = DAY_START - 2 * DAY
AFTER_CLOSE = DAY_END + HOUR


def dir_market(breek, vm, asset="SOL"):
    contract, _ = breek
    warp_to(vm, BEFORE)
    res = contract.create_market("DIR_DAILY", "CRYPTO", asset, "DAILY", DAY_ID)
    return int(res.split(":")[1])


def rel_market(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    res = contract.create_market("REL_DAILY", "CRYPTO", "", "DAILY", DAY_ID)
    return int(res.split(":")[1])


def mock_sol(vm, a=("115.15", "116.61"), b=None):
    b = a if b is None else b
    vm.clear_mocks()
    mock_asset(
        vm, "SOL", DAY_START, DAY_END,
        a_open=a[0], a_close=a[1], b_open=b[0], b_close=b[1],
    )


def mock_three(vm, a_map, b_map=None):
    b_map = a_map if b_map is None else b_map
    vm.clear_mocks()
    for sym in ("SOL", "ETH", "NEAR"):
        mock_asset(
            vm, sym, DAY_START, DAY_END,
            a_open=a_map[sym][0], a_close=a_map[sym][1],
            b_open=b_map[sym][0], b_close=b_map[sym][1],
        )


# --- agreement -------------------------------------------------------------


def test_validator_agrees_when_it_sees_the_same_feeds(breek, vm):
    """The happy path: independent fetch, identical payload, vote AGREE."""
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm)
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "SETTLED:UP"
    assert strict_eq_agrees(vm) is True


def test_validator_agrees_on_relative_market(breek, vm):
    contract, _ = breek
    mid = rel_market(breek, vm)
    mock_three(
        vm,
        {"SOL": ("115.15", "116.61"), "ETH": ("2690.25", "2685.52"),
         "NEAR": ("4.325", "4.583")},
    )
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "SETTLED:NEAR"
    assert strict_eq_agrees(vm) is True


def test_validator_agrees_across_cosmetic_decimal_differences(breek, vm):
    """A feed respelling 115.15 as 115.15000000 must not split consensus.

    Both spellings scale to the same integer and the payload is rebuilt from the
    integer, so the agreed string is identical either way.
    """
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm, a=("115.15", "116.61"))
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    mock_sol(vm, a=("115.15000000", "116.61000000"))
    assert strict_eq_agrees(vm) is True


def test_validator_agrees_when_candles_arrive_in_a_different_order(breek, vm):
    """Array order is not part of the meaning, so it must not affect the vote."""
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    vm.clear_mocks()
    mock_asset(
        vm, "SOL", DAY_START, DAY_END,
        a_open="115.15", a_close="116.61",
        gate_kwargs={"reverse": True},
    )
    assert strict_eq_agrees(vm) is True


# --- disagreement ----------------------------------------------------------


def test_validator_rejects_when_its_own_source_a_differs(breek, vm):
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm, a=("115.15", "116.61"))
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    # This validator's Gate.io fetch reports a different close.
    mock_sol(vm, a=("115.15", "100.00"))
    assert strict_eq_agrees(vm) is False


def test_validator_rejects_when_its_own_source_b_differs(breek, vm):
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm, a=("115.15", "116.61"))
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    mock_sol(vm, a=("115.15", "116.61"), b=("115.15", "90.00"))
    assert strict_eq_agrees(vm) is False


def test_validator_rejects_a_forged_leader_payload(breek, vm):
    """A leader that simply asserts a result cannot carry the round."""
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    forged = (
        "v1|DIR_DAILY|CRYPTO|SOL|DAILY|gate.io|coingecko|2026-09-24"
        "|SOL:999.00000000:1000.00000000|UP"
        "|SOL:999.00000000:1000.00000000|UP|UP"
    )
    assert strict_eq_agrees(vm, leader_result=forged) is False


def test_validator_rejects_a_leader_payload_for_another_window(breek, vm):
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    replayed = (
        "v1|DIR_DAILY|CRYPTO|SOL|DAILY|gate.io|coingecko|2026-09-23"
        "|SOL:115.15000000:116.61000000|UP"
        "|SOL:115.15000000:116.61000000|UP|UP"
    )
    assert strict_eq_agrees(vm, leader_result=replayed) is False


def test_validator_rejects_when_leader_errored_but_it_succeeded(breek, vm):
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    assert strict_eq_agrees(vm, leader_result=LEADER_ERRORED) is False


def test_validator_rejects_a_different_relative_winner(breek, vm):
    contract, _ = breek
    mid = rel_market(breek, vm)
    base = {
        "SOL": ("115.15", "116.61"),
        "ETH": ("2690.25", "2685.52"),
        "NEAR": ("4.325", "4.583"),
    }
    mock_three(vm, base)
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "SETTLED:NEAR"
    # This validator sees SOL as the runaway winner instead.
    mock_three(vm, {**base, "SOL": ("115.15", "300.00")})
    assert strict_eq_agrees(vm) is False


# --- inconclusive rounds still have to converge -----------------------------


def test_validators_converge_on_an_inconclusive_round(breek, vm):
    """Disagreement between SOURCES is a normal, agreed-upon outcome.

    The two feeds contradict each other, so the payload says INCONCLUSIVE -- and
    every validator that fetches the same feeds agrees on exactly that.
    """
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm, a=("100.0", "110.0"), b=("100.0", "90.0"))
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "INCONCLUSIVE:SOURCES_DISAGREE"
    assert strict_eq_agrees(vm) is True
    assert contract.get_evidence(mid)["final"] == "INCONCLUSIVE"


def test_validators_converge_on_a_tie_round(breek, vm):
    contract, _ = breek
    mid = rel_market(breek, vm)
    mock_three(
        vm,
        {"SOL": ("100.0", "110.0"), "ETH": ("200.0", "220.0"), "NEAR": ("4.0", "4.1")},
    )
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "INCONCLUSIVE:SOURCES_DISAGREE"
    assert strict_eq_agrees(vm) is True


# --- snapshot / rollback ---------------------------------------------------


def test_snapshot_rollback_lets_one_market_settle_several_ways(breek, vm, alice, bob):
    """Same market, same stakes, three different worlds -- via state rollback.

    This is the cheap way to prove the outcome is a function of the feeds and
    nothing else: only the mocked external data changes between branches.
    """
    contract, _ = breek
    mid = dir_market(breek, vm)
    vm.sender = alice
    vm.value = 2 * GEN
    contract.take_position(mid, "UP")
    vm.sender = bob
    vm.value = 3 * GEN
    contract.take_position(mid, "DOWN")
    vm.value = 0
    warp_to(vm, AFTER_CLOSE)

    base = vm.snapshot()
    outcomes = {}

    for label, a, b in [
        ("up", ("100.0", "110.0"), ("100.0", "110.0")),
        ("down", ("100.0", "90.0"), ("100.0", "90.0")),
        ("split", ("100.0", "110.0"), ("100.0", "90.0")),
        ("flat", ("100.0", "100.0"), ("100.0", "100.0")),
    ]:
        mock_sol(vm, a=a, b=b)
        warp_to(vm, AFTER_CLOSE)
        contract.resolve_market(mid)
        outcomes[label] = contract.get_market(mid)["outcome"]
        assert strict_eq_agrees(vm) is True
        vm.revert(base)
        warp_to(vm, AFTER_CLOSE)

    assert outcomes == {
        "up": "UP",
        "down": "DOWN",
        "split": "INCONCLUSIVE",
        "flat": "DOWN",
    }
    # After the final rollback the market is unsettled again.
    assert contract.get_market(mid)["settled"] is False


def test_rollback_restores_stakes_and_pool(breek, vm, alice):
    contract, _ = breek
    mid = dir_market(breek, vm)
    base = vm.snapshot()
    vm.sender = alice
    vm.value = 4 * GEN
    contract.take_position(mid, "UP")
    vm.value = 0
    assert contract.get_market(mid)["pool_wei"] == str(4 * GEN)
    vm.revert(base)
    assert contract.get_market(mid)["pool_wei"] == "0"


def test_transient_round_leaves_nothing_behind(breek, vm):
    """A failed round must not half-settle the market."""
    contract, _ = breek
    mid = dir_market(breek, vm)
    vm.clear_mocks()
    vm.mock_web(GATE_URL_RE % "SOL", {"method": "GET", "status": 503, "body": "{}"})
    warp_to(vm, AFTER_CLOSE)
    with pytest.raises(Exception, match="TRANSIENT:HTTP_503"):
        contract.resolve_market(mid)
    m = contract.get_market(mid)
    assert m["settled"] is False and m["outcome"] == "" and m["settled_at"] == "0"
    mock_sol(vm)
    warp_to(vm, AFTER_CLOSE)
    assert contract.resolve_market(mid) == "SETTLED:UP"
    assert strict_eq_agrees(vm) is True


def test_two_honest_runs_produce_byte_identical_payloads(breek, vm):
    """strict_eq is byte equality, so the payload must be fully deterministic.

    Same window, same feed values, freshly rebuilt mocks: the string a second
    validator computes has to match the leader's exactly, character for
    character, including how every price is spelt.
    """
    contract, _ = breek
    mid = dir_market(breek, vm)
    mock_sol(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    leader = leader_payload(vm)
    assert leader == (
        "v1|DIR_DAILY|CRYPTO|SOL|DAILY|gate.io|coingecko|2026-09-24"
        "|SOL:115.15000000:116.61000000|UP"
        "|SOL:115.15000000:116.61000000|UP"
        "|UP"
    )
    mock_sol(vm)  # a second validator, rebuilt mocks, same underlying data
    assert validator_payload(vm) == leader


def test_payload_carries_both_series_so_the_result_is_auditable(breek, vm):
    """Anyone can recompute the verdict from the payload alone."""
    contract, mod = breek
    mid = rel_market(breek, vm)
    mock_three(
        vm,
        {"SOL": ("115.15", "116.61"), "ETH": ("2690.25", "2685.52"),
         "NEAR": ("4.325", "4.583")},
    )
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    parts = leader_payload(vm).split("|")
    symbols = ("SOL", "ETH", "NEAR")
    a_series = mod._decode_series(symbols, parts[8])
    b_series = mod._decode_series(symbols, parts[10])
    assert mod._relative_verdict(symbols, a_series) == parts[9] == "NEAR"
    assert mod._relative_verdict(symbols, b_series) == parts[11] == "NEAR"
    assert mod._combine(parts[9], parts[11]) == parts[12] == "NEAR"
