"""
The holes in the kickoff lock, and the per-tournament relaxation of it.

Three ways past the lock were found after it was repaired, all live against
production data:

  - the week was read off the submitted payload, so relabelling a lineup
    "99|..." made every salary lookup miss and the check pass;
  - defences were skipped entirely — the check collected only numeric ids
    while scoring counts team codes — so a defence that had played could be
    swapped for one that had not;
  - the same player in two slots passed nine-slot completeness and scored
    twice.

Plus `skip_validation`, which bypassed the whole thing and carried no
authentication at all.

The fourth thing here is the `unplayed` lock mode, which freezes only the
players who have played. It is opt-in: an entry with no setting behaves
exactly as before, which is the assertion that matters most since every
tournament that already exists is in that state.

Fixtures use the real "{sleeper_id}_W{week}_D{game_date}" salary key, and the
real "{name}_{team}_W{week}_D{date}" key for defences, for the reason the
sibling file gives: tests written against a key the store does not hold are
what hid the original bug.
"""

import datetime

import pytest
import lzstring

import nfl_helper as nh

LZS = lzstring.LZString()

WEEK = 7
SATURDAY = "2026-10-24 09:00"   # Thursday night is over, Sunday has not begun
WEDNESDAY = "2026-10-21 09:00"  # nothing has played


def lineup(tokens, week=WEEK, username="MrJocke"):
    body = ",".join(f"{t}-5000" for t in tokens)
    return f"{week}|{LZS.compressToEncodedURIComponent(f'{username}:{body}')}"


def player_row(sleeper_id, date, start, day, name=None, team="CHI"):
    return (f"{sleeper_id}_W{WEEK}_D{date}", {
        "sleeper_id": sleeper_id, "name": name or f"P{sleeper_id}", "team": team,
        "week": WEEK, "game_date": date, "game_start_time": start, "game_day": day,
    })


def defence_row(team, date, start, day, nickname):
    # How the scrape keys a defence: no numeric id, so name and team instead.
    return (f"{nickname}_{team}_W{WEEK}_D{date}", {
        "sleeper_id": team, "name": nickname, "team": team,
        "week": WEEK, "game_date": date, "game_start_time": start, "game_day": day,
    })


PLAYED = "11560"                                  # Thursday
UNPLAYED = [str(10212 + i) for i in range(8)]     # Sunday
SPARE = "10300"                                   # Sunday, not in any lineup


@pytest.fixture
def salaries(monkeypatch):
    rows = dict(
        [player_row(PLAYED, "2026-10-22", "8:15PM", "Thursday", "Caleb Williams")]
        + [player_row(p, "2026-10-25", "1:00PM", "Sunday", f"Sunday {i}", team="NO")
           for i, p in enumerate(UNPLAYED)]
        + [player_row(SPARE, "2026-10-25", "1:00PM", "Sunday", "Spare Guy", team="NO")]
        + [defence_row("CHI", "2026-10-22", "8:15PM", "Thursday", "Bears"),
           defence_row("SF", "2026-10-25", "1:00PM", "Sunday", "49ers")]
    )
    monkeypatch.setattr(nh, "dfs_salaries_data", rows)
    return rows


def freeze(monkeypatch, when):
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    fixed = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=et)
    real = datetime.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(nh.datetime, "datetime", Frozen)


# ─────────────────────────────── the bypasses ───────────────────────────────

class TestTheWeekCameFromTheSubmission:
    def test_a_relabelled_lineup_used_to_slip_past(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        played = [PLAYED] + UNPLAYED
        # Honest label: refused.
        ok, _why, _s = nh.validate_lineup_players_not_started(lineup(played, week=WEEK))
        assert ok is False
        # Lied-about label, same players: no salary row matches week 99, so every
        # player reads as unknown and the check used to pass.
        ok, _why, _s = nh.validate_lineup_players_not_started(lineup(played, week=99))
        assert ok is True, "this is the bypass, reproduced"

    def test_the_caller_can_pin_the_week(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        ok, why, started = nh.validate_lineup_players_not_started(
            lineup([PLAYED] + UNPLAYED, week=99), week=WEEK)
        assert ok is False
        assert "Caleb Williams" in why
        assert [p["sleeper_id"] for p in started] == [PLAYED]

    def test_add_judges_against_the_entrys_week(self, salaries, monkeypatch, client):
        freeze(monkeypatch, SATURDAY)
        monkeypatch.setattr(nh, "tinyurl_data", {"cup": {
            "name": "cup", "allowed_names": ["MrJocke"], "week": WEEK,
            "user_submissions": {},
        }})
        resp = client.post("/tinyurl/cup/add", json={
            "name": "MrJocke", "data": lineup([PLAYED] + UNPLAYED, week=99)})
        assert resp.status_code == 400
        assert "already started" in resp.get_json()["error"]


class TestDefencesWereNeverChecked:
    def test_a_defence_is_resolved_by_its_team_code(self, salaries):
        # Keyed "Bears_CHI_W7_D...", so no prefix built from "CHI" can match it.
        assert not any(k.startswith("CHI_W7") for k in salaries)
        rows = nh.dfs_salary_rows("CHI", WEEK)
        assert len(rows) == 1
        assert rows[0]["game_date"] == "2026-10-22"

    def test_a_played_defence_locks_the_lineup(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        ok, why, started = nh.validate_lineup_players_not_started(
            lineup(UNPLAYED + ["CHI"]), week=WEEK)
        assert ok is False, "the Bears played on the Thursday"
        assert "Bears" in why

    def test_an_unplayed_defence_does_not(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        ok, _why, _s = nh.validate_lineup_players_not_started(
            lineup(UNPLAYED + ["SF"]), week=WEEK)
        assert ok is True

    def test_scoring_already_counted_defences(self):
        # Which is why the check had to: the two were reading different lineups.
        assert "CHI" in nh.NFL_TEAM_CODES


class TestADuplicateIsNotALineup:
    def test_the_same_player_twice_is_refused(self):
        nine_tokens_eight_players = [PLAYED, PLAYED] + UNPLAYED[:7]
        ok, why = nh.validate_lineup_is_complete(lineup(nine_tokens_eight_players))
        assert ok is False
        assert "more than one slot" in why
        assert PLAYED in why

    def test_a_proper_lineup_still_passes(self):
        ok, why = nh.validate_lineup_is_complete(lineup([PLAYED] + UNPLAYED))
        assert ok is True and why is None

    def test_a_duplicate_defence_is_refused_too(self):
        ok, why = nh.validate_lineup_is_complete(lineup(UNPLAYED[:7] + ["CHI", "CHI"]))
        assert ok is False
        assert "CHI" in why


# ──────────────────────────────── the modes ────────────────────────────────

class TestTheDefaultIsTheOldRule:
    """Every tournament that already exists has no setting, so this is the
    assertion that keeps them behaving as they did."""

    def test_an_absent_setting_reads_as_full(self):
        assert nh.lineup_lock_mode({}) == "full"
        assert nh.lineup_lock_mode({"lineup_lock": None}) == "full"

    def test_an_unrecognised_setting_reads_as_full(self):
        # A typo in stored data must not quietly relax the rule.
        assert nh.lineup_lock_mode({"lineup_lock": "unpalyed"}) == "full"
        assert nh.lineup_lock_mode({"lineup_lock": ""}) == "full"

    def test_case_and_spacing_are_tolerated(self):
        assert nh.lineup_lock_mode({"lineup_lock": " Unplayed "}) == "unplayed"

    def test_an_entry_with_no_setting_refuses_any_edit(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        stored = lineup([PLAYED] + UNPLAYED)
        swapped = lineup([PLAYED] + UNPLAYED[:7] + [SPARE])
        ok, why, _s = nh.validate_lineup_change(stored, swapped, WEEK, nh.lineup_lock_mode({}))
        assert ok is False
        assert "Cannot overwrite lineup" in why


class TestTheUnplayedRule:
    def test_an_unplayed_player_may_be_swapped(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        stored = lineup([PLAYED] + UNPLAYED)
        swapped = lineup([PLAYED] + UNPLAYED[:7] + [SPARE])
        ok, why, started = nh.validate_lineup_change(stored, swapped, WEEK, "unplayed")
        assert ok is True, why
        # Still reports who is frozen.
        assert [p["sleeper_id"] for p in started] == [PLAYED]

    def test_a_played_player_may_not_be_removed(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        stored = lineup([PLAYED] + UNPLAYED)
        dropped = lineup(UNPLAYED + [SPARE])
        ok, why, _s = nh.validate_lineup_change(stored, dropped, WEEK, "unplayed")
        assert ok is False
        assert "Cannot remove" in why and "Caleb Williams" in why

    def test_a_played_player_may_not_be_added(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        stored = lineup(UNPLAYED + [SPARE])
        added = lineup(UNPLAYED + [PLAYED])
        ok, why, _s = nh.validate_lineup_change(stored, added, WEEK, "unplayed")
        assert ok is False
        assert "Cannot add" in why and "Caleb Williams" in why

    def test_a_played_defence_may_not_be_swapped(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        stored = lineup(UNPLAYED + ["CHI"])
        swapped = lineup(UNPLAYED + ["SF"])
        ok, why, _s = nh.validate_lineup_change(stored, swapped, WEEK, "unplayed")
        assert ok is False, "the Bears already played; swapping them is the exploit"
        assert "Cannot remove" in why

    def test_a_reorder_is_allowed(self, salaries, monkeypatch):
        # Slot-agnostic on purpose: a lineup's points are a plain sum and there
        # is no server-side cap or position check, so the slot is not scored.
        freeze(monkeypatch, SATURDAY)
        stored = lineup([PLAYED] + UNPLAYED)
        reordered = lineup(list(reversed([PLAYED] + UNPLAYED)))
        ok, why, _s = nh.validate_lineup_change(stored, reordered, WEEK, "unplayed")
        assert ok is True, why

    def test_before_any_kickoff_everything_is_allowed(self, salaries, monkeypatch):
        freeze(monkeypatch, WEDNESDAY)
        stored = lineup([PLAYED] + UNPLAYED)
        swapped = lineup(UNPLAYED + [SPARE])
        for mode in ("full", "unplayed"):
            ok, why, _s = nh.validate_lineup_change(stored, swapped, WEEK, mode)
            assert ok is True, f"{mode}: {why}"

    def test_a_first_submission_may_not_contain_a_played_player(self, salaries, monkeypatch):
        freeze(monkeypatch, SATURDAY)
        for mode in ("full", "unplayed"):
            ok, why, _s = nh.validate_lineup_change(
                None, lineup([PLAYED] + UNPLAYED), WEEK, mode)
            assert ok is False, mode
            assert "already started" in why


class TestTheRelaxationIsNeverWeakerThanTheRule:
    def test_an_unreadable_stored_lineup_falls_back_to_full(self, salaries, monkeypatch):
        # Neither side can be compared, so it must not wave the submission
        # through — that would make unplayed looser than full on a path an
        # entrant can reach.
        freeze(monkeypatch, SATURDAY)
        ok, why, _s = nh.validate_lineup_change(
            "7|not-a-real-payload", lineup([PLAYED] + UNPLAYED), WEEK, "unplayed")
        assert ok is False
        assert "already started" in why

    def test_an_unreadable_new_lineup_is_still_allowed(self, salaries, monkeypatch):
        # Documented rather than fixed: refusing what we cannot read would lock
        # everyone out the moment the encoding changes.
        freeze(monkeypatch, SATURDAY)
        ok, _why, _s = nh.validate_lineup_change(
            lineup(UNPLAYED + [SPARE]), "7|rubbish", WEEK, "unplayed")
        assert ok is True


class TestTheAvailableEndpointUnderUnplayed:
    def _entry(self, monkeypatch, mode, stored_tokens):
        monkeypatch.setattr(nh, "tinyurl_data", {"cup": {
            "name": "cup", "allowed_names": ["MrJocke"], "week": WEEK,
            "lineup_lock": mode,
            "user_submissions": {"mrjocke": {
                "username": "MrJocke", "data": lineup(stored_tokens)}},
        }})

    def test_unplayed_is_not_locked_but_names_the_frozen_player(
            self, salaries, monkeypatch, client):
        self._entry(monkeypatch, "unplayed", [PLAYED] + UNPLAYED)
        freeze(monkeypatch, SATURDAY)
        row = client.get("/tinyurl/MrJocke/available").get_json()["entries"][0]
        assert row["lineup_lock"] == "unplayed"
        assert row["locked"] is False, "eight slots can still change"
        assert [p["name"] for p in row["locked_by"]] == ["Caleb Williams"]

    def test_full_is_locked_by_the_same_player(self, salaries, monkeypatch, client):
        self._entry(monkeypatch, "full", [PLAYED] + UNPLAYED)
        freeze(monkeypatch, SATURDAY)
        row = client.get("/tinyurl/MrJocke/available").get_json()["entries"][0]
        assert row["locked"] is True

    def test_unplayed_locks_once_every_slot_has_played(self, salaries, monkeypatch, client):
        # Nothing left to change, so offering an edit would be a lie.
        self._entry(monkeypatch, "unplayed", [PLAYED] * 1 + ["CHI"])
        freeze(monkeypatch, SATURDAY)
        row = client.get("/tinyurl/MrJocke/available").get_json()["entries"][0]
        assert row["locked"] is True

    def test_an_entry_with_no_setting_reports_full(self, salaries, monkeypatch, client):
        monkeypatch.setattr(nh, "tinyurl_data", {"cup": {
            "name": "cup", "allowed_names": ["MrJocke"], "week": WEEK,
            "user_submissions": {},
        }})
        row = client.get("/tinyurl/MrJocke/available").get_json()["entries"][0]
        assert row["lineup_lock"] == "full"


# ──────────────────────────────── history ─────────────────────────────────

class TestHistory:
    def _post(self, client, tokens, user="MrJocke"):
        return client.post("/tinyurl/cup/add",
                           json={"name": user, "data": lineup(tokens, username=user)})

    @pytest.fixture
    def entry(self, salaries, monkeypatch):
        monkeypatch.setattr(nh, "tinyurl_data", {"cup": {
            "name": "cup", "allowed_names": ["MrJocke"], "week": WEEK,
            "type": "multiweek_dfs", "num_weeks": 7, "user_submissions": {},
        }})
        freeze(monkeypatch, WEDNESDAY)

    def _history(self):
        return nh.tinyurl_data["cup"]["user_submissions"]["mrjocke"]["history"]

    def test_the_first_submission_is_recorded(self, entry, client):
        assert self._post(client, UNPLAYED + [SPARE]).status_code == 200
        assert len(self._history()) == 1

    def test_each_submission_appends(self, entry, client):
        self._post(client, UNPLAYED + [SPARE])
        self._post(client, UNPLAYED + [PLAYED])
        history = self._history()
        assert len(history) == 2
        # Oldest first, and the newest is what is stored under `data`.
        assert history[-1]["data"] == \
            nh.tinyurl_data["cup"]["user_submissions"]["mrjocke"]["data"]

    def test_the_eleventh_drops_the_oldest(self, entry, client):
        for i in range(12):
            self._post(client, UNPLAYED + [SPARE] if i % 2 else UNPLAYED + [PLAYED])
        history = self._history()
        assert len(history) == nh.LINEUP_HISTORY_LIMIT == 10
        ats = [h["at"] for h in history]
        assert ats == sorted(ats), "oldest first"

    def test_an_organiser_clear_keeps_the_history(self, entry, client, monkeypatch):
        self._post(client, UNPLAYED + [SPARE])
        monkeypatch.setattr(nh, "request_is_from_organiser", lambda: True)
        resp = client.delete("/tinyurl/cup/entrants/MrJocke/lineup")
        assert resp.status_code == 200
        sub = nh.tinyurl_data["cup"]["user_submissions"]["mrjocke"]
        assert sub.get("data") is None
        assert len(sub.get("history") or []) == 1, "what they had is the thing worth keeping"

    def test_scoring_discards_it_with_the_submissions(self, entry, client, monkeypatch):
        self._post(client, UNPLAYED + [SPARE])
        assert self._history()
        monkeypatch.setattr(nh, "fetch_sleeper_matchup_points", lambda week: {})
        monkeypatch.setattr(nh, "save_tinyurl_data", lambda: None)
        # The cleanup reads Sleeper's own week off the scraper; the entry is on
        # WEEK, so the week after is what makes it roll over and score.
        class _Scraper:
            def get_league_week(self):
                return WEEK + 1
        monkeypatch.setattr(nh, "FantasyDataScraper", _Scraper)
        nh.clear_tinyurl_data(delete_finished=False)
        subs = nh.tinyurl_data.get("cup", {}).get("user_submissions", {})
        assert subs == {}, "the weekly reset is what gives history its lifetime"


class TestHistoryIsNotPublic:
    @pytest.fixture
    def entry(self, salaries, monkeypatch):
        monkeypatch.setattr(nh, "tinyurl_data", {"cup": {
            "name": "cup", "allowed_names": ["MrJocke"], "week": WEEK,
            "user_submissions": {"mrjocke": {
                "username": "MrJocke", "data": lineup(UNPLAYED + [SPARE]),
                "pin": "1234", "update_count": 2,
                "history": [{"at": "2026-10-24T06:00:00", "data": lineup(UNPLAYED + [PLAYED])}],
            }},
        }})

    def test_the_results_view_leaks_neither_history_nor_pin(self, entry, client):
        # Ungated, and ?action=results skips even the PIN prompt. Against
        # production this route was handing out every entrant's PIN.
        body = client.get("/tinyurl/cup/data?action=results").get_json()
        sub = body["user_submissions"]["mrjocke"]
        assert "history" not in sub
        assert "pin" not in sub

    def test_it_still_serves_the_lineup(self, entry, client):
        # Which is the whole purpose of the route; DFSResults depends on it.
        sub = client.get("/tinyurl/cup/data?action=results").get_json()["user_submissions"]["mrjocke"]
        assert sub["data"]
        assert sub["username"] == "MrJocke"
        assert sub["update_count"] == 2

    def test_the_projection_is_an_allowlist(self):
        # So the next field added inside a submission is private by default.
        projected = nh.public_user_submissions({"user_submissions": {
            "x": {"username": "x", "data": "d", "pin": "9", "something_new": "s"}}})
        assert set(projected["x"]) <= set(nh.PUBLIC_SUBMISSION_FIELDS)
        assert "something_new" not in projected["x"]


class TestTheOrganiserRoutes:
    @pytest.fixture
    def entry(self, monkeypatch):
        monkeypatch.setattr(nh, "tinyurl_data", {"cup": {
            "name": "cup", "allowed_names": ["MrJocke"], "week": WEEK,
            "user_submissions": {"mrjocke": {
                "username": "MrJocke", "data": "7|x", "update_count": 3,
                "history": [{"at": "2026-10-24T06:00:00", "data": "7|x"}],
            }},
        }})
        monkeypatch.setattr(nh, "save_tinyurl_data", lambda: None)
        monkeypatch.setattr(nh, "request_is_from_organiser", lambda: True)

    def test_an_organiser_sets_the_mode(self, entry, client):
        resp = client.post("/admin/tinyurl/cup/settings", json={"lineup_lock": "unplayed"})
        assert resp.status_code == 200
        assert resp.get_json()["lineup_lock"] == "unplayed"
        assert nh.tinyurl_data["cup"]["lineup_lock"] == "unplayed"

    def test_the_default_is_written_out_explicitly(self, entry, client):
        client.post("/admin/tinyurl/cup/settings", json={"lineup_lock": "full"})
        assert nh.tinyurl_data["cup"]["lineup_lock"] == "full", \
            "stored so a dispute reads a decision rather than an absence"

    def test_an_unknown_mode_is_refused(self, entry, client):
        resp = client.post("/admin/tinyurl/cup/settings", json={"lineup_lock": "whatever"})
        assert resp.status_code == 400
        assert "lineup_lock" in resp.get_json()["error"]

    def test_an_empty_body_is_refused(self, entry, client):
        # A typo should not look like a saved setting.
        assert client.post("/admin/tinyurl/cup/settings", json={}).status_code == 400

    def test_an_unknown_tournament_is_404(self, entry, client):
        assert client.post("/admin/tinyurl/nope/settings",
                           json={"lineup_lock": "full"}).status_code == 404

    def test_history_is_served_newest_first(self, entry, client):
        body = client.get("/admin/tinyurl/cup/history").get_json()
        assert body["week"] == WEEK
        assert body["limit"] == nh.LINEUP_HISTORY_LIMIT
        assert body["entrants"]["MrJocke"]["update_count"] == 3
        assert len(body["entrants"]["MrJocke"]["history"]) == 1

    def test_history_carries_no_pins(self, entry, client):
        body = client.get("/admin/tinyurl/cup/history").get_json()
        assert "pin" not in str(body)

    def test_details_reports_the_mode(self, entry, client):
        assert client.get("/tinyurl/cup/details").get_json()["lineup_lock"] == "full"
