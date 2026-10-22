"""
How far each scheduled run looks ahead.

The lookahead is the single biggest lever on prop spend — every event inside
the window costs (markets x regions) — so the two scheduled runs size it
differently. Thursday reaches Sunday's slate; Sunday only has to reach Monday
night.
"""

import datetime

import odds_api as oa


def _at(year, month, day, hour=9):
    """A naive-UTC instant, which is what the fetch works in."""
    return datetime.datetime(year, month, day, hour)


# 2026-10-22 is a Thursday, 2026-10-25 a Sunday.
THURSDAY = _at(2026, 10, 22)
SUNDAY   = _at(2026, 10, 25)


# A real week in UTC, which is the thing that makes these windows awkward:
# every night game lands on the following calendar day.
TNF        = datetime.datetime(2026, 10, 23, 0, 15)   # Thu night
SAT_GAME   = datetime.datetime(2026, 10, 24, 21, 0)   # late-season Saturday
SUN_EARLY  = datetime.datetime(2026, 10, 25, 13, 30)  # London
SUN_BULK   = datetime.datetime(2026, 10, 25, 17, 0)
SNF        = datetime.datetime(2026, 10, 26, 0, 20)   # Sun night
MNF        = datetime.datetime(2026, 10, 27, 0, 15)   # Mon night
NEXT_TNF   = datetime.datetime(2026, 10, 30, 0, 15)

WEEK = [TNF, SAT_GAME, SUN_EARLY, SUN_BULK, SNF, MNF, NEXT_TNF]


def _covered(now, games=WEEK):
    """Which of `games` a run at `now` would buy props for."""
    cutoff = oa._props_cutoff(now, games)
    return [g for g in games if now <= g <= cutoff]


class TestLookaheadByDay:
    def test_thursday_stops_short_of_the_sunday_slate(self):
        assert oa.props_lookahead_days(THURSDAY) == 3

    def test_sunday_only_has_to_reach_monday_night(self):
        assert oa.props_lookahead_days(SUNDAY) == 2

    def test_an_unscheduled_day_falls_back_to_the_default(self):
        # A startup refresh can land on any day, and should behave as before.
        assert oa.props_lookahead_days(_at(2026, 10, 20)) == oa.PROPS_LOOKAHEAD_DAYS

    def test_the_two_scheduled_days_are_the_ones_configured(self):
        assert set(oa.PROPS_LOOKAHEAD_BY_WEEKDAY) == set(oa.REFRESH_WEEKDAYS)


class TestTheWindowsPartitionTheWeek:
    """
    The point of the two sizes is that between them they buy every fixture
    exactly once. Overlap is what the old four-day Thursday was paying for.
    """

    def test_thursday_takes_the_midweek_fixtures(self):
        assert _covered(THURSDAY) == [TNF, SAT_GAME]

    def test_sunday_takes_the_slate_and_both_night_games(self):
        assert _covered(SUNDAY) == [SUN_EARLY, SUN_BULK, SNF, MNF]

    def test_between_them_they_cover_the_week_once_each(self):
        bought = _covered(THURSDAY) + _covered(SUNDAY)
        assert sorted(bought) == [TNF, SAT_GAME, SUN_EARLY, SUN_BULK, SNF, MNF]
        assert len(bought) == len(set(bought))

    def test_neither_run_reaches_the_following_week(self):
        assert NEXT_TNF not in _covered(THURSDAY)
        assert NEXT_TNF not in _covered(SUNDAY)

    def test_sunday_needs_two_days_for_monday_night(self):
        # Monday night is Tuesday 00:15 UTC, so a one-day window would miss it.
        assert MNF in _covered(SUNDAY)
        assert MNF > SUNDAY + datetime.timedelta(days=1)

    def test_a_started_game_is_not_bought_again(self):
        # Sunday's run is after Thursday night; there is nothing left to price.
        assert TNF not in _covered(SUNDAY)


class TestOpenerFallbackStillWorks:
    def test_deep_offseason_stretches_to_the_opener(self):
        # Nothing inside the rolling window, so the cutoff reaches the first
        # game plus the buffer rather than catching nothing at all.
        now = _at(2026, 7, 1)
        opener = datetime.datetime(2026, 9, 10, 0, 20)
        cutoff = oa._props_cutoff(now, [opener])
        assert cutoff == opener + datetime.timedelta(days=oa.PROPS_OPENER_BUFFER_DAYS)

    def test_a_game_inside_the_window_keeps_the_rolling_cutoff(self):
        now = THURSDAY
        cutoff = oa._props_cutoff(now, [now + datetime.timedelta(days=1)])
        assert cutoff == now + datetime.timedelta(days=3)


class TestStatusAgreesWithTheFetch:
    def test_the_reported_window_is_the_one_that_will_be_used(self, monkeypatch):
        # The note on /odds/status used to quote the fixed default, which after
        # this change would describe a fetch that never happens on a Sunday.
        monkeypatch.setattr(oa, "odds_games", {
            "a": {"commence_time": "2026-10-25T17:00:00Z"},
        })
        fixed = datetime.datetime(2026, 10, 25, 9)

        class _Clock(datetime.datetime):
            @classmethod
            def utcnow(cls):
                return fixed

        monkeypatch.setattr(oa.datetime, "datetime", _Clock)
        ok, why = oa.should_run_scheduled_refresh()
        assert ok
        assert "within 2 days" in why
