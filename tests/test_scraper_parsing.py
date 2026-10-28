import sys
import json
import pytest
import responses as responses_lib
from bs4 import BeautifulSoup
from unittest.mock import patch, MagicMock

nfl_helper = sys.modules["nfl_helper"]

from get_dfs_salaries_and_stats import DFFSalariesScraper, ROW_TAG_RE


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


class TestBeingTurnedAwayIsNotAnEmptySlate:
    """
    DailyFantasyFuel redirects an outdated browser to its homepage. The scraper
    carried a Chrome 91 string from 2021, so the projections pages started
    answering 302 to "/", requests followed it, and the scrape parsed 300 KB of
    homepage: no rows, HTTP 200, raise_for_status happy. It logged "no players
    found (this may be normal if data isn't available yet)" for every date.

    The slates JSON is not gated, so slate discovery kept working and the logs
    read exactly like a site that had not posted its salaries yet.
    """

    PAGE = "https://www.dailyfantasyfuel.com/nfl/projections/draftkings/2026-11-01"

    def _response(self, final_url, body=""):
        resp = MagicMock()
        resp.url = final_url
        resp.text = body
        resp.raise_for_status = MagicMock()
        return resp

    def test_a_redirect_elsewhere_returns_nothing_and_says_why(self, caplog):
        scraper = DFFSalariesScraper()
        with patch.object(scraper.session, "get",
                          return_value=self._response("https://www.dailyfantasyfuel.com:443/")):
            with caplog.at_level("ERROR"):
                players = scraper.scrape_dff_projections(date="2026-11-01", slate_url="25FC8")

        assert players == []
        assert "Redirected away from the projections page" in caplog.text
        # Names the actual cause, since that is the whole point of the message.
        assert "User-Agent" in caplog.text

    def test_the_same_page_is_parsed_normally(self):
        # A trailing slash or the explicit :443 port is not a redirect.
        scraper = DFFSalariesScraper()
        # The real page carries class=" projections-listing " on each row, which
        # is what the selector matches on; make_player_row omits it because the
        # parsing tests above feed rows in directly.
        row = str(make_player_row(name="Josh Allen", pos="QB", team="BUF", salary="7700"))
        row = row.replace("<tr ", '<tr class=" projections-listing " ', 1)
        body = f"<table>{row}</table>"
        for served in (self.PAGE, self.PAGE + "/", self.PAGE.replace(".com", ".com:443")):
            with patch.object(scraper.session, "get",
                              return_value=self._response(served, body)):
                players = scraper.scrape_dff_projections(date="2026-11-01", slate_url="25FC8")
            assert len(players) == 1, f"served {served} should have parsed"
            assert players[0]["name"] == "Josh Allen"

    def test_the_user_agent_is_not_the_one_that_gets_turned_away(self):
        # Pinning the failure rather than the exact string: any Chrome older than
        # about 100 is refused, and the point is not to drift back there.
        ua = DFFSalariesScraper().session.headers["User-Agent"]
        assert "Chrome/" in ua
        major = int(ua.split("Chrome/")[1].split(".")[0])
        assert major >= 120, f"Chrome/{major} is old enough to be redirected away"


class TestOnlyTheRowsAreParsed:
    """
    A slate page is 1.4 MB of HTML and every field this scraper reads lives in a
    data-* attribute on the <tr> itself, so the row bodies are never looked at.
    Handing the whole document to BeautifulSoup cost 27.6 MB of tree per page,
    about seven pages a run, and no job handed that heap back — the largest
    single allocation in a process with 512 MB to live in.

    Pulling the opening tags out of the text first and parsing only those is 19x
    cheaper. The thing that matters is that it is not *also* a correctness
    change, which is what these assert.
    """

    def _page(self, rows=3):
        body = "".join(
            f'<td>filler that the old parse built a tree for</td>' * 20
        )
        trs = "".join(
            f'<tr class=" projections-listing " data-name="P{i}" data-pos="QB"'
            f' data-salary="{7000+i}" data-ppg_proj="20.{i}" data-week="8"'
            f' data-team="KC" data-opp="LV" data-value_proj="3.0"'
            f' data-szn_avg="21.0" data-l5_avg="22.0" data-l10_avg="23.0"'
            f' data-spread="-3.0" data-ou="48.0" data-proj_score="24.0"'
            f' data-opp_rank="5"><td>{body}</td></tr>'
            for i in range(rows)
        )
        return f"<html><body><table>{trs}</table></body></html>"

    def test_it_finds_the_same_rows_the_full_parse_did(self):
        html = self._page()
        old = BeautifulSoup(html, "html.parser").find_all(
            "tr", class_="projections-listing")
        new = BeautifulSoup(
            f"<table>{''.join(f'{t}</tr>' for t in ROW_TAG_RE.findall(html))}</table>",
            "html.parser").find_all("tr")
        assert len(new) == len(old) == 3

    def test_every_attribute_survives(self):
        # A cheaper parse that silently dropped a field would otherwise look
        # exactly like a win.
        html = self._page()
        old = BeautifulSoup(html, "html.parser").find_all(
            "tr", class_="projections-listing")
        new = BeautifulSoup(
            f"<table>{''.join(f'{t}</tr>' for t in ROW_TAG_RE.findall(html))}</table>",
            "html.parser").find_all("tr")
        for a, b in zip(old, new):
            assert set(a.attrs) == set(b.attrs)
            assert all(a[k] == b[k] for k in a.attrs)

    def test_the_parsed_players_are_identical(self):
        html = self._page()
        scraper = DFFSalariesScraper()
        parse = lambda rows: [p for p in (scraper._parse_player_row(r) for r in rows) if p]
        old = parse(BeautifulSoup(html, "html.parser").find_all(
            "tr", class_="projections-listing"))
        new = parse(BeautifulSoup(
            f"<table>{''.join(f'{t}</tr>' for t in ROW_TAG_RE.findall(html))}</table>",
            "html.parser").find_all("tr"))
        assert old == new
        assert old[0]["name"] == "P0" and old[0]["salary"] == 7000

    def test_the_pattern_tolerates_the_whitespace_in_the_live_class(self):
        # class=" projections-listing " with surrounding spaces is what the site
        # actually sends, and is why SoupStrainer finds nothing here.
        for attr in (' class=" projections-listing "',
                     ' class="projections-listing"',
                     ' class="hidden projections-listing "'):
            html = f'<tr{attr} data-name="x">'
            assert ROW_TAG_RE.findall(html), attr

    def test_it_does_not_match_an_unrelated_row(self):
        assert ROW_TAG_RE.findall('<tr class="proj-labels hidden-xs">') == []
