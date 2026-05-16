import sys
import pytest

nfl_helper = sys.modules["nfl_helper"]

from conftest import make_lineup_string, create_entry


class TestCreateEmpty:
    def test_single_success(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "myleague", "names": ["alice", "bob"], "week": 8
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "myleague"
        assert "myleague" in nfl_helper.tinyurl_data

    def test_missing_name_returns_400(self, client):
        resp = client.post("/tinyurl/create/empty", json={"names": ["alice"]})
        assert resp.status_code == 400

    def test_empty_names_list_returns_400(self, client):
        resp = client.post("/tinyurl/create/empty", json={"name": "x", "names": []})
        assert resp.status_code == 400

    def test_invalid_type_returns_400(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "x", "names": ["a"], "type": "badtype"
        })
        assert resp.status_code == 400

    def test_duplicate_name_case_insensitive_returns_400(self, client):
        client.post("/tinyurl/create/empty", json={"name": "League", "names": ["a"]})
        resp = client.post("/tinyurl/create/empty", json={"name": "league", "names": ["b"]})
        assert resp.status_code == 400

    def test_max_10_entries_returns_400(self, client):
        for i in range(10):
            nfl_helper.tinyurl_data[f"entry{i}"] = {"name": f"entry{i}", "week": 8}
        resp = client.post("/tinyurl/create/empty", json={"name": "new", "names": ["a"]})
        assert resp.status_code == 400

    def test_multiweek_requires_num_weeks(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "x", "names": ["a"], "type": "multiweek_dfs", "week": 8
        })
        assert resp.status_code == 400
        assert "num_weeks" in resp.get_json()["error"]

    def test_multiweek_num_weeks_below_2_returns_400(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "x", "names": ["a"], "type": "multiweek_dfs", "week": 8, "num_weeks": 1
        })
        assert resp.status_code == 400

    def test_multiweek_num_weeks_above_18_returns_400(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "x", "names": ["a"], "type": "multiweek_dfs", "week": 8, "num_weeks": 19
        })
        assert resp.status_code == 400

    def test_multiweek_success(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "tourney", "names": ["alice", "bob"],
            "type": "multiweek_dfs", "week": 8, "num_weeks": 4,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["num_weeks"] == 4
        entry = nfl_helper.tinyurl_data["tourney"]
        assert entry["start_week"] == 8
        assert entry["standings"] == {}
        assert entry["num_weeks"] == 4


class TestAddToTinyurl:
    def test_first_submission_success(self, client):
        create_entry("league", week=8, allowed_names=["alice", "bob"])
        lineup = make_lineup_string(8, ["12345:QB"])
        resp = client.post("/tinyurl/league/add", json={
            "name": "alice", "data": lineup, "skip_validation": True
        })
        assert resp.status_code == 200
        assert resp.get_json()["update_count"] == 1

    def test_second_submission_increments_count(self, client):
        create_entry("league", week=8, allowed_names=["alice"])
        lineup = make_lineup_string(8, ["12345:QB"])
        client.post("/tinyurl/league/add", json={"name": "alice", "data": lineup, "skip_validation": True})
        resp = client.post("/tinyurl/league/add", json={"name": "alice", "data": lineup, "skip_validation": True})
        assert resp.status_code == 200
        assert resp.get_json()["update_count"] == 2

    def test_unauthorized_user_returns_401(self, client):
        create_entry("league", week=8, allowed_names=["alice"])
        resp = client.post("/tinyurl/league/add", json={
            "name": "charlie", "data": make_lineup_string(8, ["1:QB"]), "skip_validation": True
        })
        assert resp.status_code == 401

    def test_nonexistent_entry_returns_404(self, client):
        resp = client.post("/tinyurl/ghost/add", json={
            "name": "alice", "data": make_lineup_string(8, ["1:QB"]), "skip_validation": True
        })
        assert resp.status_code == 404

    def test_case_insensitive_username_match(self, client):
        create_entry("league", week=8, allowed_names=["Alice"])
        resp = client.post("/tinyurl/league/add", json={
            "name": "alice", "data": make_lineup_string(8, ["1:QB"]), "skip_validation": True
        })
        assert resp.status_code == 200

    def test_entry_without_allowed_names_returns_400(self, client):
        nfl_helper.tinyurl_data["bare"] = {"name": "bare", "week": 8, "allowed_names": []}
        resp = client.post("/tinyurl/bare/add", json={
            "name": "alice", "data": make_lineup_string(8, ["1:QB"]), "skip_validation": True
        })
        assert resp.status_code == 400


class TestGetTinyurlDetails:
    def test_single_entry_fields(self, client):
        create_entry("league", week=8)
        resp = client.get("/tinyurl/league/details")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["week"] == 8
        assert data["type"] == "single"
        assert "allowed_names" in data

    def test_multiweek_includes_num_weeks_and_start_week(self, client):
        create_entry("tourney", week=8, entry_type="multiweek_dfs", num_weeks=4, start_week=8)
        resp = client.get("/tinyurl/tourney/details")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["type"] == "multiweek_dfs"
        assert data["num_weeks"] == 4
        assert data["start_week"] == 8

    def test_nonexistent_returns_404(self, client):
        resp = client.get("/tinyurl/ghost/details")
        assert resp.status_code == 404

    def test_case_insensitive_name_lookup(self, client):
        create_entry("League", week=8)
        resp = client.get("/tinyurl/LEAGUE/details")
        assert resp.status_code == 200


class TestStandings:
    def test_single_type_returns_400(self, client):
        create_entry("league", week=8, entry_type="single")
        resp = client.get("/tinyurl/league/standings")
        assert resp.status_code == 400

    def test_nonexistent_returns_404(self, client):
        resp = client.get("/tinyurl/ghost/standings")
        assert resp.status_code == 404

    def test_empty_standings_returns_empty_list(self, client):
        create_entry("tourney", week=8, entry_type="multiweek_dfs", num_weeks=3)
        resp = client.get("/tinyurl/tourney/standings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["standings"] == []
        assert data["count"] == 0

    def test_sorted_descending_by_total_points(self, client):
        create_entry("tourney", week=9, entry_type="multiweek_dfs", num_weeks=3)
        nfl_helper.tinyurl_data["tourney"]["standings"] = {
            "alice": {"total_points": 100.0, "week_points": {8: 100.0}, "last_updated": ""},
            "bob":   {"total_points": 150.0, "week_points": {8: 150.0}, "last_updated": ""},
            "carol": {"total_points": 80.0,  "week_points": {8: 80.0},  "last_updated": ""},
        }
        resp = client.get("/tinyurl/tourney/standings")
        assert resp.status_code == 200
        standings = resp.get_json()["standings"]
        totals = [s["total_points"] for s in standings]
        assert totals == sorted(totals, reverse=True)
        assert standings[0]["username"] == "bob"


class TestDeleteAndList:
    def test_delete_existing_entry(self, client):
        create_entry("league")
        resp = client.delete("/tinyurl/league")
        assert resp.status_code == 200
        assert "league" not in nfl_helper.tinyurl_data

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/tinyurl/ghost")
        assert resp.status_code == 404

    def test_delete_case_insensitive(self, client):
        create_entry("League")
        resp = client.delete("/tinyurl/LEAGUE")
        assert resp.status_code == 200

    def test_list_empty(self, client):
        resp = client.get("/tinyurl/list")
        assert resp.status_code == 200
        assert resp.get_json()["total_entries"] == 0

    def test_list_returns_all_entries(self, client):
        create_entry("league1")
        create_entry("league2")
        resp = client.get("/tinyurl/list")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_entries"] == 2
        names = [e["name"] for e in data["entries"]]
        assert "league1" in names
        assert "league2" in names
