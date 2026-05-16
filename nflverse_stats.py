"""
nflverse_stats.py — nflverse data pipeline for NFL player/team statistics.

Downloads parquet files directly from nflverse GitHub releases (no local cache —
Koyeb has an ephemeral filesystem). All data is held in in-memory dicts that are
rebuilt on startup and refreshed weekly by the scheduler.
"""

import io
import logging
import datetime
import requests
import pandas as pd

logger = logging.getLogger(__name__)

NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
PLAYER_STATS_URL = f"{NFLVERSE_BASE}/player_stats/player_stats.parquet"
SCHEDULES_URL = f"{NFLVERSE_BASE}/schedules/games.parquet"

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K"}

# Columns summed for season totals (everything else is averaged)
SUM_COLS = {
    "completions", "attempts", "passing_yards", "passing_tds", "interceptions",
    "carries", "rushing_yards", "rushing_tds",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "fantasy_points", "fantasy_points_ppr",
}
AVG_COLS = {"target_share", "air_yards_share", "wopr", "racr"}
STAT_COLS = sorted(SUM_COLS | AVG_COLS)

# In-memory storage (populated by refresh_nflverse_data)
nflverse_player_stats: dict = {}   # sleeper_id → player dict
nflverse_team_stats: dict = {}     # team abbr → team stats dict
nflverse_schedule: dict = {}       # team abbr → most-recent-season game dict
nflverse_games: dict = {}          # week (int) → list of game dicts
nflverse_current_season: int | None = None
nflverse_last_updated: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fetch_parquet(url: str) -> pd.DataFrame:
    resp = requests.get(url, allow_redirects=True, timeout=60)
    resp.raise_for_status()
    return pd.read_parquet(io.BytesIO(resp.content))


def _roster_url(year: int) -> str:
    return f"{NFLVERSE_BASE}/rosters/roster_{year}.parquet"


def _safe_float(val) -> float:
    try:
        f = float(val)
        return 0.0 if f != f else f  # NaN → 0.0
    except (TypeError, ValueError):
        return 0.0


def _rolling_avg(weekly: list, n: int) -> dict:
    """Average of the last n weeks for each stat column."""
    subset = weekly[-n:]
    if not subset:
        return {}
    result = {}
    for col in STAT_COLS:
        vals = [w[col] for w in subset if col in w]
        result[col] = round(sum(vals) / len(vals), 2) if vals else 0.0
    return result


# ── ID map (gsis_id → sleeper_id) ───────────────────────────────────────────

def build_id_map(year: int = 2025) -> dict:
    """Download seasonal rosters parquet and return gsis_id → sleeper_id dict."""
    url = _roster_url(year)
    try:
        df = _fetch_parquet(url)
    except Exception:
        fallback = year - 1
        logger.warning("roster_%d unavailable, falling back to roster_%d", year, fallback)
        df = _fetch_parquet(_roster_url(fallback))

    id_map = {}
    for _, row in df.iterrows():
        gsis = row.get("gsis_id")
        sleeper = row.get("sleeper_id")
        if gsis and sleeper and pd.notna(gsis) and pd.notna(sleeper):
            try:
                id_map[str(gsis)] = str(int(float(sleeper)))
            except (ValueError, OverflowError):
                pass
    return id_map


# ── Player stats ─────────────────────────────────────────────────────────────

def build_player_stats_dict(df: pd.DataFrame, id_map: dict) -> dict:
    """
    Build nflverse_player_stats from the combined weekly player_stats DataFrame.
    Keyed by sleeper_id. Uses the most recent REG season available in the data.
    """
    reg = df[df["season_type"] == "REG"].copy()
    if reg.empty:
        logger.error("No REG season data in player_stats")
        return {}

    latest_season = int(reg["season"].max())
    reg = reg[reg["season"] == latest_season]
    reg = reg[reg["position"].isin(SKILL_POSITIONS)]

    result = {}
    for gsis_id, group in reg.groupby("player_id"):
        sleeper_id = id_map.get(str(gsis_id))
        if not sleeper_id:
            continue

        group_sorted = group.sort_values("week")
        first = group_sorted.iloc[0]

        weekly = []
        for _, row in group_sorted.iterrows():
            entry = {"week": int(row["week"])}
            for col in STAT_COLS:
                if col in row.index:
                    entry[col] = _safe_float(row[col])
            weekly.append(entry)

        season_totals: dict = {}
        for col in STAT_COLS:
            if col not in reg.columns:
                continue
            if col in SUM_COLS:
                season_totals[col] = round(_safe_float(group_sorted[col].sum()), 1)
            else:
                vals = [_safe_float(v) for v in group_sorted[col]]
                season_totals[col] = round(sum(vals) / len(vals), 3) if vals else 0.0
        season_totals["games_played"] = len(weekly)

        result[sleeper_id] = {
            "name": str(first.get("player_display_name", "") or ""),
            "position": str(first.get("position", "") or ""),
            "team": str(first.get("recent_team", "") or ""),
            "gsis_id": str(gsis_id),
            "season": latest_season,
            "headshot_url": str(first.get("headshot_url", "") or ""),
            "season_totals": season_totals,
            "weekly": weekly,
            "rolling_3": _rolling_avg(weekly, 3),
            "rolling_5": _rolling_avg(weekly, 5),
        }

    return result


# ── Team stats ───────────────────────────────────────────────────────────────

def build_team_stats_dict(df: pd.DataFrame) -> dict:
    """Compute per-game team aggregate stats for the most recent REG season."""
    reg = df[df["season_type"] == "REG"]
    latest_season = int(reg["season"].max())
    reg = reg[reg["season"] == latest_season]
    skill = reg[reg["position"].isin(SKILL_POSITIONS)]

    result = {}
    for team in skill["recent_team"].dropna().unique():
        team_df = skill[skill["recent_team"] == team]
        n_games = len(team_df["week"].unique())
        if n_games == 0:
            continue

        qb_df = team_df[team_df["position"] == "QB"]
        result[str(team)] = {
            "season": latest_season,
            "games_played": n_games,
            "targets_per_game": round(_safe_float(team_df["targets"].sum()) / n_games, 1),
            "pass_attempts_per_game": round(_safe_float(qb_df["attempts"].sum()) / n_games, 1),
            "rush_attempts_per_game": round(_safe_float(team_df["carries"].sum()) / n_games, 1),
            "ppr_points_per_game": round(
                _safe_float(team_df["fantasy_points_ppr"].sum()) / n_games, 1
            ),
        }
    return result


# ── Schedule ─────────────────────────────────────────────────────────────────

def build_schedule_dicts(df: pd.DataFrame) -> tuple:
    """
    Build (team_schedule, games_by_week) from the games DataFrame.

    team_schedule: team → most-recent-week game info (last entry in schedule data).
    games_by_week: week (int) → list of game dicts.
    """
    reg = df[df["game_type"] == "REG"].copy()
    if reg.empty:
        return {}, {}
    latest_season = int(reg["season"].max())
    reg = reg[reg["season"] == latest_season]

    games_by_week: dict = {}
    for _, row in reg.iterrows():
        week = int(row["week"])
        home_score = row.get("home_score")
        away_score = row.get("away_score")
        game = {
            "home_team": str(row["home_team"]),
            "away_team": str(row["away_team"]),
            "spread_line": _safe_float(row.get("spread_line")),
            "total_line": _safe_float(row.get("total_line")),
            "gameday": str(row.get("gameday", "") or ""),
            "home_score": None if pd.isna(home_score) else int(home_score),
            "away_score": None if pd.isna(away_score) else int(away_score),
        }
        games_by_week.setdefault(week, []).append(game)

    # team → most-recent available week game (iterate weeks in reverse)
    team_schedule: dict = {}
    for week in sorted(games_by_week.keys(), reverse=True):
        for game in games_by_week[week]:
            home, away = game["home_team"], game["away_team"]
            if home not in team_schedule:
                team_schedule[home] = {
                    "week": week,
                    "opponent": away,
                    "spread": game["spread_line"],
                    "total": game["total_line"],
                    "is_home": True,
                    "gameday": game["gameday"],
                    "home_score": game["home_score"],
                    "away_score": game["away_score"],
                }
            if away not in team_schedule:
                team_schedule[away] = {
                    "week": week,
                    "opponent": home,
                    "spread": -game["spread_line"],
                    "total": game["total_line"],
                    "is_home": False,
                    "gameday": game["gameday"],
                    "home_score": game["home_score"],
                    "away_score": game["away_score"],
                }

    return team_schedule, games_by_week


# ── Refresh orchestrator ──────────────────────────────────────────────────────

def refresh_nflverse_data():
    """Download and rebuild all nflverse in-memory data. Safe to call repeatedly."""
    global nflverse_player_stats, nflverse_team_stats
    global nflverse_schedule, nflverse_games
    global nflverse_current_season, nflverse_last_updated

    logger.info("nflverse: starting data refresh")
    print(f"{datetime.datetime.now()} - nflverse: starting data refresh")
    try:
        id_map = build_id_map(2025)
        logger.info("nflverse: id_map built (%d entries)", len(id_map))

        stats_df = _fetch_parquet(PLAYER_STATS_URL)
        logger.info("nflverse: player_stats downloaded (%d rows)", len(stats_df))

        games_df = _fetch_parquet(SCHEDULES_URL)
        logger.info("nflverse: schedule downloaded (%d rows)", len(games_df))

        player_stats = build_player_stats_dict(stats_df, id_map)
        team_stats = build_team_stats_dict(stats_df)
        schedule, games = build_schedule_dicts(games_df)

        reg = stats_df[stats_df["season_type"] == "REG"]
        current_season = int(reg["season"].max()) if not reg.empty else None

        nflverse_player_stats.clear()
        nflverse_player_stats.update(player_stats)
        nflverse_team_stats.clear()
        nflverse_team_stats.update(team_stats)
        nflverse_schedule.clear()
        nflverse_schedule.update(schedule)
        nflverse_games.clear()
        nflverse_games.update(games)
        nflverse_current_season = current_season
        nflverse_last_updated = datetime.datetime.utcnow().isoformat() + "Z"

        print(
            f"{datetime.datetime.now()} - nflverse: refresh complete "
            f"({len(nflverse_player_stats)} players, {len(nflverse_team_stats)} teams, "
            f"season={nflverse_current_season})"
        )
    except Exception:
        logger.exception("nflverse: refresh failed")


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_top_players(limit: int = 300, position: str = None, team: str = None) -> list:
    """Return players sorted by season fantasy_points_ppr (descending)."""
    players = list(nflverse_player_stats.values())
    if position:
        players = [p for p in players if p["position"] == position.upper()]
    if team:
        players = [p for p in players if p["team"] == team.upper()]
    players.sort(key=lambda p: p["season_totals"].get("fantasy_points_ppr", 0), reverse=True)
    return players[:limit]


def project_player(sleeper_id: str, week: int) -> dict:
    """
    Rolling-5 average projection with a light total-line adjustment.
    Adjustment: +/-1% per point the game total differs from the neutral baseline (44).
    Capped at ±15%.
    """
    player = nflverse_player_stats.get(str(sleeper_id))
    if not player:
        return {}

    rolling = player.get("rolling_5") or player.get("rolling_3") or {}
    base_proj = rolling.get("fantasy_points_ppr", 0.0)

    team = player.get("team", "")
    opp_info = nflverse_schedule.get(team, {})

    adj = 1.0
    if opp_info.get("week") == week and opp_info.get("total"):
        adj = max(0.85, min(1.15, 1.0 + (opp_info["total"] - 44) * 0.01))

    return {
        "sleeper_id": sleeper_id,
        "name": player["name"],
        "position": player["position"],
        "team": team,
        "projected_ppr": round(base_proj * adj, 2),
        "rolling_5_ppr": rolling.get("fantasy_points_ppr", 0.0),
        "adjustment_factor": round(adj, 3),
        "opponent": opp_info.get("opponent"),
        "spread": opp_info.get("spread"),
        "total": opp_info.get("total"),
    }
