"""Hostile and boundary inputs.

The rule these all test: ``commit_forecast`` is payable, so it must never revert
once the fee has been credited. Every rejection has to come back as a refund
inside the same call. A revert here would strand the fee with no path out.

Commit-reveal moves where a malformed price can do damage. The payable call now
carries only a digest, so an oversized or nonsense number cannot reach it at
all; the number arrives at ``reveal_forecast``, which is not payable, where a
revert costs a signature and strands nothing. Both halves are tested.
"""

import pytest

from tests.conftest import (
    DAY,
    ENTRY_FEE,
    GEN,
    HOUR,
    commitment,
    day_window,
    hexaddr,
    warp_to,
)

DAY_ID = "2026-09-24"
DAY_START, DAY_END = day_window(2026, 9, 24)
BEFORE = DAY_START - 2 * DAY


def a_round(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    return int(contract.open_round("CRYPTO", "SOL", "DAILY", DAY_ID).split(":")[1])


SALT = "feedfacecafe0001"


def enter(contract, vm, who, rid, forecast, fee=ENTRY_FEE):
    """Commit a sealed forecast."""
    vm.sender = who
    vm.origin = who
    vm.value = fee
    try:
        return contract.commit_forecast(rid, commitment(rid, who, forecast, SALT))
    finally:
        vm.value = 0


def open_it(contract, vm, who, rid, forecast, salt=SALT):
    """Reveal, from inside the reveal window."""
    warp_to(vm, int(contract.get_round(rid)["locks_at"]) + HOUR)
    vm.sender = who
    vm.origin = who
    vm.value = 0
    return contract.reveal_forecast(rid, forecast, salt)


# --- oversized numbers -----------------------------------------------------


def test_absurdly_large_forecast_cannot_strand_a_fee(breek, vm, bob):
    """A 70-digit forecast would overflow the u256 storage slot.

    Under commit-reveal it cannot reach the payable call, because that call
    takes a digest. It surfaces at reveal, which holds no value, so the revert
    is free: the entry stays open and the entrant can reveal properly instead.
    """
    contract, _ = breek
    rid = a_round(breek, vm)
    huge = "1" + "0" * 70

    # Committing to an absurd number is allowed -- the contract cannot tell,
    # which is the entire point of a commitment.
    assert enter(contract, vm, bob, rid, huge).startswith("COMMITTED:")
    assert contract.get_round(rid)["pot_wei"] == str(ENTRY_FEE)

    with pytest.raises(Exception, match="BAD_FORECAST"):
        open_it(contract, vm, bob, rid, huge)

    # Nothing stranded, nothing written: the entry is intact and unrevealed.
    entry = contract.get_entry(rid, hexaddr(bob))
    assert entry["entered"] is True
    assert entry["revealed"] is False
    assert entry["forecast"] == ""


def test_forecast_past_the_bound_is_rejected_at_reveal(breek, vm, bob, mod):
    """MAX_FORECAST sits far below the u256 ceiling, so nothing can overflow."""
    from gltest.direct import create_address

    contract, _ = breek
    rid = a_round(breek, vm)
    sizes = (19, 25, 69, 70, 78, 100)

    # Commit every oversized number first; the digest gives nothing away, so
    # each one is accepted and each fee is taken.
    people = []
    for i, size in enumerate(sizes):
        who = create_address("oversize-%d" % i)
        people.append((who, "9" * size))
        assert enter(contract, vm, who, rid, "9" * size).startswith("COMMITTED:")

    # Then none of them can be opened, and none of the reverts strand a fee.
    for who, number in people:
        with pytest.raises(Exception, match="BAD_FORECAST"):
            open_it(contract, vm, who, rid, number)
        assert contract.get_entry(rid, hexaddr(who))["revealed"] is False
    # and the bound really is under the storage ceiling
    assert mod.MAX_FORECAST < 2**256


def test_very_long_but_valid_fraction_is_accepted(breek, vm, bob):
    """Excess precision truncates rather than being rejected."""
    contract, _ = breek
    rid = a_round(breek, vm)
    number = "117.9" + "9" * 40
    assert enter(contract, vm, bob, rid, number).startswith("COMMITTED:")
    # The reveal must scale the same way the client did, or the digest will not
    # match -- so truncation being identical on both sides is load bearing.
    assert open_it(contract, vm, bob, rid, number) == "REVEALED:117.99999999"


def test_huge_forecast_cannot_break_scoring(breek, vm, alice, bob):
    """Even an accepted extreme value must not blow up the grading pass."""
    from tests.conftest import mock_feeds

    contract, _ = breek
    rid = a_round(breek, vm)
    extreme = "1" + "0" * 17
    enter(contract, vm, alice, rid, "117.95")
    # The largest forecast the contract will accept.
    assert enter(contract, vm, bob, rid, extreme).startswith("COMMITTED:")
    open_it(contract, vm, alice, rid, "117.95")
    open_it(contract, vm, bob, rid, extreme)
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
        assert enter(contract, vm, who, rid, "117.%02d" % (i % 100)).startswith("COMMITTED:")
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


MALFORMED = ["", " ", "abc", "-1", "1e5", "1.2.3", "0", "0.0", "+", ".", "1,5", "NaN"]


def test_malformed_commitments_are_all_refunded(breek, vm, bob):
    """Garbage in the payable slot always comes back as a refund."""
    contract, _ = breek
    rid = a_round(breek, vm)
    for bad in MALFORMED + ["0x" + "a" * 62, "a" * 64 + "a", " " * 64]:
        vm.sender = bob
        vm.origin = bob
        vm.value = ENTRY_FEE
        try:
            result = contract.commit_forecast(rid, bad)
        finally:
            vm.value = 0
        assert result == "REFUNDED:BAD_COMMITMENT", "%r -> %s" % (bad, result)
    assert contract.get_round(rid)["pot_wei"] == "0"


def test_malformed_forecasts_are_all_refused_at_reveal(breek, vm, bob):
    """None of these can hash to the commitment, and none of them strand a fee."""
    contract, _ = breek
    rid = a_round(breek, vm)
    enter(contract, vm, bob, rid, "117.95")
    warp_to(vm, int(contract.get_round(rid)["locks_at"]) + HOUR)
    vm.sender = bob
    vm.origin = bob
    for bad in MALFORMED:
        with pytest.raises(Exception):
            contract.reveal_forecast(rid, bad, SALT)
    assert contract.get_entry(rid, hexaddr(bob))["revealed"] is False
    # The real number still opens afterwards.
    assert contract.reveal_forecast(rid, "117.95", SALT) == "REVEALED:117.95000000"


def test_a_wrong_salt_cannot_open_a_commitment(breek, vm, bob):
    contract, _ = breek
    rid = a_round(breek, vm)
    enter(contract, vm, bob, rid, "117.95")
    warp_to(vm, int(contract.get_round(rid)["locks_at"]) + HOUR)
    vm.sender = bob
    vm.origin = bob
    with pytest.raises(Exception, match="COMMITMENT_MISMATCH"):
        contract.reveal_forecast(rid, "117.95", "0000000000000000")
    with pytest.raises(Exception, match="BAD_SALT"):
        contract.reveal_forecast(rid, "117.95", "short")
    with pytest.raises(Exception, match="BAD_SALT"):
        contract.reveal_forecast(rid, "117.95", "f" * 65)
    assert contract.get_entry(rid, hexaddr(bob))["revealed"] is False


# --- views must never divide by zero ---------------------------------------


def test_views_survive_a_round_nobody_could_score(breek, vm, alice, bob):
    """VOID_NO_SCORES leaves total_weight at zero; no view may divide by it."""
    from tests.conftest import mock_feeds

    contract, _ = breek
    rid = a_round(breek, vm)
    enter(contract, vm, alice, rid, "500.00")
    enter(contract, vm, bob, rid, "900.00")
    open_it(contract, vm, alice, rid, "500.00")
    open_it(contract, vm, bob, rid, "900.00")
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
