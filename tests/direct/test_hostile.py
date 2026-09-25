"""Hostile and boundary inputs.

The rule these all test: ``submit_forecast`` is payable, so it must never revert
once the fee has been credited. Every rejection has to come back as a refund
inside the same call. A revert here would strand the fee with no path out.
"""

import pytest

from tests.conftest import DAY, ENTRY_FEE, GEN, HOUR, day_window, hexaddr, warp_to

DAY_ID = "2026-09-24"
DAY_START, DAY_END = day_window(2026, 9, 24)
BEFORE = DAY_START - 2 * DAY


def a_round(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    return int(contract.open_round("CRYPTO", "SOL", "DAILY", DAY_ID).split(":")[1])


def enter(contract, vm, who, rid, forecast, fee=ENTRY_FEE):
    vm.sender = who
    vm.value = fee
    try:
        return contract.submit_forecast(rid, forecast)
    finally:
        vm.value = 0


# --- oversized numbers -----------------------------------------------------


def test_absurdly_large_forecast_is_refunded_not_reverted(breek, vm, bob):
    """A 70-digit forecast would overflow the u256 storage slot.

    That write happens AFTER the fee is credited, so if it raises the fee is
    stranded. It must be rejected before the Entry is constructed.
    """
    contract, _ = breek
    rid = a_round(breek, vm)
    huge = "1" + "0" * 70
    result = enter(contract, vm, bob, rid, huge)
    assert result.startswith("REFUNDED:"), result
    assert contract.get_round(rid)["pot_wei"] == "0"
    assert contract.get_entry(rid, hexaddr(bob))["entered"] is False


def test_forecast_past_the_bound_is_refunded(breek, vm, bob, mod):
    """MAX_FORECAST sits far below the u256 ceiling, so nothing can overflow."""
    contract, _ = breek
    rid = a_round(breek, vm)
    for size in (19, 25, 69, 70, 78, 100):
        result = enter(contract, vm, bob, rid, "9" * size)
        assert result.startswith("REFUNDED:"), "%d digits -> %s" % (size, result)
    assert contract.get_round(rid)["pot_wei"] == "0"
    # and the bound really is under the storage ceiling
    assert mod.MAX_FORECAST < 2**256


def test_very_long_but_valid_fraction_is_accepted(breek, vm, bob):
    """Excess precision truncates rather than being rejected."""
    contract, _ = breek
    rid = a_round(breek, vm)
    assert enter(contract, vm, bob, rid, "117.9" + "9" * 40).startswith("ENTERED:")


def test_huge_forecast_cannot_break_scoring(breek, vm, alice, bob):
    """Even an accepted extreme value must not blow up the grading pass."""
    from tests.conftest import mock_feeds

    contract, _ = breek
    rid = a_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")
    # The largest forecast the contract will accept.
    assert enter(contract, vm, bob, rid, "1" + "0" * 17).startswith("ENTERED:")
    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close="117.88", b_close="117.96")
    warp_to(vm, DAY_END + HOUR)
    assert contract.score_round(rid).startswith("SCORED:")
    assert contract.get_entry(rid, hexaddr(bob))["outcome"] == "OUTSIDE_BAND"
    vm.sender = alice
    assert contract.collect(rid).endswith(":SCORED")


# --- capacity --------------------------------------------------------------


def test_round_refuses_entries_past_the_cap(breek, vm, mod):
    """MAX_ENTRIES bounds the single grading pass, so it must hold."""
    from gltest.direct import create_address

    contract, _ = breek
    rid = a_round(breek, vm)
    cap = mod.MAX_ENTRIES
    for i in range(cap):
        who = create_address("filler-%d" % i)
        assert enter(contract, vm, who, rid, "117.%02d" % (i % 100)).startswith("ENTERED:")
    assert contract.get_round(rid)["entrants"] == str(cap)

    overflow = create_address("one-too-many")
    assert enter(contract, vm, overflow, rid, "118.00") == "REFUNDED:ROUND_FULL"
    assert contract.get_round(rid)["entrants"] == str(cap)
    assert contract.get_round(rid)["pot_wei"] == str(cap * ENTRY_FEE)


# --- fee handling ----------------------------------------------------------


@pytest.mark.parametrize("fee", [1, ENTRY_FEE - 1, ENTRY_FEE + 1, 2 * ENTRY_FEE, 100 * GEN])
def test_any_fee_but_the_exact_one_is_refunded(breek, vm, bob, fee):
    contract, _ = breek
    rid = a_round(breek, vm)
    assert enter(contract, vm, bob, rid, "117.95", fee=fee) == "REFUNDED:WRONG_FEE"
    assert contract.get_round(rid)["pot_wei"] == "0"


def test_malformed_forecasts_are_all_refunded(breek, vm, bob):
    contract, _ = breek
    rid = a_round(breek, vm)
    for bad in ["", " ", "abc", "-1", "1e5", "1.2.3", "0", "0.0", "+", ".", "1,5", "NaN"]:
        result = enter(contract, vm, bob, rid, bad)
        assert result.startswith("REFUNDED:"), "%r -> %s" % (bad, result)
    assert contract.get_round(rid)["pot_wei"] == "0"


# --- views must never divide by zero ---------------------------------------


def test_views_survive_a_round_nobody_could_score(breek, vm, alice, bob):
    """VOID_NO_SCORES leaves total_weight at zero; no view may divide by it."""
    from tests.conftest import mock_feeds

    contract, _ = breek
    rid = a_round(breek, vm)
    enter(contract, vm, alice, rid, "500.00")
    enter(contract, vm, bob, rid, "900.00")
    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close="117.88", b_close="117.96")
    warp_to(vm, DAY_END + HOUR)
    assert contract.score_round(rid) == "VOID:NO_SCORES"

    # every view that touches weights must still answer
    assert contract.get_round(rid)["total_weight"] == "0"
    assert contract.get_entry(rid, hexaddr(alice))["collectable_wei"] == str(ENTRY_FEE)
    board = contract.get_leaderboard(rid, 50)
    assert len(board["entries"]) == 2
    assert contract.list_entries(hexaddr(alice), 10)["entries"][0]["entry"]["outcome"].startswith(
        "REFUND_"
    )


def test_views_survive_an_empty_round(breek, vm):
    """A round nobody entered still prices, and every view must cope."""
    from tests.conftest import mock_feeds

    contract, _ = breek
    rid = a_round(breek, vm)
    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close="117.88", b_close="117.96")
    warp_to(vm, DAY_END + HOUR)
    assert contract.score_round(rid).startswith("SCORED:")
    assert contract.get_round(rid)["total_weight"] == "0"
    assert contract.get_leaderboard(rid, 50)["entries"] == []
    assert contract.get_evidence(rid)["consensus"] != ""


# --- unknown ids -----------------------------------------------------------


def test_views_reject_unknown_rounds_cleanly(breek, vm, alice):
    contract, _ = breek
    a_round(breek, vm)
    for fn in ("get_round", "get_phase", "get_evidence"):
        with pytest.raises(Exception, match="NO_SUCH_ROUND"):
            getattr(contract, fn)(4242)
    with pytest.raises(Exception, match="NO_SUCH_ROUND"):
        contract.get_entry(4242, hexaddr(alice))
    with pytest.raises(Exception, match="NO_SUCH_ROUND"):
        contract.get_leaderboard(4242, 10)


def test_list_entries_for_a_stranger_is_empty_not_an_error(breek, vm, carol):
    contract, _ = breek
    a_round(breek, vm)
    out = contract.list_entries(hexaddr(carol), 10)
    assert out["entries"] == []
