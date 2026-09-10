"""Grading stored betting lines against what actually happened.

Two things make this easy to get silently wrong: nflverse dates games in Eastern
while the odds feed stores UTC, and week numbers repeat every season.
"""

import sys

import pytest
from unittest.mock import patch

nfl_helper = sys.modules["nfl_helper"]

import odds_api as oa
import nflverse_stats as ns


THURSDAY_NIGHT = {
    "home_abbr": "SEA", "away_abbr": "NE",
    "commence_time": "2026-09-10T00:15:00Z",      # 8:15pm ET on the 9th
    "total": {"line": 43.5},
    "ou_eval": {"signal": "over"},
}

PLAYED_GAME = {
    "home_team": "SEA", "away_team": "NE",
    "gameday": "2026-09-09",                       # nflverse dates it Eastern
    "home_score": 13, "away_score": 10,
}


@pytest.fixture
def stored_game():
    oa.odds_history.clear()
    ns.nflverse_games.clear()
    oa.odds_history["evt1"] = dict(THURSDAY_NIGHT)
    ns.nflverse_games[1] = [dict(PLAYED_GAME)]
    yield
    oa.odds_history.clear()
    ns.nflverse_games.clear()


class TestNightGameDates:
    def test_a_night_game_is_graded_despite_the_utc_date(self, client, stored_game):
        """8:15pm ET is stored as the next UTC day; it must still find its game."""
        row = client.get("/odds/results").get_json()[0]

        assert row["result"] is not None, "night games must not be left ungraded"
        assert row["result"]["home_score"] == 13
        assert row["result"]["actual_total"] == 23

    def test_the_over_under_call_is_graded(self, client, stored_game):
        row = client.get("/odds/results").get_json()[0]

        assert row["result"]["ou_result"] == "under", "23 is under a line of 43.5"
        assert row["result"]["edge_correct"] is False, "the signal said over"

    def test_an_afternoon_game_still_matches(self, client):
        """The straightforward case must not regress: ET and UTC agree at 1pm."""
        oa.odds_history.clear(); ns.nflverse_games.clear()
        oa.odds_history["evt2"] = {
            "home_abbr": "CIN", "away_abbr": "TB",
            "commence_time": "2026-09-13T17:00:00Z",
            "total": {"line": 40.0}, "ou_eval": {"signal": "under"},
        }
        ns.nflverse_games[1] = [{
            "home_team": "CIN", "away_team": "TB", "gameday": "2026-09-13",
            "home_score": 20, "away_score": 17,
        }]

        row = client.get("/odds/results").get_json()[0]

        assert row["result"]["actual_total"] == 37
        assert row["result"]["edge_correct"] is True
        oa.odds_history.clear(); ns.nflverse_games.clear()

    def test_an_unplayed_game_stays_ungraded(self, client):
        oa.odds_history.clear(); ns.nflverse_games.clear()
        oa.odds_history["evt3"] = dict(THURSDAY_NIGHT)
        ns.nflverse_games[1] = [{**PLAYED_GAME, "home_score": None, "away_score": None}]

        assert client.get("/odds/results").get_json()[0]["result"] is None
        oa.odds_history.clear(); ns.nflverse_games.clear()


class TestPropSeasonGuard:
    """Week 1 exists in every season, so grading must check which one."""

    def setup_snapshot(self):
        oa.odds_props_history.clear()
        oa.odds_props_history["p1"] = {
            "sleeper_id": "111", "market": "player_pass_yds",
            "commence_time": "2026-09-10T00:15:00Z",
            "nfl_week": 1, "line": 250.0,
        }
        ns.nflverse_player_stats.clear()
        ns.nflverse_player_stats["111"] = {"weekly": [{"week": 1, "passing_yards": 310}]}

    def teardown(self):
        oa.odds_props_history.clear()
        ns.nflverse_player_stats.clear()

    def test_props_are_not_graded_against_another_season(self):
        self.setup_snapshot()
        ns.nflverse_current_season = 2025          # stats still on last season
        try:
            row = oa.grade_props_history()[0]
            assert row["actual"] is None, "a 2026 prop must not read 2025 week 1"
            assert row["result"] is None
        finally:
            self.teardown()

    def test_props_are_graded_once_the_seasons_agree(self):
        self.setup_snapshot()
        ns.nflverse_current_season = 2026
        try:
            row = oa.grade_props_history()[0]
            assert row["actual"] == 310
            assert row["result"] is not None
        finally:
            self.teardown()

    @pytest.mark.parametrize("commence,expected", [
        ("2026-09-10T00:15:00Z", 2026),
        ("2027-01-04T01:15:00Z", 2026),   # January belongs to the season before
        ("2027-02-09T23:30:00Z", 2026),   # so does the Super Bowl
        ("2027-09-12T17:00:00Z", 2027),
    ])
    def test_season_is_derived_from_kickoff(self, commence, expected):
        assert oa._season_for_commence(commence) == expected


class TestDevReadThrough:
    def test_an_unprefixed_instance_reads_only_its_own_row(self):
        with patch.object(nfl_helper, "SUPABASE_KEY_PREFIX", ""):
            assert nfl_helper._supabase_read_keys("odds_history") == ["odds_history"]

    def test_a_prefixed_instance_falls_back_to_the_shared_row(self):
        with patch.object(nfl_helper, "SUPABASE_KEY_PREFIX", "dev_"):
            assert nfl_helper._supabase_read_keys("odds_history") == [
                "dev_odds_history", "odds_history",
            ]

    def test_its_own_row_wins_when_present(self):
        """Copy-on-write: once dev has written, it must stop reading production."""
        with patch.object(nfl_helper, "SUPABASE_KEY_PREFIX", "dev_"):
            keys = nfl_helper._supabase_read_keys("tinyurl_data")
        assert keys[0] == "dev_tinyurl_data"
