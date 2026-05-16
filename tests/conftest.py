import importlib.util
import sys
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def _load_nfl_helper():
    mock_scheduler = MagicMock()
    with patch("apscheduler.schedulers.background.BackgroundScheduler", return_value=mock_scheduler):
        spec = importlib.util.spec_from_file_location(
            "nfl_helper",
            PROJECT_ROOT / "nfl-helper.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["nfl_helper"] = module
        spec.loader.exec_module(module)
    return module


nfl_helper = _load_nfl_helper()

GLOBAL_DICTS = [
    "all_players", "filtered_players", "scraped_ranks", "teams_data",
    "picks_data", "fantasy_points_data", "dfs_salaries_data",
    "tinyurl_data", "tournament_data",
]


@pytest.fixture(scope="session")
def flask_app():
    nfl_helper.app.config["TESTING"] = True
    return nfl_helper.app


@pytest.fixture
def client(flask_app):
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_globals():
    for name in GLOBAL_DICTS:
        getattr(nfl_helper, name).clear()
    with patch.object(nfl_helper, "save_tinyurl_data"), \
         patch.object(nfl_helper, "save_tournament_data"):
        yield
    for name in GLOBAL_DICTS:
        getattr(nfl_helper, name).clear()


def make_lineup_string(week: int, player_entries: list) -> str:
    """Build a lineup data string the backend can decode.
    player_entries: list like ["12345:QB", "67890:RB"]
    """
    content = ",".join(player_entries)
    encoded = base64.b64encode(content.encode()).decode()
    return f"{week}|{encoded}"


def create_entry(name="testleague", week=8, allowed_names=None, entry_type="single",
                 num_weeks=None, start_week=None):
    """Directly insert a tinyurl_data entry, bypassing the HTTP layer."""
    import datetime
    normalized = nfl_helper.normalize_tinyurl_name(name)
    entry = {
        "name": name,
        "week": week,
        "type": entry_type,
        "allowed_names": allowed_names or ["alice", "bob"],
        "user_submissions": {},
        "data": None,
        "created_at": datetime.datetime.now().isoformat(),
    }
    if entry_type == "multiweek_dfs":
        entry["standings"] = {}
        if num_weeks is not None:
            entry["num_weeks"] = num_weeks
        if start_week is not None:
            entry["start_week"] = start_week
    nfl_helper.tinyurl_data[normalized] = entry
    return normalized
