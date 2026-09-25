"""The contest maths: consensus pricing, error, accuracy weight.

This is what replaces a prediction market's verdict logic. There is no side to
win, so nothing here produces UP/DOWN or a winner -- it produces a price and a
distance from it.
"""

import pytest

SCALE = 10**8


def px(mod, text):
    return mod._dec_to_scaled(text)


# --- spread between the two feeds -----------------------------------------


def test_spread_is_zero_when_feeds_match(mod):
    assert mod._spread_bps(100 * SCALE, 100 * SCALE) == 0


def test_spread_is_relative_to_the_lower_feed(mod):
    # 1% apart
    assert mod._spread_bps(100 * SCALE, 101 * SCALE) == 100
    # order must not matter
    assert mod._spread_bps(101 * SCALE, 100 * SCALE) == 100


def test_spread_matches_live_probe_numbers(mod):
    """Gate 115.15 vs CoinGecko 115.09859487 on 2026-09-24: well inside band."""
    spread = mod._spread_bps(px(mod, "115.15"), px(mod, "115.09859487"))
    assert spread == 4
    assert spread <= mod.TOLERANCE_BPS


def test_spread_rejects_non_positive(mod):
    for bad in [(0, SCALE), (SCALE, 0)]:
        with pytest.raises(Exception, match="NON_POSITIVE_PRICE"):
            mod._spread_bps(*bad)


# --- consensus price -------------------------------------------------------


def test_consensus_is_the_midpoint(mod):
    assert mod._consensus_of(100 * SCALE, 102 * SCALE) == 101 * SCALE


def test_consensus_is_order_independent(mod):
    a, b = px(mod, "115.15"), px(mod, "115.09859487")
    assert mod._consensus_of(a, b) == mod._consensus_of(b, a)


def test_consensus_floors_odd_sums(mod):
    """Integer maths only; a half-unit rounds down deterministically."""
    assert mod._consensus_of(1, 2) == 1


# --- error -----------------------------------------------------------------


def test_perfect_call_has_zero_error(mod):
    assert mod._error_bps(100 * SCALE, 100 * SCALE) == 0


def test_error_is_absolute(mod):
    """Over and under by the same amount score identically."""
    high = mod._error_bps(101 * SCALE, 100 * SCALE)
    low = mod._error_bps(99 * SCALE, 100 * SCALE)
    assert high == low == 100


def test_error_scales_with_distance(mod):
    assert mod._error_bps(110 * SCALE, 100 * SCALE) == 1000
    assert mod._error_bps(200 * SCALE, 100 * SCALE) == 10000


def test_error_rejects_non_positive_consensus(mod):
    with pytest.raises(Exception, match="NON_POSITIVE_CONSENSUS"):
        mod._error_bps(SCALE, 0)


# --- accuracy weight -------------------------------------------------------


def test_perfect_call_takes_the_maximum_weight(mod):
    assert mod._accuracy_weight(0) == mod.SCORE_CUTOFF_BPS


def test_weight_decays_linearly(mod):
    cutoff = mod.SCORE_CUTOFF_BPS
    assert mod._accuracy_weight(1) == cutoff - 1
    assert mod._accuracy_weight(cutoff // 2) == cutoff - cutoff // 2


def test_weight_is_zero_at_and_beyond_the_cutoff(mod):
    """A wild guess must not dilute the people who were close."""
    cutoff = mod.SCORE_CUTOFF_BPS
    assert mod._accuracy_weight(cutoff) == 0
    assert mod._accuracy_weight(cutoff + 1) == 0
    assert mod._accuracy_weight(10_000_000) == 0


def test_closer_always_scores_strictly_higher(mod):
    """The ordering property the whole contest rests on."""
    previous = None
    for error in range(0, mod.SCORE_CUTOFF_BPS, 37):
        weight = mod._accuracy_weight(error)
        if previous is not None:
            assert weight < previous
        previous = weight


def test_payout_shares_are_proportional_to_accuracy(mod):
    """Worked example: three entrants, one pot, no winning side involved."""
    consensus = px(mod, "117.92")
    pot = 3 * 10**18

    forecasts = {
        "near": px(mod, "117.95"),
        "ok": px(mod, "118.40"),
        "far": px(mod, "116.10"),
    }
    weights = {
        name: mod._accuracy_weight(mod._error_bps(f, consensus))
        for name, f in forecasts.items()
    }
    total = sum(weights.values())
    payouts = {name: (pot * w) // total for name, w in weights.items()}

    # Everyone inside the band is paid; closer is paid more.
    assert payouts["near"] > payouts["ok"] > payouts["far"] > 0
    # Nothing is created out of thin air.
    assert sum(payouts.values()) <= pot


def test_an_entry_outside_the_band_earns_nothing_and_takes_no_share(mod):
    consensus = 100 * SCALE
    inside = mod._accuracy_weight(mod._error_bps(101 * SCALE, consensus))
    outside = mod._accuracy_weight(mod._error_bps(300 * SCALE, consensus))
    assert outside == 0
    assert inside > 0
    # The outside entry contributes zero to the denominator, so it cannot
    # reduce what the accurate entrant receives.
    assert (10**18 * inside) // (inside + outside) == 10**18
