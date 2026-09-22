"""Which prop calls we are willing to flag as value.

A yes/no market has no "no" side at any book, so an under on anytime TD is a
call that could never have been placed. It also fired constantly — a player yet
to score projects 0.0, which is under every price going — and those calls came
in whenever he simply did not score, which flattered the flagged hit rate from
43% to 56% across the first two weeks of 2026.
"""

import sys

import pytest

nfl_helper = sys.modules["nfl_helper"]

import odds_api as oa
import nflverse_stats as ns


ANYTIME_TD = "player_anytime_td"


@pytest.fixture(autouse=True)
def bare_stats():
    """No team stats means no matchup adjustment, so a projection is recent form
    alone and each case below turns on the threshold rather than the defence."""
    saved_players = dict(ns.nflverse_player_stats)
    saved_teams = dict(ns.nflverse_team_stats)
    ns.nflverse_player_stats.clear()
    ns.nflverse_team_stats.clear()
    yield
    ns.nflverse_player_stats.clear(); ns.nflverse_player_stats.update(saved_players)
    ns.nflverse_team_stats.clear();   ns.nflverse_team_stats.update(saved_teams)


def _weeks(*td_counts):
    return [{"week": i + 1, "rushing_tds": n, "receiving_tds": 0.0}
            for i, n in enumerate(td_counts)]


def _flag(player_data, weekly=None, rolling_5=None):
    ns.nflverse_player_stats["1"] = {
        "weekly": weekly or [],
        "rolling_5": rolling_5 or {},
    }
    meta = {"1": {"name": "Test Player", "position": "WR", "team": "MIA"}}
    event = {"1": {"home_abbr": "MIA", "away_abbr": "KC"}}
    result = oa._compute_value_flags({"1": player_data}, event, meta)
    return result[0]["props"]


class TestAnytimeTd:
    def test_a_player_yet_to_score_is_not_flagged_under(self):
        """0.0 against any price is a huge negative edge, and used to flag."""
        props = _flag({ANYTIME_TD: {"best_over_price": 2.75}}, weekly=_weeks(0, 0, 0))

        entry = props[ANYTIME_TD]
        assert entry["projection"] == pytest.approx(0.0)
        assert entry["value_flag"] is None
        assert entry["value_pct"] is None

    def test_over_is_still_flagged(self):
        """Backing the yes side is a real bet, so nothing changes there."""
        props = _flag({ANYTIME_TD: {"best_over_price": 5.0}}, weekly=_weeks(1, 1, 1))

        assert props[ANYTIME_TD]["value_flag"] == "over"
        assert props[ANYTIME_TD]["value_pct"] > 0

    def test_a_scorer_priced_fairly_is_left_alone(self):
        props = _flag({ANYTIME_TD: {"best_over_price": 2.0}}, weekly=_weeks(1, 0))

        assert props[ANYTIME_TD]["value_flag"] is None

    def test_the_rest_of_the_entry_survives(self):
        """Only the call is withheld — the row still shows its numbers."""
        props = _flag({ANYTIME_TD: {"best_over_price": 2.75}}, weekly=_weeks(0, 0, 0))

        entry = props[ANYTIME_TD]
        assert entry["implied_prob"] == pytest.approx(0.3636, abs=1e-4)
        assert entry["sample_games"] == 3
        assert entry["grade_threshold"] == oa.BINARY_THRESHOLD


class TestYardageMarketsUnaffected:
    def test_under_is_still_flagged_on_a_real_line(self):
        """These have both sides on the board, so an under is bettable."""
        props = _flag({"player_rush_yds": {"line": 60.0}},
                      rolling_5={"rushing_yards": 30.0})

        assert props["player_rush_yds"]["value_flag"] == "under"
        assert props["player_rush_yds"]["value_pct"] == pytest.approx(-0.5)

    def test_over_is_still_flagged(self):
        props = _flag({"player_rush_yds": {"line": 30.0}},
                      rolling_5={"rushing_yards": 60.0})

        assert props["player_rush_yds"]["value_flag"] == "over"
