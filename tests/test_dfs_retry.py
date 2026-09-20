"""A DFS scrape that fails should say so and try again.

The morning this was written, a restart landed before DailyFantasyFuel published
the day's slate. The scrape aborted correctly, nothing retried, and the only
evidence was `last_dfs_salaries_update: Never` — which reads the same whether the
job never ran, failed early, or died halfway. DFS data was missing for four hours.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

nfl_helper = sys.modules["nfl_helper"]


@pytest.fixture(autouse=True)
def reset_dfs_state():
    """Each test starts with no attempt, no error and no retries queued.

    The retries register real jobs, so give each test a scheduler of its own: the
    shared mock carries the registrations made at import, and
    test_rollover_schedule.py inspects those to check the cron staggering.
    """
    nfl_helper.dfs_last_attempt = None
    nfl_helper.dfs_last_error = None
    nfl_helper.dfs_retry_count = 0
    nfl_helper.last_dfs_salaries_update = None
    with patch.object(nfl_helper, "scheduler", MagicMock()):
        yield


def _scraper_returning(rows):
    """Stand in for DFFSalariesScraper, yielding whatever the scrape 'found'."""
    scraper = MagicMock()
    scraper.get_salaries_with_sleeper_ids.return_value = rows
    return MagicMock(return_value=scraper)


def _retry_jobs():
    return [c for c in nfl_helper.scheduler.add_job.call_args_list
            if str(c.kwargs.get("id", "")).startswith("dfs_salaries_retry")]


class TestFailedScrape:
    def test_empty_scrape_records_why_and_queues_a_retry(self):
        with patch.object(nfl_helper, "DFFSalariesScraper", _scraper_returning([])):
            nfl_helper.update_dfs_salaries_data()

        assert nfl_helper.dfs_last_attempt is not None, "an attempt should be recorded even when it fails"
        assert "no slate data" in nfl_helper.dfs_last_error
        assert nfl_helper.last_dfs_salaries_update is None
        assert len(_retry_jobs()) == 1
        assert nfl_helper.dfs_retry_count == 1

    def test_raised_error_is_kept_and_retried(self):
        boom = MagicMock()
        boom.get_salaries_with_sleeper_ids.side_effect = RuntimeError("connection reset")

        with patch.object(nfl_helper, "DFFSalariesScraper", MagicMock(return_value=boom)):
            nfl_helper.update_dfs_salaries_data()

        assert nfl_helper.dfs_last_error == "connection reset"
        assert len(_retry_jobs()) == 1

    def test_retries_are_capped(self):
        with patch.object(nfl_helper, "DFFSalariesScraper", _scraper_returning([])):
            for _ in range(nfl_helper.DFS_MAX_RETRIES + 3):
                nfl_helper.update_dfs_salaries_data()

        # Beyond the cap it stops queueing and waits for the next scheduled run.
        assert nfl_helper.dfs_retry_count == nfl_helper.DFS_MAX_RETRIES
        assert len(_retry_jobs()) == nfl_helper.DFS_MAX_RETRIES

    def test_a_queued_retry_runs_the_same_job(self):
        with patch.object(nfl_helper, "DFFSalariesScraper", _scraper_returning([])):
            nfl_helper.update_dfs_salaries_data()

        job = _retry_jobs()[0]
        assert job.kwargs["func"] is nfl_helper.update_dfs_salaries_data


class TestSuccessfulScrape:
    def _succeed(self):
        rows = [{
            "name": "Test Player", "team": "MIN", "position": "WR",
            "sleeper_id": "12345", "week": 2, "salary": 5000,
            "projected_points": 12.5, "game_date": "2026-09-20",
        }]
        with patch.object(nfl_helper, "DFFSalariesScraper", _scraper_returning(rows)):
            nfl_helper.update_dfs_salaries_data()

    def test_success_clears_the_error_and_the_retry_count(self):
        nfl_helper.dfs_last_error = "no slate data available for 2026-09-20"
        nfl_helper.dfs_retry_count = 2

        self._succeed()

        assert nfl_helper.dfs_last_error is None
        assert nfl_helper.dfs_retry_count == 0
        assert nfl_helper.last_dfs_salaries_update is not None

    def test_success_queues_no_retry(self):
        self._succeed()
        assert _retry_jobs() == []


class TestStatisticsReporting:
    def test_a_failure_is_visible_without_reading_logs(self, client):
        with patch.object(nfl_helper, "DFFSalariesScraper", _scraper_returning([])):
            nfl_helper.update_dfs_salaries_data()

        body = client.get("/statistics").get_json()

        assert body["last_dfs_salaries_update"] == "Never"
        assert body["last_dfs_salaries_attempt"] != "Never", "a failed attempt still happened"
        assert "no slate data" in body["dfs_salaries_error"]
        assert body["dfs_salaries_retries_queued"] == 1

    def test_never_having_run_looks_different_from_having_failed(self, client):
        body = client.get("/statistics").get_json()

        assert body["last_dfs_salaries_attempt"] == "Never"
        assert body["dfs_salaries_error"] is None
        assert body["dfs_salaries_retries_queued"] == 0


class TestManualTrigger:
    def test_it_returns_at_once_rather_than_holding_the_request(self, client):
        """The scrape outlives the hosting gateway's 100s limit, so a synchronous
        trigger reported success as a 504."""
        started = {}

        def fake_thread(target=None, name=None, daemon=None):
            started["target"] = target
            started["daemon"] = daemon
            return MagicMock()

        with patch.object(nfl_helper.threading, "Thread", side_effect=fake_thread):
            resp = client.post("/admin/dfs-salaries/update")

        assert resp.status_code == 202
        assert started["target"] is nfl_helper.update_dfs_salaries_data
        assert started["daemon"] is True
        assert "/statistics" in resp.get_json()["check"]
