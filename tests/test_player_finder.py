"""
The Player Finder's one endpoint, and the join behind it.

Three dicts meet here that are owned by different parts of the app and keyed
the same way, so most of what can go wrong is a join problem: a player present
in one and absent from another, or a field renamed on the way out such that the
frontend's existing value helpers stop reading it.
"""

import sys

import pytest

import nflverse_stats as ns
import strength_of_schedule as sos

nfl_helper = sys.modules["nfl_helper"]


# ── Fixtures ─────────────────────────────────────────────────────────────────

def player_stats(name, position, team, points=120.0, games=6, last5=18.0):
    return {
        "name": name,
        "position": position,
        "team": team,
        "season_totals": {"fantasy_points_ppr": points, "games_played": games},
        "rolling_5": {"fantasy_points_ppr": last5},
        "weekly": [],
    }


GAMES = {
    1: [{"home_team": "GB", "away_team": "CHI", "home_score": 27, "away_score": 13}],
    2: [{"home_team": "GB", "away_team": "MIN", "home_score": None, "away_score": None}],
    15: [{"home_team": "GB", "away_team": "CHI", "home_score": None, "away_score": None}],
    16: [{"home_team": "MIN", "away_team": "GB", "home_score": None, "away_score": None}],
    17: [{"home_team": "GB", "away_team": "MIN", "home_score": None, "away_score": None}],
}

TEAM_STATS = {
    "GB": {"def_fpts_allowed_qb_per_game": 18.0, "def_fpts_allowed_wr_per_game": 30.0},
    "CHI": {"def_fpts_allowed_qb_per_game": 22.0, "def_fpts_allowed_wr_per_game": 36.0},
    "MIN": {"def_fpts_allowed_qb_per_game": 14.0, "def_fpts_allowed_wr_per_game": 26.0},
}


@pytest.fixture(autouse=True)
def nflverse_loaded():
    """Populate the nflverse globals, and put them back afterwards."""
    for store in (ns.nflverse_player_stats, ns.nflverse_team_stats,
                  ns.nflverse_games, ns.nflverse_team_sos):
        store.clear()

    ns.nflverse_player_stats.update({
        "1": player_stats("Jordan Love", "QB", "GB"),
        "2": player_stats("Jayden Reed", "WR", "GB", points=90.0, games=5, last5=12.5),
        "3": player_stats("Brandon McManus", "K", "GB"),
        "4": player_stats("Nobody Here", "WR", None),
    })
    ns.nflverse_team_stats.update(TEAM_STATS)
    ns.nflverse_games.update(GAMES)
    ns.nflverse_team_sos.update(sos.build_team_sos(
        GAMES, sos.team_records(GAMES),
        {"CHI": {"win_pct": 0.75}, "MIN": {"win_pct": 0.25}, "GB": {"win_pct": 0.5}},
        TEAM_STATS,
    ))
    yield
    for store in (ns.nflverse_player_stats, ns.nflverse_team_stats,
                  ns.nflverse_games, ns.nflverse_team_sos):
        store.clear()


FILTERED = {
    "1": {
        "first_name": "Jordan", "last_name": "Love", "age": 27,
        "position": "QB", "team": "GB", "injury_status": None,
        "KTC Value": 5600, "KTC Position Rank": "QB8", "FC Value": 4100,
        "pts_ppr": 118.4, "gp": 6,
    },
}


def rows_by_id(filtered=FILTERED):
    return {row["sleeper_id"]: row for row in ns.build_finder_rows(filtered)}


# ── Who is in the universe ───────────────────────────────────────────────────

class TestTheUniverse:
    def test_only_qb_rb_wr_te(self):
        """
        Kickers are dropped: the dynasty sources do not price them and there is
        no points-allowed-to-kickers figure, so every column that matters would
        be blank. Defences never appear in nflverse_player_stats at all.
        """
        rows = rows_by_id()

        assert set(rows) == {"1", "2", "4"}
        assert "3" not in rows, "the kicker should not be in the payload"
        assert ns.FINDER_POSITIONS == ("QB", "RB", "WR", "TE")

    def test_a_player_the_dynasty_scrape_has_never_priced_still_appears(self):
        """
        Unknown is not zero. Dropping them would hide real players; zeroing them
        would make them look worthless.
        """
        row = rows_by_id()["2"]

        assert row["KTC Value"] is None
        assert row["FC Value"] is None
        assert row["last5_ppg"] == 12.5, "nflverse's own figures still come through"
        assert row["games_played"] == 5

    def test_the_season_figures_fall_back_to_nflverse(self):
        """
        Sleeper only carries these for players its own stats feed covers. Without
        the fallback the points and points-per-game columns — and the
        cost-per-point ratio built on them — would be blank for part of the table
        while the last-5 column beside them was filled in for everyone.
        """
        row = rows_by_id()["2"]

        assert row["pts_ppr"] == 90.0, "from nflverse's season_totals"
        assert row["gp"] == 5

    def test_sleepers_own_figures_win_where_it_has_them(self):
        row = rows_by_id()["1"]

        assert row["pts_ppr"] == 118.4, "Sleeper's, not nflverse's 120.0"
        assert row["gp"] == 6

    def test_the_name_falls_back_to_nflverses_own(self):
        row = rows_by_id()["2"]

        assert (row["first_name"], row["last_name"]) == ("Jayden", "Reed")

    def test_filtered_players_wins_where_both_have_a_name(self):
        row = rows_by_id()["1"]

        assert (row["first_name"], row["last_name"]) == ("Jordan", "Love")


# ── The contract the frontend reads ──────────────────────────────────────────

class TestFieldNames:
    def test_the_value_and_points_keys_are_spelled_as_filtered_players_spells_them(self):
        """
        The frontend calls its existing playerValueOf() and pointsPerGame() on
        these rows unmodified, and both destructure these exact names. Renaming
        any of them here silently blanks a column over there.
        """
        row = rows_by_id()["1"]

        assert row["KTC Value"] == 5600
        assert row["FC Value"] == 4100
        assert row["pts_ppr"] == 118.4
        assert row["gp"] == 6
        assert row["age"] == 27

    def test_both_games_counts_are_present_and_separate(self):
        """
        Sleeper's `gp` drives points-per-game; nflverse's `games_played` is what
        the last-5 average is drawn from. They can disagree, so each filter
        counts what it actually filters.
        """
        row = rows_by_id()["1"]

        assert row["gp"] == 6
        assert row["games_played"] == 6


# ── The schedule block ───────────────────────────────────────────────────────

class TestStrengthOfSchedule:
    def test_both_windows_and_all_three_bases_reach_the_row(self):
        sos_block = rows_by_id()["1"]["sos"]

        assert set(sos_block) == {"ros", "post"}
        assert set(sos_block["ros"]) == {"2025", "2026", "vspos"}

    def test_vspos_is_narrowed_to_the_players_own_position(self):
        """
        A quarterback and a receiver on the same roster share a schedule but not
        a matchup. GB's playoff opponents are CHI, MIN, MIN.
        """
        rows = rows_by_id()
        qb = rows["1"]["sos"]["post"]["vspos"]["value"]
        wr = rows["2"]["sos"]["post"]["vspos"]["value"]

        assert qb == pytest.approx((22.0 + 14.0 + 14.0) / 3, abs=1e-4)
        assert wr == pytest.approx((36.0 + 26.0 + 26.0) / 3, abs=1e-4)
        assert qb != wr

    def test_a_player_with_no_team_has_no_schedule(self):
        assert rows_by_id()["4"]["sos"] is None

    def test_the_remaining_window_leaves_out_what_has_been_played(self):
        """
        GB's week 1 is final, so what is left is weeks 2, 15, 16 and 17 — four
        games. Counted on the vspos basis because every team has a defensive
        figure, where only some have a record (see the next test).
        """
        ros = rows_by_id()["1"]["sos"]["ros"]

        assert ros["vspos"]["games"] == 4

    def test_an_opponent_with_no_record_yet_cannot_contribute_a_win_pct(self):
        """
        The reason the 2025 basis exists. MIN has not finished a game in this
        fixture, so three of GB's four remaining opponents have no win % and the
        2026 average rests on the one team that does. Early in a real season
        that is the normal state of this column, and averaging an absent record
        in as 0.000 would make every schedule look like a cakewalk.
        """
        ros = rows_by_id()["1"]["sos"]["ros"]

        assert ros["vspos"]["games"] == 4
        assert ros["2026"]["games"] == 1, "only CHI has played"
        assert ros["2025"]["games"] == 4, "last season's records cover everyone"

    def test_the_two_year_bases_are_reported_separately(self):
        sos_block = rows_by_id()["1"]["sos"]["post"]

        assert sos_block["2025"]["value"] != sos_block["2026"]["value"]
        assert sos_block["2025"]["rank"] and sos_block["2026"]["rank"]


# ── The endpoint ─────────────────────────────────────────────────────────────

class TestEndpoint:
    def test_it_serves_the_whole_universe_uncapped(self, client):
        nfl_helper.filtered_players.update(FILTERED)

        response = client.get("/player-finder/data")

        assert response.status_code == 200
        body = response.get_json()
        assert isinstance(body, list), "a plain array, not a map"
        assert len(body) == 3, "every non-kicker, with no limit applied"

    def test_it_joins_in_the_dynasty_values(self, client):
        nfl_helper.filtered_players.update(FILTERED)

        body = client.get("/player-finder/data").get_json()
        love = next(r for r in body if r["sleeper_id"] == "1")

        assert love["KTC Value"] == 5600
        assert love["sos"]["post"]["vspos"]["rank"]

    def test_it_answers_before_the_dynasty_scrape_has_run(self, client):
        """
        filtered_players is empty on a cold boot for a while. The Finder should
        come back with players and blank values rather than an error.
        """
        response = client.get("/player-finder/data")

        assert response.status_code == 200
        body = response.get_json()
        assert len(body) == 3
        assert all(row["KTC Value"] is None for row in body)
