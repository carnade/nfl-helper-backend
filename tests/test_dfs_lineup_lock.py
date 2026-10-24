"""
The kickoff lock on DFS lineups.

A submitted lineup is frozen once any of its players has kicked off — both the
stored one and the replacement are checked, so a single played player ends your
edits for the week.

It had not worked for a long time. Salary rows are keyed
"{sleeper_id}_W{week}_D{game_date}", the date having been added when DFS gained
the Thursday and Monday slates, and the check still built "{sleeper_id}_W{week}".
Every lookup missed, every player was skipped as unknown, and every lineup
reported clean. It was found by noticing an entrant had updated a lineup on the
Saturday with a Thursday player still in it.

These tests use the real key format for that reason. The same tests written
against a bare "{sleeper_id}_W{week}" key would have passed against the broken
code, which is how it went unnoticed.
"""

import datetime

import pytest
import lzstring

import nfl_helper as nh


LZS = lzstring.LZString()


def lineup_data(players, week=7, username="MrJocke"):
    """A submission, encoded the way the DFS page encodes it."""
    body = ",".join(f"{p['sleeper_id']}-{p.get('salary', 5000)}" for p in players)
    return f"{week}|{LZS.compressToEncodedURIComponent(f'{username}:{body}')}"


def salary_row(sleeper_id, game_date, start_time, day, name=None, team="CHI", week=7):
    """A salary row under the key the scrape actually writes."""
    return (
        f"{sleeper_id}_W{week}_D{game_date}",
        {
            "sleeper_id": sleeper_id,
            "name": name or f"Player {sleeper_id}",
            "team": team,
            "week": week,
            "game_date": game_date,
            "game_start_time": start_time,
            "game_day": day,
        },
    )


# A past Thursday and a Sunday still to come, relative to a fixed "now".
THURSDAY = {"sleeper_id": "11560", "salary": 7000}
SUNDAY = [{"sleeper_id": str(10212 + i), "salary": 4000} for i in range(8)]


@pytest.fixture
def salaries(monkeypatch):
    rows = dict(
        [salary_row("11560", "2026-10-22", "8:15PM", "Thursday", "Caleb Williams")]
        + [salary_row(p["sleeper_id"], "2026-10-25", "1:00PM", "Sunday",
                      f"Sunday Guy {i}", team="NO") for i, p in enumerate(SUNDAY)]
    )
    monkeypatch.setattr(nh, "dfs_salaries_data", rows)
    return rows


class TestTheLookupThatWasBroken:
    def test_a_player_is_found_under_the_dated_key(self, salaries):
        assert nh.dfs_salary_rows("11560", 7), "the live key carries a _D<date> suffix"

    def test_the_old_undated_key_is_not_what_the_store_holds(self, salaries):
        # Recording the actual shape, since a test that asserted this key
        # existed is what would have hidden the bug.
        assert "11560_W7" not in salaries
        assert "11560_W7_D2026-10-22" in salaries

    def test_one_player_cannot_match_another_by_prefix(self, salaries):
        # "1_W7" must not pick up "10_W7_D..." — hence the "_D" in the prefix.
        rows = dict([salary_row("1", "2026-10-25", "1:00PM", "Sunday"),
                     salary_row("10", "2026-10-22", "8:15PM", "Thursday")])
        import unittest.mock as mock
        with mock.patch.object(nh, "dfs_salaries_data", rows):
            assert len(nh.dfs_salary_rows("1", 7)) == 1
            assert nh.dfs_salary_rows("1", 7)[0]["game_date"] == "2026-10-25"

    def test_an_unknown_player_yields_nothing(self, salaries):
        assert nh.dfs_salary_rows("999999", 7) == []


class TestTheLock:
    def test_a_played_player_blocks_the_lineup(self, salaries, monkeypatch):
        # Saturday: Thursday night is long over.
        _freeze(monkeypatch, "2026-10-24 09:00")
        ok, err, started = nh.validate_lineup_players_not_started(
            lineup_data([THURSDAY] + SUNDAY))
        assert ok is False
        assert "already started" in err
        assert [p["name"] for p in started] == ["Caleb Williams"]

    def test_a_lineup_of_unplayed_players_is_allowed(self, salaries, monkeypatch):
        _freeze(monkeypatch, "2026-10-24 09:00")
        ok, err, started = nh.validate_lineup_players_not_started(
            lineup_data(SUNDAY + [{"sleeper_id": "10220", "salary": 4000}]))
        assert ok is True
        assert err is None
        assert started == []

    def test_before_kickoff_the_same_lineup_is_allowed(self, salaries, monkeypatch):
        # Wednesday, nothing has played.
        _freeze(monkeypatch, "2026-10-21 09:00")
        ok, _err, _started = nh.validate_lineup_players_not_started(
            lineup_data([THURSDAY] + SUNDAY))
        assert ok is True

    def test_the_earliest_slate_is_the_one_that_locks(self, salaries, monkeypatch):
        # A player held against two slates must not be waved through by the
        # later row once the earlier game has been played.
        rows = dict(salaries)
        rows.update([salary_row("11560", "2026-10-26", "8:15PM", "Monday", "Caleb Williams")])
        monkeypatch.setattr(nh, "dfs_salaries_data", rows)
        _freeze(monkeypatch, "2026-10-24 09:00")
        ok, _err, started = nh.validate_lineup_players_not_started(
            lineup_data([THURSDAY] + SUNDAY))
        assert ok is False
        assert started[0]["game_date"] == "2026-10-22"


class TestTheUsernamePrefix:
    def test_a_handle_containing_digits_does_not_hide_a_player(self, salaries, monkeypatch):
        # isalpha() is false for "Ringside1981", so the prefix was left in place
        # and the first pair parsed as the handle — exempting that player.
        _freeze(monkeypatch, "2026-10-24 09:00")
        ok, _err, started = nh.validate_lineup_players_not_started(
            lineup_data([THURSDAY] + SUNDAY, username="Ringside1981"))
        assert ok is False, "the played player is first in the list"
        assert [p["name"] for p in started] == ["Caleb Williams"]

    def test_a_handle_starting_with_digits_is_handled_too(self, salaries, monkeypatch):
        _freeze(monkeypatch, "2026-10-24 09:00")
        ok, _err, _ = nh.validate_lineup_players_not_started(
            lineup_data([THURSDAY] + SUNDAY, username="52Ravens"))
        assert ok is False

    def test_an_all_letters_handle_still_works(self, salaries, monkeypatch):
        _freeze(monkeypatch, "2026-10-24 09:00")
        ok, _err, _ = nh.validate_lineup_players_not_started(
            lineup_data([THURSDAY] + SUNDAY, username="MrJocke"))
        assert ok is False


class TestWhatItWillNotJudge:
    def test_an_undecodable_lineup_is_allowed_through(self, salaries):
        # Deliberate: refusing a submission we cannot read would lock people out
        # on a format change. Worth knowing it is the one remaining way past.
        ok, _err, _ = nh.validate_lineup_players_not_started("7|not-real-data")
        assert ok is True

    def test_a_player_we_hold_no_salary_row_for_is_skipped(self, salaries, monkeypatch):
        _freeze(monkeypatch, "2026-10-24 09:00")
        ok, _err, _ = nh.validate_lineup_players_not_started(
            lineup_data([{"sleeper_id": "999999", "salary": 5000}] + SUNDAY))
        assert ok is True

    def test_a_malformed_data_string_is_refused(self, salaries):
        ok, err, _ = nh.validate_lineup_players_not_started("no-pipe-here")
        assert ok is False
        assert "format" in err.lower()


def _freeze(monkeypatch, when):
    """Pin 'now' in Eastern time, which is what the check compares against."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    fixed = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=et)

    real = datetime.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(nh.datetime, "datetime", Frozen)


class TestThePayloadThatLookedLikeBase64AndWasNot:
    """
    compressToEncodedURIComponent output is not a base64 string: its length can
    be one more than a multiple of four, which no base64 string ever is. The
    decoder tried raw base64 first and gave up when it failed, so a quarter of
    all lineups — every one whose encoded length landed on that remainder —
    skipped the kickoff check whatever the key lookup did.
    """

    def test_the_awkward_length_really_does_occur(self):
        lengths = {
            len(LZS.compressToEncodedURIComponent(f"{user}:" + ",".join(
                f"{10000 + i}-{4000 + i}" for i in range(9)))) % 4
            for user in ("MrJocke", "Ringside1981", "52Ravens", "carnade", "lidell",
                         "calleGrundberg", "a", "ab", "abc", "abcd", "abcde")
        }
        assert 1 in lengths, "no sample landed on the remainder base64 cannot have"

    def test_such_a_payload_is_still_decoded(self):
        for user in ("MrJocke", "Ringside1981", "52Ravens", "carnade", "lidell",
                     "a", "ab", "abc", "abcd", "abcde"):
            body = ",".join(f"{10000 + i}-{4000 + i}" for i in range(9))
            payload = LZS.compressToEncodedURIComponent(f"{user}:{body}")
            decoded = nh._decode_lineup_payload(payload)
            assert decoded == f"{user}:{body}", (
                f"length {len(payload)} (mod 4 = {len(payload) % 4}) failed to decode"
            )

    def test_plain_base64_still_decodes(self):
        # The older hand-made format, kept working.
        import base64
        body = "11560-7000,10212-4000"
        payload = base64.b64encode(f"MrJocke:{body}".encode()).decode().rstrip("=")
        assert nh._decode_lineup_payload(payload) == f"MrJocke:{body}"

    def test_nonsense_returns_none_rather_than_raising(self):
        assert nh._decode_lineup_payload("!!! not a payload !!!") is None
        assert nh._decode_lineup_payload("") is None


class TestTheAvailableEndpointReportsTheLock:
    """
    The page needs to know a lineup is frozen before it offers to replace one.
    The answer comes from the same function that enforces it on submit, so the
    two cannot drift — which is what went wrong in the first place.
    """

    @pytest.fixture
    def entry(self, salaries, monkeypatch):
        monkeypatch.setattr(nh, "tinyurl_data", {
            "frozen": {
                "name": "frozen",
                "allowed_names": ["MrJocke"],
                "week": 7,
                "user_submissions": {
                    "mrjocke": {"data": lineup_data([THURSDAY] + SUNDAY), "username": "MrJocke"},
                },
            },
            "open": {
                "name": "open",
                "allowed_names": ["MrJocke"],
                "week": 7,
                "user_submissions": {
                    "mrjocke": {"data": lineup_data(SUNDAY + [{"sleeper_id": "10220"}]),
                                "username": "MrJocke"},
                },
            },
            "nothing_sent": {
                "name": "nothing_sent",
                "allowed_names": ["MrJocke"],
                "week": 7,
                "user_submissions": {},
            },
        })
        _freeze(monkeypatch, "2026-10-24 09:00")

    def test_a_frozen_lineup_is_reported_locked(self, entry, client):
        rows = {e["name"]: e for e in client.get("/tinyurl/MrJocke/available").get_json()["entries"]}
        assert rows["frozen"]["locked"] is True
        assert [p["name"] for p in rows["frozen"]["locked_by"]] == ["Caleb Williams"]

    def test_a_lineup_of_unplayed_players_is_not_locked(self, entry, client):
        rows = {e["name"]: e for e in client.get("/tinyurl/MrJocke/available").get_json()["entries"]}
        assert rows["open"]["locked"] is False
        assert "locked_by" not in rows["open"]

    def test_an_entry_with_nothing_submitted_is_not_locked(self, entry, client):
        rows = {e["name"]: e for e in client.get("/tinyurl/MrJocke/available").get_json()["entries"]}
        assert rows["nothing_sent"]["locked"] is False

    def test_before_kickoff_nothing_is_locked(self, salaries, monkeypatch, client):
        monkeypatch.setattr(nh, "tinyurl_data", {
            "frozen": {
                "name": "frozen", "allowed_names": ["MrJocke"], "week": 7,
                "user_submissions": {
                    "mrjocke": {"data": lineup_data([THURSDAY] + SUNDAY), "username": "MrJocke"},
                },
            },
        })
        _freeze(monkeypatch, "2026-10-21 09:00")
        rows = client.get("/tinyurl/MrJocke/available").get_json()["entries"]
        assert rows[0]["locked"] is False
