"""
tests/test_stats.py — Tests for nflverse stats pipeline and /stats/* endpoints.

Uses in-memory fake data — no network calls are made.
"""

import sys
import pytest
import pandas as pd

import nflreadpy as nfl
import nflverse_stats as ns

nfl_helper = sys.modules["nfl_helper"]


# ── DataFrame helpers ─────────────────────────────────────────────────────────

def _make_stats_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "season_type": "REG", "season": 2025, "week": 1,
        "player_id": "00-0001234", "player_display_name": "Test Player",
        "position": "WR", "position_group": "WR",
        "team": "MIN", "headshot_url": "",
        "completions": 0.0, "attempts": 0.0,
        "passing_yards": 0.0, "passing_tds": 0.0, "passing_interceptions": 0.0,
        "carries": 0.0, "rushing_yards": 0.0, "rushing_tds": 0.0,
        "receptions": 5.0, "targets": 8.0,
        "receiving_yards": 80.0, "receiving_tds": 1.0,
        "receiving_air_yards": 40.0, "passing_air_yards": 0.0,
        "target_share": 0.25, "air_yards_share": 0.30,
        "wopr": 0.55, "racr": 0.85,
        "passing_epa": 0.0, "rushing_epa": 0.0,
        "fantasy_points": 18.0, "fantasy_points_ppr": 23.0,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _make_team_stats_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "season_type": "REG", "season": 2025, "week": 1,
        "team": "MIN", "opponent_team": "GB",
        "attempts": 32.0, "carries": 25.0, "targets": 32.0,
        "passing_yards": 240.0, "rushing_yards": 110.0,
        "passing_tds": 1.5, "rushing_tds": 0.8,
        "passing_epa": 2.0, "rushing_epa": 0.5,
        "def_sacks": 2.0, "def_interceptions": 1.0, "def_pass_defended": 3.0,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _make_games_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "game_type": "REG", "season": 2025, "week": 1,
        "home_team": "MIN", "away_team": "GB",
        "spread_line": -3.0, "total_line": 47.5,
        "gameday": "2025-09-07", "gametime": "13:00",
        "roof": "outdoors", "surface": "grass",
        "temp": None, "wind": None,
        "home_score": None, "away_score": None,
        "home_moneyline": None, "away_moneyline": None,
        "home_qb_name": "", "away_qb_name": "",
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _make_snap_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "game_type": "REG", "season": 2025, "week": 1,
        "pfr_player_id": "JeffJu00", "player": "Justin Jefferson",
        "position": "WR", "team": "MIN", "opponent": "GB",
        "offense_pct": 0.92, "offense_snaps": 65,
        "defense_pct": 0.0, "defense_snaps": 0,
        "st_pct": 0.0, "st_snaps": 0,
    }
    if not rows:
        return pd.DataFrame(columns=list(defaults.keys()))
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _make_opp_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "season": 2025, "week": 1.0,
        "player_id": "00-0001234", "full_name": "Test Player", "position": "WR",
        "total_fantasy_points_exp": 18.0,
        "total_fantasy_points": 20.5,
        "total_fantasy_points_diff": 2.5,
    }
    if not rows:
        return pd.DataFrame(columns=list(defaults.keys()))
    return pd.DataFrame([{**defaults, **r} for r in rows])


@pytest.fixture(autouse=True)
def clear_nflverse():
    for d in (ns.nflverse_player_stats, ns.nflverse_player_advanced,
              ns.nflverse_team_stats, ns.nflverse_schedule, ns.nflverse_games):
        d.clear()
    ns.nflverse_current_season = None
    ns.nflverse_last_updated = None
    yield
    for d in (ns.nflverse_player_stats, ns.nflverse_player_advanced,
              ns.nflverse_team_stats, ns.nflverse_schedule, ns.nflverse_games):
        d.clear()


# ── _current_nfl_season ───────────────────────────────────────────────────────

class TestCurrentNflSeason:
    def test_before_september_returns_prior_year(self):
        import unittest.mock as mock
        with mock.patch("nflverse_stats.datetime") as dt:
            dt.datetime.utcnow.return_value = mock.Mock(month=5, year=2026)
            assert ns._current_nfl_season() == 2025

    def test_september_returns_current_year(self):
        import unittest.mock as mock
        with mock.patch("nflverse_stats.datetime") as dt:
            dt.datetime.utcnow.return_value = mock.Mock(month=9, year=2026)
            assert ns._current_nfl_season() == 2026

    def test_january_returns_prior_year(self):
        import unittest.mock as mock
        with mock.patch("nflverse_stats.datetime") as dt:
            dt.datetime.utcnow.return_value = mock.Mock(month=1, year=2027)
            assert ns._current_nfl_season() == 2026


# ── build_id_maps ─────────────────────────────────────────────────────────────

class TestBuildIdMaps:
    def test_builds_gsis_and_pfr_maps(self):
        df = pd.DataFrame([{
            "gsis_id": "00-0001234", "pfr_id": "JeffJu00",
            "sleeper_id": "999", "week": 1,
        }])
        from unittest.mock import patch, MagicMock
        mock_result = MagicMock()
        mock_result.to_pandas.return_value = df
        with patch.object(nfl, "load_rosters", return_value=mock_result):
            gsis_map, pfr_map = ns.build_id_maps(2025)
        assert gsis_map["00-0001234"] == "999"
        assert pfr_map["JeffJu00"] == "999"

    def test_skips_missing_sleeper_id(self):
        df = pd.DataFrame([{
            "gsis_id": "00-0001234", "pfr_id": "JeffJu00",
            "sleeper_id": None, "week": 1,
        }])
        from unittest.mock import patch, MagicMock
        mock_result = MagicMock()
        mock_result.to_pandas.return_value = df
        with patch.object(nfl, "load_rosters", return_value=mock_result):
            gsis_map, pfr_map = ns.build_id_maps(2025)
        assert gsis_map == {}
        assert pfr_map == {}


# ── build_player_stats_dict ───────────────────────────────────────────────────

class TestBuildPlayerStatsDict:
    def test_maps_gsis_to_sleeper(self):
        df = _make_stats_df([{"player_id": "00-0001234"}])
        assert "999" in ns.build_player_stats_dict(df, {"00-0001234": "999"})

    def test_uses_team_column(self):
        df = _make_stats_df([{"player_id": "00-0001234", "team": "KC"}])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result["999"]["team"] == "KC"

    def test_non_skill_excluded(self):
        df = _make_stats_df([{"player_id": "00-0001234", "position": "OL"}])
        assert ns.build_player_stats_dict(df, {"00-0001234": "999"}) == {}

    def test_preseason_excluded(self):
        df = _make_stats_df([{"player_id": "00-0001234", "season_type": "PRE"}])
        assert ns.build_player_stats_dict(df, {"00-0001234": "999"}) == {}

    def test_uses_most_recent_season(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "season": 2024, "fantasy_points_ppr": 5.0},
            {"player_id": "00-0001234", "season": 2025, "fantasy_points_ppr": 30.0},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result["999"]["season"] == 2025
        assert result["999"]["season_totals"]["fantasy_points_ppr"] == pytest.approx(30.0)

    def test_weekly_ordered_by_week(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": 3},
            {"player_id": "00-0001234", "week": 1},
            {"player_id": "00-0001234", "week": 2},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert [w["week"] for w in result["999"]["weekly"]] == [1, 2, 3]

    def test_season_totals_sum_ppr(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": 1, "fantasy_points_ppr": 20.0},
            {"player_id": "00-0001234", "week": 2, "fantasy_points_ppr": 30.0},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result["999"]["season_totals"]["fantasy_points_ppr"] == pytest.approx(50.0)

    def test_season_totals_avg_target_share(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": 1, "target_share": 0.2},
            {"player_id": "00-0001234", "week": 2, "target_share": 0.4},
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result["999"]["season_totals"]["target_share"] == pytest.approx(0.3, abs=1e-3)

    def test_rolling_3_last_three_weeks(self):
        df = _make_stats_df([
            {"player_id": "00-0001234", "week": w, "fantasy_points_ppr": float(w * 10)}
            for w in range(1, 6)  # 10, 20, 30, 40, 50 → last 3 avg = 40
        ])
        result = ns.build_player_stats_dict(df, {"00-0001234": "999"})
        assert result["999"]["rolling_3"]["fantasy_points_ppr"] == pytest.approx(40.0)


# ── build_player_advanced_dict ────────────────────────────────────────────────

class TestBuildPlayerAdvancedDict:
    def test_snap_pct_stored(self):
        snap = _make_snap_df([{"pfr_player_id": "JeffJu00", "week": 1, "offense_pct": 0.9}])
        opp  = _make_opp_df([])
        result = ns.build_player_advanced_dict(snap, opp, {}, {"JeffJu00": "999"})
        assert "999" in result
        assert result["999"]["snap_pct_avg"] == pytest.approx(0.9)

    def test_expected_fp_stored(self):
        snap = _make_snap_df([])
        opp  = _make_opp_df([{
            "player_id": "00-0001234", "week": 1.0,
            "total_fantasy_points_exp": 20.0,
            "total_fantasy_points": 25.0,
            "total_fantasy_points_diff": 5.0,
        }])
        result = ns.build_player_advanced_dict(snap, opp, {"00-0001234": "999"}, {})
        assert result["999"]["expected_fp_avg"] == pytest.approx(20.0)
        assert result["999"]["fp_diff_avg"] == pytest.approx(5.0)

    def test_merges_snap_and_opportunity(self):
        snap = _make_snap_df([{"pfr_player_id": "JeffJu00", "week": 1, "offense_pct": 0.92}])
        opp  = _make_opp_df([{
            "player_id": "00-0001234", "week": 1.0,
            "total_fantasy_points_exp": 18.0,
            "total_fantasy_points": 22.0,
            "total_fantasy_points_diff": 4.0,
        }])
        result = ns.build_player_advanced_dict(snap, opp, {"00-0001234": "999"}, {"JeffJu00": "999"})
        weekly = result["999"]["weekly"]
        assert len(weekly) == 1
        assert weekly[0]["snap_pct"] == pytest.approx(0.92)
        assert weekly[0]["expected_fp"] == pytest.approx(18.0)

    def test_weekly_sorted_by_week(self):
        snap = _make_snap_df([
            {"pfr_player_id": "JeffJu00", "week": 3, "offense_pct": 0.8},
            {"pfr_player_id": "JeffJu00", "week": 1, "offense_pct": 0.9},
        ])
        result = ns.build_player_advanced_dict(snap, _make_opp_df([]), {}, {"JeffJu00": "999"})
        weeks = [w["week"] for w in result["999"]["weekly"]]
        assert weeks == [1, 3]

    def test_no_snap_data_snap_pct_avg_is_none(self):
        opp = _make_opp_df([{
            "player_id": "00-0001234", "week": 1.0,
            "total_fantasy_points_exp": 15.0,
            "total_fantasy_points": 12.0,
            "total_fantasy_points_diff": -3.0,
        }])
        result = ns.build_player_advanced_dict(_make_snap_df([]), opp, {"00-0001234": "999"}, {})
        assert result["999"]["snap_pct_avg"] is None


# ── build_team_stats_dict ─────────────────────────────────────────────────────

class TestBuildTeamStatsDict:
    def test_offensive_stats(self):
        df = _make_team_stats_df([
            {"team": "MIN", "opponent_team": "GB", "week": 1, "attempts": 35.0, "passing_yards": 280.0},
            {"team": "MIN", "opponent_team": "CHI", "week": 2, "attempts": 30.0, "passing_yards": 220.0},
            # GB and CHI offensive rows (opponents of MIN)
            {"team": "GB", "opponent_team": "MIN", "week": 1, "passing_yards": 200.0, "rushing_yards": 90.0,
             "passing_tds": 1.0, "rushing_tds": 0.0, "targets": 28.0,
             "def_sacks": 3.0, "def_interceptions": 1.0, "def_pass_defended": 4.0},
            {"team": "CHI", "opponent_team": "MIN", "week": 2, "passing_yards": 180.0, "rushing_yards": 110.0,
             "passing_tds": 2.0, "rushing_tds": 1.0, "targets": 25.0,
             "def_sacks": 1.0, "def_interceptions": 0.0, "def_pass_defended": 2.0},
        ])
        result = ns.build_team_stats_dict(df)
        assert result["MIN"]["pass_attempts_per_game"] == pytest.approx(32.5)
        assert result["MIN"]["passing_yards_per_game"] == pytest.approx(250.0)

    def test_defensive_allowed_stats(self):
        df = _make_team_stats_df([
            {"team": "MIN", "opponent_team": "GB", "week": 1, "def_sacks": 2.0, "def_interceptions": 1.0, "def_pass_defended": 3.0},
            {"team": "GB",  "opponent_team": "MIN", "week": 1, "passing_yards": 200.0, "rushing_yards": 90.0,
             "passing_tds": 1.0, "rushing_tds": 0.0, "targets": 28.0,
             "def_sacks": 0.0, "def_interceptions": 0.0, "def_pass_defended": 0.0},
        ])
        result = ns.build_team_stats_dict(df)
        assert result["MIN"]["def_pass_yards_allowed_per_game"] == pytest.approx(200.0)
        assert result["MIN"]["def_rush_yards_allowed_per_game"] == pytest.approx(90.0)
        assert result["MIN"]["def_sacks_per_game"] == pytest.approx(2.0)

    def test_preseason_excluded(self):
        df = _make_team_stats_df([{"team": "MIN", "season_type": "PRE"}])
        result = ns.build_team_stats_dict(df)
        assert result == {}


# ── build_schedule_dicts ──────────────────────────────────────────────────────

class TestBuildScheduleDicts:
    def test_games_by_week(self):
        df = _make_games_df([{"week": 5, "home_team": "MIN", "away_team": "GB"}])
        _, games = ns.build_schedule_dicts(df)
        assert 5 in games
        assert games[5][0]["home_team"] == "MIN"

    def test_home_team_schedule(self):
        df = _make_games_df([{"week": 5, "home_team": "MIN", "away_team": "GB"}])
        sched, _ = ns.build_schedule_dicts(df)
        assert sched["MIN"]["is_home"] is True
        assert sched["MIN"]["opponent"] == "GB"

    def test_away_spread_inverted(self):
        df = _make_games_df([{"week": 5, "home_team": "MIN", "away_team": "GB", "spread_line": -3.0}])
        sched, _ = ns.build_schedule_dicts(df)
        assert sched["GB"]["spread"] == pytest.approx(3.0)

    def test_weather_fields_present(self):
        df = _make_games_df([{"week": 1, "temp": 72.0, "wind": 8.0, "roof": "outdoors"}])
        _, games = ns.build_schedule_dicts(df)
        game = games[1][0]
        assert game["temp"] == pytest.approx(72.0)
        assert game["wind"] == pytest.approx(8.0)
        assert game["roof"] == "outdoors"

    def test_non_reg_excluded(self):
        df = _make_games_df([{"game_type": "POST", "home_team": "KC", "away_team": "BUF"}])
        sched, games = ns.build_schedule_dicts(df)
        assert not games

    def test_empty_returns_empty(self):
        sched, games = ns.build_schedule_dicts(_make_games_df([{"game_type": "POST"}]))
        assert games == {}


# ── get_top_players ───────────────────────────────────────────────────────────

class TestGetTopPlayers:
    def _pop(self):
        ns.nflverse_player_stats.update({
            "1": {"name": "Alice", "position": "WR", "team": "MIN",
                  "season_totals": {"fantasy_points_ppr": 200.0}},
            "2": {"name": "Bob",   "position": "QB", "team": "KC",
                  "season_totals": {"fantasy_points_ppr": 350.0}},
            "3": {"name": "Carol", "position": "WR", "team": "MIN",
                  "season_totals": {"fantasy_points_ppr": 150.0}},
        })

    def test_sorted_descending(self):
        self._pop()
        result = ns.get_top_players(10)
        totals = [p["season_totals"]["fantasy_points_ppr"] for p in result]
        assert totals == sorted(totals, reverse=True)

    def test_position_filter(self):
        self._pop()
        assert all(p["position"] == "WR" for p in ns.get_top_players(10, position="WR"))

    def test_team_filter(self):
        self._pop()
        assert all(p["team"] == "MIN" for p in ns.get_top_players(10, team="MIN"))

    def test_limit(self):
        self._pop()
        assert len(ns.get_top_players(2)) == 2


# ── project_player ────────────────────────────────────────────────────────────

class TestProjectPlayer:
    def _add(self, sid="999", ppr=20.0, team="MIN"):
        ns.nflverse_player_stats[sid] = {
            "name": "Test", "position": "WR", "team": team,
            "season_totals": {}, "weekly": [],
            "rolling_3": {"fantasy_points_ppr": 18.0},
            "rolling_5": {"fantasy_points_ppr": ppr},
        }

    def test_unknown_player_empty(self):
        assert ns.project_player("nope", 8) == {}

    def test_base_from_rolling_5(self):
        self._add(ppr=25.0)
        assert ns.project_player("999", 8)["rolling_5_ppr"] == pytest.approx(25.0)

    def test_high_total_adjusts_up(self):
        self._add(ppr=20.0)
        ns.nflverse_schedule["MIN"] = {"week": 8, "opponent": "GB", "total": 54.0, "spread": -3.0}
        assert ns.project_player("999", 8)["projected_ppr"] > 20.0

    def test_adjustment_capped(self):
        self._add(ppr=20.0)
        ns.nflverse_schedule["MIN"] = {"week": 8, "opponent": "GB", "total": 999.0, "spread": 0.0}
        assert ns.project_player("999", 8)["projected_ppr"] <= 20.0 * 1.15 + 0.01

    def test_wrong_week_no_adjustment(self):
        self._add(ppr=20.0)
        ns.nflverse_schedule["MIN"] = {"week": 9, "opponent": "GB", "total": 54.0, "spread": -3.0}
        assert ns.project_player("999", 8)["adjustment_factor"] == pytest.approx(1.0)


# ── /stats/* endpoints ────────────────────────────────────────────────────────

class TestStatsEndpoints:
    def _player(self, sid="111", pos="WR", team="MIN", week=8):
        ns.nflverse_player_stats[sid] = {
            "name": "Test", "position": pos, "team": team, "season": 2025,
            "gsis_id": "00-0001", "headshot_url": "",
            "season_totals": {"fantasy_points_ppr": 200.0, "games_played": 10},
            "weekly": [{"week": week, "fantasy_points_ppr": 25.0, "targets": 8.0}],
            "rolling_3": {"fantasy_points_ppr": 22.0},
            "rolling_5": {"fantasy_points_ppr": 21.0},
        }

    def test_status_200(self, client):
        resp = client.get("/stats/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "advanced_count" in data

    def test_list_players_empty(self, client):
        assert client.get("/stats/players").get_json() == []

    def test_list_players_sorted(self, client):
        self._player("111", week=1)
        ns.nflverse_player_stats["222"] = {
            "name": "Other", "position": "QB", "team": "KC", "season": 2025,
            "gsis_id": "00-0002", "headshot_url": "",
            "season_totals": {"fantasy_points_ppr": 400.0, "games_played": 10},
            "weekly": [], "rolling_3": {}, "rolling_5": {},
        }
        data = client.get("/stats/players").get_json()
        assert data[0]["season_totals"]["fantasy_points_ppr"] == 400.0

    def test_list_players_position_filter(self, client):
        self._player("111", pos="WR", week=1)
        self._player("222", pos="QB", week=1)
        data = client.get("/stats/players?position=WR").get_json()
        assert all(p["position"] == "WR" for p in data)

    def test_list_players_by_week(self, client):
        self._player("111", week=8)
        data = client.get("/stats/players?week=8").get_json()
        assert len(data) == 1 and data[0]["week"] == 8

    def test_players_by_team(self, client):
        self._player("111", team="MIN", week=1)
        self._player("222", team="KC", week=1)
        data = client.get("/stats/players/team/MIN").get_json()
        assert all(p["team"] == "MIN" for p in data)

    def test_player_detail(self, client):
        self._player("111")
        data = client.get("/stats/player/111").get_json()
        assert data["sleeper_id"] == "111" and "weekly" in data

    def test_player_detail_404(self, client):
        assert client.get("/stats/player/nope").status_code == 404

    def test_player_advanced_returns_data(self, client):
        ns.nflverse_player_advanced["111"] = {
            "snap_pct_avg": 0.92, "expected_fp_avg": 18.5, "fp_diff_avg": 1.5,
            "weekly": [{"week": 8, "snap_pct": 0.92, "expected_fp": 18.5, "actual_fp": 20.0, "fp_diff": 1.5}],
        }
        resp = client.get("/stats/player/111/advanced")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["snap_pct_avg"] == pytest.approx(0.92)

    def test_player_advanced_404(self, client):
        assert client.get("/stats/player/nope/advanced").status_code == 404

    def test_week_endpoint(self, client):
        self._player("111", week=8)
        data = client.get("/stats/week/8").get_json()
        assert "111" in data

    def test_week_404(self, client):
        assert client.get("/stats/week/99").status_code == 404

    def test_projections(self, client):
        self._player("111", week=1)
        data = client.get("/stats/projections/week/8").get_json()
        assert isinstance(data, list) and "projected_ppr" in data[0]

    def test_schedule(self, client):
        ns.nflverse_games[8] = [{"home_team": "MIN", "away_team": "GB",
                                   "spread_line": -3.0, "total_line": 47.5,
                                   "gameday": "2025-10-26", "gametime": "13:00",
                                   "roof": "outdoors", "surface": "grass",
                                   "temp": None, "wind": None,
                                   "home_score": None, "away_score": None,
                                   "home_moneyline": None, "away_moneyline": None,
                                   "home_qb": "", "away_qb": ""}]
        ns.nflverse_current_season = 2025
        data = client.get("/stats/schedule/8").get_json()
        assert data["week"] == 8 and len(data["games"]) == 1

    def test_schedule_404(self, client):
        assert client.get("/stats/schedule/99").status_code == 404

    def test_team_stats_includes_defense(self, client):
        ns.nflverse_team_stats["MIN"] = {
            "season": 2025, "games_played": 17,
            "pass_attempts_per_game": 35.0, "rush_attempts_per_game": 26.0,
            "targets_per_game": 35.0, "passing_yards_per_game": 250.0,
            "rushing_yards_per_game": 110.0, "passing_tds_per_game": 1.8,
            "rushing_tds_per_game": 0.9, "passing_epa_per_game": 2.0,
            "rushing_epa_per_game": 0.5,
            "def_pass_yards_allowed_per_game": 210.0,
            "def_rush_yards_allowed_per_game": 95.0,
            "def_pass_tds_allowed_per_game": 1.4,
            "def_rush_tds_allowed_per_game": 0.6,
            "def_targets_allowed_per_game": 28.0,
            "def_sacks_per_game": 2.5,
            "def_interceptions_per_game": 1.0,
            "def_pass_defended_per_game": 3.2,
        }
        data = client.get("/stats/team/MIN").get_json()
        assert data["team"] == "MIN"
        assert "def_pass_yards_allowed_per_game" in data
        assert data["def_pass_yards_allowed_per_game"] == pytest.approx(210.0)

    def test_team_stats_case_insensitive(self, client):
        ns.nflverse_team_stats["MIN"] = {"season": 2025, "games_played": 17,
            "pass_attempts_per_game": 35.0, "rush_attempts_per_game": 26.0,
            "targets_per_game": 35.0, "passing_yards_per_game": 250.0,
            "rushing_yards_per_game": 110.0, "passing_tds_per_game": 1.8,
            "rushing_tds_per_game": 0.9, "passing_epa_per_game": 2.0,
            "rushing_epa_per_game": 0.5,
            "def_pass_yards_allowed_per_game": 210.0,
            "def_rush_yards_allowed_per_game": 95.0,
            "def_pass_tds_allowed_per_game": 1.4,
            "def_rush_tds_allowed_per_game": 0.6,
            "def_targets_allowed_per_game": 28.0,
            "def_sacks_per_game": 2.5,
            "def_interceptions_per_game": 1.0,
            "def_pass_defended_per_game": 3.2}
        assert client.get("/stats/team/min").status_code == 200

    def test_team_stats_404(self, client):
        assert client.get("/stats/team/UNKNOWN").status_code == 404
