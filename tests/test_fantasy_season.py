"""The fantasy-points scraper must ask FantasyData for the season being played.

Asking for the wrong one returns a full set of plausible numbers from another
year rather than failing, so this is worth pinning down.
"""

import datetime
import sys

import pytest
from unittest.mock import patch, MagicMock

nfl_helper = sys.modules["nfl_helper"]
from fantasydatascraper import FantasyDataScraper


def sleeper_returning(season):
    resp = MagicMock()
    resp.json.return_value = {"season": season, "week": 1, "season_type": "regular"}
    resp.raise_for_status.return_value = None
    return resp


class TestCurrentSeason:
    def test_uses_the_season_sleeper_reports(self):
        s = FantasyDataScraper()
        with patch.object(s.session, "get", return_value=sleeper_returning("2026")):
            assert s.get_current_season() == "2026_REG"

    def test_is_not_pinned_to_a_hardcoded_year(self):
        s = FantasyDataScraper()
        with patch.object(s.session, "get", return_value=sleeper_returning("2031")):
            assert s.get_current_season() == "2031_REG"

    def test_resolves_once_per_scraper(self):
        s = FantasyDataScraper()
        with patch.object(s.session, "get", return_value=sleeper_returning("2026")) as get:
            s.get_current_season()
            s.get_current_season()
            assert get.call_count == 1, "second call must come from the cache"

    @pytest.mark.parametrize("today,expected", [
        (datetime.datetime(2026, 9, 10), "2026_REG"),   # mid-season
        (datetime.datetime(2027, 1, 15), "2026_REG"),   # January still belongs to 2026
        (datetime.datetime(2027, 2, 28), "2026_REG"),   # so does February
        (datetime.datetime(2027, 3, 1), "2027_REG"),    # March rolls over
    ])
    def test_falls_back_to_the_date_when_sleeper_is_unreachable(self, today, expected):
        s = FantasyDataScraper()

        class FakeDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return today

        with patch.object(s.session, "get", side_effect=Exception("offline")), \
             patch("fantasydatascraper.datetime.datetime", FakeDateTime):
            assert s.get_current_season() == expected


class TestScrapeUsesCurrentSeason:
    def test_scrape_position_requests_the_current_season(self):
        s = FantasyDataScraper()
        with patch.object(s, "get_current_season", return_value="2026_REG"), \
             patch.object(s, "_make_request", return_value=None) as req:
            s.scrape_position("QB", week_from=1, week_to=1)

        assert "sp=2026_REG" in req.call_args[0][0]

    def test_an_explicit_season_still_wins(self):
        """Back-filling a past week must remain possible."""
        s = FantasyDataScraper()
        with patch.object(s, "get_current_season", return_value="2026_REG"), \
             patch.object(s, "_make_request", return_value=None) as req:
            s.scrape_position("QB", week_from=1, week_to=1, season="2025_REG")

        assert "sp=2025_REG" in req.call_args[0][0]

    def test_all_positions_share_one_resolved_season(self):
        s = FantasyDataScraper()
        with patch.object(s, "get_current_season", return_value="2026_REG") as season, \
             patch.object(s, "scrape_position", return_value=[]) as scrape:
            s.scrape_all_positions(week_from=1, week_to=1)

        assert season.call_count == 1
        assert {c[0][3] for c in scrape.call_args_list} == {"2026_REG"}
