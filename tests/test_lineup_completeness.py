"""A lineup has to fill all nine slots.

Nothing checked, so a half-built lineup submitted fine and then scored as
whatever it happened to contain — competing against full ones.

The page drops empty slots when it encodes, so an unfinished lineup arrives as a
shorter list rather than as anything malformed. Counting is therefore the whole
check, and it counts slots that were filled rather than players we can identify:
a manual entry encodes a name where a Sleeper id would go, and that slot is
still filled.
"""

import sys
from unittest.mock import patch

import pytest

nfl_helper = sys.modules["nfl_helper"]

from conftest import make_lineup_string, make_full_lineup_string, create_entry


def lineup(*entries):
    return make_lineup_string(8, list(entries))


FULL = ["11111-5000", "22222-4000", "33333-4000", "44444-4000", "55555-4000",
        "66666-4000", "77777-4000", "88888-4000", "CHI-3000"]


class TestTheCheck:
    def test_a_full_lineup_passes(self):
        ok, err = nfl_helper.validate_lineup_is_complete(lineup(*FULL))
        assert ok and err is None

    @pytest.mark.parametrize("filled", [0, 1, 5, 8])
    def test_a_short_lineup_is_refused(self, filled):
        ok, err = nfl_helper.validate_lineup_is_complete(lineup(*FULL[:filled]))
        assert not ok
        assert f"{filled} of 9" in err
        assert f"{9 - filled} still empty" in err

    def test_too_many_is_refused_too(self):
        ok, err = nfl_helper.validate_lineup_is_complete(lineup(*(FULL + ["99999-4000"])))
        assert not ok
        assert "too many" in err

    def test_a_manually_named_player_still_counts(self):
        """The page encodes a name when it cannot resolve an id. The slot is
        filled; refusing it would block a lineup that is actually complete."""
        with_name = ["Some Player-5000"] + FULL[1:]
        ok, err = nfl_helper.validate_lineup_is_complete(lineup(*with_name))
        assert ok, err

    def test_the_username_prefix_is_not_counted_as_a_slot(self):
        prefixed = make_lineup_string(8, ["alice:11111-5000"] + FULL[1:])
        ok, err = nfl_helper.validate_lineup_is_complete(prefixed)
        assert ok, err

    def test_a_numeric_username_prefix_is_handled(self):
        """'52Ravens' is not alphabetic, which the older parsers tripped over."""
        prefixed = make_lineup_string(8, ["52Ravens:11111-5000"] + FULL[1:])
        ok, err = nfl_helper.validate_lineup_is_complete(prefixed)
        assert ok, err

    def test_the_defence_slot_counts(self):
        """It is a team code rather than a numeric id."""
        tokens = nfl_helper._lineup_slot_tokens(lineup(*FULL))
        assert tokens[-1] == "CHI"
        assert len(tokens) == 9

    def test_something_undecodable_is_left_alone(self):
        """Other checks already deal with junk; refusing it here would report
        the wrong reason."""
        assert nfl_helper.validate_lineup_is_complete("8|!!!not base64!!!") == (True, None)
        assert nfl_helper.validate_lineup_is_complete("no pipe at all") == (True, None)
        assert nfl_helper.validate_lineup_is_complete("") == (True, None)


class TestTheRoute:
    @pytest.fixture(autouse=True)
    def no_kickoff_check(self):
        with patch.object(nfl_helper, "validate_lineup_players_not_started",
                          return_value=(True, None, [])):
            yield

    def _post(self, client, data, **extra):
        create_entry("cup", allowed_names=["alice"])
        body = {"name": "alice", "data": data}
        body.update(extra)
        return client.post("/tinyurl/cup/add", json=body)

    def test_a_complete_lineup_is_accepted(self, client):
        assert self._post(client, make_full_lineup_string(8)).status_code == 200

    def test_a_short_lineup_is_refused(self, client):
        resp = self._post(client, lineup(*FULL[:6]))
        assert resp.status_code == 400
        assert "6 of 9" in resp.get_json()["error"]

    def test_nothing_is_stored_when_it_is_refused(self, client):
        self._post(client, lineup(*FULL[:6]))
        assert nfl_helper.tinyurl_data["cup"].get("user_submissions", {}) == {}

    def test_skip_validation_does_not_wave_it_through(self, client):
        """skip_validation is caller-supplied, so anything it can bypass is
        effectively optional. A short lineup is invalid whenever it arrives."""
        resp = self._post(client, lineup(*FULL[:6]), skip_validation=True)
        assert resp.status_code == 400
        assert "6 of 9" in resp.get_json()["error"]

    def test_an_existing_lineup_is_not_replaced_by_a_short_one(self, client):
        create_entry("cup", allowed_names=["alice"])
        assert client.post("/tinyurl/cup/add",
                           json={"name": "alice", "data": make_full_lineup_string(8)}
                           ).status_code == 200
        kept = nfl_helper.tinyurl_data["cup"]["user_submissions"]["alice"]["data"]

        resp = client.post("/tinyurl/cup/add",
                           json={"name": "alice", "data": lineup(*FULL[:3])})

        assert resp.status_code == 400
        assert nfl_helper.tinyurl_data["cup"]["user_submissions"]["alice"]["data"] == kept


class TestAnEmptyLineup:
    """Submitting with nothing selected — the extreme of the reported bug."""

    def test_a_username_with_no_players_is_zero_slots(self):
        """What the page encodes when every slot is empty: "alice:" and no more."""
        ok, err = nfl_helper.validate_lineup_is_complete(make_lineup_string(8, ["alice:"]))
        assert not ok
        assert "0 of 9" in err

    def test_nothing_encoded_at_all_is_zero_slots(self):
        assert nfl_helper._lineup_slot_tokens("8|") == []


class TestTheCompressedFormat:
    """What the page actually sends.

    DFS.js compresses with LZString.compressToEncodedURIComponent, whose output
    is not always valid base64 — decoding it as base64 first raises outright for
    a good share of real lineups. Checked against the 18 live submissions in
    Giljotin_1: base64 failed for 4 of them and a URL-safe payload took the whole
    ladder down for a 5th, so the check silently passed everything it could not
    read. All 18 now read as nine slots.
    """

    # Ids chosen so the compressed payload is NOT valid base64 — the shape that
    # actually broke. A payload that happens to survive b64decode proves nothing
    # here, since a later rung of the ladder would catch it either way.
    NOT_BASE64 = ["10005-4600", "10142-4800", "10279-4100", "10416-4300",
                  "10553-4500", "10690-4700", "10827-4000", "10964-4200",
                  "CHI-3000"]

    def _compressed(self, players):
        lzstring = pytest.importorskip("lzstring")
        payload = lzstring.LZString().compressToEncodedURIComponent(
            "alice:" + ",".join(players))
        return f"8|{payload}"

    def test_the_sample_really_is_not_valid_base64(self):
        """Guard the guard: if this ever decodes, the test below stops testing
        anything and needs new ids."""
        import base64
        payload = self._compressed(self.NOT_BASE64).split("|", 1)[1]
        with pytest.raises(Exception):
            base64.b64decode(payload + "=" * (-len(payload) % 4))

    def test_a_payload_that_is_not_valid_base64_is_still_read(self):
        tokens = nfl_helper._lineup_slot_tokens(self._compressed(self.NOT_BASE64))
        assert tokens == [p.split("-")[0] for p in self.NOT_BASE64]

    def test_a_compressed_full_lineup_is_read(self):
        assert nfl_helper._lineup_slot_tokens(self._compressed(FULL)) == [
            "11111", "22222", "33333", "44444", "55555",
            "66666", "77777", "88888", "CHI"]

    def test_a_compressed_full_lineup_is_accepted(self):
        ok, err = nfl_helper.validate_lineup_is_complete(self._compressed(FULL))
        assert ok, err

    def test_a_compressed_short_lineup_is_refused(self):
        ok, err = nfl_helper.validate_lineup_is_complete(self._compressed(FULL[:4]))
        assert not ok
        assert "4 of 9" in err

    def test_plain_base64_still_works_alongside_it(self):
        """Both forms are in circulation, so neither may shadow the other."""
        ok, err = nfl_helper.validate_lineup_is_complete(lineup(*FULL))
        assert ok, err
