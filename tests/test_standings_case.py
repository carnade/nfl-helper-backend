"""One entrant, one row — whatever capitalisation they typed that week.

user_submissions has always been keyed by the normalized name, but standings
were keyed by whatever the entrant wrote. Entering as "Redhelge" one week and
"redhelge" the next opened a second row and split the season across the two,
which reads wrong and ranks them below people they are in fact beating.

Seen in production: Hovås5weekTest had 'redhelge' holding week 1 (159.70) and
'Redhelge' holding week 2 (177.48) instead of one row on 337.18.
"""

import sys
from unittest.mock import patch

import pytest

nfl_helper = sys.modules["nfl_helper"]

from conftest import make_lineup_string, create_entry


@pytest.fixture(autouse=True)
def no_kickoff_check():
    with patch.object(nfl_helper, "validate_lineup_players_not_started",
                      return_value=(True, None, [])):
        yield


def _submit(name, username, week, lineup):
    """File a lineup the way the add route does: submissions keyed normalized."""
    entry = nfl_helper.tinyurl_data[name]
    entry["user_submissions"][nfl_helper.normalize_tinyurl_name(username)] = {
        "username": username,
        "data": make_lineup_string(week, lineup),
    }


def _score(week_now):
    with patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=week_now), \
         patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={"11111": 10.0}):
        nfl_helper.score_multiweek_tinyurls()


class TestScoringAcrossWeeks:
    def test_changing_capitalisation_keeps_one_row(self):
        name = create_entry("cup", week=1, entry_type="multiweek_dfs", num_weeks=4, start_week=1)

        _submit(name, "Redhelge", 1, ["11111-5000"])
        _score(2)

        # Week two, same person, lower case this time.
        nfl_helper.tinyurl_data[name]["week"] = 2
        _submit(name, "redhelge", 2, ["11111-5000", "11111-5000"])
        _score(3)

        standings = nfl_helper.tinyurl_data[name]["standings"]
        assert list(standings) == ["redhelge"], "one entrant, one row"
        assert standings["redhelge"]["week_points"] == {"1": 10.0, "2": 20.0}
        assert standings["redhelge"]["total_points"] == 30.0

    def test_the_name_is_shown_as_last_typed(self):
        name = create_entry("cup", week=1, entry_type="multiweek_dfs", num_weeks=4, start_week=1)

        _submit(name, "redhelge", 1, ["11111-5000"])
        _score(2)
        nfl_helper.tinyurl_data[name]["week"] = 2
        _submit(name, "RedHelge", 2, ["11111-5000"])
        _score(3)

        assert nfl_helper.tinyurl_data[name]["standings"]["redhelge"]["display_name"] == "RedHelge"

    def test_different_people_still_get_their_own_rows(self):
        name = create_entry("cup", week=1, entry_type="multiweek_dfs", num_weeks=4, start_week=1)

        _submit(name, "Redhelge", 1, ["11111-5000"])
        _submit(name, "carnade", 1, ["11111-5000"])
        _score(2)

        assert set(nfl_helper.tinyurl_data[name]["standings"]) == {"redhelge", "carnade"}


class TestMigratingExistingData:
    """Rows written before the key was normalized still have to be folded in."""

    def _split(self):
        name = create_entry("cup", week=2, entry_type="multiweek_dfs", num_weeks=5, start_week=1)
        nfl_helper.tinyurl_data[name]["standings"] = {
            "carnade":  {"total_points": 253.72, "week_points": {"1": 131.74, "2": 121.98},
                         "last_updated": "2026-09-23T06:00:01"},
            "redhelge": {"total_points": 159.70, "week_points": {"1": 159.70},
                         "last_updated": "2026-09-16T06:00:01"},
            "Redhelge": {"total_points": 177.48, "week_points": {"2": 177.48},
                         "last_updated": "2026-09-23T06:00:01"},
        }
        return name

    def test_the_two_rows_become_one(self):
        name = self._split()

        merged = nfl_helper.merge_case_split_standings(nfl_helper.tinyurl_data)

        assert merged == 1
        standings = nfl_helper.tinyurl_data[name]["standings"]
        assert set(standings) == {"carnade", "redhelge"}
        assert standings["redhelge"]["week_points"] == {"1": 159.70, "2": 177.48}
        assert standings["redhelge"]["total_points"] == pytest.approx(337.18)

    def test_the_newer_capitalisation_is_kept_for_display(self):
        name = self._split()
        nfl_helper.merge_case_split_standings(nfl_helper.tinyurl_data)

        assert nfl_helper.tinyurl_data[name]["standings"]["redhelge"]["display_name"] == "Redhelge"

    def test_an_untouched_entrant_is_left_exactly_as_it_was(self):
        name = self._split()
        nfl_helper.merge_case_split_standings(nfl_helper.tinyurl_data)

        carnade = nfl_helper.tinyurl_data[name]["standings"]["carnade"]
        assert carnade["week_points"] == {"1": 131.74, "2": 121.98}
        assert carnade["total_points"] == pytest.approx(253.72)

    def test_the_newer_row_wins_a_week_they_both_hold(self):
        """Only a rescore produces this, and the later pass is the right answer."""
        name = create_entry("cup", week=2, entry_type="multiweek_dfs")
        nfl_helper.tinyurl_data[name]["standings"] = {
            "user": {"total_points": 50.0, "week_points": {"1": 50.0},
                     "last_updated": "2026-09-16T06:00:01"},
            "User": {"total_points": 80.0, "week_points": {"1": 80.0},
                     "last_updated": "2026-09-23T06:00:01"},
        }

        nfl_helper.merge_case_split_standings(nfl_helper.tinyurl_data)

        assert nfl_helper.tinyurl_data[name]["standings"]["user"]["week_points"] == {"1": 80.0}

    def test_clean_standings_are_reported_as_unchanged(self):
        create_entry("cup", week=2, entry_type="multiweek_dfs")
        nfl_helper.tinyurl_data["cup"]["standings"] = {
            "carnade": {"total_points": 10.0, "week_points": {"1": 10.0}, "last_updated": "x"},
        }

        assert nfl_helper.merge_case_split_standings(nfl_helper.tinyurl_data) == 0

    def test_entries_without_standings_are_ignored(self):
        create_entry("single_entry", week=2)

        assert nfl_helper.merge_case_split_standings(nfl_helper.tinyurl_data) == 0


class TestEndpoints:
    def test_standings_returns_one_row_with_the_typed_name(self, client):
        name = create_entry("cup", week=2, entry_type="multiweek_dfs")
        nfl_helper.tinyurl_data[name]["standings"] = {
            "redhelge": {"total_points": 337.18, "week_points": {"1": 159.70, "2": 177.48},
                         "display_name": "Redhelge", "last_updated": "2026-09-23T06:00:01"},
        }

        body = client.get("/tinyurl/cup/standings").get_json()

        assert body["count"] == 1
        assert body["standings"][0]["username"] == "Redhelge"
        assert body["standings"][0]["total_points"] == pytest.approx(337.18)

    def test_an_old_row_without_a_display_name_still_shows_something(self, client):
        name = create_entry("cup", week=2, entry_type="multiweek_dfs")
        nfl_helper.tinyurl_data[name]["standings"] = {
            "carnade": {"total_points": 1.0, "week_points": {"1": 1.0}, "last_updated": "x"},
        }

        body = client.get("/tinyurl/cup/standings").get_json()

        assert body["standings"][0]["username"] == "carnade"

    def test_set_points_finds_the_row_whatever_the_caps(self, client):
        name = create_entry("cup", week=2, entry_type="multiweek_dfs")
        nfl_helper.tinyurl_data[name]["standings"] = {
            "redhelge": {"total_points": 159.70, "week_points": {"1": 159.70},
                         "display_name": "redhelge", "last_updated": "x"},
        }

        with patch.object(nfl_helper, "verify_sleeper_token",
                          return_value={"user_id": "1", "display_name": "carnade"}):
            resp = client.post("/tinyurl/cup/set-points",
                               json={"username": "RedHelge", "week": 2, "points": 177.48},
                               headers={"Authorization": "tok"})

        assert resp.status_code == 200, resp.get_json()
        standings = nfl_helper.tinyurl_data[name]["standings"]
        assert set(standings) == {"redhelge"}, "no second row for the same person"
        assert standings["redhelge"]["total_points"] == pytest.approx(337.18)
