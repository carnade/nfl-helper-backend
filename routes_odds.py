"""
routes_odds.py — Flask Blueprint for /odds/* endpoints backed by The Odds API.
"""

from flask import Blueprint, jsonify, request
import odds_api as oa
from nflverse_stats import nflverse_team_stats, nflverse_schedule

odds_bp = Blueprint("odds", __name__, url_prefix="/odds")


def _ou_eval(home_abbr: str, away_abbr: str, total_line: float | None):
    """Return implied total + edge signal using season/rolling team score data."""
    if total_line is None:
        return None
    home = nflverse_team_stats.get(home_abbr, {})
    away = nflverse_team_stats.get(away_abbr, {})

    h_ppg = home.get("points_per_game") or 0
    h_apg = home.get("points_allowed_per_game") or 0
    h_r5  = home.get("points_rolling5") or 0
    h_ar5 = home.get("points_allowed_rolling5") or 0
    h_r3  = home.get("points_rolling3") or 0
    h_ar3 = home.get("points_allowed_rolling3") or 0

    a_ppg = away.get("points_per_game") or 0
    a_apg = away.get("points_allowed_per_game") or 0
    a_r5  = away.get("points_rolling5") or 0
    a_ar5 = away.get("points_allowed_rolling5") or 0
    a_r3  = away.get("points_rolling3") or 0
    a_ar3 = away.get("points_allowed_rolling3") or 0

    # Fall back to season-only if rolling data is absent
    has_r5 = h_r5 or a_r5 or h_ar5 or a_ar5
    has_r3 = h_r3 or a_r3 or h_ar3 or a_ar3
    has_season = h_ppg or a_ppg or h_apg or a_apg

    if not has_season:
        return None

    w_season = 1.0 if not has_r5 else 0.40
    w_r5     = 0.0 if not has_r5 else (0.60 if not has_r3 else 0.35)
    w_r3     = 0.0 if not has_r3 else 0.25

    home_season = (h_ppg + a_apg) / 2
    away_season = (a_ppg + h_apg) / 2
    home_r5 = (h_r5 + a_ar5) / 2
    away_r5 = (a_r5 + h_ar5) / 2
    home_r3 = (h_r3 + a_ar3) / 2
    away_r3 = (a_r3 + h_ar3) / 2

    implied_home  = w_season * home_season + w_r5 * home_r5 + w_r3 * home_r3
    implied_away  = w_season * away_season + w_r5 * away_r5 + w_r3 * away_r3
    implied_total = round(implied_home + implied_away, 1)

    edge_pct = round((implied_total - total_line) / total_line, 4)
    if edge_pct > 0.05:
        signal = "over"
    elif edge_pct < -0.05:
        signal = "under"
    else:
        signal = None

    return {"implied": implied_total, "edge_pct": edge_pct, "signal": signal}


@odds_bp.route("/status")
def odds_status():
    """Health/status for the odds data pipeline."""
    flagged = sum(
        1 for p in oa.odds_props
        for m in p.get("props", {}).values()
        if m.get("value_flag")
    )
    return jsonify({
        "last_updated":       oa.odds_last_updated,
        "credits_remaining":  oa.odds_credits_remaining,
        "game_count":         len(oa.odds_games),
        "player_prop_count":  len(oa.odds_props),
        "value_flag_count":   flagged,
    })


@odds_bp.route("/games")
def all_games():
    """All upcoming NFL games with best available moneyline, spread, and total."""
    games = sorted(oa.odds_games.values(), key=lambda g: g.get("commence_time", ""))
    result = []
    for g in games:
        entry = dict(g)
        total_line = (g.get("total") or {}).get("line")
        entry["ou_eval"] = _ou_eval(g.get("home_abbr", ""), g.get("away_abbr", ""), total_line)
        sched = nflverse_schedule.get(g.get("home_abbr", "")) or nflverse_schedule.get(g.get("away_abbr", ""))
        entry["nfl_week"] = sched.get("week") if sched else None
        result.append(entry)
    return jsonify(result)


@odds_bp.route("/games/<event_id>")
def game_detail(event_id: str):
    """Single game odds."""
    game = oa.odds_games.get(event_id)
    if not game:
        return jsonify({"error": f"No game found for event_id {event_id}"}), 404
    return jsonify(game)


@odds_bp.route("/props")
def all_props():
    """
    All player props.
    Query params:
      position   — filter by position (QB, RB, WR, TE)
      market     — filter by market key (player_pass_yds, player_rush_yds, etc.)
      value_only — if "true", only return players with at least one value flag
    """
    position   = request.args.get("position", "").upper()
    market     = request.args.get("market", "")
    value_only = request.args.get("value_only", "").lower() == "true"

    result = []
    for p in oa.odds_props:
        if position and p.get("position") != position:
            continue

        props = p.get("props", {})
        if market and market not in props:
            continue

        if value_only and not any(m.get("value_flag") for m in props.values()):
            continue

        entry = dict(p)
        if market:
            entry["props"] = {market: props[market]}
        sched = nflverse_schedule.get(p.get("home_abbr", "")) or nflverse_schedule.get(p.get("away_abbr", ""))
        entry["nfl_week"] = sched.get("week") if sched else None
        result.append(entry)

    return jsonify(result)


@odds_bp.route("/props/<sleeper_id>")
def player_props(sleeper_id: str):
    """All props for a single player."""
    player = next((p for p in oa.odds_props if p["sleeper_id"] == sleeper_id), None)
    if not player:
        return jsonify({"error": f"No props found for sleeper_id {sleeper_id}"}), 404
    return jsonify(player)


@odds_bp.route("/value")
def value_props():
    """
    Only value-flagged props, sorted by abs(value_pct) descending.
    Query params: position, market (same as /props)
    """
    position = request.args.get("position", "").upper()
    market   = request.args.get("market", "")

    flat = []
    for p in oa.odds_props:
        if position and p.get("position") != position:
            continue
        for mkey, m in p.get("props", {}).items():
            if not m.get("value_flag"):
                continue
            if market and mkey != market:
                continue
            flat.append({
                "sleeper_id":    p["sleeper_id"],
                "name":          p["name"],
                "position":      p["position"],
                "team":          p["team"],
                "event_id":      p.get("event_id"),
                "home_abbr":     p.get("home_abbr"),
                "away_abbr":     p.get("away_abbr"),
                "commence_time": p.get("commence_time"),
                "market":        mkey,
                **m,
            })

    flat.sort(key=lambda x: abs(x.get("value_pct") or 0), reverse=True)
    return jsonify(flat)
