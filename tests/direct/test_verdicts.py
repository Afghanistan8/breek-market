"""Verdict maths: direction, relative winner, and how two sources combine.

The central guarantee is here: one source can never produce a direction or a
winner, and a TIE can never produce a winner.
"""

import pytest

SCALE = 10**8


def px(text, mod):
    return mod._dec_to_scaled(text)


# --- direction -------------------------------------------------------------


def test_direction_up_and_down(mod):
    assert mod._direction_verdict(100 * SCALE, 101 * SCALE) == "UP"
    assert mod._direction_verdict(100 * SCALE, 99 * SCALE) == "DOWN"


def test_direction_flat_is_down(mod):
    """Flat resolves DOWN by design; a market never settles 'unchanged'."""
    assert mod._direction_verdict(100 * SCALE, 100 * SCALE) == "DOWN"


def test_direction_one_smallest_unit_decides(mod):
    assert mod._direction_verdict(100 * SCALE, 100 * SCALE + 1) == "UP"
    assert mod._direction_verdict(100 * SCALE, 100 * SCALE - 1) == "DOWN"


# --- relative --------------------------------------------------------------


def test_relative_picks_strictly_greatest_bps(mod):
    symbols = ("SOL", "ETH", "NEAR")
    series = {
        "SOL": (100 * SCALE, 101 * SCALE),   # +100 bps
        "ETH": (100 * SCALE, 100 * SCALE),   #    0 bps
        "NEAR": (100 * SCALE, 105 * SCALE),  # +500 bps
    }
    assert mod._relative_verdict(symbols, series) == "NEAR"


def test_relative_winner_can_be_the_least_bad(mod):
    """Every asset down still has a winner: the smallest loss."""
    symbols = ("SOL", "ETH", "NEAR")
    series = {
        "SOL": (100 * SCALE, 90 * SCALE),
        "ETH": (100 * SCALE, 99 * SCALE),
        "NEAR": (100 * SCALE, 80 * SCALE),
    }
    assert mod._relative_verdict(symbols, series) == "ETH"


def test_relative_exact_tie_is_tie(mod):
    symbols = ("SOL", "ETH", "NEAR")
    series = {
        "SOL": (100 * SCALE, 105 * SCALE),
        "ETH": (200 * SCALE, 210 * SCALE),  # same +500 bps
        "NEAR": (100 * SCALE, 101 * SCALE),
    }
    assert mod._relative_verdict(symbols, series) == "TIE"


def test_relative_tie_detected_even_when_leader_seen_first(mod):
    """A later equal score must still poison an already-chosen leader."""
    symbols = ("SOL", "ETH")
    series = {"SOL": (100 * SCALE, 110 * SCALE), "ETH": (10 * SCALE, 11 * SCALE)}
    assert mod._relative_verdict(symbols, series) == "TIE"


def test_relative_all_flat_is_tie(mod):
    symbols = ("SOL", "ETH", "NEAR")
    series = {s: (100 * SCALE, 100 * SCALE) for s in symbols}
    assert mod._relative_verdict(symbols, series) == "TIE"


def test_relative_single_asset_never_ties(mod):
    assert mod._relative_verdict(("SOL",), {"SOL": (100 * SCALE, 90 * SCALE)}) == "SOL"


# --- combining two sources -------------------------------------------------


def test_agreement_settles(mod):
    assert mod._combine("UP", "UP") == "UP"
    assert mod._combine("DOWN", "DOWN") == "DOWN"
    assert mod._combine("NEAR", "NEAR") == "NEAR"


def test_disagreement_is_inconclusive(mod):
    assert mod._combine("UP", "DOWN") == "INCONCLUSIVE"
    assert mod._combine("DOWN", "UP") == "INCONCLUSIVE"


def test_different_relative_winners_is_inconclusive(mod):
    assert mod._combine("SOL", "NEAR") == "INCONCLUSIVE"
    assert mod._combine("NEAR", "ETH") == "INCONCLUSIVE"


def test_tie_on_either_side_can_never_produce_a_winner(mod):
    assert mod._combine("TIE", "TIE") == "INCONCLUSIVE"
    assert mod._combine("TIE", "NEAR") == "INCONCLUSIVE"
    assert mod._combine("NEAR", "TIE") == "INCONCLUSIVE"


def test_empty_verdict_can_never_settle(mod):
    """A single source that produced nothing must not carry the result."""
    assert mod._combine("", "UP") == "INCONCLUSIVE"
    assert mod._combine("UP", "") == "INCONCLUSIVE"
    assert mod._combine("", "") == "INCONCLUSIVE"


def test_inconclusive_is_absorbing(mod):
    assert mod._combine("INCONCLUSIVE", "UP") == "INCONCLUSIVE"
    assert mod._combine("UP", "INCONCLUSIVE") == "INCONCLUSIVE"


@pytest.mark.parametrize("verdict", ["UP", "DOWN", "SOL", "ETH", "NEAR"])
def test_a_single_source_never_decides(mod, verdict):
    """Whatever one source says, the other must say the same or it is void."""
    assert mod._combine(verdict, "") == "INCONCLUSIVE"
    assert mod._combine("", verdict) == "INCONCLUSIVE"
    assert mod._combine(verdict, "TIE") == "INCONCLUSIVE"
