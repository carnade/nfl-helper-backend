import sys
import json
import pytest
import responses as responses_lib
from bs4 import BeautifulSoup
from unittest.mock import patch, MagicMock

nfl_helper = sys.modules["nfl_helper"]

from get_dfs_salaries_and_stats import DFFSalariesScraper


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_player_row(name="Patrick Mahomes", pos="QB", salary="8200",
                    ppg_proj="28.5", week="8", team="KC", opp="LV",
                    value_proj="3.5", szn_avg="25.0", l5_avg="27.0",
                    l10_avg="26.5", spread="-7.0", ou="52.5",
                    proj_score="28.0", opp_rank="12"):
    html = (
        f'<tr data-name="{name}" data-pos="{pos}" data-salary="{salary}"'
        f' data-ppg_proj="{ppg_proj}" data-week="{week}" data-team="{team}"'
        f' data-opp="{opp}" data-value_proj="{value_proj}" data-szn_avg="{szn_avg}"'
        f' data-l5_avg="{l5_avg}" data-l10_avg="{l10_avg}" data-spread="{spread}"'
        f' data-ou="{ou}" data-proj_score="{proj_score}" data-opp_rank="{opp_rank}"></tr>'
    )
    return BeautifulSoup(html, "html.parser").find("tr")


# ── DFFSalariesScraper._parse_player_row ─────────────────────────────────────

class TestParsePlayerRow:
    def setup_method(self):
        self.scraper = DFFSalariesScraper()

    def test_valid_row_returns_dict(self):
        row = make_player_row()
        result = self.scraper._parse_player_row(row)
        assert result is not None
        assert result["name"] == "Patrick Mahomes"
        assert result["position"] == "QB"
        assert isinstance(result["salary"], int)
        assert result["salary"] == 8200
        assert isinstance(result["projected_points"], float)
        assert result["projected_points"] == pytest.approx(28.5)

    def test_missing_name_returns_none(self):
        row = make_player_row(name="")
        result = self.scraper._parse_player_row(row)
        assert result is None

    def test_invalid_salary_defaults_to_zero(self):
        row = make_player_row(salary="notanumber")
        result = self.scraper._parse_player_row(row)
        assert result is not None
        assert result["salary"] == 0

    def test_invalid_projected_points_defaults_to_zero(self):
        row = make_player_row(ppg_proj="N/A")
        result = self.scraper._parse_player_row(row)
        assert result is not None
        assert result["projected_points"] == 0.0

    def test_team_and_opponent_extracted(self):
        row = make_player_row(team="KC", opp="LV")
        result = self.scraper._parse_player_row(row)
        assert result["team"] == "KC"
        assert result["opponent"] == "LV"


# ── DFFSalariesScraper.get_active_main_slate (mocked HTTP) ───────────────────

SLATES_URL = "https://www.dailyfantasyfuel.com/data/slates/recent/NFL/draftkings"


def slate_response(slates: list):
    return json.dumps({"slates": slates})


def main_slate(game_count=13, url="MAIN123"):
    return {"showdown_flag": 0, "game_count": game_count, "team_count": game_count * 2, "url": url}


def showdown_slate(url="SHOW456"):
    return {"showdown_flag": 1, "game_count": 2, "team_count": 4, "url": url}


class TestGetActiveMainSlate:
    def setup_method(self):
        self.scraper = DFFSalariesScraper()

    @responses_lib.activate
    def test_picks_largest_non_showdown_slate(self):
        responses_lib.add(
            responses_lib.GET, SLATES_URL,
            body=slate_response([showdown_slate("SD1"), main_slate(13, "MAIN1"), main_slate(6, "SMALL1")]),
            content_type="application/json",
        )
        result = self.scraper.get_active_main_slate(date="2026-10-01")
        assert result == "MAIN1"

    @responses_lib.activate
    def test_only_showdown_slates_returns_none(self):
        # All 7 dates tried will return only showdown slates
        for _ in range(7):
            responses_lib.add(
                responses_lib.GET, SLATES_URL,
                body=slate_response([showdown_slate()]),
                content_type="application/json",
            )
        result = self.scraper.get_active_main_slate(date="2026-10-01")
        assert result is None

    @responses_lib.activate
    def test_empty_slates_falls_through_to_next_date(self):
        # First date: empty; subsequent dates: main slate
        responses_lib.add(
            responses_lib.GET, SLATES_URL,
            body=slate_response([]),
            content_type="application/json",
        )
        for _ in range(6):
            responses_lib.add(
                responses_lib.GET, SLATES_URL,
                body=slate_response([main_slate(13, "FOUND")]),
                content_type="application/json",
            )
        result = self.scraper.get_active_main_slate(date="2026-10-01")
        assert result == "FOUND"


# ── update_fantasy_points_data (patched FantasyDataScraper) ──────────────────

class TestUpdateFantasyPointsData:
    def test_populates_dict_with_matched_player(self):
        nfl_helper.filtered_players["999"] = {
            "first_name": "Patrick", "last_name": "Mahomes",
            "full_name": "Patrick Mahomes", "position": "QB",
        }
        mock_data = {
            "QB": [{"name": "Patrick Mahomes", "fantasy_points": 35.5, "week": 8, "team": "KC"}]
        }
        with patch.object(nfl_helper.FantasyDataScraper, "scrape_all_positions", return_value=mock_data), \
             patch.object(nfl_helper.FantasyDataScraper, "get_current_week", return_value=8):
            nfl_helper.update_fantasy_points_data()

        assert len(nfl_helper.fantasy_points_data) > 0
        # At least one key should contain _8
        keys = list(nfl_helper.fantasy_points_data.keys())
        assert any("_8" in k for k in keys)

    def test_skips_unmatched_players_no_crash(self):
        # filtered_players is empty — no Sleeper ID will be found
        mock_data = {
            "QB": [{"name": "Unknown Player", "fantasy_points": 10.0, "week": 8, "team": "XX"}]
        }
        with patch.object(nfl_helper.FantasyDataScraper, "scrape_all_positions", return_value=mock_data), \
             patch.object(nfl_helper.FantasyDataScraper, "get_current_week", return_value=8):
            nfl_helper.update_fantasy_points_data()

        assert nfl_helper.fantasy_points_data == {}
