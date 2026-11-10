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


# 2026-10-22 is a Thursday, 2026-10-24 a Saturday.
THURSDAY = _at(2026, 10, 22)
SATURDAY = _at(2026, 10, 24)


# A real week in UTC, which is the thing that makes these windows awkward:
# every night game lands on the following calendar day.
TNF        = datetime.datetime(2026, 10, 23, 0, 15)   # Thu night
FRI_GAME   = datetime.datetime(2026, 10, 24, 0, 15)   # Friday night
SAT_GAME   = datetime.datetime(2026, 10, 24, 21, 0)   # late-season Saturday
SUN_EARLY  = datetime.datetime(2026, 10, 25, 13, 30)  # London
SUN_BULK   = datetime.datetime(2026, 10, 25, 17, 0)
SNF        = datetime.datetime(2026, 10, 26, 0, 20)   # Sun night
MNF        = datetime.datetime(2026, 10, 27, 0, 15)   # Mon night
NEXT_TNF   = datetime.datetime(2026, 10, 30, 0, 15)

WEEK = [TNF, FRI_GAME, SAT_GAME, SUN_EARLY, SUN_BULK, SNF, MNF, NEXT_TNF]


def _covered(now, games=WEEK):
    """Which of `games` a run at `now` would buy props for."""
    cutoff = oa._props_cutoff(now, games)
    return [g for g in games if now <= g <= cutoff]


class TestLookaheadByDay:
    def test_thursday_covers_only_the_midweek_fixtures(self):
        assert oa.props_lookahead_days(THURSDAY) == 2

    def test_saturday_has_to_reach_monday_night(self):
        assert oa.props_lookahead_days(SATURDAY) == 3

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

    def test_thursday_takes_thursday_and_friday_night(self):
        assert _covered(THURSDAY) == [TNF, FRI_GAME]

    def test_saturday_takes_its_own_games_through_monday_night(self):
        assert _covered(SATURDAY) == [SAT_GAME, SUN_EARLY, SUN_BULK, SNF, MNF]

    def test_between_them_they_cover_the_week_once_each(self):
        bought = _covered(THURSDAY) + _covered(SATURDAY)
        assert sorted(bought) == [TNF, FRI_GAME, SAT_GAME, SUN_EARLY, SUN_BULK, SNF, MNF]
        assert len(bought) == len(set(bought)), "no game should be bought twice"

    def test_the_two_windows_meet_without_a_gap(self):
        # Thursday's cutoff is Saturday morning and Saturday's run starts there,
        # so nothing can fall between them.
        assert oa._props_cutoff(THURSDAY, WEEK) == SATURDAY

    def test_neither_run_reaches_the_following_week(self):
        assert NEXT_TNF not in _covered(THURSDAY)
        assert NEXT_TNF not in _covered(SATURDAY)

    def test_saturday_needs_three_days_for_monday_night(self):
        # Monday night is Tuesday 00:15 UTC. Two days would miss it, and no
        # later run exists to pick it up.
        assert MNF in _covered(SATURDAY)
        assert MNF > SATURDAY + datetime.timedelta(days=2)

    def test_a_started_game_is_not_bought_again(self):
        # Saturday's run is after Thursday night; there is nothing left to price.
        assert TNF not in _covered(SATURDAY)


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
        assert cutoff == now + datetime.timedelta(days=2)


class TestStatusAgreesWithTheFetch:
    def test_the_reported_window_is_the_one_that_will_be_used(self, monkeypatch):
        # The note on /odds/status used to quote the fixed default, which after
        # this change would describe a fetch that never happens on a Sunday.
        monkeypatch.setattr(oa, "odds_games", {
            "a": {"commence_time": "2026-10-25T17:00:00Z"},
        })
        fixed = datetime.datetime(2026, 10, 24, 9)   # Saturday

        class _Clock(datetime.datetime):
            @classmethod
            def utcnow(cls):
                return fixed

        monkeypatch.setattr(oa.datetime, "datetime", _Clock)
        ok, why = oa.should_run_scheduled_refresh()
        assert ok
        assert "within 3 days" in why


# ── The window cannot pause the run forever ──────────────────────────────────

def _frozen(monkeypatch, now):
    """Pin utcnow() for everything in odds_api that reads it."""
    class _Clock(datetime.datetime):
        @classmethod
        def utcnow(cls):
            return now

    monkeypatch.setattr(oa.datetime, "datetime", _Clock)


def _held(monkeypatch, commence_times, last_updated):
    monkeypatch.setattr(oa, "odds_games", {
        str(i): {"commence_time": t} for i, t in enumerate(commence_times)
    })
    monkeypatch.setattr(oa, "odds_last_updated", last_updated)


class TestTheSkipCannotBecomePermanent:
    """The window is measured against the games we are *holding*, which is a
    self-reinforcing trap: once every held game has been played the count is
    zero and stays zero, so the run skips, the cache is never updated, and the
    next run counts the same dead games again.

    Production hit exactly this. Both runs skipped, the whole billing period
    spent no credits at all, and the served odds were 22 days old while
    /odds/status still said the refresh would resume by itself.
    """

    # Week 8, all played. The kind of thing the cache is left holding.
    PLAYED = ["2026-10-23T00:15:00Z", "2026-10-25T17:00:00Z", "2026-10-27T00:15:00Z"]

    def test_a_stale_cache_of_played_games_refreshes_anyway(self, monkeypatch):
        now = _at(2026, 11, 12)                     # a Thursday, a fortnight on
        _frozen(monkeypatch, now)
        _held(monkeypatch, self.PLAYED, "2026-10-17T08:00:00Z")

        assert oa.games_within_window() == 0, "nothing held is ahead of us"
        ok, why = oa.should_run_scheduled_refresh()
        assert ok, "a cache this old must not keep deferring its own refresh"
        assert "past the" in why and "mark" in why

    def test_a_fresh_cache_with_an_empty_window_still_skips(self, monkeypatch):
        """The saving this check exists for is untouched: a quiet Thursday in
        the offseason with recent data buys nothing."""
        now = _at(2026, 7, 2)
        _frozen(monkeypatch, now)
        _held(monkeypatch, ["2026-09-10T00:20:00Z"], "2026-07-01T08:00:00Z")

        ok, why = oa.should_run_scheduled_refresh()
        assert not ok
        assert "will resume automatically" in why

    def test_the_threshold_is_the_one_the_boot_fetch_uses(self, monkeypatch):
        """Both are answering "is what we hold too old to keep?", so they
        answer it the same way. Were the scheduled run's bar the higher of the
        two, a restart would spend the credits the run had declined to."""
        now = _at(2026, 11, 12)
        _frozen(monkeypatch, now)
        hours = oa.STARTUP_REFRESH_MAX_AGE_HOURS
        just_past = now - datetime.timedelta(hours=hours + 1)
        just_under = now - datetime.timedelta(hours=hours - 1)

        _held(monkeypatch, self.PLAYED, just_past.isoformat() + "Z")
        assert oa.should_run_scheduled_refresh()[0]
        assert oa.should_refresh_on_startup()

        _held(monkeypatch, self.PLAYED, just_under.isoformat() + "Z")
        assert not oa.should_run_scheduled_refresh()[0]
        assert not oa.should_refresh_on_startup()

    def test_an_unreadable_timestamp_leaves_the_window_in_charge(self, monkeypatch):
        """cache_age_hours() is None for a missing or malformed stamp. That is
        not evidence of staleness, so it must not become a reason to spend."""
        now = _at(2026, 7, 2)
        _frozen(monkeypatch, now)
        _held(monkeypatch, ["2026-09-10T00:20:00Z"], None)
        assert oa.cache_age_hours() is None
        assert not oa.should_run_scheduled_refresh()[0]

        _held(monkeypatch, ["2026-09-10T00:20:00Z"], "not a timestamp")
        assert oa.cache_age_hours() is None
        assert not oa.should_run_scheduled_refresh()[0]

    def test_holding_nothing_at_all_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(oa, "odds_games", {})
        ok, why = oa.should_run_scheduled_refresh()
        assert ok and "no games held" in why
