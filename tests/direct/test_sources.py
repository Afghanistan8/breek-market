"""Source parsers.

Source A (Gate.io) must rebuild a GMT+1 window from hourly candle OPEN TIMES,
not array positions, and must refuse an incomplete or still-open window.
Source B (CoinGecko) must select the samples at exactly the two window instants,
so it can never compare a 23h sample against a 24h close.
"""

import json

import pytest

from tests.conftest import (
    CG_URL_RE,
    GATE_URL_RE,
    HOUR,
    cg_body,
    day_window,
    gate_body,
    week_window,
)

SCALE = 10**8
DAY_START, DAY_END = day_window(2026, 9, 24)
WEEK_START, WEEK_END = week_window(2026, 9, 14)


def mock_gate(vm, symbol, body, status=200):
    vm.mock_web(GATE_URL_RE % symbol, {"method": "GET", "status": status, "body": body})


def mock_cg(vm, slug, body, status=200):
    vm.mock_web(CG_URL_RE % slug, {"method": "GET", "status": status, "body": body})


# --- Gate.io ---------------------------------------------------------------


def test_gate_reads_first_open_and_last_close(breek, vm, mod):
    mock_gate(vm, "SOL", gate_body(DAY_START, DAY_END, "115.15", "116.61"))
    assert mod._fetch_gate("SOL", DAY_START, DAY_END) == (
        mod._dec_to_scaled("115.15"),
        mod._dec_to_scaled("116.61"),
    )


def test_gate_selects_by_timestamp_not_position(breek, vm, mod):
    """Reversing the array must not change the result."""
    forward = gate_body(DAY_START, DAY_END, "115.15", "116.61")
    backward = gate_body(DAY_START, DAY_END, "115.15", "116.61", reverse=True)
    assert json.loads(forward) != json.loads(backward)
    mock_gate(vm, "SOL", forward)
    a = mod._fetch_gate("SOL", DAY_START, DAY_END)
    vm.clear_mocks()
    mock_gate(vm, "SOL", backward)
    assert mod._fetch_gate("SOL", DAY_START, DAY_END) == a


def test_gate_weekly_expects_168_candles(breek, vm, mod):
    mock_gate(vm, "SOL", gate_body(WEEK_START, WEEK_END, "99.73", "111.04"))
    assert len(json.loads(gate_body(WEEK_START, WEEK_END, "1", "2"))) == 168
    assert mod._fetch_gate("SOL", WEEK_START, WEEK_END) == (
        mod._dec_to_scaled("99.73"),
        mod._dec_to_scaled("111.04"),
    )


def test_gate_rejects_short_window(breek, vm, mod):
    """A missing hour changes the count, which is caught before anything else."""
    mock_gate(vm, "SOL", gate_body(DAY_START, DAY_END, "1", "2", drop_hour=5))
    with pytest.raises(Exception, match="GATE_CANDLE_COUNT"):
        mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_rejects_still_open_candle(breek, vm, mod):
    """An unclosed final candle would settle on a partial window."""
    mock_gate(vm, "SOL", gate_body(DAY_START, DAY_END, "1", "2", all_closed=False))
    with pytest.raises(Exception, match="GATE_CANDLE_OPEN"):
        mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_rejects_unaligned_timestamp(breek, vm, mod):
    mock_gate(vm, "SOL", gate_body(DAY_START, DAY_END, "1", "2", unaligned=True))
    with pytest.raises(Exception, match="GATE_TS_UNALIGNED"):
        mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_rejects_wrong_window_offset(breek, vm, mod):
    """Candles for a UTC day are one hour off a GMT+1 day and must be refused."""
    utc_start = DAY_START + HOUR
    mock_gate(vm, "SOL", gate_body(utc_start, utc_start + 86400, "1", "2"))
    with pytest.raises(Exception, match="GATE_MISSING_HOUR"):
        mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_rejects_row_shape(breek, vm, mod):
    rows = [[str(DAY_START + i * HOUR), "1", "2"] for i in range(24)]
    mock_gate(vm, "SOL", json.dumps(rows))
    with pytest.raises(Exception, match="GATE_ROW_SHAPE"):
        mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_transient_on_429_and_5xx(breek, vm, mod):
    for status in (429, 500, 502, 503):
        vm.clear_mocks()
        mock_gate(vm, "SOL", "{}", status=status)
        with pytest.raises(Exception, match="TRANSIENT:HTTP_%d" % status):
            mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_external_on_4xx(breek, vm, mod):
    for status in (400, 403, 404):
        vm.clear_mocks()
        mock_gate(vm, "SOL", "{}", status=status)
        with pytest.raises(Exception, match="EXTERNAL:HTTP_%d" % status):
            mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_rejects_bad_json(breek, vm, mod):
    mock_gate(vm, "SOL", "not json at all")
    with pytest.raises(Exception, match="BAD_JSON"):
        mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_rejects_oversized_body(breek, vm, mod):
    mock_gate(vm, "SOL", "[" + "0," * 40000 + "0]")
    with pytest.raises(Exception, match="BODY_TOO_LARGE"):
        mod._fetch_gate("SOL", DAY_START, DAY_END)


def test_gate_unknown_symbol(breek, vm, mod):
    with pytest.raises(Exception, match="NO_GATE_PAIR_BTC"):
        mod._fetch_gate("BTC", DAY_START, DAY_END)


# --- CoinGecko -------------------------------------------------------------


def test_coingecko_reads_exact_window_instants(breek, vm, mod):
    mock_cg(vm, "solana", cg_body(DAY_START, DAY_END, "115.0985948771", "116.5538319674"))
    open_, close = mod._fetch_coingecko("SOL", DAY_START, DAY_END)
    assert open_ == mod._dec_to_scaled("115.09859487")
    assert close == mod._dec_to_scaled("116.55383196")


def test_coingecko_ignores_neighbouring_samples(breek, vm, mod):
    """Filler samples sit at 50.5; picking one would be a completely different price."""
    mock_cg(vm, "solana", cg_body(DAY_START, DAY_END, "115.15", "116.61"))
    open_, close = mod._fetch_coingecko("SOL", DAY_START, DAY_END)
    assert open_ == mod._dec_to_scaled("115.15")
    assert close == mod._dec_to_scaled("116.61")


def test_coingecko_requires_sample_at_window_start(breek, vm, mod):
    mock_cg(vm, "solana", cg_body(DAY_START, DAY_END, "1", "2", omit_start=True))
    with pytest.raises(Exception, match="CG_NO_SAMPLE_AT_START"):
        mod._fetch_coingecko("SOL", DAY_START, DAY_END)


def test_coingecko_requires_sample_at_window_end(breek, vm, mod):
    """This is the guard that stops a 23h sample standing in for a 24h close."""
    mock_cg(vm, "solana", cg_body(DAY_START, DAY_END, "1", "2", omit_end=True))
    with pytest.raises(Exception, match="CG_NO_SAMPLE_AT_END"):
        mod._fetch_coingecko("SOL", DAY_START, DAY_END)


def test_coingecko_accepts_integer_prices(breek, vm, mod):
    mock_cg(vm, "solana", cg_body(DAY_START, DAY_END, "115", "117", numeric=True))
    open_, close = mod._fetch_coingecko("SOL", DAY_START, DAY_END)
    assert (open_, close) == (115 * SCALE, 117 * SCALE)


def test_coingecko_rejects_missing_series(breek, vm, mod):
    mock_cg(vm, "solana", json.dumps({"market_caps": []}))
    with pytest.raises(Exception, match="CG_NO_SERIES"):
        mod._fetch_coingecko("SOL", DAY_START, DAY_END)


def test_coingecko_rejects_subsecond_timestamps(breek, vm, mod):
    doc = {"prices": [[DAY_START * 1000 + 1, 1.0], [DAY_END * 1000, 2.0]]}
    mock_cg(vm, "solana", json.dumps(doc))
    with pytest.raises(Exception, match="CG_SUBSECOND_TS"):
        mod._fetch_coingecko("SOL", DAY_START, DAY_END)


def test_coingecko_rejects_point_shape(breek, vm, mod):
    mock_cg(vm, "solana", json.dumps({"prices": [[DAY_START * 1000]]}))
    with pytest.raises(Exception, match="CG_POINT_SHAPE"):
        mod._fetch_coingecko("SOL", DAY_START, DAY_END)


def test_coingecko_rejects_non_positive_price(breek, vm, mod):
    doc = {"prices": [[DAY_START * 1000, 0.0], [DAY_END * 1000, 2.0]]}
    mock_cg(vm, "solana", json.dumps(doc))
    with pytest.raises(Exception, match="CG_NON_POSITIVE|NON_POSITIVE"):
        mod._fetch_coingecko("SOL", DAY_START, DAY_END)


def test_coingecko_transient_on_429(breek, vm, mod):
    mock_cg(vm, "solana", "{}", status=429)
    with pytest.raises(Exception, match="TRANSIENT:HTTP_429"):
        mod._fetch_coingecko("SOL", DAY_START, DAY_END)


def test_coingecko_unknown_symbol(breek, vm, mod):
    with pytest.raises(Exception, match="NO_COINGECKO_ID_BTC"):
        mod._fetch_coingecko("BTC", DAY_START, DAY_END)


def test_both_sources_measure_the_same_instants(breek, vm, mod):
    """The property the whole design rests on: A and B read the same two times.

    Feeding both sources the identical open/close must produce identical scaled
    pairs. Then, shifting source B's series back by an hour so the interesting
    prices land one hour early must change B's answer: it reads the instants, not
    whichever samples happen to bound the payload.
    """
    mock_gate(vm, "SOL", gate_body(DAY_START, DAY_END, "115.15", "116.61"))
    mock_cg(vm, "solana", cg_body(DAY_START, DAY_END, "115.15", "116.61"))
    aligned = mod._fetch_coingecko("SOL", DAY_START, DAY_END)
    assert mod._fetch_gate("SOL", DAY_START, DAY_END) == aligned

    vm.clear_mocks()
    mock_cg(vm, "solana", cg_body(DAY_START - HOUR, DAY_END - HOUR, "115.15", "116.61"))
    shifted = mod._fetch_coingecko("SOL", DAY_START, DAY_END)
    assert shifted != aligned
    # Both boundary reads fell on filler samples, so nothing from the shifted
    # series leaked into the window's real open or close.
    assert shifted == (mod._dec_to_scaled("50.5"), mod._dec_to_scaled("50.5"))


def test_coingecko_rejects_a_23_hour_span(breek, vm, mod):
    """A series that stops one hour short must fail, not substitute the last point."""
    body = json.loads(cg_body(DAY_START, DAY_END, "115.15", "116.61"))
    body["prices"] = [p for p in body["prices"] if p[0] < DAY_END * 1000]
    assert body["prices"][-1][0] == (DAY_END - HOUR) * 1000
    mock_cg(vm, "solana", json.dumps(body))
    with pytest.raises(Exception, match="CG_NO_SAMPLE_AT_END"):
        mod._fetch_coingecko("SOL", DAY_START, DAY_END)
