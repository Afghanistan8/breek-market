"""Agreed-payload re-derivation.

The string returned by the equivalence block is data, never an instruction.
``_parse_agreed`` re-checks every field against the market it is settling and
recomputes both verdicts and the final result from the series. These tests hand
it payloads that are internally plausible but wrong, and require every one to be
rejected with an ``INVARIANT:`` error.
"""

import pytest

from tests.conftest import DAY, GEN, HOUR, day_window, mock_asset, warp_to

DAY_ID = "2026-09-24"
DAY_START, DAY_END = day_window(2026, 9, 24)
BEFORE = DAY_START - 2 * DAY
AFTER_CLOSE = DAY_END + HOUR

DIR_GOOD = (
    "v1|DIR_DAILY|CRYPTO|SOL|DAILY|gate.io|coingecko|2026-09-24"
    "|SOL:115.15000000:116.61000000|UP"
    "|SOL:115.09859487:116.55383196|UP"
    "|UP"
)
REL_GOOD = (
    "v1|REL_DAILY|CRYPTO||DAILY|gate.io|coingecko|2026-09-24"
    "|SOL:115.15000000:116.61000000,ETH:2690.25000000:2685.52000000,"
    "NEAR:4.32500000:4.58300000|NEAR"
    "|SOL:115.09859487:116.55383196,ETH:2689.53060195:2684.27783801,"
    "NEAR:4.32873039:4.58129904|NEAR"
    "|NEAR"
)


def make_market(breek, vm, kind="DIR_DAILY", asset="SOL"):
    """Create a market and hand back (market_record, symbols, parse_fn)."""
    contract, mod = breek
    warp_to(vm, BEFORE)
    res = contract.create_market(kind, "CRYPTO", asset, "DAILY", DAY_ID)
    mid = int(res.split(":")[1])
    record = contract.markets[mid]
    symbols = (asset,) if asset else ("SOL", "ETH", "NEAR")
    return record, symbols, contract._parse_agreed


def swap(payload: str, index: int, value: str) -> str:
    parts = payload.split("|")
    parts[index] = value
    return "|".join(parts)


# --- the good payloads must be accepted -----------------------------------


def test_direction_payload_accepted(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    assert parse(DIR_GOOD, record, symbols) == "UP"


def test_relative_payload_accepted(breek, vm):
    record, symbols, parse = make_market(breek, vm, kind="REL_DAILY", asset="")
    assert parse(REL_GOOD, record, symbols) == "NEAR"


# --- structural checks -----------------------------------------------------


def test_field_count_enforced(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    for bad in [DIR_GOOD + "|extra", "|".join(DIR_GOOD.split("|")[:-1]), "", "v1"]:
        with pytest.raises(Exception, match="INVARIANT:FIELD_COUNT"):
            parse(bad, record, symbols)


def test_version_enforced(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:VERSION"):
        parse(swap(DIR_GOOD, 0, "v2"), record, symbols)


# --- binding to THIS market ------------------------------------------------


def test_payload_for_another_kind_rejected(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:MARKET_BINDING"):
        parse(swap(DIR_GOOD, 1, "REL_DAILY"), record, symbols)


def test_payload_for_another_asset_rejected(breek, vm):
    """A correct ETH settlement must not settle a SOL market."""
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:MARKET_BINDING"):
        parse(swap(DIR_GOOD, 3, "ETH"), record, symbols)


def test_payload_for_another_category_rejected(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:MARKET_BINDING"):
        parse(swap(DIR_GOOD, 2, "DOMINANCE"), record, symbols)


def test_payload_for_another_window_rejected(breek, vm):
    """Settling today's market with yesterday's window is the classic replay."""
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:WINDOW_BINDING"):
        parse(swap(DIR_GOOD, 7, "2026-09-23"), record, symbols)


def test_payload_for_another_timeframe_rejected(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:WINDOW_BINDING"):
        parse(swap(DIR_GOOD, 4, "WEEKLY"), record, symbols)


def test_payload_must_name_both_expected_sources(breek, vm):
    """A result derived from some other feed cannot be smuggled in."""
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:SOURCE_BINDING"):
        parse(swap(DIR_GOOD, 5, "binance"), record, symbols)
    with pytest.raises(Exception, match="INVARIANT:SOURCE_BINDING"):
        parse(swap(DIR_GOOD, 6, "gate.io"), record, symbols)


def test_single_source_payload_rejected(breek, vm):
    """Naming the same feed twice is not two sources."""
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:SOURCE_BINDING"):
        parse(swap(swap(DIR_GOOD, 5, "gate.io"), 6, "gate.io"), record, symbols)


# --- forged verdicts -------------------------------------------------------


def test_forged_a_verdict_rejected(breek, vm):
    """Series says UP, verdict claims DOWN."""
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:A_VERDICT"):
        parse(swap(DIR_GOOD, 9, "DOWN"), record, symbols)


def test_forged_b_verdict_rejected(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:B_VERDICT"):
        parse(swap(DIR_GOOD, 11, "DOWN"), record, symbols)


def test_forged_final_rejected(breek, vm):
    """Both verdicts UP, final claims DOWN."""
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:FINAL"):
        parse(swap(DIR_GOOD, 12, "DOWN"), record, symbols)


def test_final_cannot_override_a_disagreement(breek, vm):
    """A=UP, B=DOWN must be INCONCLUSIVE; claiming UP is rejected."""
    record, symbols, parse = make_market(breek, vm)
    forged = swap(DIR_GOOD, 10, "SOL:200.00000000:100.00000000")
    forged = swap(forged, 11, "DOWN")
    with pytest.raises(Exception, match="INVARIANT:FINAL"):
        parse(swap(forged, 12, "UP"), record, symbols)
    # ... and stated honestly it settles as INCONCLUSIVE
    assert parse(swap(forged, 12, "INCONCLUSIVE"), record, symbols) == "INCONCLUSIVE"


def test_forged_relative_winner_rejected(breek, vm):
    """SOL is not the strongest asset in this series; saying so must not stick."""
    record, symbols, parse = make_market(breek, vm, kind="REL_DAILY", asset="")
    with pytest.raises(Exception, match="INVARIANT:A_VERDICT"):
        parse(swap(REL_GOOD, 9, "SOL"), record, symbols)
    with pytest.raises(Exception, match="INVARIANT:B_VERDICT"):
        parse(swap(REL_GOOD, 11, "SOL"), record, symbols)


def test_winner_outside_catalog_rejected(breek, vm):
    """An off-catalog winner cannot survive even with matching verdict fields."""
    record, symbols, parse = make_market(breek, vm, kind="REL_DAILY", asset="")
    forged = swap(swap(swap(REL_GOOD, 9, "DOGE"), 11, "DOGE"), 12, "DOGE")
    with pytest.raises(Exception, match="INVARIANT:A_VERDICT"):
        parse(forged, record, symbols)


def test_direction_market_cannot_settle_to_a_symbol(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    forged = swap(swap(swap(DIR_GOOD, 9, "SOL"), 11, "SOL"), 12, "SOL")
    with pytest.raises(Exception, match="INVARIANT:A_VERDICT"):
        parse(forged, record, symbols)


def test_tie_cannot_be_promoted_to_a_winner(breek, vm):
    record, symbols, parse = make_market(breek, vm, kind="REL_DAILY", asset="")
    tied = (
        "SOL:100.00000000:110.00000000,ETH:200.00000000:220.00000000,"
        "NEAR:4.00000000:4.01000000"
    )
    forged = swap(swap(REL_GOOD, 8, tied), 10, tied)
    # Honest: both sides TIE -> INCONCLUSIVE
    honest = swap(swap(swap(forged, 9, "TIE"), 11, "TIE"), 12, "INCONCLUSIVE")
    assert parse(honest, record, symbols) == "INCONCLUSIVE"
    # Forged: claim SOL won anyway
    with pytest.raises(Exception, match="INVARIANT:A_VERDICT"):
        parse(swap(swap(swap(forged, 9, "SOL"), 11, "SOL"), 12, "SOL"), record, symbols)


# --- series integrity ------------------------------------------------------


def test_series_must_match_catalog_length_and_order(breek, vm):
    record, symbols, parse = make_market(breek, vm, kind="REL_DAILY", asset="")
    short = "SOL:1.0:2.0,ETH:1.0:2.0"
    with pytest.raises(Exception, match="INVARIANT:SERIES_LENGTH"):
        parse(swap(REL_GOOD, 8, short), record, symbols)
    reordered = (
        "ETH:2690.25000000:2685.52000000,SOL:115.15000000:116.61000000,"
        "NEAR:4.32500000:4.58300000"
    )
    with pytest.raises(Exception, match="INVARIANT:SERIES_SYMBOL_ORDER"):
        parse(swap(REL_GOOD, 8, reordered), record, symbols)


def test_non_positive_prices_rejected(breek, vm):
    record, symbols, parse = make_market(breek, vm)
    with pytest.raises(Exception, match="INVARIANT:NON_POSITIVE_OPEN"):
        parse(swap(DIR_GOOD, 8, "SOL:0.00000000:116.61000000"), record, symbols)
    with pytest.raises(Exception, match="INVARIANT:NON_POSITIVE_CLOSE"):
        parse(swap(DIR_GOOD, 8, "SOL:115.15000000:0.00000000"), record, symbols)


def test_decimal_spelling_does_not_change_the_verdict(breek, vm):
    """Trailing zeros are cosmetic; the re-derivation must not care."""
    record, symbols, parse = make_market(breek, vm)
    terse = swap(DIR_GOOD, 8, "SOL:115.15:116.61")
    assert parse(terse, record, symbols) == "UP"


# --- end-to-end: a forged payload cannot settle a real market -------------


def test_resolve_persists_the_payload_it_verified(breek, vm):
    contract, mod = breek
    warp_to(vm, BEFORE)
    mid = int(contract.create_market(
        "DIR_DAILY", "CRYPTO", "SOL", "DAILY", DAY_ID).split(":")[1])
    vm.clear_mocks()
    mock_asset(vm, "SOL", DAY_START, DAY_END, a_open="115.15", a_close="116.61")
    warp_to(vm, AFTER_CLOSE)
    contract.resolve_market(mid)
    stored = contract.get_evidence(mid)["payload"]
    # The stored evidence must itself survive re-derivation.
    record = contract.markets[mid]
    assert contract._parse_agreed(stored, record, ("SOL",)) == "UP"
