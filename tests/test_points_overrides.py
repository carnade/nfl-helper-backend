"""An organiser can state a player's points for a week, above every other source.

A player rostered in neither scoring league scores 0 with no error, and Sleeper
never backfills a settled week — which is how Carson Wentz came to be worth
nothing in a week he actually played. An override fixes the input rather than the
total, so it reaches both the displayed points and the multiweek standings.

It only bites on a week not yet scored: scoring wipes the lineups it read, so a
settled week cannot be recomputed from them.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

nfl_helper = sys.modules["nfl_helper"]

from conftest import make_lineup_string, create_entry


@pytest.fixture(autouse=True)
def no_kickoff_check():
    with patch.object(nfl_helper, "validate_lineup_players_not_started",
                      return_value=(True, None, [])):
        yield


@pytest.fixture
def organiser():
    """Every mutating route is organiser-gated."""
    with patch.object(nfl_helper, "verify_sleeper_token",
                      return_value={"user_id": "1", "display_name": "carnade"}) as stub:
        yield stub


@pytest.fixture(autouse=True)
def current_week():
    """Week 7 is live, so an override for week 7 is still in time."""
    with patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=7):
        yield


def auth():
    return {"Authorization": "tok"}


class TestPrecedence:
    """The override outranks Sleeper's matchup points and the FantasyData scrape."""

    def test_override_beats_both_sources(self):
        nfl_helper.points_overrides["11111_7"] = {"sleeper_id": "11111", "week": 7, "points": 25.0}
        nfl_helper.fantasy_points_data["11111_7"] = {"fantasy_points": 40.0}

        total = nfl_helper.calculate_dfs_points_from_lineup(
            make_lineup_string(7, ["11111-5000"]), 7, {"11111": 18.0})

        assert total == 25.0

    def test_zero_is_a_real_score(self):
        """The fantasy-data lookup drops a 0.0 through a truthiness test; an
        override must not inherit that — 0 is a statement, not an absence."""
        nfl_helper.points_overrides["11111_7"] = {"sleeper_id": "11111", "week": 7, "points": 0.0}

        total = nfl_helper.calculate_dfs_points_from_lineup(
            make_lineup_string(7, ["11111-5000"]), 7, {"11111": 18.0})

        assert total == 0.0

    def test_negative_is_kept(self):
        nfl_helper.points_overrides["11111_7"] = {"sleeper_id": "11111", "week": 7, "points": -2.0}

        total = nfl_helper.calculate_dfs_points_from_lineup(
            make_lineup_string(7, ["11111-5000"]), 7, {"11111": 18.0})

        assert total == -2.0

    def test_other_players_are_untouched(self):
        nfl_helper.points_overrides["11111_7"] = {"sleeper_id": "11111", "week": 7, "points": 5.0}

        total = nfl_helper.calculate_dfs_points_from_lineup(
            make_lineup_string(7, ["11111-5000", "22222-4000"]), 7,
            {"11111": 18.0, "22222": 12.0})

        assert total == 17.0

    def test_a_defence_can_be_overridden(self):
        nfl_helper.points_overrides["CHI_7"] = {"sleeper_id": "CHI", "week": 7, "points": 14.0}

        total = nfl_helper.calculate_dfs_points_from_lineup(
            make_lineup_string(7, ["CHI-3000"]), 7, {"CHI": 3.0})

        assert total == 14.0

    def test_a_different_week_is_not_affected(self):
        nfl_helper.points_overrides["11111_8"] = {"sleeper_id": "11111", "week": 8, "points": 99.0}

        total = nfl_helper.calculate_dfs_points_from_lineup(
            make_lineup_string(7, ["11111-5000"]), 7, {"11111": 18.0})

        assert total == 18.0


class TestScoringUsesIt:
    def test_the_weekly_pass_scores_with_the_override(self):
        create_entry("cup", week=7, entry_type="multiweek_dfs", num_weeks=4, start_week=7)
        nfl_helper.tinyurl_data["cup"]["user_submissions"] = {
            "alice": {"username": "alice", "data": make_lineup_string(7, ["11111-5000"])}
        }
        nfl_helper.points_overrides["11111_7"] = {"sleeper_id": "11111", "week": 7, "points": 31.0}

        with patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=8), \
             patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={"11111": 4.0}):
            nfl_helper.score_multiweek_tinyurls()

        standings = nfl_helper.tinyurl_data["cup"]["standings"]["alice"]
        assert standings["week_points"]["7"] == 31.0
        assert standings["total_points"] == 31.0


class TestPruning:
    def _override(self, week):
        nfl_helper.points_overrides[f"11111_{week}"] = {
            "sleeper_id": "11111", "week": week, "points": 10.0}

    def test_the_scoring_pass_keeps_them(self):
        """Wednesday scores but deletes nothing, so results pages stay whole until
        Thursday. Dropping an override here would strip it from the display while
        the standings it produced kept it."""
        self._override(7)

        with patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=8):
            nfl_helper.score_multiweek_tinyurls()

        assert "11111_7" in nfl_helper.points_overrides

    def test_the_deleting_pass_drops_spent_ones(self):
        self._override(7)
        self._override(8)

        with patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=8), \
             patch.object(nfl_helper, "save_points_overrides"):
            nfl_helper.clear_tinyurl_data()

        assert "11111_7" not in nfl_helper.points_overrides
        assert "11111_8" in nfl_helper.points_overrides, "the live week is still to come"


class TestEndpoints:
    def test_set_list_and_delete(self, client, organiser):
        resp = client.post("/points-overrides",
                           json={"sleeper_id": "3161", "week": 7, "points": 6.3},
                           headers=auth())
        assert resp.status_code == 200, resp.get_json()

        listed = client.get("/points-overrides/week/7").get_json()
        assert listed["overrides"] == {"3161": 6.3}

        assert client.delete("/points-overrides/3161/7", headers=auth()).status_code == 200
        assert client.get("/points-overrides/week/7").get_json()["overrides"] == {}

    def test_reading_needs_no_token(self, client):
        """Entrants see the results page too, not just whoever set the override."""
        assert client.get("/points-overrides/week/7").status_code == 200

    def test_setting_requires_an_organiser(self, client, organiser):
        organiser.return_value = {"user_id": "2", "display_name": "bob"}
        resp = client.post("/points-overrides",
                           json={"sleeper_id": "3161", "week": 7, "points": 6.3},
                           headers=auth())
        assert resp.status_code == 403
        assert nfl_helper.points_overrides == {}

    def test_setting_requires_a_token_at_all(self, client, organiser):
        organiser.return_value = None
        assert client.post("/points-overrides",
                           json={"sleeper_id": "3161", "week": 7, "points": 6.3}).status_code == 403

    def test_deleting_requires_an_organiser(self, client, organiser):
        nfl_helper.points_overrides["3161_7"] = {"sleeper_id": "3161", "week": 7, "points": 6.3}
        organiser.return_value = {"user_id": "2", "display_name": "bob"}
        assert client.delete("/points-overrides/3161/7", headers=auth()).status_code == 403
        assert "3161_7" in nfl_helper.points_overrides

    def test_a_settled_week_is_refused(self, client, organiser):
        """Scoring wiped the lineups, so an override there could never apply."""
        resp = client.post("/points-overrides",
                           json={"sleeper_id": "3161", "week": 5, "points": 6.3},
                           headers=auth())
        assert resp.status_code == 400
        assert "already been scored" in resp.get_json()["error"]

    def test_zero_is_accepted(self, client, organiser):
        resp = client.post("/points-overrides",
                           json={"sleeper_id": "3161", "week": 7, "points": 0},
                           headers=auth())
        assert resp.status_code == 200
        assert nfl_helper.points_overrides["3161_7"]["points"] == 0.0

    def test_nonsense_is_rejected(self, client, organiser):
        bad = [
            {"sleeper_id": "", "week": 7, "points": 1},
            {"sleeper_id": "notaplayer", "week": 7, "points": 1},
            {"sleeper_id": "3161", "week": "seven", "points": 1},
            {"sleeper_id": "3161", "week": 7, "points": "lots"},
            {"sleeper_id": "3161", "week": 7, "points": True},
        ]
        for body in bad:
            assert client.post("/points-overrides", json=body, headers=auth()).status_code == 400, body

    def test_deleting_something_absent_is_a_404(self, client, organiser):
        assert client.delete("/points-overrides/3161/7", headers=auth()).status_code == 404


class TestSetPointsIsGated:
    def test_it_no_longer_accepts_anonymous_writes(self, client, organiser):
        """It rewrites standings directly and was reachable by anyone."""
        create_entry("cup", week=7, entry_type="multiweek_dfs")
        organiser.return_value = None

        resp = client.post("/tinyurl/cup/set-points",
                           json={"username": "alice", "week": 7, "points": 100.0})

        assert resp.status_code == 403
