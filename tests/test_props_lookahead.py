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


class TestLookaheadByDay:
    def test_thursday_reaches_sundays_slate(self):
        assert oa.props_lookahead_days(THURSDAY) == 4

    def test_sunday_only_has_to_reach_monday_night(self):
        assert oa.props_lookahead_days(SUNDAY) == 2

    def test_an_unscheduled_day_falls_back_to_the_default(self):
        # A startup refresh can land on any day, and should behave as before.
        assert oa.props_lookahead_days(_at(2026, 10, 20)) == oa.PROPS_LOOKAHEAD_DAYS

    def test_the_two_scheduled_days_are_the_ones_configured(self):
        assert set(oa.PROPS_LOOKAHEAD_BY_WEEKDAY) == set(oa.REFRESH_WEEKDAYS)


class TestWindowCoversTheWeek:
    """
    The windows have to between them reach every fixture. Kickoffs in UTC run
    late: Thursday night is Friday 00:15, Sunday night Monday 00:20, and Monday
    night Tuesday 00:15 — which is why Sunday needs two days and not one.
    """

    def test_thursday_covers_thursday_night(self):
        cutoff = oa._props_cutoff(THURSDAY, [_at(2026, 10, 23, 0) + datetime.timedelta(minutes=15)])
        assert cutoff >= datetime.datetime(2026, 10, 23, 0, 15)

    def test_thursday_covers_the_sunday_games(self):
        cutoff = oa._props_cutoff(THURSDAY, [datetime.datetime(2026, 10, 25, 20, 25)])
        assert cutoff >= datetime.datetime(2026, 10, 25, 20, 25)

    def test_sunday_covers_monday_night(self):
        # Monday night is Tuesday 00:15 UTC. One day would miss it.
        monday_night = datetime.datetime(2026, 10, 27, 0, 15)
        assert oa._props_cutoff(SUNDAY, [monday_night]) >= monday_night

    def test_sunday_does_not_reach_next_thursday_night(self):
        # Thursday's own run buys that one; buying it twice is the waste.
        # The list has to include a game inside the window, or the off-season
        # opener fallback stretches the cutoff out to meet the only fixture it
        # can see.
        next_tnf = datetime.datetime(2026, 10, 30, 0, 15)
        this_week = [datetime.datetime(2026, 10, 25, 17, 0), next_tnf]
        assert oa._props_cutoff(SUNDAY, this_week) < next_tnf


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
        assert cutoff == now + datetime.timedelta(days=4)


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
