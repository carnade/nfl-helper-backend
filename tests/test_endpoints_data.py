import sys
import pytest

nfl_helper = sys.modules["nfl_helper"]


class TestHealthCheck:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200


class TestFantasyPointsWeek:
    def test_returns_data_for_requested_week(self, client):
        nfl_helper.fantasy_points_data["111_8"] = {
            "sleeper_id": "111", "fantasy_points": 30.0, "week": 8
        }
        nfl_helper.fantasy_points_data["222_9"] = {
            "sleeper_id": "222", "fantasy_points": 25.0, "week": 9
        }
        resp = client.get("/fantasy-points/week/8")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "111" in data
        assert "222" not in data

    def test_empty_returns_200_with_empty_dict(self, client):
        resp = client.get("/fantasy-points/week/8")
        assert resp.status_code == 200
        assert resp.get_json() == {}

    def test_week_9_filtered_correctly(self, client):
        nfl_helper.fantasy_points_data["111_8"] = {"sleeper_id": "111", "fantasy_points": 20.0, "week": 8}
        nfl_helper.fantasy_points_data["333_9"] = {"sleeper_id": "333", "fantasy_points": 18.0, "week": 9}
        resp = client.get("/fantasy-points/week/9")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "333" in data
        assert "111" not in data


class TestDfsSalariesWeek:
    def test_returns_data_for_requested_week(self, client):
        nfl_helper.dfs_salaries_data["abc_W8"] = {"sleeper_id": "abc", "salary": 7500, "week": 8}
        nfl_helper.dfs_salaries_data["def_W9"] = {"sleeper_id": "def", "salary": 6000, "week": 9}
        resp = client.get("/dfs-salaries/week/8")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "abc_W8" in data
        assert "def_W9" not in data

    def test_no_data_returns_404(self, client):
        resp = client.get("/dfs-salaries/week/99")
        assert resp.status_code == 404
