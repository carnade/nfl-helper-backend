"""
A retired prop market is neither bought nor served.

Credits are a purchased balance and every event costs (markets x regions), so
a market left in the request list keeps costing a flat share of the prop bill
whether or not anyone looks at it. These tests pin both halves of dropping one:
it stops being asked for, and the copy already sitting in the cache and the
grading history stops being handed out.
"""

import odds_api as oa
import routes_odds


class TestNotBought:
    def test_retired_market_is_not_requested(self):
        for market in oa.RETIRED_PROP_MARKETS:
            assert market not in oa.PROP_MARKETS

    def test_anytime_td_is_the_retired_one(self):
        assert "player_anytime_td" in oa.RETIRED_PROP_MARKETS

    def test_the_markets_still_bought_are_the_yardage_and_volume_ones(self):
        assert oa.PROP_MARKETS == [
            "player_pass_yds",
            "player_rush_attempts",
            "player_rush_yds",
            "player_receptions",
            "player_reception_yds",
        ]


class TestStillReadable:
    """
    The binary machinery has to survive the retirement: the grading history
    still holds these rows, and interpreting a stored anytime-TD line needs the
    same tables it was written with.
    """

    def test_binary_handling_is_retained(self):
        assert "player_anytime_td" in oa.BINARY_MARKETS
        assert "player_anytime_td" in oa.PROP_GAME_STAT_COLS
        assert "player_anytime_td" in oa.MARKET_TO_DEF_STAT

    def test_putting_it_back_is_one_line_in_each_list(self):
        # Nothing else gates the market, so re-enabling means adding it to
        # PROP_MARKETS and removing it from RETIRED_PROP_MARKETS.
        assert oa.RETIRED_PROP_MARKETS == {"player_anytime_td"}


class TestNotServed:
    def test_live_props_drops_retired_markets(self):
        kept = routes_odds._live_props({
            "player_rush_yds": {"line": 55.5},
            "player_anytime_td": {"best_over_price": 2.4},
        })
        assert set(kept) == {"player_rush_yds"}

    def test_live_props_tolerates_nothing(self):
        assert routes_odds._live_props(None) == {}
        assert routes_odds._live_props({}) == {}

    def test_a_player_with_only_retired_props_is_left_out(self, client, monkeypatch):
        # The cached fetch outlives the decision, so until the next refresh the
        # only thing keeping these off the page is the serving filter.
        monkeypatch.setattr(oa, "odds_props", [
            {"sleeper_id": "1", "name": "Only TD", "position": "RB", "team": "KC",
             "event_id": "e1", "commence_time": "2026-10-25T17:00:00Z",
             "props": {"player_anytime_td": {"best_over_price": 2.4}}},
            {"sleeper_id": "2", "name": "Has Yards", "position": "RB", "team": "KC",
             "event_id": "e1", "commence_time": "2026-10-25T17:00:00Z",
             "props": {"player_rush_yds": {"line": 55.5},
                       "player_anytime_td": {"best_over_price": 2.4}}},
        ])
        rows = client.get("/odds/props").get_json()
        assert [r["sleeper_id"] for r in rows] == ["2"]
        assert set(rows[0]["props"]) == {"player_rush_yds"}

    def test_single_player_route_also_filters(self, client, monkeypatch):
        monkeypatch.setattr(oa, "odds_props", [
            {"sleeper_id": "2", "name": "Has Yards", "position": "RB", "team": "KC",
             "event_id": "e1", "commence_time": "2026-10-25T17:00:00Z",
             "props": {"player_rush_yds": {"line": 55.5},
                       "player_anytime_td": {"best_over_price": 2.4}}},
        ])
        body = client.get("/odds/props/2").get_json()
        assert set(body["props"]) == {"player_rush_yds"}

    def test_value_route_does_not_flag_a_retired_market(self, client, monkeypatch):
        monkeypatch.setattr(oa, "odds_props", [
            {"sleeper_id": "3", "name": "Flagged TD", "position": "WR", "team": "SF",
             "event_id": "e2", "commence_time": "2026-10-25T17:00:00Z",
             "props": {"player_anytime_td": {"best_over_price": 5.0,
                                             "value_flag": "over", "value_pct": 40}}},
        ])
        assert client.get("/odds/value").get_json() == []

    def test_results_drop_retired_markets_before_the_hit_rates(self, client, monkeypatch):
        # Dropped before summarising, so a market we no longer buy cannot go on
        # moving an overall hit rate that is meant to be comparable over time.
        monkeypatch.setattr(oa, "grade_props_history", lambda: [
            {"market": "player_rush_yds", "position": "RB",
             "result": {"call_correct": True, "projection_side_correct": True}},
            {"market": "player_anytime_td", "position": "RB",
             "result": {"call_correct": False, "projection_side_correct": False}},
        ])
        body = client.get("/odds/prop-results").get_json()
        assert [r["market"] for r in body["results"]] == ["player_rush_yds"]
        assert "player_anytime_td" not in body["by_market"]
        assert body["summary"]["flagged_hit_rate"] == 1.0


class TestNotGraded:
    def test_snapshot_does_not_freeze_a_retired_market(self, monkeypatch):
        monkeypatch.setattr(oa, "odds_props", [
            {"event_id": "e1", "sleeper_id": "9", "name": "Mixed", "position": "RB",
             "team": "KC", "commence_time": "2099-01-01T00:00:00Z",
             "props": {"player_rush_yds": {"line": 55.5},
                       "player_anytime_td": {"best_over_price": 2.4}}},
        ])
        monkeypatch.setattr(oa, "odds_props_history", {})
        oa.snapshot_current_props()
        markets = {k.rsplit(":", 1)[1] for k in oa.odds_props_history}
        assert markets == {"player_rush_yds"}
