"""
routes_stats.py — Flask Blueprint for /stats/* endpoints backed by nflverse data.
"""

from flask import Blueprint, jsonify, request
import nflverse_stats as ns

stats_bp = Blueprint("stats", __name__, url_prefix="/stats")


@stats_bp.route("/players")
def list_players():
    """
    Top players by season fantasy_points_ppr.
    Query params: position, team, week (filters to that week's stats), limit (max 500, default 300).
    """
    position = request.args.get("position")
    team = request.args.get("team")
    week = request.args.get("week", type=int)
    limit = min(max(request.args.get("limit", 300, type=int), 1), 500)

    if week is not None:
        players = []
        for sleeper_id, p in ns.nflverse_player_stats.items():
            week_data = next((w for w in p["weekly"] if w["week"] == week), None)
            if week_data is None:
                continue
            if position and p["position"] != position.upper():
                continue
            if team and p["team"] != team.upper():
                continue
            players.append({
                "sleeper_id": sleeper_id,
                "name": p["name"],
                "position": p["position"],
                "team": p["team"],
                **week_data,
                "matchup": ns._matchup_block(p["team"], p["position"]),
            })
        players.sort(key=lambda p: p.get("fantasy_points_ppr", 0), reverse=True)
        return jsonify(players[:limit])

    return jsonify(ns.get_top_players(limit, position, team))


@stats_bp.route("/players/team/<string:team>")
def players_by_team(team):
    """All players for a given team, sorted by season fantasy_points_ppr."""
    team = team.upper()
    players = [
        {"sleeper_id": sid, **p}
        for sid, p in ns.nflverse_player_stats.items()
        if p["team"] == team
    ]
    players.sort(key=lambda p: p["season_totals"].get("fantasy_points_ppr", 0), reverse=True)
    return jsonify(players)


@stats_bp.route("/player/<string:sleeper_id>")
def player_detail(sleeper_id):
    """Full stats for a single player: season totals, weekly breakdown, rolling averages."""
    player = ns.nflverse_player_stats.get(str(sleeper_id))
    if not player:
        return jsonify({"error": "Player not found"}), 404
    return jsonify({"sleeper_id": sleeper_id, **player})


@stats_bp.route("/player/<string:sleeper_id>/advanced")
def player_advanced(sleeper_id):
    """Advanced stats: snap%, expected vs actual fantasy points per week."""
    adv = ns.nflverse_player_advanced.get(str(sleeper_id))
    if not adv:
        return jsonify({"error": "No advanced data for player"}), 404
    return jsonify({"sleeper_id": sleeper_id, **adv})


@stats_bp.route("/week/<int:week>")
def stats_for_week(week):
    """All players who have stats recorded for a specific week."""
    result = {}
    for sleeper_id, player in ns.nflverse_player_stats.items():
        week_data = next((w for w in player["weekly"] if w["week"] == week), None)
        if week_data:
            result[sleeper_id] = {
                "name": player["name"],
                "position": player["position"],
                "team": player["team"],
                **week_data,
            }
    if not result:
        return jsonify({"error": f"No data for week {week}"}), 404
    return jsonify(result)


@stats_bp.route("/projections/week/<int:week>")
def projections_for_week(week):
    """
    Rolling-average projections for all players for a given week.
    Query params: position, team, limit (max 500, default 300).
    """
    position = request.args.get("position")
    team = request.args.get("team")
    limit = min(max(request.args.get("limit", 300, type=int), 1), 500)

    projections = []
    for sleeper_id in ns.nflverse_player_stats:
        proj = ns.project_player(sleeper_id, week)
        if not proj:
            continue
        if position and proj["position"] != position.upper():
            continue
        if team and proj["team"] != team.upper():
            continue
        projections.append(proj)

    projections.sort(key=lambda p: p["projected_ppr"], reverse=True)
    return jsonify(projections[:limit])


@stats_bp.route("/schedule/<int:week>")
def schedule_for_week(week):
    """Matchups for a specific week with Vegas spread and total."""
    games = ns.nflverse_games.get(week)
    if not games:
        return jsonify({"error": f"No schedule data for week {week}"}), 404
    return jsonify({"week": week, "season": ns.nflverse_current_season, "games": games})


@stats_bp.route("/teams")
def all_teams():
    """All 32 teams with stats and current week schedule info, sorted by team abbreviation."""
    teams = [
        {"team": team, **stats, "schedule": ns.nflverse_schedule.get(team, {})}
        for team, stats in ns.nflverse_team_stats.items()
    ]
    teams.sort(key=lambda t: t["team"])
    return jsonify(teams)


@stats_bp.route("/team/<string:team>")
def team_stats(team):
    """Team-level aggregate stats plus most-recent-week schedule info."""
    team = team.upper()
    stats = ns.nflverse_team_stats.get(team)
    if not stats:
        return jsonify({"error": f"No data for team {team}"}), 404
    return jsonify({"team": team, **stats, "schedule": ns.nflverse_schedule.get(team, {})})


@stats_bp.route("/status")
def stats_status():
    """Health/status for the nflverse data pipeline."""
    return jsonify({
        "last_updated":    ns.nflverse_last_updated,
        "current_season":  ns.nflverse_current_season,
        "player_count":    len(ns.nflverse_player_stats),
        "advanced_count":  len(ns.nflverse_player_advanced),
        "team_count":      len(ns.nflverse_team_stats),
        "schedule_weeks":  sorted(ns.nflverse_games.keys()) if ns.nflverse_games else [],
    })
