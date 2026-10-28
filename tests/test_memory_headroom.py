"""
The things keeping this process inside its 512 MB.

Every assertion here is about memory rather than output, which is why they read
oddly: a scrape is checked for what it does *not* still hold, and a scheduler
for what it has *not* started. All of it exists because the instance reached
490 MB and was killed.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

nfl_helper = sys.modules["nfl_helper"]

import get_dynasty_ranks


# ── KTC: one page's soup at a time, and one format's rows at a time ──────────

def ranking_page(rows):
    """A KeepTradeCut rankings page holding the given (name, rank, value) rows."""
    body = "".join(
        f'<div class="onePlayer">'
        f'<p class="player-name">{name}</p>'
        f'<p class="position">{rank}</p>'
        f'<p class="value">{value}</p>'
        f'<p class="position hidden-xs">24.5y</p>'
        f'</div>'
        for name, rank, value in rows
    )
    return f"<html><body>{body}</body></html>".encode()


class FakeKTC:
    """Serves one page per format and empties the rest, counting the requests."""

    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def __call__(self, url, *args, **kwargs):
        self.urls.append(url)
        page = int(url.split("page=")[1].split("&")[0])
        format = int(url.split("format=")[1].split("&")[0])
        body = self.pages.get(format, b"") if page == 0 else b""
        return MagicMock(content=body or b"<html></html>")


@pytest.fixture
def fake_ktc(monkeypatch):
    def install(pages):
        fake = FakeKTC(pages)
        monkeypatch.setattr(get_dynasty_ranks.requests, "get", fake)
        monkeypatch.setattr(get_dynasty_ranks, "tqdm", lambda it, **kw: it)
        return fake

    return install


class TestRankingRowsHoldText:
    def test_rows_come_back_as_plain_strings(self):
        """
        Not BeautifulSoup Tags. A Tag keeps a reference to its whole document,
        so a list of them across ten pages pinned ten parsed pages — about
        59 MB, and twice that once the Superflex pass had run.
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(ranking_page([("Bijan RobinsonATL", "RB1", "9500")]),
                             "html.parser")
        row = get_dynasty_ranks._ranking_row_text(soup.find(class_="onePlayer"))

        assert row == {"name": "Bijan RobinsonATL", "position_rank": "RB1",
                       "value": "9500", "age": "24.5y"}
        assert all(v is None or type(v) is str for v in row.values())

    def test_a_row_with_no_age_shown_reads_as_none(self):
        from bs4 import BeautifulSoup
        html = ('<div class="onePlayer"><p class="player-name">2029 Late 1stFA</p>'
                '<p class="position">PI</p><p class="value">4544</p></div>')
        row = get_dynasty_ranks._ranking_row_text(
            BeautifulSoup(html, "html.parser").find(class_="onePlayer"))

        assert row["age"] is None
        assert row["value"] == "4544"
        assert row["name"] == "2029 Late 1stFA"


class TestEachFormatReadsOnlyItsOwnRows:
    def test_a_player_missing_from_superflex_keeps_an_empty_sf_value(self, fake_ktc):
        """
        The two passes used to share one list, which was never emptied, so the
        Superflex pass read the 1QB rows a second time and wrote 1QB numbers
        into SFValue. One row in a live run: "2029 Late 1st".
        """
        fake_ktc({
            1: ranking_page([("Bijan RobinsonATL", "RB1", "9500"),
                             ("2029 Late 1stFA", "PI", "4544")]),
            0: ranking_page([("Bijan RobinsonATL", "RB2", "8800")]),
        })

        players = {p["Player Name"]: p for p in get_dynasty_ranks.scrape_ktc()}

        assert players["Bijan Robinson"]["Value"] == 9500
        assert players["Bijan Robinson"]["SFValue"] == 8800
        # Absent from the Superflex rankings, so there is no Superflex value to
        # report. Both readers fall back to Value when this is 0.
        assert players["2029 Late 1st"]["SFValue"] == 0

    def test_both_formats_are_fetched_page_by_page(self, fake_ktc):
        fake = fake_ktc({1: ranking_page([("Bijan RobinsonATL", "RB1", "9500")]),
                         0: ranking_page([("Bijan RobinsonATL", "RB2", "8800")])})

        get_dynasty_ranks.scrape_ktc()

        assert len(fake.urls) == 20, "ten pages of each format, one request each"


# ── Handing the heap back ────────────────────────────────────────────────────

class TestReleaseAfter:
    def test_the_heap_is_released_when_the_job_finishes(self):
        calls = []
        with patch.object(nfl_helper, "release_free_memory",
                          lambda: calls.append("released")):
            nfl_helper._release_after(lambda: calls.append("ran"))()

        assert calls == ["ran", "released"]

    def test_it_is_released_even_when_the_job_raises(self):
        """A job that failed half way through has still allocated everything
        it got to."""
        calls = []

        def boom():
            calls.append("ran")
            raise RuntimeError("scrape failed")

        with patch.object(nfl_helper, "release_free_memory",
                          lambda: calls.append("released")):
            with pytest.raises(RuntimeError):
                nfl_helper._release_after(boom)()

        assert calls == ["ran", "released"]

    def test_the_wrapped_job_keeps_its_name(self):
        """The logs and the staggering test both read the job by name."""
        def update_dfs_salaries_data():
            pass

        assert nfl_helper._release_after(
            update_dfs_salaries_data).__name__ == "update_dfs_salaries_data"

    @pytest.mark.parametrize("name", sorted({
        "fetch_and_filter_data",
        "update_filtered_players_with_scraped_data",
        "update_fantasy_points_data",
        "update_dfs_salaries_data",
        "_refresh_odds",
        "_snapshot_odds",
    }))
    def test_every_heavy_scheduled_job_releases_afterwards(self, name):
        registered = [c.kwargs["func"] for c in nfl_helper.scheduler.add_job.call_args_list
                      if c.kwargs["func"].__name__ == name]
        assert registered, f"{name} is not registered with the scheduler"
        for func in registered:
            assert hasattr(func, "__wrapped__"), (
                f"{name} runs without releasing the heap afterwards")

    def test_the_nflverse_refresh_releases_afterwards(self):
        """Its own named wrapper, predating the decorator, and still the only
        job that has to release before the next step rather than after."""
        funcs = {c.kwargs["func"].__name__
                 for c in nfl_helper.scheduler.add_job.call_args_list}
        assert "_refresh_nflverse_and_release" in funcs


# ── The scheduler waits for initialisation ───────────────────────────────────

class TestTheSchedulerWaitsForInitialisation:
    def test_importing_the_module_does_not_start_it(self):
        """
        Initialisation runs the same heavy functions the jobs do, on a plain
        thread the scheduler cannot see, so a boot at 14:58 had the 15:00 DFS
        scrape allocating beside initialisation's own.
        """
        assert not nfl_helper.scheduler.start.called

    def test_initialisation_starts_it_even_if_it_fails(self):
        """A process with no scheduler quietly serves whatever it managed to
        load until somebody restarts it."""
        started = []
        with patch.object(nfl_helper, "start_scheduler", lambda: started.append(True)), \
             patch.object(nfl_helper, "load_tinyurl_data", side_effect=RuntimeError("gist down")), \
             patch("threading.Thread") as thread:
            nfl_helper.initialize_data_in_background()
            initialise = thread.call_args.kwargs["target"]
            with pytest.raises(RuntimeError):
                initialise()

        assert started == [True]

    def test_one_worker_so_heavy_jobs_queue_instead_of_overlapping(self):
        """
        The default is ten, and then only the choice of cron hours stands
        between two ~190 MB transients and the OOM killer.
        """
        from apscheduler.schedulers.background import BackgroundScheduler
        import inspect

        source = inspect.getsource(sys.modules["nfl_helper"])
        assert "ThreadPoolExecutor(1)" in source
        # Queueing is only safe with the grace time raised: it defaults to one
        # second, so a job held behind a long refresh is dropped as a misfire.
        assert '"misfire_grace_time": 3600' in source


# ── Reporting ────────────────────────────────────────────────────────────────

class TestRSSReporting:
    def test_it_reads_the_resident_set_from_statm(self, tmp_path):
        import builtins
        statm = tmp_path / "statm"
        # size resident shared text lib data dt — resident is the second field
        statm.write_text("30000 25600 1000 1 0 20000 0\n")
        real_open = builtins.open

        with patch.object(builtins, "open",
                          lambda f, *a, **k: real_open(statm if f == "/proc/self/statm" else f, *a, **k)):
            with patch("os.sysconf", return_value=4096):
                assert nfl_helper.process_rss_mb() == 100.0

    def test_it_is_none_where_there_is_no_statm(self):
        """macOS, which is where this is developed and not where it runs out
        of memory."""
        with patch("builtins.open", side_effect=FileNotFoundError):
            assert nfl_helper.process_rss_mb() is None

    def test_statistics_reports_it_against_the_limit(self, client):
        response = client.get("/statistics")
        assert response.status_code == 200
        body = response.get_json()
        assert "rss_mb" in body, "nothing reported memory, which is why a climb to 490 MB was invisible"
        assert body["memory_limit_mb"] == 512


class TestMallocArenas:
    def test_an_environment_setting_wins(self):
        """It is applied before the process starts, which is earlier than
        anything here can manage."""
        with patch.dict("os.environ", {"MALLOC_ARENA_MAX": "2"}):
            assert nfl_helper.limit_malloc_arenas() is None

    def test_it_is_harmless_where_there_is_no_mallopt(self):
        libc = MagicMock(spec=[])  # no mallopt attribute
        with patch.dict("os.environ", {}, clear=False), \
             patch("ctypes.CDLL", return_value=libc), \
             patch("ctypes.util.find_library", return_value="libc.so.6"):
            import os
            os.environ.pop("MALLOC_ARENA_MAX", None)
            assert nfl_helper.limit_malloc_arenas() is None
