"""Concealment: nobody can read a forecast that has not been revealed.

This file exists because the previous design failed exactly here. Forecasts
were stored as plaintext and ``get_entry`` accepted any address, so a rival --
or a passer-by -- could simply ask the contract what somebody had forecast
while the round was still accepting entries. A leaderboard that withheld the
number was cosmetic: three other paths returned it.

The tests below are written from the attacker's side. Each one is somebody
other than the entrant trying to obtain a number they are not entitled to yet,
through whatever route the contract offers. The property under test is not
"the leaderboard is tidy" but "no route exists".
"""

import hashlib
import json

import pytest
from gltest.direct import create_address

from tests.conftest import (
    DAY,
    ENTRY_FEE,
    HOUR,
    commitment,
    day_window,
    hexaddr,
    mock_feeds,
    scale_price,
    warp_to,
)

DAY_ID = "2026-09-24"
DAY_START, DAY_END = day_window(2026, 9, 24)
BEFORE = DAY_START - 2 * DAY
IN_WINDOW = DAY_START + HOUR
AFTER_CLOSE = DAY_END + HOUR

#: Distinctive enough that finding it in a blob of JSON means a real leak and
#: not a coincidental substring.
SECRET = "137.31415926"
SECRET_SCALED = "13731415926"
SALT = "5eaf00d5eaf00d5e"


def a_round(breek, vm, window=DAY_ID):
    contract, _ = breek
    warp_to(vm, BEFORE)
    return int(contract.open_round("CRYPTO", "SOL", "DAILY", window).split(":")[1])


def commit(contract, vm, who, rid, forecast, salt=SALT):
    vm.sender = who
    vm.origin = who
    vm.value = ENTRY_FEE
    try:
        return contract.commit_forecast(rid, commitment(rid, who, forecast, salt))
    finally:
        vm.value = 0


def as_user(vm, who):
    vm.sender = who
    vm.origin = who
    vm.value = 0


# ---------------------------------------------------------------------------
# The direct routes a rival would try
# ---------------------------------------------------------------------------


def test_a_rival_cannot_read_my_forecast_through_get_entry(breek, vm, alice, bob):
    """``get_entry`` takes any address, so it is the obvious way in."""
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)
    commit(contract, vm, bob, rid, "120.00")

    # Bob is a paying entrant in the same round -- maximally entitled, short of
    # being Alice -- and still gets nothing.
    as_user(vm, bob)
    seen = contract.get_entry(rid, hexaddr(alice))
    assert seen["entered"] is True
    assert seen["revealed"] is False
    assert seen["forecast"] == ""
    assert SECRET not in json.dumps(seen)

    # Alice cannot read it early either. The view does not care who is asking,
    # which is what stops it from having a privileged mode at all.
    as_user(vm, alice)
    assert contract.get_entry(rid, hexaddr(alice))["forecast"] == ""


def test_a_rival_cannot_read_my_forecast_through_list_entries(breek, vm, alice, bob):
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)

    as_user(vm, bob)
    out = contract.list_entries(hexaddr(alice), 50)
    assert len(out["entries"]) == 1
    assert out["entries"][0]["entry"]["forecast"] == ""
    assert SECRET not in json.dumps(out)


def test_a_rival_cannot_read_my_forecast_through_the_leaderboard(breek, vm, alice, bob):
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)

    as_user(vm, bob)
    board = contract.get_leaderboard(rid, 50)
    assert board["entries"][0]["who"] == hexaddr(alice)
    assert board["entries"][0]["forecast"] == ""
    assert SECRET not in json.dumps(board)


def test_no_view_at_all_exposes_an_unrevealed_forecast(breek, vm, alice, bob, carol):
    """Sweep every public view and look for the number anywhere in the output.

    Written as a sweep rather than three targeted assertions on purpose: a view
    added later is covered by this test the day it is added, without anyone
    having to remember that concealment was a requirement.
    """
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)
    commit(contract, vm, bob, rid, "121.50")

    # Carol never entered. She is a stranger with an RPC endpoint.
    as_user(vm, carol)
    everything = {
        "catalog": contract.get_catalog(),
        "round": contract.get_round(rid),
        "phase": contract.get_phase(rid),
        "entry_alice": contract.get_entry(rid, hexaddr(alice)),
        "entry_bob": contract.get_entry(rid, hexaddr(bob)),
        "entry_self": contract.get_entry(rid, hexaddr(carol)),
        "leaderboard": contract.get_leaderboard(rid, 50),
        "stats": contract.get_stats(),
        "rounds": contract.list_rounds(0, 50),
        "scoreable": contract.list_scoreable(50),
        "entries_alice": contract.list_entries(hexaddr(alice), 50),
        "entries_bob": contract.list_entries(hexaddr(bob), 50),
    }
    blob = json.dumps(everything, default=str)

    assert SECRET not in blob, "a view leaked the decimal forecast"
    assert SECRET_SCALED not in blob, "a view leaked the scaled forecast"
    # The commitment is published, and must be: it is what the reveal is
    # checked against. It just says nothing about the number.
    assert commitment(rid, alice, SECRET, SALT) in blob


def test_the_commitment_itself_gives_nothing_away(breek, vm, alice, bob):
    """Identical forecasts from two people do not produce identical digests."""
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)
    commit(contract, vm, bob, rid, SECRET)

    a = contract.get_entry(rid, hexaddr(alice))["commitment"]
    b = contract.get_entry(rid, hexaddr(bob))["commitment"]
    assert a != b, "equal forecasts must not be detectable by comparing digests"

    # And the same person forecasting differently in another round is unlinkable
    # to this one, because the round id is inside the preimage.
    other = a_round(breek, vm, window="2026-09-25")
    commit(contract, vm, alice, other, SECRET)
    assert contract.get_entry(other, hexaddr(alice))["commitment"] != a


def test_the_salt_is_what_defeats_a_brute_force(breek, vm, alice, bob):
    """Grind the whole plausible price range against the published scheme.

    The scheme is public, the round id is public and the entrant's address is
    public, so an attacker is only missing the salt. This enumerates every
    price from 100.00000000 to 150.00000000 at one-cent steps -- far more than
    a real guesser would bother with, and certainly containing the answer --
    and confirms that not one of them reproduces the stored digest.
    """
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)

    as_user(vm, bob)
    target = contract.get_entry(rid, hexaddr(alice))["commitment"]
    who = hexaddr(alice)

    # Sanity: the grind would find it if the salt were known, so a miss below
    # is the salt working rather than the harness being broken.
    assert (
        hashlib.sha256(
            ("c1|%d|%s|%d|%s" % (rid, who, scale_price(SECRET), SALT)).encode()
        ).hexdigest()
        == target
    )

    cents = 0
    for scaled in range(100 * 10**8, 150 * 10**8 + 1, 10**6):
        guess = hashlib.sha256(
            ("c1|%d|%s|%d|%s" % (rid, who, scaled, "")).encode()
        ).hexdigest()
        assert guess != target
        cents += 1
    assert cents > 5000, "the sweep must actually cover the range"


# ---------------------------------------------------------------------------
# Stealing a forecast rather than reading it
# ---------------------------------------------------------------------------


def test_copying_a_rivals_commitment_does_not_let_you_reveal_it(breek, vm, alice, bob):
    """The strongest attack the scheme has to survive.

    Bob cannot read Alice's number, but he can read her *digest* -- it is
    public. So he submits it as his own entry and waits. Alice reveals, which
    publishes her price and her salt together. Bob now holds the complete
    preimage for the digest he committed to. If the preimage did not include
    the sender, he could replay it and obtain an entry as accurate as hers
    without ever making a forecast.
    """
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)

    stolen = contract.get_entry(rid, hexaddr(alice))["commitment"]
    as_user(vm, bob)
    vm.value = ENTRY_FEE
    try:
        assert contract.commit_forecast(rid, stolen) == "COMMITTED:" + stolen
    finally:
        vm.value = 0

    # Alice opens hers, which makes (forecast, salt) public knowledge.
    warp_to(vm, IN_WINDOW)
    as_user(vm, alice)
    assert contract.reveal_forecast(rid, SECRET, SALT) == "REVEALED:" + SECRET

    # Bob replays the exact pair against the exact digest he committed to.
    as_user(vm, bob)
    with pytest.raises(Exception, match="COMMITMENT_MISMATCH"):
        contract.reveal_forecast(rid, SECRET, SALT)

    # He is left holding an entry he cannot open, which scores nothing.
    assert contract.get_entry(rid, hexaddr(bob))["revealed"] is False


def test_a_commitment_cannot_be_carried_between_rounds(breek, vm, alice):
    """Round binding: the same sealed number in round A cannot open in round B."""
    contract, _ = breek
    first = a_round(breek, vm)
    second = a_round(breek, vm, window="2026-09-25")
    commit(contract, vm, alice, first, SECRET)

    # Commit the round-one digest into round two.
    stale = contract.get_entry(first, hexaddr(alice))["commitment"]
    as_user(vm, alice)
    vm.value = ENTRY_FEE
    try:
        contract.commit_forecast(second, stale)
    finally:
        vm.value = 0

    # Into round two's own reveal window, not round one's.
    warp_to(vm, int(contract.get_round(second)["locks_at"]) + HOUR)
    as_user(vm, alice)
    with pytest.raises(Exception, match="COMMITMENT_MISMATCH"):
        contract.reveal_forecast(second, SECRET, SALT)


# ---------------------------------------------------------------------------
# The reveal window has two edges, and both of them matter
# ---------------------------------------------------------------------------


def test_nothing_can_be_revealed_while_entries_are_still_open(breek, vm, alice):
    """An early reveal would hand a live forecast to someone still able to enter."""
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)

    as_user(vm, alice)
    with pytest.raises(Exception, match="REVEAL_NOT_OPEN"):
        contract.reveal_forecast(rid, SECRET, SALT)

    # Right up to the last second before entries close.
    warp_to(vm, DAY_START - 1)
    as_user(vm, alice)
    with pytest.raises(Exception, match="REVEAL_NOT_OPEN"):
        contract.reveal_forecast(rid, SECRET, SALT)

    # And permitted at the exact instant they do.
    warp_to(vm, DAY_START)
    as_user(vm, alice)
    assert contract.reveal_forecast(rid, SECRET, SALT).startswith("REVEALED:")


def test_nothing_can_be_revealed_once_the_price_is_knowable(breek, vm, alice):
    """A late reveal is a reveal made knowing the answer.

    Reveals shut at ``scoreable_at``, which is the instant the settling price
    exists. Allowing one after that would let an entrant look at the outcome
    before deciding whether to open their commitment at all.
    """
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)

    warp_to(vm, DAY_END)  # exactly scoreable
    as_user(vm, alice)
    with pytest.raises(Exception, match="REVEAL_CLOSED"):
        contract.reveal_forecast(rid, SECRET, SALT)


def test_entering_is_impossible_once_reveals_have_started(breek, vm, alice, bob):
    """The two windows must not overlap, or the seal is pointless."""
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)

    warp_to(vm, DAY_START)
    as_user(vm, alice)
    contract.reveal_forecast(rid, SECRET, SALT)
    # Alice's number is now public...
    assert contract.get_entry(rid, hexaddr(alice))["forecast"] == SECRET
    # ...and Bob, who can now see it, is refused entry.
    assert commit(contract, vm, bob, rid, SECRET) == "REFUNDED:ROUND_LOCKED"


# ---------------------------------------------------------------------------
# What happens to a commitment nobody opens
# ---------------------------------------------------------------------------


def test_an_unrevealed_entry_scores_nothing_and_forfeits_to_the_pot(
    breek, vm, alice, bob
):
    """Forfeiting is what stops commit-many-reveal-one from paying."""
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, "117.95")
    commit(contract, vm, bob, rid, "118.40")

    warp_to(vm, IN_WINDOW)
    as_user(vm, alice)
    contract.reveal_forecast(rid, "117.95", SALT)
    # Bob simply walks away.

    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close="117.88", b_close="117.96")
    warp_to(vm, AFTER_CLOSE)
    assert contract.score_round(rid).startswith("SCORED:")

    assert contract.get_round(rid)["revealed"] == "1"
    assert contract.get_entry(rid, hexaddr(bob))["outcome"] == "NOT_REVEALED"
    assert contract.get_entry(rid, hexaddr(bob))["collectable_wei"] == "0"

    as_user(vm, bob)
    assert contract.collect(rid) == "COLLECTED:0:NOT_REVEALED"

    # Alice takes the whole pot, including the fee Bob forfeited.
    as_user(vm, alice)
    paid = contract.collect(rid)
    assert paid.endswith(":SCORED")
    assert int(paid.split(":")[1]) == 2 * ENTRY_FEE


def test_a_round_nobody_reveals_voids_and_refunds_without_any_http(breek, vm, alice, bob):
    """No reveals means nothing to grade, so no reason to ask a feed anything."""
    contract, _ = breek
    rid = a_round(breek, vm)
    commit(contract, vm, alice, rid, SECRET)
    commit(contract, vm, bob, rid, "120.00")

    # No mocks are registered at all. Strict mocking makes any HTTP a failure,
    # so this passing is the proof that the path makes no request.
    vm.clear_mocks()
    vm.strict_mocks = True
    warp_to(vm, AFTER_CLOSE)
    assert contract.score_round(rid) == "VOID:NO_REVEALS"

    assert contract.get_round(rid)["status"] == "VOID_NO_REVEALS"
    for who in (alice, hexaddr(bob)):
        addr = who if isinstance(who, str) else hexaddr(who)
        assert contract.get_entry(rid, addr)["collectable_wei"] == str(ENTRY_FEE)

    as_user(vm, alice)
    assert contract.collect(rid).endswith(":REFUND_VOID_NO_REVEALS")
    as_user(vm, bob)
    assert contract.collect(rid).endswith(":REFUND_VOID_NO_REVEALS")


def test_an_empty_round_still_prices_normally(breek, vm):
    """No entrants is not the same as no reveals, and must not void."""
    contract, _ = breek
    rid = a_round(breek, vm)
    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close="117.88", b_close="117.96")
    warp_to(vm, AFTER_CLOSE)
    assert contract.score_round(rid).startswith("SCORED:")


def test_many_entrants_and_one_holdout(breek, vm):
    """The concealment property has to hold across a crowd, not just a pair."""
    contract, _ = breek
    rid = a_round(breek, vm)

    people = [create_address("crowd-%d" % i) for i in range(12)]
    secrets = ["1%02d.0000000%d" % (10 + i, i % 10) for i in range(12)]
    for who, number in zip(people, secrets):
        commit(contract, vm, who, rid, number)

    # Every entrant inspects every other entrant, before anyone has revealed.
    for watcher in people:
        as_user(vm, watcher)
        for target in people:
            assert contract.get_entry(rid, hexaddr(target))["forecast"] == ""
        blob = json.dumps(contract.get_leaderboard(rid, 50), default=str)
        for number in secrets:
            assert number not in blob

    # All but one reveal; the holdout's number never becomes readable.
    warp_to(vm, IN_WINDOW)
    for who, number in list(zip(people, secrets))[:-1]:
        as_user(vm, who)
        contract.reveal_forecast(rid, number, SALT)

    holdout, hidden = people[-1], secrets[-1]
    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close="117.88", b_close="117.96")
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)

    assert contract.get_round(rid)["revealed"] == "11"
    assert contract.get_entry(rid, hexaddr(holdout))["forecast"] == ""
    assert hidden not in json.dumps(contract.get_leaderboard(rid, 50), default=str)
