"""
DailyFantasyFuel's logged-out preview.

Between the 15th and the 18th of November 2026 the site began showing the top
25 players of a slate to anyone without an account and putting the rest behind
a free login, ending the table with "Log In or create a free account to see all
players".

Nothing about the response says so. It is a 200, it is the usual 380 KB, the
markup is unchanged, and all 25 rows that are there parse perfectly. Three days
of scrapes stored a quarter of each slate and logged success; the first anyone
knew of it was a missing running back.

So the scrape refuses a preview outright rather than storing it, and the rows
already held are kept — stale but whole — instead of being half-refreshed.
"""

import pytest
import requests

import nfl_helper as nh
from get_dfs_salaries_and_stats import DFFAccountGate, DFFSalariesScraper, GATE_TEXT_RE


# The two shapes the page comes in, cut down to what the scrape looks at.
ROW = (
    '<tr class=" projections-listing " data-name="Joe Burrow" data-fn="Joe" '
    'data-ln="Burrow" data-pos="QB" data-team="CIN" data-opp="WAS" data-loc="vs" '
    'data-salary="7800" data-ppg_proj="21.4" data-value_proj="2.74" '
    'data-start_date="2026-11-22" data-week="11" data-opp_rank="14" '
    'data-l5_avg="18.0" data-l10_avg="19.1" data-szn_avg="18.7" '
    'data-proj_score="23" data-spread="-6.5" data-ou="54.5" data-inj="">'
    "<td>Joe Burrow</td></tr>"
)

GATED_PAGE = (
    "<html><body><table data-preview=\"true\"><tbody>"
    + ROW
    + "</tbody></table>"
    '<div class="consistency-show-more-container">'
    "<div>Log In or create a free account to see all players</div>"
    '<a href="/auth"><span>LOG IN TO SEE ALL</span></a>"'
    "</div></body></html>"
)

FULL_PAGE = "<html><body><table><tbody>" + ROW * 3 + "</tbody></table></body></html>"


class _Response:
    def __init__(self, text, url):
        self.text = text
        self.url = url
        self.status_code = 200

    def raise_for_status(self):
        return None


@pytest.fixture
def scraper(monkeypatch):
    monkeypatch.delenv("DFF_COOKIE", raising=False)
    return DFFSalariesScraper()


def _serves(monkeypatch, scraper, text):
    """Answer every request with this page, from the URL that was asked for."""
    def fake_get(url, **kwargs):
        return _Response(text, url.split("?")[0])

    monkeypatch.setattr(scraper.session, "get", fake_get)


class TestSpottingThePreview:
    def test_the_marker_matches_the_live_page(self):
        # Taken from the real response on 2026-11-18. If the wording changes
        # this test is the thing that should fail, rather than the scrape
        # quietly going back to storing a quarter of a slate.
        assert GATE_TEXT_RE.search(GATED_PAGE)

    def test_a_preview_is_refused_rather_than_parsed(self, scraper, monkeypatch):
        _serves(monkeypatch, scraper, GATED_PAGE)
        with pytest.raises(DFFAccountGate) as raised:
            scraper.scrape_dff_projections("26468", "2026-11-22")
        assert "DFF_COOKIE" in str(raised.value)

    def test_the_rows_it_did_serve_are_not_kept(self, scraper, monkeypatch):
        # A parseable row on a gated page is still a quarter of the truth. The
        # danger is that it looks like data, which is why this raises rather
        # than returning what it managed to read.
        _serves(monkeypatch, scraper, GATED_PAGE)
        with pytest.raises(DFFAccountGate):
            scraper.scrape_dff_projections("26468", "2026-11-22")

    def test_a_full_page_is_scraped_as_before(self, scraper, monkeypatch):
        _serves(monkeypatch, scraper, FULL_PAGE)
        players = scraper.scrape_dff_projections("26468", "2026-11-22")
        assert len(players) == 3
        assert players[0]["name"] == "Joe Burrow"

    def test_a_genuinely_small_slate_is_not_mistaken_for_a_preview(self, scraper, monkeypatch):
        # A single-game showdown really does have a handful of players. Matching
        # on the page's own words rather than on a row count is what keeps those
        # from being thrown away.
        one = "<html><body><table><tbody>" + ROW + "</tbody></table></body></html>"
        _serves(monkeypatch, scraper, one)
        assert len(scraper.scrape_dff_projections("26468", "2026-11-22")) == 1


class TestTheCookie:
    def test_it_is_sent_when_the_environment_has_one(self, monkeypatch):
        monkeypatch.setenv("DFF_COOKIE", "sess=abc123; other=def")
        assert DFFSalariesScraper().session.headers["Cookie"] == "sess=abc123; other=def"

    def test_nothing_is_sent_without_one(self, monkeypatch):
        monkeypatch.delenv("DFF_COOKIE", raising=False)
        assert "Cookie" not in DFFSalariesScraper().session.headers

    def test_whitespace_round_a_pasted_value_is_trimmed(self, monkeypatch):
        # It is pasted out of a browser, so it arrives with whatever came with it.
        monkeypatch.setenv("DFF_COOKIE", "  sess=abc123  \n")
        assert DFFSalariesScraper().session.headers["Cookie"] == "sess=abc123"

    def test_an_empty_value_is_the_same_as_none(self, monkeypatch):
        monkeypatch.setenv("DFF_COOKIE", "   ")
        assert "Cookie" not in DFFSalariesScraper().session.headers

    @pytest.mark.parametrize("quote", ["'", '"'])
    def test_quotes_round_the_whole_value_are_dropped(self, monkeypatch, quote):
        # A .env convention that a hosting panel's environment field does not
        # share, and this value gets pasted into both. Left on, the quotes land
        # on whichever cookie sits at each end of the string — survivable when
        # that is a Google Analytics one, fatal when the browser happened to
        # order a session chunk there, and the symptom is a silent return to
        # the 25-row preview.
        inner = "_ga=GA1.2.9066; AWSELBAuthSessionCookie-0=aaa"
        monkeypatch.setenv("DFF_COOKIE", f"{quote}{inner}{quote}")
        assert DFFSalariesScraper().session.headers["Cookie"] == inner

    def test_a_quote_inside_the_value_is_left_alone(self, monkeypatch):
        # Only a matched pair wrapping the whole thing is a quoting convention.
        value = "a=1; b=it's"
        monkeypatch.setenv("DFF_COOKIE", value)
        assert DFFSalariesScraper().session.headers["Cookie"] == value

    def test_mismatched_ends_are_not_treated_as_quotes(self, monkeypatch):
        value = "'a=1; b=2"
        monkeypatch.setenv("DFF_COOKIE", value)
        assert DFFSalariesScraper().session.headers["Cookie"] == value

    def test_a_value_of_only_quotes_is_the_same_as_none(self, monkeypatch):
        monkeypatch.setenv("DFF_COOKIE", "''")
        assert "Cookie" not in DFFSalariesScraper().session.headers


class TestTellingTheTwoFailuresApart:
    """Never logged in, or logged in with a cookie that has lapsed.

    The same page comes back either way, and in a month's time the difference
    is the whole diagnosis.
    """

    def test_without_a_cookie_it_says_to_set_one(self, scraper, monkeypatch):
        _serves(monkeypatch, scraper, GATED_PAGE)
        with pytest.raises(DFFAccountGate) as raised:
            scraper.scrape_dff_projections("26468", "2026-11-22")
        assert "set DFF_COOKIE" in str(raised.value)
        assert "expired" not in str(raised.value)

    def test_with_one_it_says_the_cookie_did_not_work(self, monkeypatch):
        monkeypatch.setenv("DFF_COOKIE", "AWSELBAuthSessionCookie-0=stale")
        gated = DFFSalariesScraper()
        _serves(monkeypatch, gated, GATED_PAGE)
        with pytest.raises(DFFAccountGate) as raised:
            gated.scrape_dff_projections("26468", "2026-11-22")
        assert "expired" in str(raised.value)
        assert "AWSELBAuthSessionCookie" in str(raised.value)

    def test_a_cookie_without_the_session_part_is_called_out(self, monkeypatch, caplog):
        # The likeliest way to set this wrong: copying as far as the first
        # chunk and stopping. The value looks complete and authenticates as
        # nobody.
        monkeypatch.setenv("DFF_COOKIE", "_ga=GA1.2.9066; _gid=GA1.2.3579")
        with caplog.at_level("WARNING"):
            DFFSalariesScraper()
        assert "AWSELBAuthSessionCookie" in caplog.text

    def test_a_whole_cookie_draws_no_complaint(self, monkeypatch, caplog):
        monkeypatch.setenv(
            "DFF_COOKIE",
            "_ga=GA1.2.9066; AWSALBAuthNonce=kisD; "
            "AWSELBAuthSessionCookie-0=aaa; AWSELBAuthSessionCookie-1=bbb",
        )
        with caplog.at_level("WARNING"):
            DFFSalariesScraper()
        assert "AWSELBAuthSessionCookie" not in caplog.text


class TestWhatTheUpdateDoesAboutIt:
    @pytest.fixture
    def held(self, monkeypatch):
        """Three weeks of rows already in memory, as production has."""
        rows = {
            f"{i}_W10_D2026-11-15": {
                "sleeper_id": str(i), "name": f"Player {i}", "team": "CIN",
                "week": 10, "game_date": "2026-11-15", "game_start_time": "1:00PM",
            }
            for i in range(400)
        }
        monkeypatch.setattr(nh, "dfs_salaries_data", rows)
        return rows

    @pytest.fixture
    def gated(self, monkeypatch):
        class Gated:
            def get_salaries_with_sleeper_ids(self, *args, **kwargs):
                raise DFFAccountGate("served the logged-out preview — set DFF_COOKIE")

        monkeypatch.setattr(nh, "DFFSalariesScraper", lambda: Gated())
        monkeypatch.setattr(nh, "USE_MOCK_DATA", False)

    def test_the_rows_already_held_are_kept(self, held, gated):
        nh.update_dfs_salaries_data()
        assert len(nh.dfs_salaries_data) == 400, "stale but whole beats half-refreshed"

    def test_the_reason_reaches_the_status_endpoint(self, held, gated):
        nh.update_dfs_salaries_data()
        assert "DFF_COOKIE" in nh.dfs_last_error

    def test_it_does_not_queue_a_retry_it_cannot_win(self, held, gated, monkeypatch):
        # The page answers the same way in twenty minutes; what is missing is a
        # cookie, not a moment of bad luck. A retry loop would bury the one
        # message that says so.
        tried = []
        monkeypatch.setattr(nh, "_schedule_dfs_retry", lambda reason: tried.append(reason))
        nh.update_dfs_salaries_data()
        assert tried == []

    def test_an_ordinary_failure_still_retries(self, held, monkeypatch):
        class Broken:
            def get_salaries_with_sleeper_ids(self, *args, **kwargs):
                raise requests.RequestException("connection reset")

        monkeypatch.setattr(nh, "DFFSalariesScraper", lambda: Broken())
        monkeypatch.setattr(nh, "USE_MOCK_DATA", False)
        tried = []
        monkeypatch.setattr(nh, "_schedule_dfs_retry", lambda reason: tried.append(reason))

        nh.update_dfs_salaries_data()
        assert tried, "a dropped connection is worth trying again"
        assert len(nh.dfs_salaries_data) == 400
