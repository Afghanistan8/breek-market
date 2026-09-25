"""GMT+1 calendar maths.

GMT+1 is a fixed +3600 offset, so midnight GMT+1 is 23:00 UTC on the previous
day. Every assertion below pins that, plus leap days, century rules, week
boundaries and the consensus-time parser.
"""

import pytest

from tests.conftest import DAY, HOUR, WEEK, day_window, days_from_civil, iso, week_window


def test_leap_years(mod):
    assert mod._is_leap(2024)
    assert mod._is_leap(2000)
    assert not mod._is_leap(1900)  # century, not divisible by 400
    assert not mod._is_leap(2023)
    assert mod._is_leap(2400)


def test_days_in_month_leap_february(mod):
    assert mod._days_in_month(2024, 2) == 29
    assert mod._days_in_month(2023, 2) == 28
    assert mod._days_in_month(1900, 2) == 28
    assert mod._days_in_month(2024, 4) == 30
    assert mod._days_in_month(2024, 12) == 31


def test_civil_day_zero_is_epoch(mod):
    assert mod._days_from_civil(1970, 1, 1) == 0
    assert mod._civil_from_days(0) == (1970, 1, 1)


@pytest.mark.parametrize(
    "y,m,d",
    [
        (1970, 1, 1),
        (1999, 12, 31),
        (2000, 1, 1),
        (2000, 2, 29),
        (2024, 2, 29),
        (2026, 9, 25),
        (2100, 3, 1),
        (2399, 12, 31),
    ],
)
def test_civil_roundtrip(mod, y, m, d):
    z = mod._days_from_civil(y, m, d)
    assert mod._civil_from_days(z) == (y, m, d)


def test_civil_is_contiguous_across_leap_day(mod):
    """Feb 28 -> Feb 29 -> Mar 1 must be three consecutive day indices."""
    feb28 = mod._days_from_civil(2024, 2, 28)
    feb29 = mod._days_from_civil(2024, 2, 29)
    mar01 = mod._days_from_civil(2024, 3, 1)
    assert feb29 == feb28 + 1
    assert mar01 == feb29 + 1


def test_non_leap_year_skips_feb_29(mod):
    feb28 = mod._days_from_civil(2023, 2, 28)
    mar01 = mod._days_from_civil(2023, 3, 1)
    assert mar01 == feb28 + 1


def test_weekday_epoch_was_thursday(mod):
    # 1970-01-01 was a Thursday; 0 = Monday, so Thursday is 3.
    assert mod._weekday_from_days(0) == 3


def test_weekday_known_mondays(mod):
    for y, m, d in [(2026, 9, 21), (2026, 9, 14), (2024, 1, 1), (2000, 1, 3)]:
        assert mod._weekday_from_days(mod._days_from_civil(y, m, d)) == 0


def test_daily_window_starts_2300_utc_previous_day(mod):
    """The defining property of a GMT+1 day."""
    start, end = mod._window_bounds("DAILY", "2026-09-24")
    assert start == day_window(2026, 9, 24)[0]
    assert end - start == DAY
    # window_start is 23:00 UTC on 2026-09-23
    assert start == mod._days_from_civil(2026, 9, 23) * DAY + 23 * HOUR
    assert start % HOUR == 0


def test_daily_window_matches_live_probe_values(mod):
    """Pinned against scripts/check_sources.py output committed in docs/."""
    start, end = mod._window_bounds("DAILY", "2026-09-24")
    assert (start, end) == (1790204400, 1790290800)


def test_weekly_window_is_monday_to_monday(mod):
    start, end = mod._window_bounds("WEEKLY", "2026-09-14")
    assert (start, end) == (1789340400, 1789945200)
    assert end - start == WEEK
    # end of this week is the start of the next week's window
    nxt, _ = mod._window_bounds("WEEKLY", "2026-09-21")
    assert nxt == end


def test_weekly_window_rejects_non_monday(mod):
    for bad in ["2026-09-15", "2026-09-20", "2026-09-13"]:
        with pytest.raises(Exception, match="WEEK_MUST_START_MONDAY"):
            mod._window_bounds("WEEKLY", bad)


def test_daily_windows_tile_without_gap_or_overlap(mod):
    """Consecutive GMT+1 days must abut exactly, including across a leap day."""
    prev_end = None
    for day in ["2024-02-27", "2024-02-28", "2024-02-29", "2024-03-01", "2024-03-02"]:
        start, end = mod._window_bounds("DAILY", day)
        if prev_end is not None:
            assert start == prev_end
        assert end - start == DAY
        prev_end = end


def test_window_id_rejects_malformed(mod):
    for bad in ["2026-9-24", "26-09-24", "2026/09/24", "2026-09-24T00", "", "abcd-ef-gh"]:
        with pytest.raises(Exception, match="WINDOW_ID_FORMAT"):
            mod._parse_iso_date(bad)


def test_window_id_rejects_impossible_dates(mod):
    for bad in ["2023-02-29", "2026-13-01", "2026-00-10", "2026-04-31", "2026-01-32"]:
        with pytest.raises(Exception, match="WINDOW_ID_RANGE"):
            mod._parse_iso_date(bad)


def test_window_id_accepts_real_leap_day(mod):
    assert mod._parse_iso_date("2024-02-29") == (2024, 2, 29)


def test_consensus_datetime_parses_genvm_format(mod):
    """The exact shape studionet returned from gl.message_raw['datetime']."""
    assert mod._parse_consensus_datetime("1970-01-01T00:00:00.000000Z") == 0
    assert mod._parse_consensus_datetime("1970-01-01T00:00:01.000000Z") == 1
    assert mod._parse_consensus_datetime("2026-09-25T13:43:54.996120Z") == 1790343834


def test_consensus_datetime_truncates_fraction(mod):
    """Sub-second precision is dropped, never rounded up."""
    a = mod._parse_consensus_datetime("2026-09-25T13:43:54.000001Z")
    b = mod._parse_consensus_datetime("2026-09-25T13:43:54.999999Z")
    assert a == b


def test_consensus_datetime_accepts_space_separator(mod):
    assert mod._parse_consensus_datetime(
        "2026-09-25 13:43:54.996120Z"
    ) == mod._parse_consensus_datetime("2026-09-25T13:43:54.996120Z")


def test_consensus_datetime_clamps_leap_second(mod):
    assert mod._parse_consensus_datetime("2016-12-31T23:59:60.000000Z") == (
        mod._parse_consensus_datetime("2016-12-31T23:59:59.000000Z")
    )


def test_consensus_datetime_rejects_garbage(mod):
    for bad in ["", "not-a-time", "2026-09-25", "2026-09-25X13:43:54Z", "2026-09-25T13-43-54Z"]:
        with pytest.raises(Exception, match="CONSENSUS_TIME|WINDOW_ID"):
            mod._parse_consensus_datetime(bad)


def test_consensus_datetime_rejects_out_of_range_clock(mod):
    for bad in ["2026-09-25T24:00:00.0Z", "2026-09-25T13:60:00.0Z"]:
        with pytest.raises(Exception, match="CONSENSUS_TIME_RANGE"):
            mod._parse_consensus_datetime(bad)


def test_iso_helper_matches_contract_parser(mod):
    """The test helper and the contract must agree, or later tests lie."""
    for unix in [0, 1, 1_700_000_000, 1790204400, 1790343834]:
        assert mod._parse_consensus_datetime(iso(unix)) == unix


def test_unknown_timeframe_rejected(mod):
    with pytest.raises(Exception, match="UNKNOWN_TIMEFRAME"):
        mod._window_bounds("HOURLY", "2026-09-24")
