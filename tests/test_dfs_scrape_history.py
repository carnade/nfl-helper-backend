"""
A record of how the DFS scrapes went.

/statistics says what is true now and nothing about how it got there, which is
the wrong shape for the question being asked of it — "is the scrape healthy?"

A single error reads the same whether it is the first in a month or the fourth
today. A success that added two players reads the same as one that added six
hundred, and that is exactly the difference between a quiet midweek run and the
three days the scrape spent storing a logged-out preview while reporting
success. Both differences were visible only in the logs, on a host that rotates
them.
"""

import pytest

import nfl_helper as nh
from conftest import admin_get
from get_dfs_salaries_and_stats import DFFAccountGate


@pytest.fixture(autouse=True)
def empty_history(monkeypatch):
    monkeypatch.setattr(nh, "dfs_scrape_runs", [])
    monkeypatch.setattr(nh, "save_dfs_scrape_runs", lambda: None)


class TestKeepingTheRecord:
    def test_a_run_is_stamped_and_kept(self):
        nh._record_dfs_run("ok", scraped=1889, added=587, updated=1302)
        [run] = nh.dfs_scrape_runs
        assert run["outcome"] == "ok"
        assert run["scraped"] == 1889
        assert run["added"] == 587
        assert run["at"].startswith("20")

    def test_newest_first(self):
        nh._record_dfs_run("ok", scraped=1)
        nh._record_dfs_run("gated", error="cookie")
        assert [r["outcome"] for r in nh.dfs_scrape_runs] == ["gated", "ok"]

    def test_it_does_not_grow_without_end(self):
        # Kept beside the salaries in the same store; this is a glance at
        # recent history, not an audit trail.
        for i in range(nh.DFS_RUN_HISTORY + 10):
            nh._record_dfs_run("ok", scraped=i)
        assert len(nh.dfs_scrape_runs) == nh.DFS_RUN_HISTORY
        assert nh.dfs_scrape_runs[0]["scraped"] == nh.DFS_RUN_HISTORY + 9

    def test_the_three_outcomes_stay_apart(self):
        # They call for different actions: nothing, a fresh cookie, and a look
        # at the logs. Collapsed into a success flag the difference is lost.
        for outcome in ("ok", "gated", "failed"):
            nh._record_dfs_run(outcome)
        assert {r["outcome"] for r in nh.dfs_scrape_runs} == {"ok", "gated", "failed"}


class TestWhatTheScrapeRecords:
    @pytest.fixture
    def held(self, monkeypatch):
        monkeypatch.setattr(nh, "dfs_salaries_data", {
            f"{i}_W11_D2026-11-22": {"sleeper_id": str(i), "week": 11} for i in range(300)
        })
        monkeypatch.setattr(nh, "USE_MOCK_DATA", False)
        monkeypatch.setattr(nh, "_schedule_dfs_retry", lambda reason: None)

    def test_a_gated_scrape_is_recorded_as_gated(self, held, monkeypatch):
        class Gated:
            def get_salaries_with_sleeper_ids(self, *a, **k):
                raise DFFAccountGate("logged-out preview — set DFF_COOKIE")

        monkeypatch.setattr(nh, "DFFSalariesScraper", lambda: Gated())
        nh.update_dfs_salaries_data()

        run = nh.dfs_scrape_runs[0]
        assert run["outcome"] == "gated"
        assert "DFF_COOKIE" in run["error"]
        # What survived matters as much as what failed.
        assert run["held"] == 300

    def test_an_ordinary_failure_is_recorded_as_failed(self, held, monkeypatch):
        class Broken:
            def get_salaries_with_sleeper_ids(self, *a, **k):
                raise RuntimeError("connection reset")

        monkeypatch.setattr(nh, "DFFSalariesScraper", lambda: Broken())
        nh.update_dfs_salaries_data()

        assert nh.dfs_scrape_runs[0]["outcome"] == "failed"
        assert "connection reset" in nh.dfs_scrape_runs[0]["error"]

    def test_an_unpublished_slate_is_a_failure_with_nothing_scraped(self, held, monkeypatch):
        class Empty:
            def get_salaries_with_sleeper_ids(self, *a, **k):
                return []

        monkeypatch.setattr(nh, "DFFSalariesScraper", lambda: Empty())
        nh.update_dfs_salaries_data()

        run = nh.dfs_scrape_runs[0]
        assert run["outcome"] == "failed"
        assert run["scraped"] == 0
        assert "no slate data" in run["error"]


class TestTheEndpoint:
    def test_it_is_for_organisers_only(self, client):
        # Gated with every other /admin route by the hook, which is the point
        # of there being one hook.
        assert client.get("/admin/dfs-salaries/runs").status_code == 403

    def test_it_reports_the_runs_and_the_last_good_one(self, client, monkeypatch):
        monkeypatch.setattr(nh, "dfs_scrape_runs", [
            {"at": "2026-11-19T08:00:00", "outcome": "gated", "error": "cookie"},
            {"at": "2026-11-18T19:33:00", "outcome": "ok", "scraped": 1889, "added": 587},
        ])
        body = admin_get(client, "/admin/dfs-salaries/runs").get_json()

        assert len(body["runs"]) == 2
        assert body["last_ok"]["scraped"] == 1889
        assert body["cookie_looks_stale"] is True

    def test_an_older_gate_with_a_good_run_since_is_not_stale(self, client, monkeypatch):
        # The cookie was replaced and the next run worked. Still flagging it
        # would train the eye to ignore the flag.
        monkeypatch.setattr(nh, "dfs_scrape_runs", [
            {"at": "2026-11-19T08:00:00", "outcome": "ok", "scraped": 1889},
            {"at": "2026-11-18T19:33:00", "outcome": "gated", "error": "cookie"},
        ])
        body = admin_get(client, "/admin/dfs-salaries/runs").get_json()
        assert body["cookie_looks_stale"] is False

    def test_it_says_whether_a_cookie_is_configured_at_all(self, client, monkeypatch):
        monkeypatch.setattr(nh, "dfs_scrape_runs", [])
        monkeypatch.delenv("DFF_COOKIE", raising=False)
        assert admin_get(client, "/admin/dfs-salaries/runs").get_json()["cookie_configured"] is False

        monkeypatch.setenv("DFF_COOKIE", "sess=abc")
        assert admin_get(client, "/admin/dfs-salaries/runs").get_json()["cookie_configured"] is True

    def test_an_empty_history_is_not_an_error(self, client, monkeypatch):
        monkeypatch.setattr(nh, "dfs_scrape_runs", [])
        body = admin_get(client, "/admin/dfs-salaries/runs").get_json()
        assert body["runs"] == []
        assert body["last_ok"] is None
        assert body["cookie_looks_stale"] is False
