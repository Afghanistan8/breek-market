"""Leader / validator convergence under the equivalence principle.

``score_round`` runs its two fetches inside ``gl.eq_principle.strict_eq``, so a
validator only agrees when its own independent fetch reproduces the leader's
payload byte for byte. These tests capture the leader closure from a real
``score_round`` call and re-run it against deliberately different external data,
using snapshots to rewind state between scenarios.

Note what is being agreed here: a **price**, not a verdict. Two feeds that merely
agreed on a direction would be useless to a forecast contest, so convergence is
numeric.
"""

import pytest

from tests.conftest import (
    DAY,
    ENTRY_FEE,
    GATE_URL_RE,
    HOUR,
    LEADER_ERRORED,
    day_window,
    leader_payload,
    mock_feeds,
    strict_eq_agrees,
    validator_payload,
    warp_to,
)

pytestmark = pytest.mark.consensus

DAY_ID = "2026-09-24"
DAY_START, DAY_END = day_window(2026, 9, 24)
BEFORE = DAY_START - 2 * DAY
AFTER_CLOSE = DAY_END + HOUR


def a_round(breek, vm, asset="SOL"):
    contract, _ = breek
    warp_to(vm, BEFORE)
    return int(contract.open_round("CRYPTO", asset, "DAILY", DAY_ID).split(":")[1])


def feeds(vm, a="117.88", b="117.96"):
    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close=a, b_close=b)


# --- agreement -------------------------------------------------------------


def test_validator_agrees_when_it_sees_the_same_feeds(breek, vm):
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    assert contract.score_round(rid) == "SCORED:117.92000000"
    assert strict_eq_agrees(vm) is True


def test_validator_agrees_across_cosmetic_decimal_differences(breek, vm):
    """A feed respelling 117.88 as 117.88000000 must not split consensus."""
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm, a="117.88", b="117.96")
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    feeds(vm, a="117.88000000", b="117.96000000")
    assert strict_eq_agrees(vm) is True


def test_validator_agrees_when_candles_arrive_in_a_different_order(breek, vm):
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close="117.88", b_close="117.96",
               gate_kwargs={"reverse": True})
    assert strict_eq_agrees(vm) is True


# --- disagreement ----------------------------------------------------------


def test_validator_rejects_a_different_price_on_source_a(breek, vm):
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    feeds(vm, a="120.00")
    assert strict_eq_agrees(vm) is False


def test_validator_rejects_a_different_price_on_source_b(breek, vm):
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    feeds(vm, b="118.90")
    assert strict_eq_agrees(vm) is False


def test_validator_rejects_a_forged_leader_price(breek, vm):
    """A leader that simply asserts a number cannot carry the round."""
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    forged = (
        "f1|CRYPTO|SOL|DAILY|2026-09-24|gate.io|coingecko"
        "|999.00000000|999.00000000|0|999.00000000"
    )
    assert strict_eq_agrees(vm, leader_result=forged) is False


def test_validator_rejects_a_price_for_another_window(breek, vm):
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    replayed = (
        "f1|CRYPTO|SOL|DAILY|2026-09-23|gate.io|coingecko"
        "|117.88000000|117.96000000|6|117.92000000"
    )
    assert strict_eq_agrees(vm, leader_result=replayed) is False


def test_validator_rejects_when_leader_errored_but_it_succeeded(breek, vm):
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    assert strict_eq_agrees(vm, leader_result=LEADER_ERRORED) is False


# --- void rounds still have to converge ------------------------------------


def test_validators_converge_on_a_void_round(breek, vm):
    """Feeds disagreeing is a normal, agreed-upon outcome.

    The two prices contradict each other, so the payload says VOID_SPREAD -- and
    every validator fetching the same feeds agrees on exactly that.
    """
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm, a="100.00", b="130.00")
    warp_to(vm, AFTER_CLOSE)
    assert contract.score_round(rid) == "VOID:SPREAD"
    assert strict_eq_agrees(vm) is True
    assert contract.get_evidence(rid)["consensus"] == "VOID_SPREAD"


# --- payload determinism ---------------------------------------------------


def test_two_honest_runs_produce_byte_identical_payloads(breek, vm):
    """strict_eq is byte equality, so the payload must be fully deterministic."""
    contract, _ = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    leader = leader_payload(vm)
    assert leader == (
        "f1|CRYPTO|SOL|DAILY|2026-09-24|gate.io|coingecko"
        "|117.88000000|117.96000000|6|117.92000000"
    )
    feeds(vm)  # a second validator, rebuilt mocks, same underlying data
    assert validator_payload(vm) == leader


def test_payload_carries_both_prices_so_the_result_is_auditable(breek, vm):
    """Anyone can recompute the consensus from the payload alone."""
    contract, mod = breek
    rid = a_round(breek, vm)
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    parts = leader_payload(vm).split("|")
    a = mod._dec_to_scaled(parts[7])
    b = mod._dec_to_scaled(parts[8])
    assert mod._spread_bps(a, b) == int(parts[9])
    assert mod._consensus_of(a, b) == mod._dec_to_scaled(parts[10])


# --- snapshot / rollback ---------------------------------------------------


def test_snapshot_rollback_scores_one_round_several_ways(breek, vm, alice, bob):
    """Same round, same entries, three different worlds, via state rollback.

    Only the mocked feed data changes between branches, so the outcome is a
    function of the feeds and nothing else.
    """
    contract, _ = breek
    rid = a_round(breek, vm)
    for who, forecast in ((alice, "117.95"), (bob, "118.40")):
        vm.sender = who
        vm.value = ENTRY_FEE
        contract.submit_forecast(rid, forecast)
    vm.value = 0
    warp_to(vm, AFTER_CLOSE)

    base = vm.snapshot()
    outcomes = {}

    for label, a, b in [
        ("tight", "117.88", "117.96"),
        ("wide", "100.00", "130.00"),
        ("identical", "118.00", "118.00"),
    ]:
        feeds(vm, a=a, b=b)
        warp_to(vm, AFTER_CLOSE)
        contract.score_round(rid)
        outcomes[label] = contract.get_round(rid)["status"]
        assert strict_eq_agrees(vm) is True
        vm.revert(base)
        warp_to(vm, AFTER_CLOSE)

    assert outcomes == {
        "tight": "SCORED",
        "wide": "VOID_SPREAD",
        "identical": "SCORED",
    }
    assert contract.get_round(rid)["status"] == ""


def test_failed_round_leaves_nothing_behind(breek, vm):
    contract, _ = breek
    rid = a_round(breek, vm)
    vm.clear_mocks()
    vm.mock_web(GATE_URL_RE % "SOL", {"method": "GET", "status": 503, "body": "{}"})
    warp_to(vm, AFTER_CLOSE)
    with pytest.raises(Exception, match="TRANSIENT:HTTP_503"):
        contract.score_round(rid)
    r = contract.get_round(rid)
    assert r["status"] == "" and r["consensus"] == "" and r["scored_at"] == "0"
    feeds(vm)
    warp_to(vm, AFTER_CLOSE)
    assert contract.score_round(rid).startswith("SCORED:")
    assert strict_eq_agrees(vm) is True
