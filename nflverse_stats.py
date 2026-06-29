"""
nflverse_stats.py — nflverse data pipeline using nflreadpy.

All data is held in in-memory dicts, rebuilt on startup and refreshed weekly.
No local files — Koyeb has an ephemeral filesystem.
"""

import gc
import logging
import datetime
import pandas as pd
import nflreadpy as nfl

logger = logging.getLogger(__name__)

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K"}

SUM_COLS = {
    "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
    "carries", "rushing_yards", "rushing_tds",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "receiving_air_yards", "passing_air_yards",
    "fantasy_points", "fantasy_points_half_ppr", "fantasy_points_ppr",
}
AVG_COLS = {
    "target_share", "air_yards_share", "wopr", "racr",
    "passing_epa", "rushing_epa",
}
STAT_COLS = sorted(SUM_COLS | AVG_COLS)

# ── In-memory storage ─────────────────────────────────────────────────────────

nflverse_player_stats: dict = {}    # sleeper_id → core player stats
nflverse_player_advanced: dict = {} # sleeper_id → snap% + expected points
nflverse_team_stats: dict = {}      # team abbr → offensive + defensive aggregates
nflverse_schedule: dict = {}        # team abbr → most-recent-week game info
nflverse_games: dict = {}           # week (int) → list of game dicts
nflverse_current_season: int | None = None
nflverse_last_updated: str | None = None


# ── Season detection ──────────────────────────────────────────────────────────

def _current_nfl_season() -> int:
    """
    Return the active NFL season year.
    Season runs September–January, so before September we're in the off-season
    of the prior year's season.
      May 2026  → 2025 (2025 season just ended)
      Oct 2026  → 2026 (2026 season in progress)
      Jan 2027  → 2026 (2026 playoffs)
    """
    now = datetime.datetime.utcnow()
    return now.year - 1 if now.month < 9 else now.year


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(val) -> float:
    try:
        f = float(val)
        return 0.0 if f != f else f  # NaN → 0.0
    except (TypeError, ValueError):
        return 0.0


def _rolling_avg(weekly: list, n: int) -> dict:
    subset = weekly[-n:]
    if not subset:
        return {}
    result = {}
    for col in STAT_COLS:
        vals = [w[col] for w in subset if col in w]
        result[col] = round(sum(vals) / len(vals), 2) if vals else 0.0
    return result


# ── ID maps ───────────────────────────────────────────────────────────────────

def build_id_maps(season: int) -> tuple[dict, dict]:
    """
    Build two ID maps from nflverse rosters:
      gsis_map: gsis_id  → sleeper_id  (used for player_stats, ff_opportunity)
      pfr_map:  pfr_id   → sleeper_id  (used for snap_counts)
    Falls back to season-1 if the requested season isn't published yet.
    """
    _ROSTER_COLS = {"week", "gsis_id", "sleeper_id", "pfr_id"}
    try:
        pl_df = nfl.load_rosters([season])
        df = pl_df.select([c for c in _ROSTER_COLS if c in pl_df.columns]).to_pandas()
        del pl_df
    except Exception:
        logger.warning("rosters %d unavailable, falling back to %d", season, season - 1)
        pl_df = nfl.load_rosters([season - 1])
        df = pl_df.select([c for c in _ROSTER_COLS if c in pl_df.columns]).to_pandas()
        del pl_df

    # One row per player per week — keep the most recent entry per gsis_id
    df = df.sort_values("week").drop_duplicates("gsis_id", keep="last")

    gsis_map, pfr_map = {}, {}
    for _, row in df.iterrows():
        sleeper = row.get("sleeper_id")
        if not sleeper or pd.isna(sleeper):
            continue
        try:
            sleeper_str = str(int(float(sleeper)))
        except (ValueError, OverflowError):
            continue

        gsis = row.get("gsis_id")
        if gsis and pd.notna(gsis):
            gsis_map[str(gsis)] = sleeper_str

        pfr = row.get("pfr_id")
        if pfr and pd.notna(pfr):
            pfr_map[str(pfr)] = sleeper_str

    return gsis_map, pfr_map


# ── Core player stats ─────────────────────────────────────────────────────────

def build_player_stats_dict(df: pd.DataFrame, gsis_map: dict) -> dict:
    """
    Build nflverse_player_stats from a player_stats DataFrame.
    Filters to REG season, most recent year, skill positions only.
    Keyed by sleeper_id.
    """
    reg = df[df["season_type"] == "REG"].copy()
    if reg.empty:
        logger.error("No REG season data in player_stats")
        return {}

    latest_season = int(reg["season"].max())
    reg = reg[(reg["season"] == latest_season) & reg["position"].isin(SKILL_POSITIONS)]

    result = {}
    team_col = "team" if "team" in reg.columns else "recent_team"

    for gsis_id, group in reg.groupby("player_id"):
        sleeper_id = gsis_map.get(str(gsis_id))
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
            "team": str(first.get(team_col, "") or ""),
            "gsis_id": str(gsis_id),
            "season": latest_season,
            "headshot_url": str(first.get("headshot_url", "") or ""),
            "season_totals": season_totals,
            "weekly": weekly,
            "rolling_3": _rolling_avg(weekly, 3),
            "rolling_5": _rolling_avg(weekly, 5),
        }

    return result


# ── Advanced player stats (snap% + expected points) ──────────────────────────

def build_player_advanced_dict(
    snap_df: pd.DataFrame,
    opp_df: pd.DataFrame,
    gsis_map: dict,
    pfr_map: dict,
) -> dict:
    """
    Build nflverse_player_advanced keyed by sleeper_id.

    snap_df:  from load_snap_counts()  — offense_pct per week, keyed by pfr_player_id
    opp_df:   from load_ff_opportunity() — expected vs actual FP per week, keyed by player_id (gsis)
    """
    # week_data[sleeper_id][week] = partial dict, merged from both sources
    week_data: dict[str, dict[int, dict]] = {}

    # ── Snap counts ──
    reg_snaps = snap_df[snap_df["game_type"] == "REG"] if "game_type" in snap_df.columns else snap_df
    if "pfr_player_id" not in reg_snaps.columns:
        reg_snaps = pd.DataFrame()
    for pfr_id, group in (reg_snaps.groupby("pfr_player_id") if not reg_snaps.empty else []):
        sleeper_id = pfr_map.get(str(pfr_id))
        if not sleeper_id:
            continue
        week_data.setdefault(sleeper_id, {})
        for _, row in group.iterrows():
            week = int(row["week"])
            week_data[sleeper_id].setdefault(week, {})
            week_data[sleeper_id][week]["snap_pct"] = round(_safe_float(row.get("offense_pct")), 3)

    # ── FF opportunity (expected vs actual fantasy points) ──
    if "player_id" not in opp_df.columns:
        opp_df = pd.DataFrame()
    for gsis_id, group in (opp_df.groupby("player_id") if not opp_df.empty else []):
        sleeper_id = gsis_map.get(str(gsis_id))
        if not sleeper_id:
            continue
        week_data.setdefault(sleeper_id, {})
        for _, row in group.dropna(subset=["week"]).iterrows():
            week = int(row["week"])
            week_data[sleeper_id].setdefault(week, {})
            week_data[sleeper_id][week].update({
                "expected_fp": round(_safe_float(row.get("total_fantasy_points_exp")), 2),
                "actual_fp":   round(_safe_float(row.get("total_fantasy_points")), 2),
                "fp_diff":     round(_safe_float(row.get("total_fantasy_points_diff")), 2),
            })

    # ── Assemble final dict ──
    result = {}
    for sleeper_id, weeks in week_data.items():
        weekly = [{"week": w, **data} for w, data in sorted(weeks.items())]

        snap_vals = [w["snap_pct"] for w in weekly if "snap_pct" in w]
        exp_vals  = [w["expected_fp"] for w in weekly if "expected_fp" in w]
        diff_vals = [w["fp_diff"] for w in weekly if "fp_diff" in w]

        result[sleeper_id] = {
            "snap_pct_avg":    round(sum(snap_vals) / len(snap_vals), 3) if snap_vals else None,
            "expected_fp_avg": round(sum(exp_vals)  / len(exp_vals),  2) if exp_vals  else None,
            "fp_diff_avg":     round(sum(diff_vals) / len(diff_vals), 2) if diff_vals else None,
            "weekly": weekly,
        }

    return result


# ── Team stats (offense + defense) ───────────────────────────────────────────

def build_team_stats_dict(df: pd.DataFrame, player_df: pd.DataFrame, schedule_df: pd.DataFrame | None = None) -> dict:
    """
    Build nflverse_team_stats from the team_stats DataFrame.

    Each row is one team's stats for one game (their offense + their defensive
    counting stats). Defensive allowed stats are derived by flipping perspective:
    how opponents performed when playing against team X.

    Fantasy points allowed per position use player_df (1 PPR = fantasy_points_ppr).
    Real points scored/allowed use schedule_df (home_score/away_score per game).
    """
    reg = df[df["season_type"] == "REG"].copy()
    if reg.empty:
        return {}

    latest_season = int(reg["season"].max())
    reg = reg[reg["season"] == latest_season]

    # Player-level: REG rows with opponent_team, for def fpts allowed by position
    p_reg = player_df[
        (player_df["season_type"] == "REG") &
        (player_df["season"] == latest_season) &
        (player_df["position"].isin(SKILL_POSITIONS))
    ].copy()
    if "opponent_team" not in p_reg.columns:
        p_reg["opponent_team"] = None

    # Per-week fpts allowed per (defending_team, position): used for season avg + rolling
    def_weekly = (
        p_reg.groupby(["opponent_team", "week", "position"])["fantasy_points_ppr"]
        .sum()
        .reset_index()
        .rename(columns={"opponent_team": "def_team", "fantasy_points_ppr": "fpts"})
    )

    def _def_season(team: str, pos: str, n_games: int) -> float:
        rows = def_weekly[(def_weekly["def_team"] == team) & (def_weekly["position"] == pos)]
        if rows.empty or n_games == 0:
            return 0.0
        return round(_safe_float(rows["fpts"].sum()) / n_games, 1)

    def _def_rolling(team: str, pos: str, n: int) -> float:
        rows = (
            def_weekly[(def_weekly["def_team"] == team) & (def_weekly["position"] == pos)]
            .sort_values("week")
            .tail(n)
        )
        if rows.empty:
            return 0.0
        return round(_safe_float(rows["fpts"].mean()), 1)

    # Aggregate key offensive stats per (team, week) from player_df — column names
    # are guaranteed correct here (same source as player stats endpoints).
    p_team_col = "team" if "team" in p_reg.columns else "recent_team"
    _src_cols = [c for c in ["passing_yards", "rushing_yards", "attempts", "carries", "fantasy_points_ppr"] if c in p_reg.columns]
    _off_avgs: dict[str, dict] = {}
    if _src_cols and p_team_col in p_reg.columns:
        _wk = p_reg.groupby([p_team_col, "week"])[_src_cols].sum().reset_index()
        for _t, _grp in _wk.groupby(p_team_col):
            _off_avgs[str(_t)] = {c: round(_safe_float(_grp[c].mean()), 1) for c in _src_cols}

    # Build per-team points scored and allowed from schedule (regular season, completed games)
    _pts_for: dict[str, list[int]] = {}      # team → list of points scored per game (chronological)
    _pts_against: dict[str, list[int]] = {}  # team → list of points allowed per game (chronological)
    if schedule_df is not None and not schedule_df.empty:
        sched_reg = schedule_df[schedule_df["game_type"] == "REG"].copy()
        sched_reg = sched_reg[sched_reg["season"] == int(reg["season"].max())]
        sched_reg = sched_reg.dropna(subset=["home_score", "away_score"])
        sched_reg = sched_reg.sort_values("week")
        for _, row in sched_reg.iterrows():
            h, a = str(row["home_team"]), str(row["away_team"])
            hs, as_ = int(row["home_score"]), int(row["away_score"])
            _pts_for.setdefault(h, []).append(hs)
            _pts_against.setdefault(h, []).append(as_)
            _pts_for.setdefault(a, []).append(as_)
            _pts_against.setdefault(a, []).append(hs)

    def _score_avg(team: str, data: dict) -> float:
        vals = data.get(team, [])
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    def _score_rolling(team: str, data: dict, n: int) -> float:
        vals = data.get(team, [])[-n:]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    all_teams = set(reg["team"].dropna()) | set(reg["opponent_team"].dropna())
    result = {}

    for team in all_teams:
        team = str(team)
        off = reg[reg["team"] == team]
        opp = reg[reg["opponent_team"] == team]

        n_games = len(off["week"].unique())
        if n_games == 0:
            continue

        def _pg(series, n=n_games):
            return round(_safe_float(series.sum()) / n, 1)

        def _pg2(series, n=n_games):
            return round(_safe_float(series.sum()) / n, 2)

        ta = _off_avgs.get(team, {})

        result[team] = {
            "season": latest_season,
            "games_played": n_games,
            # ── Offense ──
            "pass_attempts_per_game":   ta.get("attempts", 0.0),
            "rush_attempts_per_game":   ta.get("carries", 0.0),
            "plays_per_game":           round(ta.get("attempts", 0.0) + ta.get("carries", 0.0), 1),
            "targets_per_game":         _pg(off["targets"]),
            "passing_yards_per_game":   ta.get("passing_yards", 0.0),
            "rushing_yards_per_game":   ta.get("rushing_yards", 0.0),
            "fpts_per_game":            ta.get("fantasy_points_ppr", 0.0),
            "points_per_game":          _score_avg(team, _pts_for),
            "points_allowed_per_game":  _score_avg(team, _pts_against),
            "points_rolling3":          _score_rolling(team, _pts_for, 3),
            "points_rolling5":          _score_rolling(team, _pts_for, 5),
            "points_allowed_rolling3":  _score_rolling(team, _pts_against, 3),
            "points_allowed_rolling5":  _score_rolling(team, _pts_against, 5),
            "passing_tds_per_game":     _pg2(off["passing_tds"]),
            "rushing_tds_per_game":     _pg2(off["rushing_tds"]),
            "passing_epa_per_game":     _pg2(off["passing_epa"]),
            "rushing_epa_per_game":     _pg2(off["rushing_epa"]),
            # ── Defense (yardage / td / pressure) ──
            "def_pass_yards_allowed_per_game":  _pg(opp["passing_yards"]),
            "def_rush_yards_allowed_per_game":  _pg(opp["rushing_yards"]),
            "def_pass_tds_allowed_per_game":    _pg2(opp["passing_tds"]),
            "def_rush_tds_allowed_per_game":    _pg2(opp["rushing_tds"]),
            "def_targets_allowed_per_game":     _pg(opp["targets"]),
            "def_sacks_per_game":               _pg2(off["def_sacks"]),
            "def_interceptions_per_game":       _pg2(off["def_interceptions"]),
            "def_pass_defended_per_game":       _pg2(off["def_pass_defended"]),
            # ── Defense: fantasy points allowed per position (1 PPR) ──
            "def_fpts_allowed_qb_per_game": _def_season(team, "QB", n_games),
            "def_fpts_allowed_rb_per_game": _def_season(team, "RB", n_games),
            "def_fpts_allowed_wr_per_game": _def_season(team, "WR", n_games),
            "def_fpts_allowed_te_per_game": _def_season(team, "TE", n_games),
            "def_fpts_allowed_rolling3": {
                "qb": _def_rolling(team, "QB", 3),
                "rb": _def_rolling(team, "RB", 3),
                "wr": _def_rolling(team, "WR", 3),
                "te": _def_rolling(team, "TE", 3),
            },
            "def_fpts_allowed_rolling5": {
                "qb": _def_rolling(team, "QB", 5),
                "rb": _def_rolling(team, "RB", 5),
                "wr": _def_rolling(team, "WR", 5),
                "te": _def_rolling(team, "TE", 5),
            },
        }

    # Second pass: rank all teams per position (rank 1 = fewest fpts allowed = best defense)
    for pos in ("qb", "rb", "wr", "te"):
        season_field = f"def_fpts_allowed_{pos}_per_game"
        r5_field     = f"def_fpts_allowed_rolling5"

        sorted_season = sorted(result.items(), key=lambda x: x[1].get(season_field, 0))
        sorted_r5     = sorted(result.items(), key=lambda x: (x[1].get(r5_field) or {}).get(pos, 0))

        for rank, (team, _) in enumerate(sorted_season, 1):
            result[team].setdefault("def_rank_vs_position", {"season": {}, "rolling5": {}})
            result[team]["def_rank_vs_position"]["season"][pos] = rank

        for rank, (team, _) in enumerate(sorted_r5, 1):
            result[team].setdefault("def_rank_vs_position", {"season": {}, "rolling5": {}})
            result[team]["def_rank_vs_position"]["rolling5"][pos] = rank

    return result


# ── Schedule ─────────────────────────────────────────────────────────────────

def build_schedule_dicts(df: pd.DataFrame) -> tuple:
    """Build (team_schedule, games_by_week) from a schedules DataFrame."""
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
            "home_team":   str(row["home_team"]),
            "away_team":   str(row["away_team"]),
            "spread_line": _safe_float(row.get("spread_line")),
            "total_line":  _safe_float(row.get("total_line")),
            "gameday":     str(row.get("gameday", "") or ""),
            "gametime":    str(row.get("gametime", "") or ""),
            "roof":        str(row.get("roof", "") or ""),
            "surface":     str(row.get("surface", "") or ""),
            "temp":        None if pd.isna(row.get("temp")) else float(row["temp"]),
            "wind":        None if pd.isna(row.get("wind")) else float(row["wind"]),
            "home_score":  None if pd.isna(home_score) else int(home_score),
            "away_score":  None if pd.isna(away_score) else int(away_score),
            "home_moneyline": None if pd.isna(row.get("home_moneyline")) else float(row["home_moneyline"]),
            "away_moneyline": None if pd.isna(row.get("away_moneyline")) else float(row["away_moneyline"]),
            "home_qb":     str(row.get("home_qb_name", "") or ""),
            "away_qb":     str(row.get("away_qb_name", "") or ""),
        }
        games_by_week.setdefault(week, []).append(game)

    # team → most-recent-week game (iterate weeks in reverse so first hit wins)
    team_schedule: dict = {}
    for week in sorted(games_by_week.keys(), reverse=True):
        for game in games_by_week[week]:
            home, away = game["home_team"], game["away_team"]
            if home not in team_schedule:
                team_schedule[home] = {
                    "week": week, "opponent": away,
                    "spread": game["spread_line"], "total": game["total_line"],
                    "is_home": True, "gameday": game["gameday"],
                    "home_score": game["home_score"], "away_score": game["away_score"],
                }
            if away not in team_schedule:
                team_schedule[away] = {
                    "week": week, "opponent": home,
                    "spread": -game["spread_line"], "total": game["total_line"],
                    "is_home": False, "gameday": game["gameday"],
                    "home_score": game["home_score"], "away_score": game["away_score"],
                }

    return team_schedule, games_by_week


# ── Refresh orchestrator ──────────────────────────────────────────────────────

def refresh_nflverse_data():
    """Download and rebuild all nflverse in-memory data. Safe to call repeatedly."""
    global nflverse_player_stats, nflverse_player_advanced, nflverse_team_stats
    global nflverse_schedule, nflverse_games
    global nflverse_current_season, nflverse_last_updated

    season = _current_nfl_season()
    print(f"{datetime.datetime.now()} - nflverse: refreshing season {season}")
    logger.info("nflverse: refreshing season %d", season)

    try:
        # 1. ID maps — load rosters, build maps, free immediately
        gsis_map, pfr_map = build_id_maps(season)
        gc.collect()
        logger.info("nflverse: id maps built (gsis=%d, pfr=%d)", len(gsis_map), len(pfr_map))

        # 2. Player stats — keep in memory until team_stats is built (used by both)
        _PLAYER_COLS = list({
            "season_type", "season", "position", "player_id", "week",
            "player_display_name", "team", "recent_team", "headshot_url",
            "opponent_team",
        } | SUM_COLS | AVG_COLS)
        pl_df = nfl.load_player_stats([season])
        stats_df = pl_df.select([c for c in _PLAYER_COLS if c in pl_df.columns]).to_pandas()
        del pl_df; gc.collect()
        logger.info("nflverse: player_stats loaded (%d rows)", len(stats_df))

        player_stats = build_player_stats_dict(stats_df, gsis_map)

        # 3. Snap counts — load, build partial advanced, free
        _SNAP_COLS = ["game_type", "pfr_player_id", "week", "offense_pct"]
        pl_snap = nfl.load_snap_counts([season])
        snap_df = pl_snap.select([c for c in _SNAP_COLS if c in pl_snap.columns]).to_pandas()
        del pl_snap; gc.collect()
        logger.info("nflverse: snap_counts loaded (%d rows)", len(snap_df))

        # 4. FF opportunity — load, build advanced, free both
        _OPP_COLS = ["player_id", "week", "total_fantasy_points_exp",
                     "total_fantasy_points", "total_fantasy_points_diff"]
        pl_opp = nfl.load_ff_opportunity([season])
        opp_df = pl_opp.select([c for c in _OPP_COLS if c in pl_opp.columns]).to_pandas()
        del pl_opp; gc.collect()
        logger.info("nflverse: ff_opportunity loaded (%d rows)", len(opp_df))

        player_advanced = build_player_advanced_dict(snap_df, opp_df, gsis_map, pfr_map)
        del snap_df, opp_df; gc.collect()

        # 5. Team stats — load, build, free
        _TEAM_COLS = [
            "season_type", "season", "team", "opponent_team", "week",
            "targets", "passing_yards", "rushing_yards", "passing_tds", "rushing_tds",
            "passing_epa", "rushing_epa", "def_sacks", "def_interceptions", "def_pass_defended",
        ]
        pl_team = nfl.load_team_stats([season])
        team_df = pl_team.select([c for c in _TEAM_COLS if c in pl_team.columns]).to_pandas()
        del pl_team; gc.collect()
        logger.info("nflverse: team_stats loaded (%d rows)", len(team_df))

        # 6. Schedules — load, build dicts, free
        _SCHED_COLS = [
            "game_type", "season", "week", "home_team", "away_team",
            "spread_line", "total_line", "gameday", "gametime", "roof", "surface",
            "temp", "wind", "home_score", "away_score",
            "home_moneyline", "away_moneyline", "home_qb_name", "away_qb_name",
        ]
        pl_sched = nfl.load_schedules([season])
        schedule_df = pl_sched.select([c for c in _SCHED_COLS if c in pl_sched.columns]).to_pandas()
        del pl_sched; gc.collect()
        logger.info("nflverse: schedules loaded (%d rows)", len(schedule_df))

        team_stats      = build_team_stats_dict(team_df, stats_df, schedule_df)
        schedule, games = build_schedule_dicts(schedule_df)

        reg = stats_df[stats_df["season_type"] == "REG"]
        current_season = int(reg["season"].max()) if not reg.empty else season

        del team_df, stats_df, schedule_df; gc.collect()

        nflverse_player_stats.clear();    nflverse_player_stats.update(player_stats)
        nflverse_player_advanced.clear(); nflverse_player_advanced.update(player_advanced)
        nflverse_team_stats.clear();      nflverse_team_stats.update(team_stats)
        nflverse_schedule.clear();        nflverse_schedule.update(schedule)
        nflverse_games.clear();           nflverse_games.update(games)
        nflverse_current_season = current_season
        nflverse_last_updated   = datetime.datetime.utcnow().isoformat() + "Z"

        print(
            f"{datetime.datetime.now()} - nflverse: done — "
            f"{len(player_stats)} players, {len(player_advanced)} advanced, "
            f"{len(team_stats)} teams, season={current_season}"
        )
    except Exception:
        logger.exception("nflverse: refresh failed")


# ── Query helpers ─────────────────────────────────────────────────────────────

_POS_DEF_KEY = {"QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "K": None}

def _matchup_block(team: str, position: str) -> dict:
    """
    Return schedule + opponent defensive fpts allowed for the player's position.
    All data is in-memory so this is a simple dict lookup.
    """
    opp_info = nflverse_schedule.get(team, {})
    opponent = opp_info.get("opponent")
    pos_key  = _POS_DEF_KEY.get(position)

    def_stats = nflverse_team_stats.get(opponent, {}) if opponent else {}

    ranks = def_stats.get("def_rank_vs_position", {})

    if pos_key:
        def_fpts_season   = def_stats.get(f"def_fpts_allowed_{pos_key}_per_game")
        def_fpts_rolling3 = (def_stats.get("def_fpts_allowed_rolling3") or {}).get(pos_key)
        def_fpts_rolling5 = (def_stats.get("def_fpts_allowed_rolling5") or {}).get(pos_key)
        opponent_rank_season  = (ranks.get("season")  or {}).get(pos_key)
        opponent_rank_rolling5 = (ranks.get("rolling5") or {}).get(pos_key)
    else:
        def_fpts_season = def_fpts_rolling3 = def_fpts_rolling5 = None
        opponent_rank_season = opponent_rank_rolling5 = None

    return {
        "week":                    opp_info.get("week"),
        "opponent":                opponent,
        "is_home":                 opp_info.get("is_home"),
        "spread":                  opp_info.get("spread"),
        "total":                   opp_info.get("total"),
        "def_fpts_allowed_season":  def_fpts_season,
        "def_fpts_allowed_rolling3": def_fpts_rolling3,
        "def_fpts_allowed_rolling5": def_fpts_rolling5,
        "opponent_rank_season":    opponent_rank_season,
        "opponent_rank_rolling5":  opponent_rank_rolling5,
    }


def get_top_players(limit: int = 300, position: str = None, team: str = None) -> list:
    players = [{"sleeper_id": sid, **p} for sid, p in nflverse_player_stats.items()]
    if position:
        players = [p for p in players if p["position"] == position.upper()]
    if team:
        players = [p for p in players if p["team"] == team.upper()]
    for p in players:
        p["matchup"] = _matchup_block(p["team"], p["position"])
    players.sort(key=lambda p: p["season_totals"].get("fantasy_points_ppr", 0), reverse=True)
    return players[:limit]


def project_player(sleeper_id: str, week: int) -> dict:
    """
    Rolling-5 projection with a light game-total adjustment (±1% per point vs 44 baseline).
    Capped at ±15%.
    """
    player = nflverse_player_stats.get(str(sleeper_id))
    if not player:
        return {}

    rolling = player.get("rolling_5") or player.get("rolling_3") or {}
    base_proj = rolling.get("fantasy_points_ppr", 0.0)

    team     = player.get("team", "")
    position = player.get("position", "")
    opp_info = nflverse_schedule.get(team, {})

    adj = 1.0
    if opp_info.get("week") == week and opp_info.get("total"):
        adj = max(0.85, min(1.15, 1.0 + (opp_info["total"] - 44) * 0.01))

    return {
        "sleeper_id":        sleeper_id,
        "name":              player["name"],
        "position":          position,
        "team":              team,
        "projected_ppr":     round(base_proj * adj, 2),
        "rolling_5_ppr":     rolling.get("fantasy_points_ppr", 0.0),
        "adjustment_factor": round(adj, 3),
        "matchup":           _matchup_block(team, position),
    }
