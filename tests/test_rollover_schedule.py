"""The weekly rollover, and the schedule it runs on.

The rollover used to decide which week was current from get_current_week(), which
reports the previous week Tuesday to Thursday so result pages keep showing the week
just played. Sleeper has moved on by Tuesday, so on Thursday morning the week that had
just finished still looked current and was left unscored for a further week. The
lifecycle tests patched that method directly, which is why none of them noticed.
"""

import datetime
import sys
from collections import Counter

import pytest
from unittest.mock import patch, MagicMock

nfl_helper = sys.modules["nfl_helper"]

from conftest import make_lineup_string, create_entry


def sleeper_state(week):
    resp = MagicMock()
    resp.json.return_value = {"season": "2026", "week": week, "season_type": "regular"}
    resp.raise_for_status.return_value = None
    return resp


class ThursdayMorning(datetime.datetime):
    """Thursday 17 Sep 2026, 10:00 — inside get_current_week's previous-week window."""
    @classmethod
    def now(cls, tz=None):
        return datetime.datetime(2026, 9, 17, 10, 0)


def seed_week_seven():
    """A finished week 7: one live multiweek tournament and three things to delete."""
    create_entry("cup", week=7, entry_type="multiweek_dfs", num_weeks=4, start_week=7)
    nfl_helper.fantasy_points_data["11111_7"] = {"fantasy_points": 20.0}
    nfl_helper.tinyurl_data["cup"]["user_submissions"] = {
        "alice": {"username": "alice", "data": make_lineup_string(7, ["11111:QB"]), "update_count": 1},
    }
    create_entry("oneoff", week=7)
    # end_week = 5 + 2 - 1 = 6, so week 7 is its grace week and it is due for removal
    create_entry("done", week=7, entry_type="multiweek_dfs", num_weeks=2, start_week=5)
    nfl_helper.tinyurl_data["noweek"] = {"name": "noweek", "type": "single"}


def wednesday(league_week):
    with patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=league_week), \
         patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={}):
        nfl_helper.score_multiweek_tinyurls()


def thursday(league_week):
    with patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=league_week), \
         patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={}):
        nfl_helper.clear_tinyurl_data()


class TestRolloverUsesSleepersWeek:
    def test_a_finished_week_is_scored_inside_the_previous_week_window(self):
        """The production failure: Thursday morning, Sleeper already on week 2."""
        create_entry("cup", week=1, entry_type="multiweek_dfs", num_weeks=4, start_week=1)
        nfl_helper.fantasy_points_data["11111_1"] = {"fantasy_points": 20.0}
        nfl_helper.tinyurl_data["cup"]["user_submissions"] = {
            "alice": {"username": "alice", "data": make_lineup_string(1, ["11111:QB"]), "update_count": 1},
        }

        with patch("requests.Session.get", return_value=sleeper_state(2)), \
             patch("fantasydatascraper.datetime.datetime", ThursdayMorning), \
             patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={}):
            nfl_helper.clear_tinyurl_data()

        entry = nfl_helper.tinyurl_data["cup"]
        assert entry["week"] == 2, "week 1 has finished and must advance"
        assert entry["standings"]["alice"]["week_points"]["1"] == pytest.approx(20.0)

    def test_the_rollover_never_consults_the_display_week(self):
        with patch.object(nfl_helper.FantasyDataScraper, "get_current_week") as display_week, \
             patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=2), \
             patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={}):
            nfl_helper.score_multiweek_tinyurls()
            nfl_helper.clear_tinyurl_data()
            nfl_helper.clear_tournament_data()

        display_week.assert_not_called()

    def test_league_week_ignores_the_display_window(self):
        scraper = nfl_helper.FantasyDataScraper()
        with patch.object(scraper.session, "get", return_value=sleeper_state(2)), \
             patch("fantasydatascraper.datetime.datetime", ThursdayMorning):
            assert scraper.get_league_week() == 2
            assert scraper.get_current_week() == 1, "the display week is still last week"

    def test_league_week_falls_back_to_the_calendar(self):
        scraper = nfl_helper.FantasyDataScraper()
        with patch.object(scraper.session, "get", side_effect=Exception("offline")), \
             patch.object(scraper, "_calculate_fallback_week", return_value=7):
            assert scraper.get_league_week() == 7


class TestWednesdayScoringPass:
    def test_scores_and_advances_multiweek(self):
        seed_week_seven()
        wednesday(8)

        cup = nfl_helper.tinyurl_data["cup"]
        assert cup["week"] == 8
        assert cup["standings"]["alice"]["week_points"]["7"] == pytest.approx(20.0)
        assert cup["user_submissions"] == {}

    def test_deletes_nothing(self):
        """Results pages stay up until Thursday."""
        seed_week_seven()
        wednesday(8)

        for name in ("oneoff", "done", "noweek"):
            assert name in nfl_helper.tinyurl_data, f"{name} must survive the scoring pass"

    def test_an_error_leaves_every_entry_in_place(self):
        """The full cleanup wipes everything on an error; the scoring pass must not."""
        seed_week_seven()
        with patch.object(nfl_helper.FantasyDataScraper, "get_league_week",
                          side_effect=RuntimeError("Sleeper unavailable")):
            nfl_helper.score_multiweek_tinyurls()

        assert set(nfl_helper.tinyurl_data) == {"cup", "oneoff", "done", "noweek"}


class TestWednesdayThenThursday:
    def test_thursday_removes_what_wednesday_kept(self):
        seed_week_seven()
        wednesday(8)
        thursday(8)

        assert "cup" in nfl_helper.tinyurl_data
        for name in ("oneoff", "done", "noweek"):
            assert name not in nfl_helper.tinyurl_data

    def test_thursday_does_not_score_the_week_again(self):
        seed_week_seven()
        wednesday(8)
        thursday(8)

        cup = nfl_helper.tinyurl_data["cup"]
        assert cup["week"] == 8
        assert cup["standings"]["alice"]["week_points"] == {"7": pytest.approx(20.0)}
        assert cup["standings"]["alice"]["total_points"] == pytest.approx(20.0)

    def test_a_late_week_flip_is_caught_on_thursday(self):
        """If Sleeper has not moved on by Wednesday morning, Thursday scores the week."""
        seed_week_seven()
        wednesday(7)
        assert nfl_helper.tinyurl_data["cup"]["week"] == 7, "nothing to score yet"

        thursday(8)
        cup = nfl_helper.tinyurl_data["cup"]
        assert cup["week"] == 8
        assert cup["standings"]["alice"]["week_points"]["7"] == pytest.approx(20.0)


# ── schedule ─────────────────────────────────────────────────────────────────

# The jobs big enough that two starting in the same hour risk the 512 MB limit.
HEAVY = {
    "_refresh_nflverse_and_release",
    "update_fantasy_points_data",
    "fetch_and_filter_data",
    "update_dfs_salaries_data",
    "update_filtered_players_with_scraped_data",
}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def registrations():
    return [(c.kwargs["func"].__name__, c.kwargs["trigger"])
            for c in nfl_helper.scheduler.add_job.call_args_list]


def triggers_for(name):
    return sorted(str(trigger) for func, trigger in registrations() if func == name)


def fire_slots():
    """(job, weekday, hour) for every run over one week, in the triggers' own zone."""
    slots = []
    start = datetime.datetime(2026, 9, 14, tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(days=7)
    for name, trigger in registrations():
        previous, now = None, start
        while True:
            fire = trigger.get_next_fire_time(previous, now)
            if fire is None or fire >= end:
                break
            slots.append((name, DAYS[fire.weekday()], fire.hour))
            previous, now = fire, fire + datetime.timedelta(seconds=1)
    return slots


class TestSchedule:
    def test_every_job_is_on_a_fixed_schedule(self):
        """An interval counts from startup, so its runs can drift onto a heavy slot."""
        from apscheduler.triggers.cron import CronTrigger
        for name, trigger in registrations():
            assert isinstance(trigger, CronTrigger), f"{name} is not on a fixed schedule"

    def test_no_two_heavy_jobs_start_in_the_same_hour(self):
        heavy = [(day, hour) for name, day, hour in fire_slots() if name in HEAVY]
        clashes = {slot: count for slot, count in Counter(heavy).items() if count > 1}
        assert not clashes, f"heavy jobs share these hours: {clashes}"

    def test_fantasy_points_run_once_per_game_window(self):
        assert triggers_for("update_fantasy_points_data") == sorted([
            "cron[day_of_week='mon,tue,fri', hour='8', minute='0']",
            "cron[day_of_week='sun', hour='23', minute='0']",
        ])
        runs = [s for s in fire_slots() if s[0] == "update_fantasy_points_data"]
        assert len(runs) == 4

    def test_multiweek_is_scored_wednesday_morning(self):
        assert triggers_for("score_multiweek_tinyurls") == [
            "cron[day_of_week='wed', hour='6', minute='0']",
        ]

    def test_finished_entries_are_cleared_thursday(self):
        assert triggers_for("clear_tinyurl_data") == ["cron[day_of_week='thu', hour='9', minute='0']"]
        assert triggers_for("clear_tournament_data") == ["cron[day_of_week='thu', hour='9', minute='0']"]
