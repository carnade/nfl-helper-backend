"""
Salary rows the scrape left without a kickoff time.

The scrape does not fill `game_start_time` on every row. In week 10 of 2026 it
left 144 of 478 empty — 30% — and not the obscure ones either: the Cardinals'
defence, Tre Tucker, a Rams tight end. The time was never missing from the
*slate*, only from those rows, so a team-mate in the same game carried it. All
144 were recoverable that way and not one ambiguously.

Left unfilled, the kickoff check guessed from the day of the week, and "Sunday"
meant the 1:00 PM slate. So from one o'clock every Sunday, every player whose
row happened to lack a time read as already playing, whatever time they really
kicked off. A real lineup built entirely from the 4:05 and 8:20 games was
refused at 14:46 ET with "games have already started" — and the page had let it
be built, because the browser's own fallback for an unknown kickoff guesses late
rather than early.

These tests are written around that lineup.
"""

import datetime

import pytest
import lzstring

import nfl_helper as nh


LZS = lzstring.LZString()


def _freeze(monkeypatch, when):
    """Pin 'now' in Eastern, which is what the check compares against."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    fixed = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=et)

    real = datetime.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(nh.datetime, "datetime", Frozen)


def row(sleeper_id, team, opponent, start_time, name, week=10, date="2026-11-15"):
    return {
        "sleeper_id": sleeper_id,
        "name": name,
        "team": team,
        "opponent": opponent,
        "week": week,
        "game_date": date,
        "game_start_time": start_time,
        "game_day": "Sunday",
    }


def lineup_data(ids, week=10, username="carnade"):
    body = ",".join(f"{i}-5000" for i in ids)
    return f"{week}|{LZS.compressToEncodedURIComponent(f'{username}:{body}')}"


class TestFillingFromTheSameGame:
    def test_a_team_mate_supplies_the_time(self):
        rows = [
            row("8150", "LAR", "ARI", "4:05PM", "Kyren Williams"),
            row("9999", "LAR", "ARI", None, "Davis Allen"),
        ]
        assert nh.fill_missing_kickoffs(rows) == 1
        assert rows[1]["game_start_time"] == "4:05PM"

    def test_the_opponent_supplies_it_when_the_team_cannot(self):
        rows = [
            row("8150", "ARI", "LAR", "4:05PM", "A Cardinal"),
            row("9999", "LAR", "ARI", None, "A Ram"),
        ]
        assert nh.fill_missing_kickoffs(rows) == 1
        assert rows[1]["game_start_time"] == "4:05PM"

    def test_a_defence_is_filled_like_anyone_else(self):
        # The one that prompted this: the Cardinals' defence had no time, and
        # its game was at 4:05, not one o'clock.
        rows = [
            row("8150", "ARI", "LAR", "4:05PM", "Michael Wilson"),
            row("ARI", "ARI", "LAR", None, "Cardinals"),
        ]
        nh.fill_missing_kickoffs(rows)
        assert rows[1]["game_start_time"] == "4:05PM"

    def test_a_time_already_there_is_never_overwritten(self):
        rows = [
            row("1", "PIT", "CIN", "8:20PM", "DK Metcalf"),
            row("2", "PIT", "CIN", "1:00PM", "Someone else"),
        ]
        assert nh.fill_missing_kickoffs(rows) == 0
        assert [r["game_start_time"] for r in rows] == ["8:20PM", "1:00PM"]

    def test_a_different_date_is_a_different_game(self):
        # Team and date together name a game. A Monday row must not take the
        # Sunday time, which is the whole reason the date is part of the key.
        rows = [
            row("1", "LAC", "BAL", "1:00PM", "Sunday guy", date="2026-11-15"),
            row("2", "LAC", "BAL", None, "Monday guy", date="2026-11-16"),
        ]
        assert nh.fill_missing_kickoffs(rows) == 0
        assert rows[1]["game_start_time"] is None

    def test_a_week_where_nothing_knows_is_left_alone(self):
        rows = [row("1", "SF", "DAL", None, "Nobody knows")]
        assert nh.fill_missing_kickoffs(rows) == 0
        assert rows[0]["game_start_time"] is None

    def test_an_empty_string_counts_as_missing(self):
        rows = [
            row("1", "SEA", "LV", "4:05PM", "JSN"),
            row("2", "SEA", "LV", "", "Somebody"),
            row("3", "SEA", "LV", "   ", "Somebody else"),
        ]
        assert nh.fill_missing_kickoffs(rows) == 2
        assert rows[1]["game_start_time"] == "4:05PM"
        assert rows[2]["game_start_time"] == "4:05PM"

    def test_a_row_without_a_date_or_team_is_skipped_rather_than_crashing(self):
        rows = [
            row("1", "KC", "ATL", "1:00PM", "Known"),
            {"sleeper_id": "2", "name": "No date", "team": "KC"},
            {"sleeper_id": "3", "name": "No team", "game_date": "2026-11-15"},
        ]
        nh.fill_missing_kickoffs(rows)
        assert rows[1].get("game_start_time") is None
        assert rows[2].get("game_start_time") is None

    def test_it_works_on_the_store_the_api_serves_from(self):
        # Called with dict.values(), because that is the live shape and the
        # rows are mutated in place rather than rebuilt.
        store = {
            "8150_W10_D2026-11-15": row("8150", "LAR", "ARI", "4:05PM", "Kyren"),
            "9999_W10_D2026-11-15": row("9999", "LAR", "ARI", None, "Davis Allen"),
        }
        nh.fill_missing_kickoffs(list(store.values()))
        assert store["9999_W10_D2026-11-15"]["game_start_time"] == "4:05PM"


class TestTheLineupThatWasRefused:
    """The real one, decoded from the submission that reported this."""

    LATE_GAMES = [
        row("3257", "LAC", "BAL", "8:15PM", "Jacoby Brissett", date="2026-11-16"),
        row("8150", "LAR", "ARI", "4:05PM", "Kyren Williams"),
        row("7021", "PIT", "CIN", "8:20PM", "Rico Dowdle"),
        row("13270", "LAR", "ARI", None, "CJ Daniels"),
        row("10213", "LV", "SEA", None, "Tre Tucker"),
        row("9488", "SEA", "LV", "4:05PM", "Jaxon Smith-Njigba"),
        row("11604", "LV", "SEA", "4:05PM", "Brock Bowers"),
        row("5846", "PIT", "CIN", "8:20PM", "DK Metcalf"),
        row("ARI", "ARI", "LAR", None, "Cardinals"),
    ]

    @pytest.fixture
    def store(self, monkeypatch):
        rows = {}
        for one in self.LATE_GAMES:
            copy = dict(one)
            rows[f"{copy['sleeper_id']}_W10_D{copy['game_date']}"] = copy
        monkeypatch.setattr(nh, "dfs_salaries_data", rows)
        return rows

    def test_it_is_accepted_on_the_sunday_afternoon(self, store):
        # 14:46 ET: the one o'clock games are over an hour old, and not one of
        # these nine is in them.
        nh.fill_missing_kickoffs(list(store.values()))
        ok, err, started = nh.validate_lineup_players_not_started(
            lineup_data([r["sleeper_id"] for r in self.LATE_GAMES])
        )
        assert ok is True, err
        assert started == []

    def test_the_three_timeless_rows_are_what_it_turned_on(self, store):
        # Without the fill they were guessed at one o'clock and rejected. This
        # is the regression: three players, in 16:05 and 20:20 games.
        timeless = [r["sleeper_id"] for r in self.LATE_GAMES
                    if r["game_start_time"] is None]
        assert timeless == ["13270", "10213", "ARI"]

        nh.fill_missing_kickoffs(list(store.values()))
        for sleeper_id in timeless:
            filled = nh.dfs_salary_rows(sleeper_id, 10)[0]["game_start_time"]
            assert filled == "4:05PM", sleeper_id

    def test_once_their_game_starts_they_do_lock(self, store):
        # The fill is not a way round the lock: with a real time on the row,
        # 16:10 ET is after a 16:05 kickoff.
        nh.fill_missing_kickoffs(list(store.values()))
        ok, err, started = nh.validate_lineup_players_not_started(
            lineup_data([r["sleeper_id"] for r in self.LATE_GAMES])
        )
        assert ok is False
        assert "already started" in err
        assert {p["name"] for p in started} >= {"CJ Daniels", "Tre Tucker", "Cardinals"}

    def test_an_unknowable_kickoff_is_skipped_not_guessed(self, monkeypatch):
        # When nothing in the slate knows the time, the player is skipped — the
        # same answer already given for a player held no row for at all.
        # Guessing the earliest slate is what refused a legal lineup.
        lonely = row("4242", "SF", "DAL", None, "Nobody knows")
        monkeypatch.setattr(nh, "dfs_salaries_data",
                            {"4242_W10_D2026-11-15": lonely})
        assert nh.fill_missing_kickoffs([lonely]) == 0

        ok, err, started = nh.validate_lineup_players_not_started(lineup_data(["4242"]))
        assert ok is True, err
        assert started == []


@pytest.fixture(autouse=True)
def _afternoon(monkeypatch, request):
    """14:46 ET on the Sunday, unless a test asks for another moment."""
    _freeze(monkeypatch, "2026-11-15 16:10"
            if request.node.name == "test_once_their_game_starts_they_do_lock"
            else "2026-11-15 14:46")
