"""
tests/test_stats.py — Tests for nflverse stats pipeline and /stats/* endpoints.

Uses in-memory fake data so no network calls are made in tests.
"""

import sys
import pytest
import pandas as pd

import nflverse_stats as ns

nfl_helper = sys.modules["nfl_helper"]


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _make_stats_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal player_stats DataFrame from a list of row dicts."""
    defaults = {
        "season_type": "REG",
        "season": 2024,
        "week": 1,
        "player_id": "00-0001234",
        "player_display_name": "Test Player",
        "position": "WR",
        "position_group": "WR",
        "recent_team": "MIN",
        "headshot_url": "",
        "completions": 0.0, "attempts": 0.0,
        "passing_yards": 0.0, "passing_tds": 0.0, "interceptions": 0.0,
        "carries": 0.0, "rushing_yards": 0.0, "rushing_tds": 0.0,
        "receptions": 5.0, "targets": 8.0,
        "receiving_yards": 80.0, "receiving_tds": 1.0,
        "target_share": 0.25, "air_yards_share": 0.30,
        "wopr": 0.55, "racr": 0.85,
        "fantasy_points": 18.0, "fantasy_points_ppr": 23.0,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _make_games_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal games DataFrame."""
    defaults = {
        "game_type": "REG",
        "season": 2024,
        "week": 1,
        "home_team": "MIN",
        "away_team": "GB",
        "spread_line": -3.0,
        "total_line": 47.5,
        "gameday": "2024-09-08",
        "home_score": None,
        "away_score": None,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


@pytest.fixture(autouse=True)
def clear_nflverse():
    """Reset all nflverse in-memory dicts before every test."""
    ns.nflverse_player_stats.clear()
    ns.nflverse_team_stats.clear()
    ns.nflverse_schedule.clear()
    ns.nflverse_games.clear()
    ns.nflverse_current_season = None
    ns.nflverse_last_updated = None
    yield
    ns.nflverse_player_stats.clear()
    ns.nflverse_team_stats.clear()
    ns.nflverse_schedule.clear()
    ns.nflverse_games.clear()


# ── build_id_map (unit, no network) ──────────────────────────────────────────

class TestBuildIdMap:
    def test_builds_gsis_to_sleeper_map(self):
        df = pd.DataFrame([
            {"gsis_id": "00-0001234", "sleeper_id": "999"},
            {"gsis_id": "00-0005678", "sleeper_id": "888"},
        ])
        from unittest.mock import patch
        with patch.object(ns, "_fetch_parquet", return_value=df):
            result = ns.build_id_map(2025)
        assert result["00-0001234"] == "999"
        assert result["00-0005678"] == "888"

    def test_skips_rows_missing_sleeper_id(self):
        df = pd.DataFrame([
            {"gsis_id": "00-0001234", "sleeper_id": None},
            {"gsis_id": "00-0005678", "sleeper_id": "888"},
        ])
        from unittest.mock import patch
        with patch.object(ns, "_fetch_parquet", return_value=df):
            result = ns.build_id_map(2025)
        assert "00-0001234" not in result
        assert "00-0005678" in result


# ── build_player_stats_dict ───────────────────────────────────────────────────

class TestBuildPlayerStatsDict:
    def test_maps_gsis_to_sleeper_id(self):
        df = _make_stats_df([{"player_id": "00-0001234", "week": 1}])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert "999" in result

    def test_player_not_in_id_map_excluded(self):
        df = _make_stats_df([{"player_id": "00-0099999"}])
        result = ns.build_player_stats_dict(df, {})
        assert result == {}

    def test_non_skill_position_excluded(self):
        df = _make_stats_df([{"player_id": "00-0001234", "position": "OL"}])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert "999" not in result

    def test_weekly_list_ordered_by_week(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": 3, "fantasy_points_ppr": 10.0},
            {"player_id": "00-0001234", "week": 1, "fantasy_points_ppr": 20.0},
            {"player_id": "00-0001234", "week": 2, "fantasy_points_ppr": 15.0},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        weeks = [w["week"] for w in result["999"]["weekly"]]
        assert weeks == [1, 2, 3]

    def test_season_totals_sum_fantasy_points(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": 1, "fantasy_points_ppr": 20.0},
            {"player_id": "00-0001234", "week": 2, "fantasy_points_ppr": 30.0},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result["999"]["season_totals"]["fantasy_points_ppr"] == pytest.approx(50.0)

    def test_season_totals_average_target_share(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": 1, "target_share": 0.2},
            {"player_id": "00-0001234", "week": 2, "target_share": 0.4},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result["999"]["season_totals"]["target_share"] == pytest.approx(0.3, abs=1e-3)

    def test_rolling_3_uses_last_3_weeks(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": w, "fantasy_points_ppr": float(w * 10)}
            for w in range(1, 6)  # weeks 1-5: 10, 20, 30, 40, 50
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        # last 3 weeks = 30+40+50 / 3 = 40.0
        assert result["999"]["rolling_3"]["fantasy_points_ppr"] == pytest.approx(40.0)

    def test_uses_most_recent_season(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": 1, "season": 2023, "fantasy_points_ppr": 5.0},
            {"player_id": "00-0001234", "week": 1, "season": 2024, "fantasy_points_ppr": 30.0},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result["999"]["season"] == 2024
        assert result["999"]["season_totals"]["fantasy_points_ppr"] == pytest.approx(30.0)

    def test_preseason_rows_excluded(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": 1, "season_type": "PRE"},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result == {}


# ── build_team_stats_dict ─────────────────────────────────────────────────────

class TestBuildTeamStatsDict:
    def test_targets_per_game(self):
        df = _make_stats_df([
            {"recent_team": "MIN", "week": 1, "targets": 10.0},
            {"recent_team": "MIN", "week": 2, "targets": 8.0},
        ])
        result = ns.build_team_stats_dict(df)
        assert result["MIN"]["targets_per_game"] == pytest.approx(9.0)

    def test_pass_attempts_per_game_only_from_qbs(self):
        df = _make_stats_df([
            {"recent_team": "KC", "week": 1, "position": "QB", "attempts": 35.0},
            {"recent_team": "KC", "week": 1, "position": "WR", "attempts": 0.0},
        ])
        result = ns.build_team_stats_dict(df)
        assert result["KC"]["pass_attempts_per_game"] == pytest.approx(35.0)

    def test_games_played_count(self):
        df = _make_stats_df([
            {"recent_team": "GB", "week": 1},
            {"recent_team": "GB", "week": 2},
            {"recent_team": "GB", "week": 3},
        ])
        result = ns.build_team_stats_dict(df)
        assert result["GB"]["games_played"] == 3


# ── build_schedule_dicts ──────────────────────────────────────────────────────

class TestBuildScheduleDicts:
    def test_games_by_week_populated(self):
        df = _make_games_df([{"week": 5, "home_team": "MIN", "away_team": "GB"}])
        _, games = ns.build_schedule_dicts(df)
        assert 5 in games
        assert games[5][0]["home_team"] == "MIN"

    def test_team_schedule_home_team(self):
        df = _make_games_df([{"week": 5, "home_team": "MIN", "away_team": "GB"}])
        schedule, _ = ns.build_schedule_dicts(df)
        assert schedule["MIN"]["is_home"] is True
        assert schedule["MIN"]["opponent"] == "GB"

    def test_team_schedule_away_team_inverts_spread(self):
        df = _make_games_df([{"week": 5, "home_team": "MIN", "away_team": "GB", "spread_line": -3.0}])
        schedule, _ = ns.build_schedule_dicts(df)
        assert schedule["GB"]["is_home"] is False
        assert schedule["GB"]["spread"] == pytest.approx(3.0)

    def test_non_reg_games_excluded(self):
        df = _make_games_df([
            {"week": 1, "game_type": "POST", "home_team": "KC", "away_team": "BUF"},
        ])
        schedule, games = ns.build_schedule_dicts(df)
        assert not games
        assert "KC" not in schedule

    def test_scores_none_when_not_played(self):
        df = _make_games_df([{"week": 8, "home_score": None, "away_score": None}])
        _, games = ns.build_schedule_dicts(df)
        game = games[8][0]
        assert game["home_score"] is None
        assert game["away_score"] is None


# ── get_top_players ───────────────────────────────────────────────────────────

class TestGetTopPlayers:
    def _populate(self):
        ns.nflverse_player_stats.update({
            "1": {"name": "Alice", "position": "WR", "team": "MIN", "season_totals": {"fantasy_points_ppr": 200.0}, "weekly": [], "rolling_3": {}, "rolling_5": {}},
            "2": {"name": "Bob", "position": "QB", "team": "KC", "season_totals": {"fantasy_points_ppr": 350.0}, "weekly": [], "rolling_3": {}, "rolling_5": {}},
            "3": {"name": "Carol", "position": "WR", "team": "MIN", "season_totals": {"fantasy_points_ppr": 150.0}, "weekly": [], "rolling_3": {}, "rolling_5": {}},
        })

    def test_sorted_descending_by_ppr(self):
        self._populate()
        result = ns.get_top_players(10)
        totals = [p["season_totals"]["fantasy_points_ppr"] for p in result]
        assert totals == sorted(totals, reverse=True)

    def test_position_filter(self):
        self._populate()
        result = ns.get_top_players(10, position="WR")
        assert all(p["position"] == "WR" for p in result)

    def test_team_filter(self):
        self._populate()
        result = ns.get_top_players(10, team="MIN")
        assert all(p["team"] == "MIN" for p in result)

    def test_limit_respected(self):
        self._populate()
        result = ns.get_top_players(2)
        assert len(result) <= 2


# ── project_player ─────────────────────────────────────────────────────────────

class TestProjectPlayer:
    def _add_player(self, sleeper_id="999", rolling5_ppr=20.0, team="MIN"):
        ns.nflverse_player_stats[sleeper_id] = {
            "name": "Test Player", "position": "WR", "team": team,
            "season_totals": {}, "weekly": [],
            "rolling_3": {"fantasy_points_ppr": 18.0},
            "rolling_5": {"fantasy_points_ppr": rolling5_ppr},
        }

    def test_returns_empty_for_unknown_player(self):
        assert ns.project_player("doesnotexist", 8) == {}

    def test_base_projection_from_rolling_5(self):
        self._add_player(rolling5_ppr=25.0)
        proj = ns.project_player("999", 8)
        assert proj["rolling_5_ppr"] == pytest.approx(25.0)

    def test_projection_uses_opponent_total_adjustment(self):
        self._add_player(rolling5_ppr=20.0, team="MIN")
        # High-scoring game (total=54) → adj > 1.0
        ns.nflverse_schedule["MIN"] = {"week": 8, "opponent": "GB", "spread": -3.0, "total": 54.0}
        proj = ns.project_player("999", 8)
        assert proj["projected_ppr"] > 20.0

    def test_adjustment_capped_at_15_percent(self):
        self._add_player(rolling5_ppr=20.0, team="MIN")
        # Extreme total → adj capped
        ns.nflverse_schedule["MIN"] = {"week": 8, "opponent": "GB", "spread": 0.0, "total": 100.0}
        proj = ns.project_player("999", 8)
        assert proj["projected_ppr"] <= 20.0 * 1.15 + 0.01

    def test_no_adjustment_when_wrong_week(self):
        self._add_player(rolling5_ppr=20.0, team="MIN")
        ns.nflverse_schedule["MIN"] = {"week": 9, "opponent": "GB", "spread": -3.0, "total": 54.0}
        proj = ns.project_player("999", 8)  # week 8 ≠ schedule week 9
        assert proj["adjustment_factor"] == pytest.approx(1.0)


# ── /stats/* endpoints ─────────────────────────────────────────────────────────

class TestStatsEndpoints:
    def _populate_player(self, sleeper_id="111", position="WR", team="MIN", week=8):
        ns.nflverse_player_stats[sleeper_id] = {
            "name": "Test", "position": position, "team": team, "season": 2024,
            "gsis_id": "00-0001", "headshot_url": "",
            "season_totals": {"fantasy_points_ppr": 200.0, "games_played": 10},
            "weekly": [{"week": week, "fantasy_points_ppr": 25.0, "targets": 8.0}],
            "rolling_3": {"fantasy_points_ppr": 22.0},
            "rolling_5": {"fantasy_points_ppr": 21.0},
        }

    def test_status_returns_200(self, client):
        resp = client.get("/stats/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "last_updated" in data
        assert "player_count" in data

    def test_list_players_empty(self, client):
        resp = client.get("/stats/players")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_list_players_returns_sorted_players(self, client):
        self._populate_player("111", week=1)
        ns.nflverse_player_stats["222"] = {
            "name": "Other", "position": "QB", "team": "KC", "season": 2024,
            "gsis_id": "00-0002", "headshot_url": "",
            "season_totals": {"fantasy_points_ppr": 400.0, "games_played": 10},
            "weekly": [], "rolling_3": {}, "rolling_5": {},
        }
        resp = client.get("/stats/players")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data[0]["season_totals"]["fantasy_points_ppr"] == 400.0

    def test_list_players_position_filter(self, client):
        self._populate_player("111", position="WR", week=1)
        self._populate_player("222", position="QB", week=1)
        ns.nflverse_player_stats["222"]["name"] = "QB Player"
        resp = client.get("/stats/players?position=WR")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(p["position"] == "WR" for p in data)

    def test_list_players_by_week(self, client):
        self._populate_player("111", week=8)
        resp = client.get("/stats/players?week=8")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["week"] == 8

    def test_players_by_team(self, client):
        self._populate_player("111", team="MIN", week=1)
        self._populate_player("222", team="KC", week=1)
        ns.nflverse_player_stats["222"]["name"] = "KC Player"
        resp = client.get("/stats/players/team/MIN")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(p["team"] == "MIN" for p in data)

    def test_player_detail_returns_full_data(self, client):
        self._populate_player("111")
        resp = client.get("/stats/player/111")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sleeper_id"] == "111"
        assert "weekly" in data
        assert "season_totals" in data

    def test_player_detail_404_unknown(self, client):
        resp = client.get("/stats/player/doesnotexist")
        assert resp.status_code == 404

    def test_week_returns_players_in_that_week(self, client):
        self._populate_player("111", week=8)
        resp = client.get("/stats/week/8")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "111" in data

    def test_week_404_when_no_data(self, client):
        resp = client.get("/stats/week/99")
        assert resp.status_code == 404

    def test_projections_returns_list(self, client):
        self._populate_player("111", week=1)
        resp = client.get("/stats/projections/week/8")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "projected_ppr" in data[0]

    def test_schedule_returns_games(self, client):
        ns.nflverse_games[8] = [{"home_team": "MIN", "away_team": "GB",
                                   "spread_line": -3.0, "total_line": 47.5,
                                   "gameday": "2024-10-20", "home_score": None, "away_score": None}]
        ns.nflverse_current_season = 2024
        resp = client.get("/stats/schedule/8")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["week"] == 8
        assert len(data["games"]) == 1

    def test_schedule_404_unknown_week(self, client):
        resp = client.get("/stats/schedule/99")
        assert resp.status_code == 404

    def test_team_stats_returns_data(self, client):
        ns.nflverse_team_stats["MIN"] = {
            "season": 2024, "games_played": 17,
            "targets_per_game": 35.0, "pass_attempts_per_game": 36.0,
            "rush_attempts_per_game": 26.0, "ppr_points_per_game": 110.0,
        }
        resp = client.get("/stats/team/MIN")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["team"] == "MIN"
        assert data["games_played"] == 17

    def test_team_stats_case_insensitive(self, client):
        ns.nflverse_team_stats["MIN"] = {"season": 2024, "games_played": 17,
            "targets_per_game": 35.0, "pass_attempts_per_game": 36.0,
            "rush_attempts_per_game": 26.0, "ppr_points_per_game": 110.0}
        resp = client.get("/stats/team/min")
        assert resp.status_code == 200

    def test_team_stats_404_unknown(self, client):
        resp = client.get("/stats/team/UNKNOWN")
        assert resp.status_code == 404
