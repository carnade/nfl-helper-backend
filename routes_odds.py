"""
routes_odds.py — Flask Blueprint for /odds/* endpoints backed by The Odds API.
"""

from flask import Blueprint, jsonify, request
import odds_api as oa

odds_bp = Blueprint("odds", __name__, url_prefix="/odds")


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
    return jsonify(games)


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
