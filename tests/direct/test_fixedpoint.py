"""Decimal -> PRICE_SCALE conversion, bps, and series encoding.

No float ever reaches a price. These tests pin that the same numeric value spelt
different ways lands on the same integer, and that anything ambiguous is
rejected rather than silently mis-scaled.
"""

import pytest

SCALE = 10**8


def test_trailing_zeros_are_irrelevant(mod):
    """The case the brief calls out by name."""
    assert mod._dec_to_scaled("80494.31000000") == mod._dec_to_scaled("80494.31")
    assert mod._dec_to_scaled("4.325") == mod._dec_to_scaled("4.32500000")
    assert mod._dec_to_scaled("100") == mod._dec_to_scaled("100.0") == 100 * SCALE


def test_known_scalings(mod):
    assert mod._dec_to_scaled("1") == SCALE
    assert mod._dec_to_scaled("0.5") == SCALE // 2
    assert mod._dec_to_scaled("115.15") == 11515000000
    assert mod._dec_to_scaled("2690.25") == 269025000000
    assert mod._dec_to_scaled("0.00000001") == 1


def test_leading_plus_and_leading_dot(mod):
    assert mod._dec_to_scaled("+12.5") == mod._dec_to_scaled("12.5")
    assert mod._dec_to_scaled(".25") == SCALE // 4
    assert mod._dec_to_scaled("  7.5  ") == mod._dec_to_scaled("7.5")


def test_excess_precision_truncates_not_rounds(mod):
    """Rounding up a price could flip a verdict; truncation is deterministic."""
    assert mod._dec_to_scaled("1.999999999") == mod._dec_to_scaled("1.99999999")
    assert mod._dec_to_scaled("1.000000009") == SCALE


def test_rejects_negative_and_exponent(mod):
    with pytest.raises(Exception, match="NEGATIVE_PRICE"):
        mod._dec_to_scaled("-1.0")
    for bad in ["1e5", "1E5", "1.2e-05"]:
        with pytest.raises(Exception, match="EXPONENT_NOTATION"):
            mod._dec_to_scaled(bad)


def test_rejects_malformed(mod):
    with pytest.raises(Exception, match="EMPTY_NUMBER"):
        mod._dec_to_scaled("   ")
    for bad in ["1.2.3", "12a", "1,2", "--1", "abc"]:
        with pytest.raises(Exception, match="MALFORMED_NUMBER|NEGATIVE_PRICE"):
            mod._dec_to_scaled(bad)


def test_scaled_to_dec_roundtrips(mod):
    for text in ["1", "0.5", "115.15", "2690.25", "0.00000001", "99999.12345678"]:
        scaled = mod._dec_to_scaled(text)
        assert mod._dec_to_scaled(mod._scaled_to_dec(scaled)) == scaled


def test_scaled_to_dec_pads_fraction(mod):
    assert mod._scaled_to_dec(SCALE) == "1.00000000"
    assert mod._scaled_to_dec(1) == "0.00000001"


def test_json_number_to_scaled_accepts_string_and_int(mod):
    """json.loads(..., parse_float=str) hands floats over as decimal text."""
    assert mod._json_number_to_scaled("115.0985948771") == mod._dec_to_scaled("115.09859487")
    assert mod._json_number_to_scaled(4) == 4 * SCALE


def test_json_number_to_scaled_rejects_bool_and_null(mod):
    for bad in [True, False, None, [], {}]:
        with pytest.raises(Exception, match="NOT_A_NUMBER"):
            mod._json_number_to_scaled(bad)


def test_bps_basics(mod):
    assert mod._bps(100 * SCALE, 100 * SCALE) == 0
    assert mod._bps(100 * SCALE, 101 * SCALE) == 100
    assert mod._bps(100 * SCALE, 99 * SCALE) == -100
    assert mod._bps(100 * SCALE, 200 * SCALE) == 10000


def test_bps_matches_live_probe(mod):
    """Numbers lifted from the committed live probe for 2026-09-24."""
    assert mod._bps(mod._dec_to_scaled("115.15"), mod._dec_to_scaled("116.61")) == 126
    assert mod._bps(mod._dec_to_scaled("2690.25"), mod._dec_to_scaled("2685.52")) == -18
    assert mod._bps(mod._dec_to_scaled("4.325"), mod._dec_to_scaled("4.583")) == 596


def test_bps_rejects_non_positive_open(mod):
    for bad_open in [0, -1]:
        with pytest.raises(Exception, match="NON_POSITIVE_OPEN"):
            mod._bps(bad_open, SCALE)


def test_series_encode_decode_roundtrip(mod):
    symbols = ("SOL", "ETH", "NEAR")
    series = {
        "SOL": (mod._dec_to_scaled("115.15"), mod._dec_to_scaled("116.61")),
        "ETH": (mod._dec_to_scaled("2690.25"), mod._dec_to_scaled("2685.52")),
        "NEAR": (mod._dec_to_scaled("4.325"), mod._dec_to_scaled("4.583")),
    }
    raw = mod._encode_series(symbols, series)
    assert raw.startswith("SOL:115.15000000:116.61000000,")
    assert mod._decode_series(symbols, raw) == series


def test_series_decode_enforces_catalog_order(mod):
    symbols = ("SOL", "ETH", "NEAR")
    good = "SOL:1.0:2.0,ETH:1.0:2.0,NEAR:1.0:2.0"
    assert len(mod._decode_series(symbols, good)) == 3
    with pytest.raises(Exception, match="SERIES_SYMBOL_ORDER"):
        mod._decode_series(symbols, "ETH:1.0:2.0,SOL:1.0:2.0,NEAR:1.0:2.0")


def test_series_decode_enforces_length_and_shape(mod):
    symbols = ("SOL", "ETH", "NEAR")
    with pytest.raises(Exception, match="SERIES_LENGTH"):
        mod._decode_series(symbols, "SOL:1.0:2.0,ETH:1.0:2.0")
    with pytest.raises(Exception, match="SERIES_SHAPE"):
        mod._decode_series(("SOL",), "SOL:1.0")


def test_series_decode_rejects_non_positive_prices(mod):
    with pytest.raises(Exception, match="NON_POSITIVE_OPEN"):
        mod._decode_series(("SOL",), "SOL:0.0:2.0")
    with pytest.raises(Exception, match="NON_POSITIVE_CLOSE"):
        mod._decode_series(("SOL",), "SOL:1.0:0.0")
