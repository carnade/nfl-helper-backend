"""How far a line has come since we first saw it.

Thursday's refresh opens the week's props; Sunday's refreshes them the morning
of the slate. Both numbers were already being kept — the opening one in the
snapshot history, the current one in the live odds — they were simply never
joined, so the pages could only ever show where a line is, never where it came
from. Against the live board, 156 of 1,586 snapshotted props had moved, by up to
14 yards.

Games and props keep their opening line differently, which is why there are two
functions. A game is snapshotted once and never touched again, so the history
IS the opening. A prop keeps being updated until kickoff, so the history carries
first_line alongside the latest.
"""

import sys

import pytest

nfl_helper = sys.modules["nfl_helper"]

import odds_api as oa


@pytest.fixture(autouse=True)
def clean_odds():
    """conftest resets the nfl-helper globals; these live in odds_api, so they
    would otherwise carry between tests and one case's game would turn up in
    another's response."""
    for container in (oa.odds_games, oa.odds_history, oa.odds_props_history):
        container.clear()
    oa.odds_props.clear()
    yield
    for container in (oa.odds_games, oa.odds_history, oa.odds_props_history):
        container.clear()
    oa.odds_props.clear()


class TestGames:
    def test_the_first_snapshot_is_the_opening_line(self):
        oa.odds_history["e1"] = {
            "spread": {"home_spread": -3.5},
            "total": {"line": 44.5},
            "snapshotted_at": "2026-10-01T12:00:00Z",
        }
        assert oa.opening_game_lines("e1") == {
            "home_spread": -3.5, "total": 44.5, "seen_at": "2026-10-01T12:00:00Z"}

    def test_a_game_never_snapshotted_has_none(self):
        assert oa.opening_game_lines("unseen") is None

    def test_a_snapshot_missing_its_lines_does_not_explode(self):
        oa.odds_history["e2"] = {"snapshotted_at": "2026-10-01T12:00:00Z"}
        assert oa.opening_game_lines("e2") == {
            "home_spread": None, "total": None, "seen_at": "2026-10-01T12:00:00Z"}

    def test_the_opening_does_not_follow_the_live_line(self):
        """A game is written once on purpose, so what was offered cannot be
        rewritten after the fact. This is the property the column rests on."""
        oa.odds_history["e3"] = {"spread": {"home_spread": -3.5},
                                 "total": {"line": 44.5}, "snapshotted_at": "x"}
        oa.odds_games["e3"] = {"spread": {"home_spread": -7.0},
                               "total": {"line": 49.5}}
        assert oa.opening_game_lines("e3")["home_spread"] == -3.5


class TestProps:
    def _snapshot(self, first, latest):
        oa.odds_props_history["ev:111:player_rush_yds"] = {
            "first_line": first, "line": latest,
            "first_seen_at": "2026-10-01T12:00:00Z",
        }

    def test_it_reads_the_first_line_not_the_latest(self):
        self._snapshot(first=42.5, latest=56.5)
        got = oa.opening_prop_line("ev", "111", "player_rush_yds")
        assert got["line"] == 42.5, "the opening, not where it has got to"
        assert got["seen_at"] == "2026-10-01T12:00:00Z"

    def test_a_prop_never_snapshotted_has_none(self):
        assert oa.opening_prop_line("ev", "nobody", "player_rush_yds") is None

    def test_the_market_is_part_of_the_identity(self):
        self._snapshot(first=42.5, latest=56.5)
        assert oa.opening_prop_line("ev", "111", "player_reception_yds") is None


class TestTheRoutesCarryIt:
    def test_games_expose_their_opening(self, client):
        oa.odds_games["e9"] = {
            "event_id": "e9", "home_abbr": "MIN", "away_abbr": "GB",
            "commence_time": "2026-10-04T17:00:00Z",
            "spread": {"home_spread": -7.0}, "total": {"line": 49.5},
        }
        oa.odds_history["e9"] = {"spread": {"home_spread": -3.5},
                                 "total": {"line": 44.5}, "snapshotted_at": "x"}

        games = client.get("/odds/games").get_json()
        mine = [g for g in games if g["event_id"] == "e9"][0]

        assert mine["opening"]["home_spread"] == -3.5
        assert mine["opening"]["total"] == 44.5
        assert mine["spread"]["home_spread"] == -7.0, "the live line is untouched"

    def test_props_expose_their_opening(self, client):
        oa.odds_props.append({
            "event_id": "ev", "sleeper_id": "111", "name": "Test Player",
            "position": "RB", "team": "MIN",
            "commence_time": "2026-10-04T17:00:00Z",
            "props": {"player_rush_yds": {"line": 56.5}},
        })
        oa.odds_props_history["ev:111:player_rush_yds"] = {
            "first_line": 42.5, "line": 56.5, "first_seen_at": "2026-10-01T12:00:00Z"}

        players = client.get("/odds/props").get_json()
        mine = [p for p in players if p["sleeper_id"] == "111"][0]

        assert mine["props"]["player_rush_yds"]["opening"]["line"] == 42.5
        assert mine["props"]["player_rush_yds"]["line"] == 56.5

    def test_annotating_does_not_write_into_the_live_props(self, client):
        """The route copies before adding. Writing into odds_props would make
        the opening line look like part of the fetched data, and the next
        refresh would be comparing against itself."""
        live = {"line": 56.5}
        oa.odds_props.append({
            "event_id": "ev2", "sleeper_id": "222", "name": "Other",
            "position": "WR", "team": "GB",
            "commence_time": "2026-10-04T17:00:00Z",
            "props": {"player_rush_yds": live},
        })
        oa.odds_props_history["ev2:222:player_rush_yds"] = {
            "first_line": 10.5, "line": 56.5, "first_seen_at": "x"}

        client.get("/odds/props")

        assert "opening" not in live, "the live dict must come back unchanged"

    def test_a_prop_with_no_history_reports_no_opening(self, client):
        oa.odds_props.append({
            "event_id": "ev3", "sleeper_id": "333", "name": "Fresh",
            "position": "TE", "team": "MIN",
            "commence_time": "2026-10-04T17:00:00Z",
            "props": {"player_rush_yds": {"line": 20.5}},
        })
        players = client.get("/odds/props").get_json()
        mine = [p for p in players if p["sleeper_id"] == "333"][0]
        assert mine["props"]["player_rush_yds"]["opening"] is None
