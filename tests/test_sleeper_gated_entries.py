"""A DFS tournament can admit anyone with a verified Sleeper login instead of a
fixed username allowlist, and can close submissions at a deadline."""

import datetime
import sys

import pytest
from unittest.mock import patch

nfl_helper = sys.modules["nfl_helper"]

from conftest import make_lineup_string, make_full_lineup_string, create_entry


ALICE = {"user_id": "111", "display_name": "alice"}


def iso(dt):
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def in_hours(n):
    return iso(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=n))


@pytest.fixture(autouse=True)
def no_kickoff_check():
    """Lineup validation hits live schedule data; these tests are about access."""
    with patch.object(nfl_helper, "validate_lineup_players_not_started",
                      return_value=(True, None, [])):
        yield


@pytest.fixture
def verified():
    """Stub Sleeper token verification. Set .return_value to None for a bad token."""
    with patch.object(nfl_helper, "verify_sleeper_token", return_value=ALICE) as stub:
        yield stub


def submit(client, entry, name=None, token=None, data=None):
    headers = {"Authorization": token} if token else {}
    body = {"data": data or make_full_lineup_string(8)}
    if name is not None:
        body["name"] = name
    return client.post(f"/tinyurl/{entry}/add", json=body, headers=headers)


class TestSleeperGatedSubmission:
    def test_verified_login_may_submit_without_being_on_a_list(self, client, verified):
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"]["access_mode"] = "sleeper"

        resp = submit(client, "open", token="good-token")

        assert resp.status_code == 200, resp.get_json()
        assert "alice" in nfl_helper.tinyurl_data["open"]["user_submissions"]

    def test_unverified_login_is_rejected(self, client, verified):
        verified.return_value = None
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"]["access_mode"] = "sleeper"

        resp = submit(client, "open", token="bad-token")

        assert resp.status_code == 401
        assert nfl_helper.tinyurl_data["open"]["user_submissions"] == {}

    def test_identity_comes_from_the_token_not_the_posted_name(self, client, verified):
        """Posting someone else's name must not attribute the lineup to them."""
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"]["access_mode"] = "sleeper"

        submit(client, "open", name="bob", token="good-token")

        submissions = nfl_helper.tinyurl_data["open"]["user_submissions"]
        assert "alice" in submissions, "must be stored under the verified account"
        assert "bob" not in submissions

    def test_allowlist_entries_are_unaffected(self, client, verified):
        """No token involved: the existing allowlist path still governs."""
        create_entry("closed", allowed_names=["alice"])

        assert submit(client, "closed", name="alice").status_code == 200
        assert submit(client, "closed", name="mallory").status_code == 401

    def test_allowlist_entry_ignores_a_valid_token(self, client, verified):
        """A Sleeper login is not a way into a tournament that did not invite you."""
        create_entry("closed", allowed_names=["bob"])

        resp = submit(client, "closed", name="alice", token="good-token")

        assert resp.status_code == 401


class TestSubmissionDeadline:
    def test_submission_before_deadline_is_accepted(self, client, verified):
        create_entry("closed", allowed_names=["alice"])
        nfl_helper.tinyurl_data["closed"]["deadline"] = in_hours(2)

        assert submit(client, "closed", name="alice").status_code == 200

    def test_submission_after_deadline_is_rejected(self, client, verified):
        create_entry("closed", allowed_names=["alice"])
        nfl_helper.tinyurl_data["closed"]["deadline"] = in_hours(-1)

        resp = submit(client, "closed", name="alice")

        assert resp.status_code == 403
        assert "deadline" in resp.get_json()["error"].lower()

    def test_deadline_applies_to_sleeper_entries_too(self, client, verified):
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"].update(access_mode="sleeper", deadline=in_hours(-1))

        assert submit(client, "open", token="good-token").status_code == 403

    def test_entry_without_deadline_is_unrestricted(self, client, verified):
        create_entry("closed", allowed_names=["alice"])
        assert submit(client, "closed", name="alice").status_code == 200


class TestDeadlineRollsWeekly:
    def test_past_deadline_advances_with_the_tournament(self, client):
        create_entry("tourney", week=7, entry_type="multiweek_dfs",
                     num_weeks=4, start_week=7)
        was = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
        nfl_helper.tinyurl_data["tourney"]["deadline"] = iso(was)

        with patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={}), \
             patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=8):
            client.post("/admin/tinyurl/cleanup")

        entry = nfl_helper.tinyurl_data["tourney"]
        rolled, _ = nfl_helper.parse_deadline(entry["deadline"])
        assert rolled > datetime.datetime.now(datetime.timezone.utc), "must be in the future"
        assert (rolled - was).days % 7 == 0, "must land on the same time of week"

    def test_future_deadline_is_left_alone(self, client):
        create_entry("tourney", week=7, entry_type="multiweek_dfs",
                     num_weeks=4, start_week=7)
        future = in_hours(72)
        nfl_helper.tinyurl_data["tourney"]["deadline"] = future

        with patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={}), \
             patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=8):
            client.post("/admin/tinyurl/cleanup")

        assert nfl_helper.tinyurl_data["tourney"]["deadline"] == future


class TestCreateEndpoint:
    def test_sleeper_mode_needs_no_names(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "opencup", "access_mode": "sleeper", "week": 8,
            "deadline": in_hours(24),
        })

        assert resp.status_code == 200, resp.get_json()
        entry = nfl_helper.tinyurl_data["opencup"]
        assert entry["access_mode"] == "sleeper"
        assert entry["allowed_names"] == []
        assert "deadline" in entry

    def test_allowlist_mode_still_requires_names(self, client):
        resp = client.post("/tinyurl/create/empty", json={"name": "closedcup", "week": 8})
        assert resp.status_code == 400
        assert "names" in resp.get_json()["error"]

    def test_rejects_unparseable_deadline(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "bad", "access_mode": "sleeper", "week": 8, "deadline": "next tuesday",
        })
        assert resp.status_code == 400
        assert "deadline" in resp.get_json()["error"]

    def test_rejects_unknown_access_mode(self, client):
        resp = client.post("/tinyurl/create/empty", json={
            "name": "bad", "access_mode": "everyone", "week": 8,
        })
        assert resp.status_code == 400


class TestDiscovery:
    def test_open_entries_are_listed_for_a_verified_login(self, client, verified):
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"]["access_mode"] = "sleeper"

        resp = client.get("/tinyurl/nobody/available", headers={"Authorization": "good"})

        names = [e["name"] for e in resp.get_json()["entries"]]
        assert "open" in names

    def test_open_entries_are_hidden_without_a_verified_login(self, client, verified):
        verified.return_value = None
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"]["access_mode"] = "sleeper"

        resp = client.get("/tinyurl/nobody/available")

        assert resp.get_json()["entries"] == []

    def test_open_entry_reports_submission_under_the_sleeper_name(self, client, verified):
        """has_data must follow the verified account, not the path username."""
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"].update(
            access_mode="sleeper",
            user_submissions={"alice": {"username": "alice", "data": "x"}},
        )

        resp = client.get("/tinyurl/someoneelse/available", headers={"Authorization": "good"})

        entry = resp.get_json()["entries"][0]
        assert entry["has_data"] is True
        assert entry["submit_as"] == "alice"


class TestDetailsForOpenEntries:
    def test_details_reports_submitters_without_an_allowlist(self, client):
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"].update(
            access_mode="sleeper",
            user_submissions={
                "alice": {"username": "alice", "data": "x", "update_count": 2},
            },
        )

        body = client.get("/tinyurl/open/details").get_json()

        assert body["access_mode"] == "sleeper"
        assert body["submissions"]["alice"]["has_submitted"] is True
        assert body["submissions"]["alice"]["update_count"] == 2

    def test_details_exposes_the_deadline(self, client):
        create_entry("open", allowed_names=[])
        nfl_helper.tinyurl_data["open"].update(access_mode="sleeper", deadline=in_hours(-1))

        body = client.get("/tinyurl/open/details").get_json()

        assert body["deadline_passed"] is True

    def test_allowlist_entry_reports_allowlist_mode(self, client):
        create_entry("closed", allowed_names=["alice"])
        body = client.get("/tinyurl/closed/details").get_json()
        assert body["access_mode"] == "allowlist"


class TestOpenOnlyForTheFirstWeek:
    """A multiweek tournament takes entrants in week one, then locks its field."""

    def advance(self, client, to_week):
        with patch.object(nfl_helper, "fetch_sleeper_matchup_points", return_value={}), \
             patch.object(nfl_helper.FantasyDataScraper, "get_league_week", return_value=to_week):
            client.post("/admin/tinyurl/cleanup")

    def make_open_tournament(self, entrants=("alice", "bob")):
        create_entry("cup", week=7, entry_type="multiweek_dfs", num_weeks=4,
                     start_week=7, allowed_names=[])
        entry = nfl_helper.tinyurl_data["cup"]
        entry["access_mode"] = "sleeper"
        entry["user_submissions"] = {
            name: {"username": name, "data": make_lineup_string(7, ["11111-5000"]),
                   "update_count": 1}
            for name in entrants
        }
        return entry

    def test_field_locks_to_week_one_entrants(self, client):
        self.make_open_tournament(("alice", "bob"))

        self.advance(client, 8)

        entry = nfl_helper.tinyurl_data["cup"]
        assert entry["access_mode"] == "allowlist", "must stop taking new entrants"
        assert sorted(entry["allowed_names"]) == ["alice", "bob"]

    def test_a_newcomer_cannot_join_after_week_one(self, client, verified):
        self.make_open_tournament(("bob",))
        self.advance(client, 8)

        # alice holds a valid Sleeper login but did not enter week one
        resp = submit(client, "cup", name="alice", token="good-token",
                      data=make_full_lineup_string(8))

        assert resp.status_code == 401

    def test_a_week_one_entrant_can_still_submit(self, client, verified):
        self.make_open_tournament(("alice",))
        self.advance(client, 8)

        resp = submit(client, "cup", name="alice",
                      data=make_full_lineup_string(8))

        assert resp.status_code == 200

    def test_empty_first_week_stays_open(self, client):
        """Locking an empty field would leave a tournament nobody could ever join."""
        self.make_open_tournament(entrants=())

        self.advance(client, 8)

        assert nfl_helper.tinyurl_data["cup"]["access_mode"] == "sleeper"

    def test_single_week_entries_are_not_locked(self, client):
        create_entry("oneoff", week=7, allowed_names=[])
        nfl_helper.tinyurl_data["oneoff"]["access_mode"] = "sleeper"

        self.advance(client, 8)

        # single entries are deleted once their week passes, not converted
        assert "oneoff" not in nfl_helper.tinyurl_data


class TestRemoveEntrant:
    def setup_tournament(self):
        create_entry("cup", week=8, entry_type="multiweek_dfs", num_weeks=4,
                     start_week=7, allowed_names=["alice", "bob"])
        nfl_helper.tinyurl_data["cup"].update(
            user_submissions={"alice": {"username": "alice", "data": "x"}},
            standings={"alice": {"total_points": 30.0, "week_points": {"7": 30.0}}},
        )

    def test_removes_from_allowlist_and_current_lineup(self, client):
        self.setup_tournament()

        resp = client.delete("/tinyurl/cup/entrants/alice")

        assert resp.status_code == 200
        entry = nfl_helper.tinyurl_data["cup"]
        assert entry["allowed_names"] == ["bob"]
        assert "alice" not in entry["user_submissions"]

    def test_keeps_standings_by_default(self, client):
        """A guillotine elimination should not erase the weeks already played."""
        self.setup_tournament()

        resp = client.delete("/tinyurl/cup/entrants/alice")

        assert nfl_helper.tinyurl_data["cup"]["standings"]["alice"]["total_points"] == 30.0
        assert resp.get_json()["standings_kept"] is True

    def test_purges_standings_on_request(self, client):
        """A withdrawal should leave no trace."""
        self.setup_tournament()

        client.delete("/tinyurl/cup/entrants/alice?purge_standings=true")

        assert "alice" not in nfl_helper.tinyurl_data["cup"]["standings"]

    def test_removal_is_case_insensitive(self, client):
        self.setup_tournament()
        assert client.delete("/tinyurl/cup/entrants/ALICE").status_code == 200
        assert nfl_helper.tinyurl_data["cup"]["allowed_names"] == ["bob"]

    def test_removed_user_can_no_longer_submit(self, client, verified):
        self.setup_tournament()
        client.delete("/tinyurl/cup/entrants/alice")

        resp = submit(client, "cup", name="alice", data=make_full_lineup_string(8))

        assert resp.status_code == 401

    def test_unknown_entrant_is_a_404(self, client):
        self.setup_tournament()
        assert client.delete("/tinyurl/cup/entrants/nobody").status_code == 404

    def test_unknown_tournament_is_a_404(self, client):
        assert client.delete("/tinyurl/nosuch/entrants/alice").status_code == 404


class TestMultiweekProgress:
    def test_reports_week_within_the_tournament_not_the_nfl_week(self, client):
        create_entry("cup", week=8, entry_type="multiweek_dfs", num_weeks=4,
                     start_week=7, allowed_names=["alice"])

        body = client.get("/tinyurl/cup/details").get_json()

        assert body["tournament_week"] == 2, "NFL week 8, second week of the cup"
        assert body["num_weeks"] == 4

    def test_first_week_reads_as_one(self, client):
        create_entry("cup", week=7, entry_type="multiweek_dfs", num_weeks=4,
                     start_week=7, allowed_names=["alice"])
        assert client.get("/tinyurl/cup/details").get_json()["tournament_week"] == 1

    def test_grace_week_is_clamped_to_the_last_week(self, client):
        """The grace week runs one past the end; it must not read as '5 of 4'."""
        create_entry("cup", week=11, entry_type="multiweek_dfs", num_weeks=4,
                     start_week=7, allowed_names=["alice"])
        assert client.get("/tinyurl/cup/details").get_json()["tournament_week"] == 4

    def test_single_entries_have_no_progress(self, client):
        create_entry("oneoff", week=8, allowed_names=["alice"])
        assert "tournament_week" not in client.get("/tinyurl/oneoff/details").get_json()

    def test_progress_is_listed_for_entrants(self, client):
        create_entry("cup", week=8, entry_type="multiweek_dfs", num_weeks=4,
                     start_week=7, allowed_names=["alice"])

        body = client.get("/tinyurl/alice/available").get_json()

        assert body["entries"][0]["tournament_week"] == 2
        assert body["entries"][0]["num_weeks"] == 4


class TestLoadingOwnLineupOnSleeperEntries:
    """A PIN keeps strangers out of a lineup. A verified token establishes who is
    asking at least as well, so the owner is let in without one.

    This was once limited to Sleeper-gated entries, on the reasoning that an
    allowlist holds names anyone could claim. But a multiweek tournament turns
    into an allowlist the moment its field locks after week one, so the proof the
    entrant logged in with stopped working a week into every tournament that used
    it. The token is checked against the name the lineup was filed under either
    way, so how the tournament admits people has no bearing on it.
    """

    def _entry_with_pinned_lineup(self, client, verified, access_mode="sleeper"):
        normalized = create_entry("cup", allowed_names=["alice"])
        entry = nfl_helper.tinyurl_data[normalized]
        entry["access_mode"] = access_mode
        if access_mode == "sleeper":
            entry["allowed_names"] = []
        submit_body = {"data": make_full_lineup_string(8), "pin": "1234"}
        if access_mode != "sleeper":
            submit_body["name"] = "alice"
        resp = client.post("/tinyurl/cup/add", json=submit_body,
                           headers={"Authorization": "tok"})
        assert resp.status_code == 200, resp.get_json()

    def test_owner_loads_without_a_pin(self, client, verified):
        self._entry_with_pinned_lineup(client, verified)
        body = client.get("/tinyurl/cup/data?username=alice",
                          headers={"Authorization": "tok"}).get_json()
        assert not body.get("pin_required")
        assert body["data"]

    def test_pin_still_works_for_the_owner(self, client, verified):
        self._entry_with_pinned_lineup(client, verified)
        body = client.get("/tinyurl/cup/data?username=alice&pin=1234",
                          headers={"Authorization": "tok"}).get_json()
        assert body["data"]

    def test_without_a_token_the_pin_is_still_required(self, client, verified):
        self._entry_with_pinned_lineup(client, verified)
        verified.return_value = None
        body = client.get("/tinyurl/cup/data?username=alice").get_json()
        assert body.get("pin_required") is True
        assert body["data"] is None

    def test_another_account_cannot_open_it(self, client, verified):
        self._entry_with_pinned_lineup(client, verified)
        verified.return_value = {"user_id": "222", "display_name": "bob"}
        body = client.get("/tinyurl/cup/data?username=alice",
                          headers={"Authorization": "tok"}).get_json()
        assert body.get("pin_required") is True
        assert body["data"] is None

    def test_an_allowlist_entry_accepts_the_login_too(self, client, verified):
        """Previously refused, which is what a locked tournament turns into."""
        self._entry_with_pinned_lineup(client, verified, access_mode="allowlist")
        body = client.get("/tinyurl/cup/data?username=alice",
                          headers={"Authorization": "tok"}).get_json()
        assert not body.get("pin_required")
        assert body["data"]

    def test_an_allowlist_entry_still_refuses_a_stranger(self, client, verified):
        self._entry_with_pinned_lineup(client, verified, access_mode="allowlist")
        verified.return_value = {"user_id": "222", "display_name": "bob"}
        body = client.get("/tinyurl/cup/data?username=alice",
                          headers={"Authorization": "tok"}).get_json()
        assert body.get("pin_required") is True
        assert body["data"] is None

    def test_a_locked_tournament_still_opens_for_its_entrants(self, client, verified):
        """The week-one lock rewrites access_mode to allowlist. That closes the
        field, and used to close the entrants out of their own lineups with it."""
        self._entry_with_pinned_lineup(client, verified)
        nfl_helper.tinyurl_data["cup"]["access_mode"] = "allowlist"
        nfl_helper.tinyurl_data["cup"]["allowed_names"] = ["alice"]

        body = client.get("/tinyurl/cup/data?username=alice",
                          headers={"Authorization": "tok"}).get_json()

        assert not body.get("pin_required")
        assert body["data"]


class TestAvailableReportsWhatTheLoginOpens:
    """The load button has to know a lineup it can open from one it cannot.

    Without this it can only see access_mode and has_pin, so it offered a PIN box
    for a lineup with no PIN and disabled the button entirely for the owner.
    """

    def _entry(self, client, access_mode="allowlist", pin=None):
        normalized = create_entry("cup", allowed_names=["alice"])
        entry = nfl_helper.tinyurl_data[normalized]
        entry["access_mode"] = access_mode
        if access_mode == "sleeper":
            entry["allowed_names"] = []
        body = {"data": make_full_lineup_string(8)}
        if pin:
            body["pin"] = pin
        if access_mode != "sleeper":
            body["name"] = "alice"
        assert client.post("/tinyurl/cup/add", json=body,
                           headers={"Authorization": "tok"}).status_code == 200

    def _entry_info(self, client, username="alice", token="tok"):
        headers = {"Authorization": token} if token else {}
        body = client.get(f"/tinyurl/{username}/available", headers=headers).get_json()
        return body["entries"][0]

    def test_the_owner_is_told_their_login_opens_it(self, client, verified):
        self._entry(client)
        assert self._entry_info(client)["can_open_with_login"] is True

    def test_it_holds_for_a_lineup_with_no_pin(self, client, verified):
        """The case that had the button disabled outright."""
        self._entry(client)
        info = self._entry_info(client)
        assert info["has_pin"] is False
        assert info["has_data"] is True
        assert info["can_open_with_login"] is True

    def test_a_different_account_is_not(self, client, verified):
        self._entry(client, pin="1234")
        verified.return_value = {"user_id": "222", "display_name": "bob"}
        assert self._entry_info(client)["can_open_with_login"] is False

    def test_without_a_token_it_is_not(self, client, verified):
        self._entry(client, pin="1234")
        verified.return_value = None
        assert self._entry_info(client, token=None)["can_open_with_login"] is False

    def test_a_sleeper_entry_still_reports_its_access_mode(self, client, verified):
        self._entry(client, access_mode="sleeper")
        info = self._entry_info(client)
        assert info["access_mode"] == "sleeper"
        assert info["can_open_with_login"] is True


class TestClearingOneLineup:
    """An organiser can wipe a single lineup so its owner can submit again. Nothing
    else moves: they stay an entrant, and earlier weeks keep their points."""

    def setup_tournament(self):
        create_entry("cup", allowed_names=["alice", "bob"], entry_type="multiweek_dfs")
        nfl_helper.tinyurl_data["cup"].update(
            user_submissions={"alice": {"username": "alice", "data": "x",
                                        "created_at": "before", "update_count": 3,
                                        "updated_at": "then", "pin": "1234"}},
            standings={"alice": {"total_points": 30.0, "week_points": {"7": 30.0}}},
        )

    def clear(self, client, who="alice", token="tok"):
        headers = {"Authorization": token} if token else {}
        return client.delete(f"/tinyurl/cup/entrants/{who}/lineup", headers=headers)

    @pytest.fixture(autouse=True)
    def organiser(self, verified):
        """Clearing is organiser-only, so the token must resolve to one."""
        verified.return_value = {"user_id": "1", "display_name": "carnade"}
        yield verified

    def test_clears_only_the_lineup(self, client, verified):
        self.setup_tournament()
        resp = self.clear(client)
        assert resp.status_code == 200, resp.get_json()
        entry = nfl_helper.tinyurl_data["cup"]
        assert entry["user_submissions"]["alice"]["data"] is None
        assert entry["user_submissions"]["alice"]["update_count"] == 0
        assert "updated_at" not in entry["user_submissions"]["alice"]

    def test_keeps_them_an_entrant(self, client, verified):
        self.setup_tournament()
        self.clear(client)
        assert nfl_helper.tinyurl_data["cup"]["allowed_names"] == ["alice", "bob"]
        assert "alice" in nfl_helper.tinyurl_data["cup"]["user_submissions"]

    def test_keeps_earlier_weeks_points(self, client, verified):
        """Clearing is about this week's lineup, never the accumulated total."""
        self.setup_tournament()
        self.clear(client)
        standings = nfl_helper.tinyurl_data["cup"]["standings"]["alice"]
        assert standings["total_points"] == 30.0
        assert standings["week_points"] == {"7": 30.0}

    def test_they_can_submit_again(self, client, verified):
        self.setup_tournament()
        self.clear(client)
        resp = submit(client, "cup", name="alice", token="tok")
        assert resp.status_code == 200, resp.get_json()
        assert nfl_helper.tinyurl_data["cup"]["user_submissions"]["alice"]["data"]

    def test_is_not_blocked_by_started_players(self, client, verified):
        """The whole point: /add refuses to overwrite a lineup whose players have
        kicked off, so clearing must not apply the same check."""
        self.setup_tournament()
        with patch.object(nfl_helper, "validate_lineup_players_not_started",
                          return_value=(False, "players started", ["11111"])):
            assert self.clear(client).status_code == 200

    def test_requires_an_organiser_token(self, client, verified):
        self.setup_tournament()
        verified.return_value = {"user_id": "222", "display_name": "bob"}
        assert self.clear(client).status_code == 403
        assert nfl_helper.tinyurl_data["cup"]["user_submissions"]["alice"]["data"] == "x"

    def test_requires_a_token_at_all(self, client, verified):
        self.setup_tournament()
        verified.return_value = None
        assert self.clear(client, token=None).status_code == 403

    def test_unknown_entrant_is_a_404(self, client, verified):
        self.setup_tournament()
        assert self.clear(client, who="nobody").status_code == 404

    def test_already_clear_is_a_404(self, client, verified):
        self.setup_tournament()
        assert self.clear(client).status_code == 200
        assert self.clear(client).status_code == 404
