"""DFS salaries survive a restart, and say how old they are.

Every other store the app keeps is written through; this one was not, so each
restart emptied it and left a ten-minute hole while the scrape refilled it —
/dfs-salaries/week/N answering 404 with nothing to say why. Seen live on
2026-09-30: the instance came up at 13:29, the scrape finished at 13:40, and
every request in between got a 404.

Persisting it has a cost that has to be paid for: an empty store used to be the
signal that something was wrong. Now the endpoint answers normally whatever
state the scrape is in, so the age has to be reported instead of inferred.
"""

import copy
import datetime
import sys
from unittest.mock import MagicMock, patch

import pytest

nfl_helper = sys.modules["nfl_helper"]

# conftest stubs every save_* so tests cannot write to the real store. These
# tests are about that function, so hold the real one from before it is stubbed
# and put it back for the round trip.
REAL_SAVE = nfl_helper.save_dfs_salaries_data


def a_row(sleeper_id="11111", week=4, date="2026-10-04"):
    return {"sleeper_id": sleeper_id, "week": week, "game_date": date,
            "name": "Test Player", "salary": 5000}


@pytest.fixture
def stored():
    """Capture what would be written, and hand it back on load."""
    box = {}

    # Copies, because the real _save_store serialises: keeping a reference would
    # mean clearing memory also emptied what was "saved".
    def save(key, store):
        box[key] = copy.deepcopy(store)

    def load(key, store):
        if key in box:
            store.clear()
            store.update(copy.deepcopy(box[key]))

    with patch.object(nfl_helper, "_save_store", side_effect=save), \
         patch.object(nfl_helper, "_load_store", side_effect=load), \
         patch.object(nfl_helper, "save_dfs_salaries_data", REAL_SAVE):
        yield box


class TestRoundTrip:
    def test_rows_survive_a_restart(self, stored):
        nfl_helper.dfs_salaries_data["11111_W4_D2026-10-04"] = a_row()
        nfl_helper.last_dfs_salaries_update = datetime.datetime(2026, 9, 30, 13, 40)
        nfl_helper.save_dfs_salaries_data()

        # The restart.
        nfl_helper.dfs_salaries_data.clear()
        nfl_helper.last_dfs_salaries_update = None
        nfl_helper.load_dfs_salaries_data()

        assert nfl_helper.dfs_salaries_data["11111_W4_D2026-10-04"]["salary"] == 5000

    def test_the_scrape_time_survives_too(self, stored):
        """Otherwise /statistics reads 'Never' while serving a full set."""
        scraped = datetime.datetime(2026, 9, 30, 13, 40)
        nfl_helper.dfs_salaries_data["11111_W4_D2026-10-04"] = a_row()
        nfl_helper.last_dfs_salaries_update = scraped
        nfl_helper.save_dfs_salaries_data()

        nfl_helper.dfs_salaries_data.clear()
        nfl_helper.last_dfs_salaries_update = None
        nfl_helper.load_dfs_salaries_data()

        assert nfl_helper.last_dfs_salaries_update == scraped

    def test_an_empty_store_leaves_memory_alone(self, stored):
        nfl_helper.dfs_salaries_data["kept"] = a_row()
        nfl_helper.load_dfs_salaries_data()
        assert "kept" in nfl_helper.dfs_salaries_data

    def test_a_corrupt_timestamp_reports_unknown_rather_than_wrong(self, stored):
        stored["dfs_salaries"] = {"scraped_at": "not a date", "rows": {"k": a_row()}}
        nfl_helper.load_dfs_salaries_data()
        assert nfl_helper.dfs_salaries_data["k"]["salary"] == 5000
        assert nfl_helper.last_dfs_salaries_update is None
        assert nfl_helper.dfs_salaries_age() is None

    def test_a_payload_without_rows_is_ignored(self, stored):
        stored["dfs_salaries"] = {"scraped_at": "2026-09-30T13:40:00"}
        nfl_helper.load_dfs_salaries_data()
        assert nfl_helper.dfs_salaries_data == {}


class TestStaleness:
    def test_fresh_data_is_not_stale(self):
        nfl_helper.dfs_salaries_data["k"] = a_row()
        nfl_helper.last_dfs_salaries_update = datetime.datetime.now()
        assert nfl_helper.dfs_salaries_are_stale() is False

    def test_data_past_a_missed_run_is_stale(self):
        """Scrapes run daily at 15:00, so 26 hours means one was missed."""
        nfl_helper.dfs_salaries_data["k"] = a_row()
        nfl_helper.last_dfs_salaries_update = (
            datetime.datetime.now() - datetime.timedelta(hours=27))
        assert nfl_helper.dfs_salaries_are_stale() is True

    def test_just_inside_the_window_is_not(self):
        nfl_helper.dfs_salaries_data["k"] = a_row()
        nfl_helper.last_dfs_salaries_update = (
            datetime.datetime.now() - datetime.timedelta(hours=25))
        assert nfl_helper.dfs_salaries_are_stale() is False

    def test_rows_with_no_known_scrape_time_are_stale(self):
        nfl_helper.dfs_salaries_data["k"] = a_row()
        nfl_helper.last_dfs_salaries_update = None
        assert nfl_helper.dfs_salaries_are_stale() is True

    def test_an_empty_store_is_not_called_stale(self):
        """The 404 already says it, and 'stale' would imply we had something."""
        nfl_helper.dfs_salaries_data.clear()
        nfl_helper.last_dfs_salaries_update = None
        assert nfl_helper.dfs_salaries_are_stale() is False

    def test_age_is_none_before_anything_is_scraped(self):
        nfl_helper.last_dfs_salaries_update = None
        assert nfl_helper.dfs_salaries_age() is None


class TestStatisticsReporting:
    def test_the_age_is_visible_without_reading_logs(self, client):
        nfl_helper.dfs_salaries_data["k"] = a_row()
        nfl_helper.last_dfs_salaries_update = (
            datetime.datetime.now() - datetime.timedelta(hours=3))

        body = client.get("/statistics").get_json()

        assert body["dfs_salaries_age_hours"] == pytest.approx(3.0, abs=0.1)
        assert body["dfs_salaries_stale"] is False
        assert body["dfs_salaries_stale_after_hours"] == 26

    def test_stale_data_says_so(self, client):
        nfl_helper.dfs_salaries_data["k"] = a_row()
        nfl_helper.last_dfs_salaries_update = (
            datetime.datetime.now() - datetime.timedelta(hours=30))

        body = client.get("/statistics").get_json()

        assert body["dfs_salaries_stale"] is True
        assert body["dfs_salaries_age_hours"] == pytest.approx(30.0, abs=0.1)


class TestItIsActuallyWiredIn:
    """The functions working is not the same as them being called.

    Without these, deleting the save from the end of the scrape would leave the
    round-trip tests above perfectly green and nothing would ever be written.
    """

    def _scrape_returning(self, rows):
        scraper = patch.object(nfl_helper, "DFFSalariesScraper")
        cls = scraper.start()
        cls.return_value.get_salaries_with_sleeper_ids.return_value = rows
        return scraper

    def test_a_successful_scrape_persists_what_it_found(self):
        saved = {}
        scraper = self._scrape_returning([
            {"name": "Test Player", "team": "MIN", "position": "WR",
             "sleeper_id": "11111", "week": 4, "salary": 5000,
             "projected_points": 12.5, "game_date": "2026-10-04"},
        ])
        try:
            with patch.object(nfl_helper, "save_dfs_salaries_data", REAL_SAVE), \
                 patch.object(nfl_helper, "_save_store",
                              side_effect=lambda key, store: saved.__setitem__(key, copy.deepcopy(store))):
                nfl_helper.update_dfs_salaries_data()
        finally:
            scraper.stop()

        assert "dfs_salaries" in saved, "the scrape has to write what it found"
        assert saved["dfs_salaries"]["rows"], "and the rows with it"
        assert saved["dfs_salaries"]["scraped_at"], "and when"

    def test_a_failed_scrape_does_not_overwrite_good_data(self):
        """An empty scrape records an error and retries; it must not persist
        the nothing it found over yesterday's usable rows."""
        saved = {}
        nfl_helper.dfs_salaries_data["keep"] = a_row()
        scraper = self._scrape_returning([])
        try:
            # A failed scrape queues a retry, which registers a job. Give it a
            # scheduler of its own: the shared mock carries the cron jobs
            # registered at import, and test_rollover_schedule inspects those.
            with patch.object(nfl_helper, "scheduler", MagicMock()), \
                 patch.object(nfl_helper, "save_dfs_salaries_data", REAL_SAVE), \
                 patch.object(nfl_helper, "_save_store",
                              side_effect=lambda key, store: saved.__setitem__(key, copy.deepcopy(store))):
                nfl_helper.update_dfs_salaries_data()
        finally:
            scraper.stop()

        assert "dfs_salaries" not in saved
        assert nfl_helper.dfs_salaries_data["keep"]["salary"] == 5000


class TestTheWeekRollIsUnaffected:
    """Persistence changes nothing about how weeks come and go.

    The week is read off the scraped rows, not a clock, and a scrape deletes
    anything older than the week it just saw. Loading a stored set simply means
    the dict is not empty when that runs.
    """

    def test_a_scrape_still_drops_the_week_that_rolled_off(self, stored):
        nfl_helper.dfs_salaries_data.update({
            "a_W3_D2026-09-27": a_row("a", week=3, date="2026-09-27"),
            "b_W4_D2026-10-04": a_row("b", week=4, date="2026-10-04"),
        })
        nfl_helper.save_dfs_salaries_data()
        nfl_helper.dfs_salaries_data.clear()
        nfl_helper.load_dfs_salaries_data()
        assert len(nfl_helper.dfs_salaries_data) == 2, "both weeks come back"

        # A scrape that now only sees week 4.
        scraper = patch.object(nfl_helper, "DFFSalariesScraper")
        with scraper as cls:
            cls.return_value.get_salaries_with_sleeper_ids.return_value = [
                {"name": "New Player", "team": "MIN", "position": "WR",
                 "sleeper_id": "c", "week": 4, "salary": 6000,
                 "projected_points": 10.0, "game_date": "2026-10-04"},
            ]
            nfl_helper.update_dfs_salaries_data()

        weeks = {r.get("week") for r in nfl_helper.dfs_salaries_data.values()}
        assert weeks == {4}, "week 3 is pruned by the scrape, as it always was"
