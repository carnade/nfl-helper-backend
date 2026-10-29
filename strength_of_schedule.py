"""
strength_of_schedule.py — how hard the rest of a team's season looks.

Pure functions over the dicts nflverse_stats already holds, so none of this
needs pandas, Flask, or the network, and all of it is testable directly.

Three readings of the same schedule, because no single one of them is good
enough on its own:

  "2025"   each opponent's win % from last season's final record. Stale on
           teams that changed, but it is the only basis with a full season
           behind it, which is what makes it worth having in September.
  "2026"   each opponent's win % so far this season. The live read, and
           near-useless in week 2 when it is one game per team.
  "vspos"  the fantasy points each opponent has allowed to the player's own
           position. Not strength of schedule in the league-standings sense,
           but much the strongest signal of the three for the question this
           feeds — measured over the real schedule, it separates teams about
           three times as widely as win % does.

Two windows: what is left of the season, and the fantasy playoffs. They
behave differently and the difference matters. The remaining window averages
ten or eleven games and regresses hard toward the middle — the real spread
across the league is about 0.17 of win percentage, which is close to nothing.
Weeks 15-17 average three, and spread about 0.51. So the playoff column is
where the signal is, and the rest-of-season column needs its rank shown beside
it or a middling number looks like a verdict.
"""

# A regular season. Week 18 exists; weeks beyond it are the real playoffs and
# no fantasy league is still scoring them.
MAX_WEEK = 18

# The fantasy playoffs, near enough universally. Fixed rather than derived:
# these are looked at as a window all season, including long before they are
# the current week, so "remaining" is the wrong idea for them.
PLAYOFF_WEEKS = (15, 16, 17)


def team_records(games_by_week):
    """
    Every team's record, from games that have actually finished.

    `games_by_week` is nflverse_stats' `{week: [game, ...]}`, where a game
    carries `home_team`, `away_team` and scores that are None until it is
    final. Serves both year bases: this season's from the live dict, last
    season's from a schedule frame run through the same builder.

    A tie counts as half a win, which is how the NFL computes it and not a
    detail worth getting wrong — there is a 1-4-1 team in the current season.

    `win_pct` is None, not 0.0, for a team that has not finished a game. A
    team that has not played and a team that has lost everything are different
    facts, and averaging the second into an opponent's schedule when you meant
    the first makes every schedule look easy in week 1.
    """
    records = {}

    def seen(team):
        return records.setdefault(team, {"w": 0, "l": 0, "t": 0, "games": 0})

    for games in (games_by_week or {}).values():
        for game in games or []:
            home_score, away_score = game.get("home_score"), game.get("away_score")
            if home_score is None or away_score is None:
                continue
            home, away = game.get("home_team"), game.get("away_team")
            if not home or not away:
                continue

            seen(home)["games"] += 1
            seen(away)["games"] += 1
            if home_score > away_score:
                records[home]["w"] += 1
                records[away]["l"] += 1
            elif away_score > home_score:
                records[away]["w"] += 1
                records[home]["l"] += 1
            else:
                records[home]["t"] += 1
                records[away]["t"] += 1

    for record in records.values():
        played = record["games"]
        record["win_pct"] = (
            (record["w"] + 0.5 * record["t"]) / played if played else None
        )
    return records


def opponents(games_by_week, team, weeks, only_unplayed=False):
    """
    Who `team` plays across `weeks`, in week order.

    A bye needs no special case: the team simply has no game that week, so
    nothing is appended. Neither does a game already played, when
    `only_unplayed` is set — a finished game has both scores. That is worth
    saying because byes are not an edge case here: 22 of the 32 teams have one
    still to come, so a remaining-schedule average is over ten games for some
    teams and eleven for others.
    """
    found = []
    for week in weeks:
        for game in (games_by_week or {}).get(week) or []:
            home, away = game.get("home_team"), game.get("away_team")
            if team not in (home, away):
                continue
            if only_unplayed and game.get("home_score") is not None \
                    and game.get("away_score") is not None:
                continue
            found.append(away if home == team else home)
    return found


def average_over_opponents(opponent_teams, value_of):
    """
    The mean of `value_of` across those opponents, and how many it covered.

    `value_of` is a callable returning a number or None, which is what lets
    one function serve all three bases: opponent win % for the year bases,
    points allowed to a position for `vspos`.

    Returns None rather than 0 when nothing is known, and carries `games`
    because the count is part of the claim — a ten-game average and an
    eleven-game average are not the same statement, and an average over two
    opponents is barely one at all.
    """
    values = []
    for team in opponent_teams or []:
        value = value_of(team)
        if value is not None:
            values.append(value)
    if not values:
        return None
    # Rounded here rather than left raw: these are served as JSON and a
    # seventeen-digit float is both noise on the wire and noise to read in a
    # test failure. Four decimals is finer than any caller displays.
    return {"value": round(sum(values) / len(values), 4), "games": len(values)}


def rank_cells(cells, tougher="higher"):
    """
    Rank teams 1-32 on the figure they already carry, in place.

    **Rank 1 is the toughest schedule**, whichever basis is being ranked:
    the highest opponent win %, or the *fewest* points allowed to the
    position. One direction for all three, because the frontend colours them
    all with `getDvpColor`, whose own comment calls getting this polarity
    backwards the easy mistake — and it is: a red cell has to mean "hard"
    everywhere or the table lies.

    `cells` maps team to the dict from `average_over_opponents`, or None.
    Teams with nothing to rank keep no rank rather than being ranked last,
    which would read as the easiest schedule in the league.
    """
    ranked = [(team, cell) for team, cell in cells.items() if cell]
    ranked.sort(key=lambda pair: pair[1]["value"], reverse=(tougher == "higher"))
    for position, (_team, cell) in enumerate(ranked, start=1):
        cell["rank"] = position
    return cells


def remaining_weeks(games_by_week):
    """
    The weeks with a game still to be played, in order.

    Derived from the schedule rather than from the current week, so a Tuesday
    in week 8 with Monday night already final does not still count week 8 as
    remaining.
    """
    weeks = []
    for week in range(1, MAX_WEEK + 1):
        for game in (games_by_week or {}).get(week) or []:
            if game.get("home_score") is None or game.get("away_score") is None:
                weeks.append(week)
                break
    return weeks


def build_team_sos(games_by_week, records_this_season, records_last_season,
                   team_stats, positions=("qb", "rb", "wr", "te")):
    """
    Every team's schedule strength, for both windows and all three bases.

        {team: {"ros":  {"2025": cell, "2026": cell, "vspos": {pos: cell}},
                "post": {...}}}

    where a cell is `{"value", "games", "rank"}` or None.

    `records_last_season` is keyed "2025" and `records_this_season` "2026" by
    the caller rather than here, so this function does not need to know what
    year it is. `team_stats` is nflverse_team_stats, read only for its
    `def_fpts_allowed_{pos}_per_game` figures.

    Small enough to precompute in full — 32 teams by two windows by six
    figures is a few KB — which keeps the per-player join a dict lookup.
    """
    windows = {
        "ros": opponents_for(games_by_week, remaining_weeks(games_by_week), only_unplayed=True),
        "post": opponents_for(games_by_week, PLAYOFF_WEEKS, only_unplayed=False),
    }

    def win_pct_of(records):
        return lambda team: (records.get(team) or {}).get("win_pct")

    def allowed_to(position):
        key = f"def_fpts_allowed_{position}_per_game"
        return lambda team: (team_stats.get(team) or {}).get(key)

    out = {team: {} for team in windows["ros"]}
    for window, by_team in windows.items():
        for team in out:
            out[team][window] = {}

        for basis, records in (("2025", records_last_season),
                               ("2026", records_this_season)):
            cells = {
                team: average_over_opponents(by_team.get(team), win_pct_of(records))
                for team in out
            }
            rank_cells(cells, tougher="higher")
            for team, cell in cells.items():
                out[team][window][basis] = cell

        for team in out:
            out[team][window]["vspos"] = {}
        for position in positions:
            cells = {
                team: average_over_opponents(by_team.get(team), allowed_to(position))
                for team in out
            }
            # Fewest points allowed is the toughest draw, so this one ranks
            # the other way round from win percentage.
            rank_cells(cells, tougher="lower")
            for team, cell in cells.items():
                out[team][window]["vspos"][position] = cell

    return out


def opponents_for(games_by_week, weeks, only_unplayed=False):
    """Every team's opponents across `weeks`, as `{team: [opponent, ...]}`."""
    teams = set()
    for games in (games_by_week or {}).values():
        for game in games or []:
            teams.add(game.get("home_team"))
            teams.add(game.get("away_team"))
    teams.discard(None)

    return {
        team: opponents(games_by_week, team, weeks, only_unplayed=only_unplayed)
        for team in sorted(teams)
    }
