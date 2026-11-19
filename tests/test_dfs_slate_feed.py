"""
The slate's own data feed, used when the projections page is gated.

Found while looking for a way round the account gate: the hub at /nfl renders a
handful of players server-side and fetches the rest from
/data/playerdetails/nfl/dk/{slate}, so the whole slate arrives as JSON — and
without an account.

It is a better source than the page in two ways. The projection comes through
at full precision rather than the tenth the HTML prints (8.050 against 8.1), and
it has no kickoff times to be missing, so the caller fills those from our own
schedule, which is published in full before the week starts. DFF's own column
had 58 rows blank on week 11, two whole games among them.

What it does not carry is the rolling averages and the game total. That is why
it is the fallback and not the source, and why a run that used it says so.
"""

import pytest

import nfl_helper as nh
from get_dfs_salaries_and_stats import DFFAccountGate, DFFSalariesScraper

# Shaped on the real response for slate 26466 on 2026-11-19.
FEED = [
    {"first_name": "Jahmyr", "last_name": "Gibbs", "team": "DET", "opp": "TB",
     "location": "vs", "position_code": "RB", "salary": 10000, "ppg": 24.285,
     "value": 2.43, "opp_rank": 1, "injury_status": "", "team_spread": -6.5,
     "projected_team_score": 27.0},
    {"first_name": "Kenneth", "last_name": "Walker III", "team": "KC", "opp": "ARI",
     "location": "vs", "position_code": "RB", "salary": 9000, "ppg": 19.300,
     "value": 2.14, "opp_rank": 20, "injury_status": "Q", "team_spread": -3.0,
     "projected_team_score": 25.5},
    {"first_name": "Bills", "last_name": "", "team": "BUF", "opp": "MIA",
     "location": "vs", "position_code": "DST", "salary": 3400, "ppg": 7.9,
     "value": 2.32, "opp_rank": 8, "injury_status": None, "team_spread": -9.5,
     "projected_team_score": 26.0},
]


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def scraper(monkeypatch):
    monkeypatch.delenv("DFF_COOKIE", raising=False)
    return DFFSalariesScraper()


class TestReadingTheFeed:
    def test_it_gives_the_whole_slate(self, scraper, monkeypatch):
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: _Response(FEED))
        players = scraper.scrape_slate_feed("26466")
        assert [p["name"] for p in players] == [
            "Jahmyr Gibbs", "Kenneth Walker III", "Bills",
        ]

    def test_the_shape_matches_what_the_page_parser_produces(self, scraper, monkeypatch):
        # Everything downstream — the Sleeper matching, the storage key, the
        # kickoff check — must not be able to tell the two apart.
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: _Response(FEED))
        gibbs = scraper.scrape_slate_feed("26466")[0]
        assert set(gibbs) == {
            "name", "position", "team", "salary", "projected_points", "value_proj",
            "opponent", "season_avg", "l5_avg", "l10_avg", "week", "spread",
            "over_under", "proj_team_score", "opp_rank", "injury_status", "start_date",
        }

    def test_the_projection_keeps_its_precision(self, scraper, monkeypatch):
        # The HTML rounds to a tenth; the feed does not.
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: _Response(FEED))
        assert scraper.scrape_slate_feed("26466")[0]["projected_points"] == 24.285

    def test_what_the_feed_cannot_answer_is_null_not_absent(self, scraper, monkeypatch):
        # A missing key reads as a bug; a null reads as unknown, which is true.
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: _Response(FEED))
        gibbs = scraper.scrape_slate_feed("26466")[0]
        for field in ("season_avg", "l5_avg", "l10_avg", "over_under", "start_date"):
            assert gibbs[field] is None, field

    def test_a_defence_comes_through_named_and_positioned(self, scraper, monkeypatch):
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: _Response(FEED))
        bills = scraper.scrape_slate_feed("26466")[2]
        assert bills["name"] == "Bills"
        assert bills["position"] == "DST"
        assert bills["injury_status"] is None

    def test_an_empty_injury_string_is_nothing_rather_than_empty(self, scraper, monkeypatch):
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: _Response(FEED))
        assert scraper.scrape_slate_feed("26466")[0]["injury_status"] is None
        assert scraper.scrape_slate_feed("26466")[1]["injury_status"] == "Q"

    def test_something_that_is_not_a_list_is_not_players(self, scraper, monkeypatch):
        monkeypatch.setattr(scraper.session, "get",
                            lambda *a, **k: _Response({"error": "nope"}))
        assert scraper.scrape_slate_feed("26466") == []


class TestFixturesFromOurOwnSchedule:
    SCHEDULE = {11: [
        {"home_team": "DET", "away_team": "TB", "gameday": "2026-11-22", "gametime": "13:00"},
        {"home_team": "KC", "away_team": "ARI", "gameday": "2026-11-22", "gametime": "16:25"},
        {"home_team": "LA", "away_team": "SEA", "gameday": "2026-11-22", "gametime": "20:20"},
    ]}

    @pytest.fixture(autouse=True)
    def schedule(self, monkeypatch):
        monkeypatch.setattr(nh.nflverse_stats, "nflverse_games", self.SCHEDULE)

    def test_both_sides_of_a_game_get_its_kickoff(self):
        rows = [{"team": "DET"}, {"team": "TB"}, {"team": "KC"}]
        assert nh.fill_times_from_schedule(rows, 11) == 3
        assert rows[0]["game_start_time"] == "13:00"
        assert rows[1]["game_start_time"] == "13:00"
        assert rows[2]["game_start_time"] == "16:25"
        assert rows[0]["game_date"] == "2026-11-22"
        assert rows[0]["week"] == 11

    def test_the_rams_are_spelt_two_ways_and_still_found(self):
        # DFF writes LAR, nflverse writes LA. Three teams differ, and on a
        # fallback run it is the whole of their kickoff times.
        rows = [{"team": "LAR"}]
        assert nh.fill_times_from_schedule(rows, 11) == 1
        assert rows[0]["game_start_time"] == "20:20"

    def test_a_time_the_scrape_already_has_is_not_overwritten(self):
        rows = [{"team": "DET", "game_start_time": "16:05", "game_date": "2026-11-22"}]
        assert nh.fill_times_from_schedule(rows, 11) == 0
        assert rows[0]["game_start_time"] == "16:05"

    def test_a_team_not_playing_that_week_is_left_alone(self):
        rows = [{"team": "NYJ"}]
        assert nh.fill_times_from_schedule(rows, 11) == 0
        assert "game_start_time" not in rows[0]

    def test_a_week_we_hold_no_schedule_for_changes_nothing(self):
        rows = [{"team": "DET"}]
        assert nh.fill_times_from_schedule(rows, 99) == 0


class TestTheStoreIsTimedWeekByWeek:
    """The store holds more than one week, so the week comes off each row."""

    SCHEDULE = {
        10: [{"home_team": "CIN", "away_team": "PIT",
              "gameday": "2026-11-15", "gametime": "20:20"}],
        11: [{"home_team": "DET", "away_team": "TB",
              "gameday": "2026-11-22", "gametime": "13:00"}],
    }

    @pytest.fixture(autouse=True)
    def schedule(self, monkeypatch):
        monkeypatch.setattr(nh.nflverse_stats, "nflverse_games", self.SCHEDULE)

    def test_each_row_is_timed_against_its_own_week(self):
        rows = [
            {"team": "CIN", "week": 10},
            {"team": "DET", "week": 11},
        ]
        assert nh.fill_kickoffs_from_schedule(rows) == 2
        assert rows[0]["game_start_time"] == "20:20"
        assert rows[0]["game_date"] == "2026-11-15"
        assert rows[1]["game_start_time"] == "13:00"
        assert rows[1]["game_date"] == "2026-11-22"

    def test_a_team_playing_in_both_weeks_is_not_given_the_wrong_one(self):
        # The failure this grouping exists to prevent: one week's kickoff
        # written onto another week's row.
        rows = [{"team": "CIN", "week": 10}, {"team": "CIN", "week": 11}]
        nh.fill_kickoffs_from_schedule(rows)
        assert rows[0]["game_date"] == "2026-11-15"
        assert "game_date" not in rows[1], "CIN does not play in week 11 here"

    def test_a_row_with_no_week_is_left_for_the_other_fill(self):
        rows = [{"team": "DET"}]
        assert nh.fill_kickoffs_from_schedule(rows) == 0

    def test_it_does_not_overwrite_a_time_the_scrape_supplied(self):
        rows = [{"team": "DET", "week": 11, "game_start_time": "16:25"}]
        assert nh.fill_kickoffs_from_schedule(rows) == 0
        assert rows[0]["game_start_time"] == "16:25"

    def test_the_team_mate_copy_still_covers_a_week_we_cannot_place(self):
        # Belt and braces: a week with no schedule falls through to the fill
        # that needs none, which is what happens on every boot.
        rows = [
            {"team": "NYJ", "week": 18, "game_date": "2027-01-03",
             "game_start_time": "13:00"},
            {"team": "NYJ", "week": 18, "game_date": "2027-01-03",
             "game_start_time": None},
        ]
        assert nh.fill_kickoffs_from_schedule(rows) == 0
        assert nh.fill_missing_kickoffs(rows) == 1
        assert rows[1]["game_start_time"] == "13:00"


class TestWhatTheRunReports:
    @pytest.fixture
    def falling_back(self, monkeypatch):
        class Fallback:
            used_feed_fallback = True

            def get_salaries_with_sleeper_ids(self, *a, **k):
                return [{
                    "sleeper_id": "9224", "name": "Chase Brown", "team": "CIN",
                    "position": "RB", "salary": 6400, "projected_points": 15.895,
                    "week": None, "game_date": None, "game_start_time": None,
                }]

        monkeypatch.setattr(nh, "DFFSalariesScraper", lambda: Fallback())
        monkeypatch.setattr(nh, "USE_MOCK_DATA", False)
        monkeypatch.setattr(nh, "dfs_salaries_data", {})
        monkeypatch.setattr(nh, "dfs_scrape_runs", [])
        monkeypatch.setattr(nh, "save_dfs_scrape_runs", lambda: None)
        monkeypatch.setattr(nh, "save_dfs_salaries_data", lambda: None)
        monkeypatch.setattr(nh, "current_nfl_week", 11)
        monkeypatch.setattr(nh.nflverse_stats, "nflverse_games", {11: [
            {"home_team": "CIN", "away_team": "WAS",
             "gameday": "2026-11-23", "gametime": "20:15"},
        ]})

    def test_it_is_recorded_as_a_fallback_rather_than_a_plain_success(self, falling_back, monkeypatch):
        # "ok" would hide the one thing worth acting on; "gated" would hide
        # that the slate is current.
        monkeypatch.setattr(nh, "_fetch_current_week_from_sleeper", lambda: 11, raising=False)
        nh.update_dfs_salaries_data()
        assert nh.dfs_scrape_runs[0]["outcome"] == "fallback"

    def test_the_cookie_complaint_survives_the_success(self, falling_back):
        nh.update_dfs_salaries_data()
        assert "DFF_COOKIE" in (nh.dfs_last_error or "")
