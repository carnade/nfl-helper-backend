import sys
import pytest
from unittest.mock import patch

nfl_helper = sys.modules["nfl_helper"]

from conftest import make_lineup_string, create_entry


@pytest.fixture
def mock_week(request):
    """Patch FantasyDataScraper.get_current_week. Use request.param to set the week (default 8)."""
    week = getattr(request, "param", 8)
    with patch.object(nfl_helper.FantasyDataScraper, "get_current_week", return_value=week):
        yield week


def do_cleanup(client):
    return client.post("/admin/tinyurl/cleanup")


class TestSingleEntryCleanup:
    def test_deletes_entry_from_past_week(self, client, mock_week):
        create_entry("old", week=7)  # current week is 8 → 7 < 8 → deleted
        resp = do_cleanup(client)
        assert resp.status_code == 200
        assert "old" not in nfl_helper.tinyurl_data

    def test_keeps_entry_for_current_week(self, client, mock_week):
        create_entry("current", week=8)  # 8 >= 8 → kept
        do_cleanup(client)
        assert "current" in nfl_helper.tinyurl_data

    def test_keeps_entry_for_future_week(self, client, mock_week):
        create_entry("future", week=10)  # 10 >= 8 → kept
        do_cleanup(client)
        assert "future" in nfl_helper.tinyurl_data

    def test_deletes_entry_with_no_week(self, client, mock_week):
        nfl_helper.tinyurl_data["noweek"] = {"name": "noweek", "type": "single"}
        do_cleanup(client)
        assert "noweek" not in nfl_helper.tinyurl_data

    def test_cleanup_returns_200(self, client, mock_week):
        resp = do_cleanup(client)
        assert resp.status_code == 200


class TestMultiweekDfsLifecycle:
    def test_calculates_points_and_advances_week(self, client, mock_week):
        create_entry("tourney", week=7, entry_type="multiweek_dfs", num_weeks=4, start_week=7)
        nfl_helper.fantasy_points_data["11111_7"] = {"fantasy_points": 40.0}
        nfl_helper.fantasy_points_data["22222_7"] = {"fantasy_points": 25.0}

        lineup_alice = make_lineup_string(7, ["11111:QB", "22222:RB"])
        lineup_bob = make_lineup_string(7, ["22222:QB", "11111:RB"])
        nfl_helper.tinyurl_data["tourney"]["user_submissions"] = {
            "alice": {"username": "alice", "data": lineup_alice, "update_count": 1},
            "bob":   {"username": "bob",   "data": lineup_bob,   "update_count": 1},
        }

        do_cleanup(client)

        entry = nfl_helper.tinyurl_data.get("tourney")
        assert entry is not None, "multiweek entry should not be deleted mid-tournament"
        assert entry["week"] == 8, "week should advance to 8"
        assert entry["user_submissions"] == {}, "lineup data should be cleared"
        assert "alice" in entry["standings"]
        assert "bob" in entry["standings"]
        assert entry["standings"]["alice"]["total_points"] == pytest.approx(65.0)
        assert entry["standings"]["bob"]["total_points"] == pytest.approx(65.0)

    def test_user_with_no_lineup_gets_zero_points(self, client, mock_week):
        create_entry("tourney", week=7, entry_type="multiweek_dfs", num_weeks=4, start_week=7)
        # alice has no submission (not in user_submissions)
        nfl_helper.tinyurl_data["tourney"]["user_submissions"] = {
            "alice": {"username": "alice", "data": None, "update_count": 0},
        }

        do_cleanup(client)

        entry = nfl_helper.tinyurl_data.get("tourney")
        assert entry is not None
        assert entry["standings"]["alice"]["total_points"] == 0.0

    def test_final_week_enters_grace_not_deleted(self, client, mock_week):
        # end_week = start_week + num_weeks - 1 = 7 + 2 - 1 = 8
        # entry_week(8) < current_week(9) AND entry_week(8) == end_week(8) → grace
        create_entry("tourney", week=8, entry_type="multiweek_dfs", num_weeks=2, start_week=7)
        with patch.object(nfl_helper.FantasyDataScraper, "get_current_week", return_value=9):
            do_cleanup(client)

        entry = nfl_helper.tinyurl_data.get("tourney")
        assert entry is not None, "should be kept for grace week"
        assert entry["week"] == 9, "week advances to grace week"

    def test_grace_week_expired_deletes_entry(self, client, mock_week):
        # end_week = 7 + 2 - 1 = 8; entry_week(9) > end_week(8) → deleted
        create_entry("tourney", week=9, entry_type="multiweek_dfs", num_weeks=2, start_week=7)
        with patch.object(nfl_helper.FantasyDataScraper, "get_current_week", return_value=10):
            do_cleanup(client)

        assert "tourney" not in nfl_helper.tinyurl_data

    def test_mid_tournament_keeps_entry(self, client, mock_week):
        # week=7, num_weeks=4, start_week=7, end_week=10; current=8 → mid-tournament
        create_entry("tourney", week=7, entry_type="multiweek_dfs", num_weeks=4, start_week=7)
        do_cleanup(client)
        assert "tourney" in nfl_helper.tinyurl_data
        assert nfl_helper.tinyurl_data["tourney"]["week"] == 8

    def test_standings_accumulate_across_weeks(self, client, mock_week):
        create_entry("tourney", week=7, entry_type="multiweek_dfs", num_weeks=4, start_week=7)
        # Pre-existing standing from a prior week
        nfl_helper.tinyurl_data["tourney"]["standings"] = {
            "alice": {"total_points": 30.0, "week_points": {6: 30.0}, "last_updated": ""},
        }
        nfl_helper.fantasy_points_data["11111_7"] = {"fantasy_points": 20.0}
        nfl_helper.tinyurl_data["tourney"]["user_submissions"] = {
            "alice": {"username": "alice", "data": make_lineup_string(7, ["11111:QB"]), "update_count": 1},
        }

        do_cleanup(client)

        entry = nfl_helper.tinyurl_data["tourney"]
        assert entry["standings"]["alice"]["week_points"][7] == pytest.approx(20.0)
        assert entry["standings"]["alice"]["total_points"] == pytest.approx(50.0)
