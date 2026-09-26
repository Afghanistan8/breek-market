"""Round lifecycle: commit, revise, reveal, score, collect.

These drive the public methods exactly as a wallet would, including the fee
attached to ``commit_forecast``, so the refund-instead-of-revert rule is
exercised for real rather than asserted about.

Entering is a two-step commit-reveal, so ``enter`` seals a forecast and
``score`` opens every commitment on the way past the window. A test that cares
about the seal itself does the two steps by hand.
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
    mock_feeds,
    warp_to,
    week_window,
)

DAY_ID = "2026-09-24"
DAY_START, DAY_END = day_window(2026, 9, 24)
WEEK_ID = "2026-09-14"
WEEK_START, WEEK_END = week_window(2026, 9, 14)

BEFORE = DAY_START - 2 * DAY
AFTER_CLOSE = DAY_END + HOUR
EXPIRED = DAY_END + 5 * DAY + HOUR


def open_round(breek, vm, asset="SOL", window=DAY_ID, timeframe="DAILY"):
    contract, _ = breek
    warp_to(vm, BEFORE if timeframe == "DAILY" else WEEK_START - 2 * DAY)
    res = contract.open_round("CRYPTO", asset, timeframe, window)
    return int(res.split(":")[1])


#: Every commitment made in the current test, so ``reveal_all`` can open them.
#: Keyed by round id; a salt is handed out per entry and never reused.
_SEALED: dict = {}


def salt_for(n: int) -> str:
    return "%016x" % (0xB0000000 + n)


def enter(contract, vm, who, round_id, forecast, fee=ENTRY_FEE):
    """Commit a sealed forecast. The plaintext never touches the chain here."""
    salt = salt_for(len(_SEALED.get(round_id, [])))
    vm.sender = who
    vm.origin = who
    vm.value = fee
    try:
        out = contract.commit_forecast(round_id, commitment(round_id, who, forecast, salt))
    finally:
        vm.value = 0
    if out.startswith("COMMITTED:"):
        _SEALED.setdefault(round_id, []).append((who, forecast, salt))
    return out


def reveal_all(contract, vm, round_id):
    """Open every commitment made for this round, inside the reveal window."""
    r = contract.get_round(round_id)
    warp_to(vm, int(r["locks_at"]) + HOUR)
    for who, forecast, salt in _SEALED.get(round_id, []):
        vm.sender = who
        vm.origin = who
        vm.value = 0
        contract.reveal_forecast(round_id, forecast, salt)


@pytest.fixture(autouse=True)
def _clear_sealed():
    _SEALED.clear()
    yield
    _SEALED.clear()


def score(breek, vm, rid, *, a="117.88", b="117.96", asset="SOL",
          start=DAY_START, end=DAY_END, at=AFTER_CLOSE, reveal=True):
    contract, _ = breek
    if reveal:
        reveal_all(contract, vm, rid)
    vm.clear_mocks()
    mock_feeds(vm, asset, start, end, a_close=a, b_close=b)
    warp_to(vm, at)
    return contract.score_round(rid)


# --- opening ---------------------------------------------------------------


def test_open_sets_derived_schedule(breek, vm):
    contract, _ = breek
    rid = open_round(breek, vm)
    r = contract.get_round(rid)
    assert r["asset"] == "SOL"
    assert r["window_start"] == str(DAY_START)
    assert r["window_end"] == str(DAY_END)
    assert r["locks_at"] == str(DAY_START)
    assert r["scoreable_at"] == str(DAY_END)
    assert r["expires_at"] == str(DAY_END + 5 * DAY)
    assert r["phase"] == "ACCEPTING"
    assert r["entry_fee_wei"] == str(ENTRY_FEE)


def test_open_rejects_dominance(breek, vm):
    """No second historical feed, so no consensus price can be formed."""
    contract, _ = breek
    warp_to(vm, BEFORE)
    with pytest.raises(Exception, match="CATEGORY_NOT_PRICEABLE"):
        contract.open_round("DOMINANCE", "BTC.D", "DAILY", DAY_ID)


def test_open_rejects_unknown_keys(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    with pytest.raises(Exception, match="UNKNOWN_CATEGORY"):
        contract.open_round("STOCKS", "SOL", "DAILY", DAY_ID)
    with pytest.raises(Exception, match="UNKNOWN_ASSET"):
        contract.open_round("CRYPTO", "BTC", "DAILY", DAY_ID)
    with pytest.raises(Exception, match="UNKNOWN_TIMEFRAME"):
        contract.open_round("CRYPTO", "SOL", "HOURLY", DAY_ID)


def test_open_rejects_past_and_duplicate(breek, vm):
    contract, _ = breek
    warp_to(vm, DAY_START + HOUR)
    with pytest.raises(Exception, match="WINDOW_NOT_IN_FUTURE"):
        contract.open_round("CRYPTO", "SOL", "DAILY", DAY_ID)
    open_round(breek, vm)
    with pytest.raises(Exception, match="DUPLICATE_ROUND"):
        contract.open_round("CRYPTO", "SOL", "DAILY", DAY_ID)


def test_anyone_can_open(breek, vm, bob):
    contract, _ = breek
    vm.sender = bob
    warp_to(vm, BEFORE)
    rid = int(contract.open_round("CRYPTO", "NEAR", "DAILY", DAY_ID).split(":")[1])
    assert contract.get_round(rid)["opener"] == hexaddr(bob)


# --- entering --------------------------------------------------------------


def test_entry_takes_a_number_not_a_side(breek, vm, bob):
    """Entering stores a sealed number, and the seal holds until reveal."""
    contract, _ = breek
    rid = open_round(breek, vm)
    assert enter(contract, vm, bob, rid, "118.40").startswith("COMMITTED:")

    entry = contract.get_entry(rid, hexaddr(bob))
    assert entry["entered"] is True
    assert entry["revealed"] is False
    assert entry["forecast"] == ""
    assert len(entry["commitment"]) == 64

    reveal_all(contract, vm, rid)
    opened = contract.get_entry(rid, hexaddr(bob))
    assert opened["revealed"] is True
    assert opened["forecast"] == "118.40000000"


def test_every_entrant_pays_the_same_flat_fee(breek, vm, bob, carol):
    """There is no stake size to vary, so only accuracy can separate payouts."""
    contract, _ = breek
    rid = open_round(breek, vm)
    assert enter(contract, vm, bob, rid, "118.40", fee=2 * GEN) == "REFUNDED:WRONG_FEE"
    assert enter(contract, vm, bob, rid, "118.40", fee=ENTRY_FEE // 2) == "REFUNDED:WRONG_FEE"
    assert enter(contract, vm, bob, rid, "118.40").startswith("COMMITTED:")
    assert enter(contract, vm, carol, rid, "117.10").startswith("COMMITTED:")
    assert contract.get_round(rid)["pot_wei"] == str(2 * ENTRY_FEE)


def test_second_entry_from_the_same_wallet_is_refunded(breek, vm, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, bob, rid, "118.40")
    assert enter(contract, vm, bob, rid, "119.00") == "REFUNDED:ALREADY_ENTERED"
    assert contract.get_round(rid)["pot_wei"] == str(ENTRY_FEE)


def test_bad_commitment_is_refunded(breek, vm, bob):
    """A commitment must be a sha256 digest, and the fee comes back if not."""
    contract, _ = breek
    rid = open_round(breek, vm)
    bad_digests = [
        "",                   # empty
        "abc",                # too short
        "z" * 64,             # right length, not hex
        "A" * 64,             # uppercase: would hash-mismatch forever
        "a" * 63,             # one short
        "a" * 65,             # one long
    ]
    for bad in bad_digests:
        vm.sender = bob
        vm.origin = bob
        vm.value = ENTRY_FEE
        try:
            assert contract.commit_forecast(rid, bad) == "REFUNDED:BAD_COMMITMENT"
        finally:
            vm.value = 0
    assert contract.get_round(rid)["pot_wei"] == "0"


def test_bad_forecast_is_rejected_at_reveal(breek, vm, bob):
    """A malformed price cannot be revealed, and cannot strand a fee either."""
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, bob, rid, "118.40")
    r = contract.get_round(rid)
    warp_to(vm, int(r["locks_at"]) + HOUR)
    vm.sender = bob
    vm.origin = bob
    for bad in ["abc", "-5", "1e5", "0"]:
        with pytest.raises(Exception):
            contract.reveal_forecast(rid, bad, salt_for(0))
    # The entry survives every rejected attempt and can still be opened.
    assert contract.get_entry(rid, hexaddr(bob))["revealed"] is False
    contract.reveal_forecast(rid, "118.40", salt_for(0))
    assert contract.get_entry(rid, hexaddr(bob))["forecast"] == "118.40000000"


def test_late_entry_is_refunded(breek, vm, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    warp_to(vm, DAY_START)  # exactly at lock
    assert enter(contract, vm, bob, rid, "118.40") == "REFUNDED:ROUND_LOCKED"


def test_entry_on_missing_round_is_refunded(breek, vm, bob):
    contract, _ = breek
    open_round(breek, vm)
    assert enter(contract, vm, bob, 999, "118.40") == "REFUNDED:NO_SUCH_ROUND"


def test_entry_with_no_fee_reverts(breek, vm, bob):
    """Nothing is at risk, so a plain revert is safe here."""
    contract, _ = breek
    rid = open_round(breek, vm)
    vm.sender = bob
    with pytest.raises(Exception, match="NO_FEE_ATTACHED"):
        contract.commit_forecast(rid, "a" * 64)


# --- revising --------------------------------------------------------------


def test_forecast_can_be_revised_freely_before_lock(breek, vm, bob):
    """The opposite of a locked side: sharpening your estimate is encouraged."""
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, bob, rid, "118.40")
    vm.sender = bob
    vm.origin = bob

    first = commitment(rid, bob, "117.95", salt_for(0))
    second = commitment(rid, bob, "117.90", salt_for(0))
    assert contract.revise_commitment(rid, first) == "REVISED:" + first
    assert contract.revise_commitment(rid, second) == "REVISED:" + second

    entry = contract.get_entry(rid, hexaddr(bob))
    assert entry["commitment"] == second
    assert entry["forecast"] == ""      # still sealed
    assert entry["revisions"] == "2"
    # revising never costs anything
    assert contract.get_round(rid)["pot_wei"] == str(ENTRY_FEE)

    # Only the last commitment can be opened.
    warp_to(vm, int(contract.get_round(rid)["locks_at"]) + HOUR)
    vm.sender = bob
    vm.origin = bob
    with pytest.raises(Exception, match="COMMITMENT_MISMATCH"):
        contract.reveal_forecast(rid, "118.40", salt_for(0))
    contract.reveal_forecast(rid, "117.90", salt_for(0))
    assert contract.get_entry(rid, hexaddr(bob))["forecast"] == "117.90000000"


def test_revision_is_rejected_after_lock(breek, vm, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, bob, rid, "118.40")
    warp_to(vm, DAY_START)
    vm.sender = bob
    with pytest.raises(Exception, match="ROUND_LOCKED"):
        contract.revise_commitment(rid, commitment(rid, bob, "117.95", salt_for(1)))


def test_revision_requires_an_entry(breek, vm, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    vm.sender = bob
    with pytest.raises(Exception, match="NOT_ENTERED"):
        contract.revise_commitment(rid, commitment(rid, bob, "117.95", salt_for(0)))


# --- phases ----------------------------------------------------------------


def test_phase_progression(breek, vm):
    contract, _ = breek
    rid = open_round(breek, vm)
    assert contract.get_phase(rid) == "ACCEPTING"
    warp_to(vm, DAY_START)
    assert contract.get_phase(rid) == "REVEALING"
    warp_to(vm, DAY_END - 1)
    assert contract.get_phase(rid) == "REVEALING"
    warp_to(vm, DAY_END)
    assert contract.get_phase(rid) == "AWAITING_SCORE"


def test_scoring_before_the_window_closes_is_rejected(breek, vm):
    contract, _ = breek
    rid = open_round(breek, vm)
    warp_to(vm, DAY_END - 1)
    with pytest.raises(Exception, match="WINDOW_NOT_CLOSED"):
        contract.score_round(rid)


# --- scoring ---------------------------------------------------------------


def test_round_scores_to_the_midpoint_of_two_feeds(breek, vm):
    contract, _ = breek
    rid = open_round(breek, vm)
    assert score(breek, vm, rid, a="117.88", b="117.96") == "SCORED:117.92000000"
    r = contract.get_round(rid)
    assert r["status"] == "SCORED"
    assert r["consensus"] == "117.92000000"
    assert r["phase"] == "SCORED"


def test_feeds_beyond_tolerance_void_the_round(breek, vm, bob):
    """Two feeds that disagree on the price cannot grade a forecast."""
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, bob, rid, "117.90")
    assert score(breek, vm, rid, a="100.00", b="130.00") == "VOID:SPREAD"
    r = contract.get_round(rid)
    assert r["status"] == "VOID_SPREAD"
    assert r["phase"] == "VOID"
    assert r["consensus"] == ""


def test_tolerance_boundary_is_exact(breek, vm, mod):
    contract, _ = breek
    # 50 bps apart on a 100.00 base is exactly the tolerance -> still priceable
    rid = open_round(breek, vm)
    assert mod._spread_bps(mod._dec_to_scaled("100.00"), mod._dec_to_scaled("100.50")) == 50
    assert score(breek, vm, rid, a="100.00", b="100.50").startswith("SCORED:")

    rid2 = open_round(breek, vm, window="2026-09-25")
    s2, e2 = day_window(2026, 9, 25)
    assert mod._spread_bps(mod._dec_to_scaled("100.00"), mod._dec_to_scaled("100.51")) == 51
    assert score(breek, vm, rid2, a="100.00", b="100.51", start=s2, end=e2,
                 at=e2 + HOUR) == "VOID:SPREAD"


def test_scoring_is_idempotent(breek, vm):
    contract, _ = breek
    rid = open_round(breek, vm)
    score(breek, vm, rid)
    with pytest.raises(Exception, match="ALREADY_SCORED"):
        contract.score_round(rid)


def test_transient_feed_failure_leaves_the_round_scoreable(breek, vm):
    contract, _ = breek
    rid = open_round(breek, vm)
    vm.clear_mocks()
    from tests.conftest import GATE_URL_RE
    vm.mock_web(GATE_URL_RE % "SOL", {"method": "GET", "status": 429, "body": "{}"})
    warp_to(vm, AFTER_CLOSE)
    with pytest.raises(Exception, match="TRANSIENT:HTTP_429"):
        contract.score_round(rid)
    assert contract.get_round(rid)["status"] == ""
    assert contract.get_phase(rid) == "AWAITING_SCORE"
    assert score(breek, vm, rid).startswith("SCORED:")


def test_one_fetch_per_source_per_round(breek, vm):
    """A round asks about one asset, so scoring is always two requests."""
    contract, _ = breek
    rid = open_round(breek, vm)
    calls = []
    vm.clear_mocks()
    mock_feeds(vm, "SOL", DAY_START, DAY_END, a_close="117.88", b_close="117.96")
    original = vm._match_web_mock

    def counting(url, method="GET"):
        calls.append(url)
        return original(url, method)

    vm._match_web_mock = counting
    warp_to(vm, AFTER_CLOSE)
    contract.score_round(rid)
    vm._match_web_mock = original
    assert len(calls) == 2, calls


# --- collecting ------------------------------------------------------------


def test_payout_is_proportional_to_accuracy_not_to_a_side(breek, vm, alice, bob, carol):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")   # closest
    enter(contract, vm, bob, rid, "118.40")     # middling
    enter(contract, vm, carol, rid, "117.20")   # furthest, still inside band
    score(breek, vm, rid, a="117.88", b="117.96")  # consensus 117.92

    payouts = {}
    for name, who in (("alice", alice), ("bob", bob), ("carol", carol)):
        vm.sender = who
        result = contract.collect(rid)
        payouts[name] = int(result.split(":")[1])
        assert result.endswith(":SCORED")

    # Everybody inside the band is paid something -- nobody "lost a side".
    assert all(v > 0 for v in payouts.values())
    assert payouts["alice"] > payouts["bob"] > payouts["carol"]
    assert sum(payouts.values()) <= int(contract.get_round(rid)["pot_wei"])


def test_an_entry_outside_the_band_collects_nothing(breek, vm, alice, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")
    enter(contract, vm, bob, rid, "300.00")  # way beyond the 10% cutoff
    score(breek, vm, rid, a="117.88", b="117.96")

    assert contract.get_entry(rid, hexaddr(bob))["outcome"] == "OUTSIDE_BAND"
    vm.sender = bob
    assert contract.collect(rid) == "COLLECTED:0:OUTSIDE_BAND"
    # and the accurate entrant still takes the whole pot
    vm.sender = alice
    assert int(contract.collect(rid).split(":")[1]) == 2 * ENTRY_FEE


def test_double_collect_is_rejected(breek, vm, alice):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")
    score(breek, vm, rid)
    vm.sender = alice
    contract.collect(rid)
    with pytest.raises(Exception, match="ALREADY_COLLECTED"):
        contract.collect(rid)


def test_collect_before_scoring_is_rejected(breek, vm, alice):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")
    vm.sender = alice
    with pytest.raises(Exception, match="NOT_SCORED"):
        contract.collect(rid)


def test_void_spread_refunds_every_entry_fee(breek, vm, alice, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")
    enter(contract, vm, bob, rid, "118.40")
    score(breek, vm, rid, a="100.00", b="130.00")
    for who in (alice, bob):
        vm.sender = who
        assert contract.collect(rid) == "COLLECTED:%d:REFUND_VOID_SPREAD" % ENTRY_FEE


def test_round_with_nobody_inside_the_band_refunds_everyone(breek, vm, alice, bob):
    """A pot no accuracy earned goes back rather than being handed out anyway."""
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "500.00")
    enter(contract, vm, bob, rid, "900.00")
    assert score(breek, vm, rid, a="117.88", b="117.96") == "VOID:NO_SCORES"
    assert contract.get_round(rid)["status"] == "VOID_NO_SCORES"
    for who in (alice, bob):
        vm.sender = who
        assert contract.collect(rid).endswith(":REFUND_VOID_NO_SCORES")


def test_expiry_refunds_with_zero_http(breek, vm, alice, bob):
    """Past expiry the contract must not touch the network at all.

    No web mocks are registered and strict_mocks is on, so any outbound request
    would raise.
    """
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")
    enter(contract, vm, bob, rid, "118.40")

    vm.clear_mocks()
    vm.strict_mocks = True
    warp_to(vm, EXPIRED)
    assert contract.score_round(rid) == "VOID:EXPIRED"
    assert contract.get_round(rid)["status"] == "VOID_EXPIRED"
    for who in (alice, bob):
        vm.sender = who
        assert contract.collect(rid).endswith(":REFUND_VOID_EXPIRED")
    vm.strict_mocks = False


# --- leaderboard and views -------------------------------------------------


def test_leaderboard_hides_forecasts_until_the_round_is_scored(breek, vm, alice, bob):
    """Publishing live numbers would let a late entrant copy the crowd."""
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")
    enter(contract, vm, bob, rid, "118.40")

    board = contract.get_leaderboard(rid, 10)
    assert len(board["entries"]) == 2
    assert all(row["forecast"] == "" for row in board["entries"])

    score(breek, vm, rid, a="117.88", b="117.96")
    board = contract.get_leaderboard(rid, 10)
    assert board["consensus"] == "117.92000000"
    assert [row["who"] for row in board["entries"]] == [hexaddr(alice), hexaddr(bob)]
    assert all(row["forecast"] != "" for row in board["entries"])
    # ordered by accuracy, best first
    errors = [int(row["error_bps"]) for row in board["entries"]]
    assert errors == sorted(errors)


def test_catalog_describes_the_contest_not_a_market(breek, vm):
    contract, _ = breek
    cat = contract.get_catalog()
    assert cat["entry_fee_wei"] == str(ENTRY_FEE)
    assert cat["tolerance_bps"] == "50"
    assert cat["score_cutoff_bps"] == "1000"
    by_key = {c["key"]: c for c in cat["categories"]}
    assert by_key["CRYPTO"]["priceable"] is True
    assert by_key["DOMINANCE"]["priceable"] is False


def test_list_rounds_is_newest_first_and_paginated(breek, vm):
    contract, _ = breek
    warp_to(vm, BEFORE)
    ids = [
        int(contract.open_round("CRYPTO", "SOL", "DAILY", d).split(":")[1])
        for d in ("2026-09-24", "2026-09-25", "2026-09-26")
    ]
    page = contract.list_rounds(0, 2)
    assert page["total"] == "3"
    assert [r["round_id"] for r in page["rounds"]] == [str(ids[2]), str(ids[1])]


def test_list_scoreable_only_shows_ready_rounds(breek, vm):
    contract, _ = breek
    rid = open_round(breek, vm)
    assert contract.list_scoreable(10)["rounds"] == []
    warp_to(vm, AFTER_CLOSE)
    assert [r["round_id"] for r in contract.list_scoreable(10)["rounds"]] == [str(rid)]
    score(breek, vm, rid)
    assert contract.list_scoreable(10)["rounds"] == []


def test_list_entries_returns_my_rounds(breek, vm, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, bob, rid, "118.40")

    out = contract.list_entries(hexaddr(bob), 10)
    assert len(out["entries"]) == 1
    # Sealed even to the entrant's own listing, because this view answers for
    # any address and must not behave differently depending on who asks.
    assert out["entries"][0]["entry"]["forecast"] == ""
    assert out["entries"][0]["entry"]["revealed"] is False

    reveal_all(contract, vm, rid)
    out = contract.list_entries(hexaddr(bob), 10)
    assert out["entries"][0]["entry"]["forecast"] == "118.40000000"


def test_stats_track_the_contest(breek, vm, alice, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, alice, rid, "117.95")
    enter(contract, vm, bob, rid, "118.40")
    score(breek, vm, rid)
    stats = contract.get_stats()
    assert stats["rounds"] == "1"
    assert stats["scored"] == "1"
    assert stats["void"] == "0"
    assert stats["entries"] == "2"


def test_weekly_round_scores_over_168_hours(breek, vm):
    contract, _ = breek
    rid = open_round(breek, vm, window=WEEK_ID, timeframe="WEEKLY")
    assert score(breek, vm, rid, a="111.04", b="110.95", start=WEEK_START,
                 end=WEEK_END, at=WEEK_END + HOUR).startswith("SCORED:")


def test_addresses_are_lowercase_hex(breek, vm, bob):
    contract, _ = breek
    rid = open_round(breek, vm)
    enter(contract, vm, bob, rid, "118.40")
    opener = contract.get_round(rid)["opener"]
    assert opener == opener.lower() and len(opener) == 42
