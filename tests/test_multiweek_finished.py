"""
The end of a multiweek tournament.

A tournament plays start_week through start_week + num_weeks - 1, then spends
one week past that so the final standings can still be read, then is removed by
the Thursday pass. That middle week is the problem these tests pin down: the
only thing that knew the tournament was over was the cleanup function, so for a
week it went on being offered on the DFS page and went on taking lineups for a
week it does not own and will never score.

Shaped on the real case — Giljotin_1, start_week 2, num_weeks 7, so weeks 2
through 8, sitting on NFL week 9 with two entrants having already filed a
week 9 lineup that was going to be discarded with the entry.
"""

import sys

import pytest

nfl_helper = sys.modules["nfl_helper"]


def tournament(**over):
    entry = {
        'type': 'multiweek_dfs',
        'name': 'Giljotin_1',
        'start_week': 2,
        'num_weeks': 7,
        'week': 5,
        'allowed_names': ['carnade'],
        'user_submissions': {},
    }
    entry.update(over)
    return entry


# ── Where the tournament ends ────────────────────────────────────────────────

class TestEndWeek:
    def test_the_last_week_it_plays(self):
        # Weeks 2, 3, 4, 5, 6, 7, 8 — seven of them, ending at 8.
        assert nfl_helper.multiweek_end_week(tournament()) == 8

    def test_a_one_week_tournament_ends_where_it_starts(self):
        assert nfl_helper.multiweek_end_week(
            tournament(start_week=9, num_weeks=1)) == 9

    def test_it_falls_back_to_the_current_week_when_no_start_is_stored(self):
        entry = tournament(week=4)
        del entry['start_week']

        assert nfl_helper.multiweek_end_week(entry) == 10

    def test_none_for_anything_that_is_not_a_multiweek_tournament(self):
        assert nfl_helper.multiweek_end_week({'type': 'single', 'week': 4}) is None

    def test_none_when_the_fields_are_missing_or_unusable(self):
        assert nfl_helper.multiweek_end_week(tournament(num_weeks=None)) is None
        assert nfl_helper.multiweek_end_week(tournament(num_weeks='seven')) is None


# ── Whether it is over ───────────────────────────────────────────────────────

class TestHasFinished:
    @pytest.mark.parametrize("week", [2, 5, 8])
    def test_running_through_its_own_weeks(self, week):
        assert nfl_helper.multiweek_has_finished(tournament(week=week)) is False

    def test_finished_on_its_final_week_plus_one(self):
        # The grace week. It is sitting on week 9, which is not one of its own.
        assert nfl_helper.multiweek_has_finished(tournament(week=9)) is True

    def test_still_finished_further_past_the_end(self):
        assert nfl_helper.multiweek_has_finished(tournament(week=12)) is True

    def test_a_single_week_entry_never_reads_as_finished_this_way(self):
        # Those are removed by week, not by a tournament length.
        assert nfl_helper.multiweek_has_finished(
            {'type': 'single', 'week': 99}) is False

    def test_an_unusable_week_is_not_a_finish(self):
        assert nfl_helper.multiweek_has_finished(tournament(week=None)) is False
        assert nfl_helper.multiweek_has_finished(tournament(week='nine')) is False

    def test_progress_cannot_answer_this_because_it_clamps(self):
        """
        Why the helper exists. multiweek_progress reports the grace week as
        "7 of 7", exactly like the real final week, so nothing downstream could
        tell a finished tournament from one on its last legs.
        """
        final = nfl_helper.multiweek_progress(tournament(week=8))
        grace = nfl_helper.multiweek_progress(tournament(week=9))

        assert final == grace == {'week': 7, 'num_weeks': 7}
        assert nfl_helper.multiweek_has_finished(tournament(week=8)) is False
        assert nfl_helper.multiweek_has_finished(tournament(week=9)) is True


# ── It stops taking lineups ──────────────────────────────────────────────────

LINEUP = "9|" + "x"  # rejected long before this is decoded


class TestSubmissionsAreRefused:
    def _add(self, client, entry):
        nfl_helper.tinyurl_data['giljotin_1'] = entry
        return client.post(
            '/tinyurl/giljotin_1/add',
            json={'name': 'carnade', 'data': LINEUP},
        )

    def test_a_finished_tournament_refuses(self, client):
        response = self._add(client, tournament(week=9))

        assert response.status_code == 403
        body = response.get_json()
        assert body['finished'] is True
        assert 'finished' in body['error'].lower()

    def test_it_says_how_many_weeks_were_played(self, client):
        body = self._add(client, tournament(week=9)).get_json()

        assert '7 weeks' in body['error']

    def test_nothing_is_stored(self, client):
        entry = tournament(week=9)
        self._add(client, entry)

        assert entry['user_submissions'] == {}

    def test_a_running_tournament_is_not_refused_for_this_reason(self, client):
        # It fails later, on the lineup itself, which is the point: the finish
        # check is not what stops it.
        response = self._add(client, tournament(week=5))

        assert response.status_code != 403 or \
            'finished' not in (response.get_json() or {}).get('error', '').lower()


# ── It says so in the listings ───────────────────────────────────────────────

class TestItIsReportedAsFinished:
    def test_details_reports_finished(self, client):
        nfl_helper.tinyurl_data['giljotin_1'] = tournament(week=9)

        body = client.get('/tinyurl/giljotin_1/details').get_json()

        assert body['finished'] is True
        assert body['tournament_week'] == 7
        assert body['num_weeks'] == 7

    def test_details_reports_a_running_tournament_as_unfinished(self, client):
        nfl_helper.tinyurl_data['giljotin_1'] = tournament(week=8)

        body = client.get('/tinyurl/giljotin_1/details').get_json()

        assert body['finished'] is False
        assert body['tournament_week'] == 7, "the real final week reads the same"

    def test_a_finished_tournament_stays_on_the_available_list(self, client):
        """
        Flagged, not dropped. Two pages read this one endpoint: the DFS page
        makes "add team to league" buttons of it and has to leave a finished
        tournament out, and the results page makes "load from your leagues" of
        it and has to keep it — which is the whole point of the grace week.
        Dropping it here served the first and silently broke the second.
        """
        nfl_helper.tinyurl_data['giljotin_1'] = tournament(week=9)

        body = client.get('/tinyurl/carnade/available').get_json()
        entries = {e['name']: e for e in body.get('entries', []) if isinstance(e, dict)}

        assert 'Giljotin_1' in entries, "the standings must stay reachable"
        assert entries['Giljotin_1']['finished'] is True

    def test_a_running_tournament_is_not_flagged(self, client):
        nfl_helper.tinyurl_data['giljotin_1'] = tournament(week=8)

        body = client.get('/tinyurl/carnade/available').get_json()
        entries = {e['name']: e for e in body.get('entries', []) if isinstance(e, dict)}

        assert entries['Giljotin_1']['finished'] is False
