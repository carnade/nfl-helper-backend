import datetime
import sys
import pytest

nfl_helper = sys.modules["nfl_helper"]

from conftest import make_lineup_string


class TestGetNflGameweek:
    def test_week_1_on_start_day(self):
        assert nfl_helper.get_nfl_gameweek(datetime.date(2026, 9, 7)) == 1

    def test_week_1_last_day(self):
        assert nfl_helper.get_nfl_gameweek(datetime.date(2026, 9, 13)) == 1

    def test_week_2_start(self):
        assert nfl_helper.get_nfl_gameweek(datetime.date(2026, 9, 14)) == 2

    def test_week_18(self):
        week_18_start = datetime.date(2026, 9, 7) + datetime.timedelta(weeks=17)
        assert nfl_helper.get_nfl_gameweek(week_18_start) == 18

    def test_pre_season_returns_nonpositive(self):
        result = nfl_helper.get_nfl_gameweek(datetime.date(2026, 9, 6))
        assert result <= 0


class TestByeWeeks2026:
    EXPECTED_TEAMS = {
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
        "DET", "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA",
        "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF", "SEA", "TB",
        "TEN", "WAS",
    }

    def test_all_32_teams_present(self):
        assert set(nfl_helper.BYE_WEEKS_2026.keys()) == self.EXPECTED_TEAMS

    def test_valid_week_range(self):
        for team, week in nfl_helper.BYE_WEEKS_2026.items():
            assert 5 <= week <= 14, f"{team} bye week {week} is outside 5-14"

    def test_spot_check_known_weeks(self):
        assert nfl_helper.BYE_WEEKS_2026["CAR"] == 5
        assert nfl_helper.BYE_WEEKS_2026["KC"] == 5
        assert nfl_helper.BYE_WEEKS_2026["ARI"] == 14
        assert nfl_helper.BYE_WEEKS_2026["DAL"] == 14


class TestNormalizeTinyurlName:
    def test_lowercases(self):
        assert nfl_helper.normalize_tinyurl_name("Alice") == "alice"

    def test_already_lowercase(self):
        assert nfl_helper.normalize_tinyurl_name("bob") == "bob"

    def test_mixed_case(self):
        assert nfl_helper.normalize_tinyurl_name("LeAgUe2026") == "league2026"

    def test_none_passthrough(self):
        assert nfl_helper.normalize_tinyurl_name(None) is None

    def test_empty_string(self):
        assert nfl_helper.normalize_tinyurl_name("") == ""


class TestCalculateDfsPoints:
    def test_empty_fantasy_data_returns_zero(self):
        lineup = make_lineup_string(8, ["12345:QB", "67890:RB"])
        assert nfl_helper.calculate_dfs_points_from_lineup(lineup, 8) == 0.0

    def test_sums_matched_players(self):
        nfl_helper.fantasy_points_data["12345_8"] = {"fantasy_points": 30.0}
        nfl_helper.fantasy_points_data["67890_8"] = {"fantasy_points": 20.5}
        lineup = make_lineup_string(8, ["12345:QB", "67890:RB"])
        assert nfl_helper.calculate_dfs_points_from_lineup(lineup, 8) == pytest.approx(50.5)

    def test_week_pipe_prefix_stripped(self):
        nfl_helper.fantasy_points_data["99999_7"] = {"fantasy_points": 25.0}
        lineup = make_lineup_string(7, ["99999:WR"])
        assert nfl_helper.calculate_dfs_points_from_lineup(lineup, 7) == pytest.approx(25.0)

    def test_unrecognized_players_excluded(self):
        nfl_helper.fantasy_points_data["99999_8"] = {"fantasy_points": 25.0}
        lineup = make_lineup_string(8, ["11111:QB"])  # 11111 not in fantasy_points_data
        assert nfl_helper.calculate_dfs_points_from_lineup(lineup, 8) == 0.0

    def test_wrong_week_key_not_matched(self):
        # Data stored for week 9, lineup submitted for week 8
        nfl_helper.fantasy_points_data["12345_9"] = {"fantasy_points": 30.0}
        lineup = make_lineup_string(8, ["12345:QB"])
        assert nfl_helper.calculate_dfs_points_from_lineup(lineup, 8) == 0.0
