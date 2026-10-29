"""
Strength of schedule: records, windows, and which direction "tough" runs.

The polarity tests are the ones worth keeping honest. Rank 1 has to mean the
hardest schedule on every basis, including the one where a *low* number is the
hard one, because the frontend paints all three with the same red-to-green ramp.
Get it backwards on one basis and the table confidently recommends the worst
players on it.
"""

import pytest

import strength_of_schedule as sos


# ── Helpers ──────────────────────────────────────────────────────────────────

def game(home, away, home_score=None, away_score=None):
    return {"home_team": home, "away_team": away,
            "home_score": home_score, "away_score": away_score}


def schedule(**weeks):
    """`schedule(w1=[game(...)])` → `{1: [game(...)]}`."""
    return {int(label.lstrip("w")): games for label, games in weeks.items()}


# ── team_records ─────────────────────────────────────────────────────────────

class TestTeamRecords:
    def test_a_finished_game_credits_both_sides(self):
        records = sos.team_records(schedule(w1=[game("GB", "CHI", 27, 13)]))

        assert records["GB"] == {"w": 1, "l": 0, "t": 0, "games": 1, "win_pct": 1.0}
        assert records["CHI"] == {"w": 0, "l": 1, "t": 0, "games": 1, "win_pct": 0.0}

    def test_the_away_side_can_win(self):
        records = sos.team_records(schedule(w1=[game("GB", "CHI", 13, 27)]))

        assert records["CHI"]["w"] == 1
        assert records["GB"]["l"] == 1

    def test_a_tie_is_half_a_win_to_each(self):
        """There is a 1-4-1 team in the live season, so this is not academic."""
        records = sos.team_records(schedule(
            w1=[game("WAS", "DAL", 20, 20)],
            w2=[game("WAS", "NYG", 10, 24)],
        ))

        assert records["WAS"]["t"] == 1
        assert records["WAS"]["win_pct"] == pytest.approx(0.25)  # (0 + 0.5) / 2

    def test_an_unplayed_game_contributes_nothing(self):
        records = sos.team_records(schedule(
            w1=[game("GB", "CHI", 27, 13)],
            w2=[game("GB", "MIN")],
        ))

        assert records["GB"]["games"] == 1
        assert "MIN" not in records, "a team whose only game is unplayed has no record"

    def test_a_half_reported_score_is_not_a_result(self):
        records = sos.team_records(schedule(w1=[game("GB", "CHI", 27, None)]))

        assert records == {}

    def test_a_team_with_no_finished_game_has_no_win_pct(self):
        """
        None, not 0.0. A team that has not played and a team that has lost
        everything are different facts, and averaging the second where the
        first was meant makes every schedule look easy in week 1.
        """
        records = sos.team_records(schedule(
            w1=[game("GB", "CHI", 27, 13), game("MIN", "DET")],
        ))

        assert "MIN" not in records
        assert records["GB"]["win_pct"] == 1.0

    def test_an_empty_schedule_is_not_an_error(self):
        assert sos.team_records({}) == {}
        assert sos.team_records(None) == {}


# ── opponents and windows ────────────────────────────────────────────────────

class TestOpponents:
    def test_opponents_come_back_in_week_order(self):
        games = schedule(
            w1=[game("GB", "CHI")],
            w2=[game("MIN", "GB")],
            w3=[game("GB", "DET")],
        )

        assert sos.opponents(games, "GB", [1, 2, 3]) == ["CHI", "MIN", "DET"]

    def test_a_bye_is_simply_absent(self):
        """
        Not an edge case: 22 of 32 teams have a bye still to come, so one
        team's remaining average covers ten games and another's eleven.
        """
        games = schedule(w1=[game("GB", "CHI")], w3=[game("GB", "DET")])

        assert sos.opponents(games, "GB", [1, 2, 3]) == ["CHI", "DET"]

    def test_only_unplayed_skips_a_finished_game(self):
        games = schedule(
            w1=[game("GB", "CHI", 27, 13)],
            w2=[game("GB", "DET")],
        )

        assert sos.opponents(games, "GB", [1, 2], only_unplayed=True) == ["DET"]
        assert sos.opponents(games, "GB", [1, 2]) == ["CHI", "DET"]

    def test_remaining_weeks_are_the_ones_with_a_game_left(self):
        games = schedule(
            w1=[game("GB", "CHI", 27, 13)],
            w2=[game("GB", "DET", 20, 17), game("MIN", "NYG")],
            w3=[game("GB", "MIN")],
        )

        assert sos.remaining_weeks(games) == [2, 3]

    def test_the_playoff_window_is_fixed(self):
        assert sos.PLAYOFF_WEEKS == (15, 16, 17)


# ── average_over_opponents ───────────────────────────────────────────────────

class TestAverageOverOpponents:
    def test_it_averages_and_counts(self):
        cell = sos.average_over_opponents(["A", "B"], {"A": 1.0, "B": 0.0}.get)

        assert cell == {"value": 0.5, "games": 2}

    def test_an_opponent_with_no_figure_is_skipped_and_not_counted(self):
        cell = sos.average_over_opponents(["A", "B"], {"A": 1.0}.get)

        assert cell == {"value": 1.0, "games": 1}, "B must not drag the mean toward zero"

    def test_nothing_known_is_none_rather_than_zero(self):
        assert sos.average_over_opponents(["A"], {}.get) is None
        assert sos.average_over_opponents([], {"A": 1.0}.get) is None


# ── Which way "tough" runs ───────────────────────────────────────────────────

class TestRankPolarity:
    def test_the_highest_win_pct_is_rank_one(self):
        cells = {
            "hard": {"value": 0.8, "games": 3},
            "mid": {"value": 0.5, "games": 3},
            "easy": {"value": 0.2, "games": 3},
        }

        sos.rank_cells(cells, tougher="higher")

        assert [cells[t]["rank"] for t in ("hard", "mid", "easy")] == [1, 2, 3]

    def test_the_fewest_points_allowed_is_also_rank_one(self):
        """
        The inverted one. A defence that concedes least is the hardest draw, so
        on this basis a low number earns rank 1 — and the frontend's red-to-green
        ramp then reads the same way on all three bases.
        """
        cells = {
            "stingy": {"value": 25.0, "games": 3},
            "mid": {"value": 30.0, "games": 3},
            "leaky": {"value": 39.0, "games": 3},
        }

        sos.rank_cells(cells, tougher="lower")

        assert [cells[t]["rank"] for t in ("stingy", "mid", "leaky")] == [1, 2, 3]

    def test_a_team_with_no_figure_goes_unranked_not_last(self):
        """Last would read as the easiest schedule in the league."""
        cells = {"known": {"value": 0.5, "games": 1}, "unknown": None}

        sos.rank_cells(cells)

        assert cells["known"]["rank"] == 1
        assert cells["unknown"] is None


# ── build_team_sos ───────────────────────────────────────────────────────────

# Four teams, so ranks run 1-4 and are easy to read. Weeks 1-2 are played,
# 3 and 15-17 are not.
FOUR_TEAM_SCHEDULE = schedule(
    w1=[game("AAA", "BBB", 30, 0), game("CCC", "DDD", 10, 7)],
    w2=[game("AAA", "CCC", 20, 17), game("BBB", "DDD", 14, 21)],
    w3=[game("AAA", "DDD"), game("BBB", "CCC")],
    w15=[game("AAA", "BBB"), game("CCC", "DDD")],
    w16=[game("AAA", "CCC"), game("BBB", "DDD")],
    w17=[game("AAA", "DDD"), game("BBB", "CCC")],
)

TEAM_STATS = {
    "AAA": {"def_fpts_allowed_wr_per_game": 20.0, "def_fpts_allowed_te_per_game": 5.0},
    "BBB": {"def_fpts_allowed_wr_per_game": 30.0, "def_fpts_allowed_te_per_game": 15.0},
    "CCC": {"def_fpts_allowed_wr_per_game": 40.0, "def_fpts_allowed_te_per_game": 10.0},
    "DDD": {"def_fpts_allowed_wr_per_game": 50.0, "def_fpts_allowed_te_per_game": 20.0},
}


@pytest.fixture
def built():
    this_season = sos.team_records(FOUR_TEAM_SCHEDULE)
    last_season = {
        "AAA": {"win_pct": 0.0}, "BBB": {"win_pct": 1.0},
        "CCC": {"win_pct": 0.5}, "DDD": {"win_pct": 0.5},
    }
    return sos.build_team_sos(FOUR_TEAM_SCHEDULE, this_season, last_season,
                              TEAM_STATS, positions=("wr", "te"))


class TestBuildTeamSos:
    def test_both_windows_and_all_three_bases_are_present(self, built):
        assert set(built) == {"AAA", "BBB", "CCC", "DDD"}
        for window in ("ros", "post"):
            assert set(built["AAA"][window]) == {"2025", "2026", "vspos"}
        assert set(built["AAA"]["ros"]["vspos"]) == {"wr", "te"}

    def test_the_remaining_window_excludes_played_games(self, built):
        """AAA's week 1 and 2 are done, so only week 3 and the playoffs remain."""
        assert built["AAA"]["ros"]["2026"]["games"] == 4  # w3, w15, w16, w17

    def test_the_playoff_window_is_three_games_regardless(self, built):
        for team in built:
            assert built[team]["post"]["2026"]["games"] == 3

    def test_the_two_year_bases_can_disagree(self, built):
        """
        Which is the entire reason both exist. BBB lost every game this season
        but won every game last season, so an opponent facing BBB has a soft
        2026 draw and the hardest possible 2025 one.
        """
        assert built["AAA"]["post"]["2025"]["value"] != built["AAA"]["post"]["2026"]["value"]

    def test_vspos_differs_by_position_for_the_same_team(self, built):
        """A WR and a TE on one roster do not have the same schedule."""
        wr = built["AAA"]["post"]["vspos"]["wr"]["value"]
        te = built["AAA"]["post"]["vspos"]["te"]["value"]

        # AAA's playoff opponents are BBB, CCC, DDD.
        assert wr == pytest.approx((30.0 + 40.0 + 50.0) / 3)
        assert te == pytest.approx((15.0 + 10.0 + 20.0) / 3)

    def test_vspos_ranks_the_stingiest_schedule_hardest(self, built):
        """
        Every team plays the other three in the playoff window, so each team's
        opponent set is "everyone but me". Facing AAA (20.0 to WRs) is the
        easiest thing to miss, so the team that does NOT play itself — i.e. AAA
        — has the leakiest opponents and the easiest rank.
        """
        ranks = {t: built[t]["post"]["vspos"]["wr"]["rank"] for t in built}
        values = {t: built[t]["post"]["vspos"]["wr"]["value"] for t in built}

        toughest = min(values, key=values.get)
        assert ranks[toughest] == 1, "fewest points allowed must rank 1"
        assert ranks[max(values, key=values.get)] == 4

    def test_ranks_are_a_permutation_within_each_basis(self, built):
        for window in ("ros", "post"):
            for basis in ("2025", "2026"):
                ranks = sorted(built[t][window][basis]["rank"] for t in built)
                assert ranks == [1, 2, 3, 4]

    def test_a_basis_with_no_records_comes_back_empty_not_zero(self):
        """A cold start has no last-season records; the column must say so."""
        this_season = sos.team_records(FOUR_TEAM_SCHEDULE)
        built = sos.build_team_sos(FOUR_TEAM_SCHEDULE, this_season, {}, TEAM_STATS)

        assert all(built[t]["ros"]["2025"] is None for t in built)
        assert built["AAA"]["ros"]["2026"] is not None
