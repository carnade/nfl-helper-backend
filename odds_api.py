"""
odds_api.py — The Odds API client and in-memory cache for NFL betting data.

Fetches game lines (h2h, spreads, totals) and player props (pass/rush/rec yds,
anytime TD) and cross-references props with nflverse rolling averages to surface
value flags.
"""

import logging
import datetime
import re
import requests

logger = logging.getLogger(__name__)


class OddsApiUnavailable(Exception):
    """
    The API rejected us for a reason that is not about this particular event —
    out of monthly credits, bad key, or rate limited. Distinct from "this game
    has no props posted yet", because the results of such a run must never be
    used to overwrite good data we already hold.
    """


# Statuses that mean "stop, the whole run is invalid" rather than "skip this event"
FATAL_STATUSES = {401, 403, 429}

BASE_URL  = "https://api.the-odds-api.com/v4"
SPORT     = "americanfootball_nfl"
REGIONS   = "us"   # game lines: one region only — cost is markets × regions
ODDS_FORMAT = "decimal"

GAME_MARKETS = "h2h,spreads,totals"

PROP_MARKETS = [
    "player_pass_yds",
    "player_rush_attempts",
    "player_rush_yds",
    "player_receptions",
    "player_reception_yds",
    "player_anytime_td",
]

# Market key → nflverse rolling_5 stat key used for value flag comparison
PROP_ROLLING_KEY = {
    "player_pass_yds":      "passing_yards",
    "player_rush_yds":      "rushing_yards",
    "player_reception_yds": "receiving_yards",
    "player_receptions":    "receptions",
    "player_rush_attempts": "carries",
}

# Markets that are a yes/no proposition rather than a quantity. Their per-game
# value is 1/0 ("did it happen"), not a total — two TDs in a game is still a
# single hit for an anytime-TD bet — and their "line" is the price's implied
# probability rather than a number posted by the book.
BINARY_MARKETS = {"player_anytime_td"}
BINARY_THRESHOLD = 0.5  # actual > 0.5 means it happened

# Yes/no markets need a much wider value threshold than yardage lines. Their
# projection is a hit rate estimated from a handful of games, so its standard
# error is large: at a ~40% scoring rate over a full 17-game season the error is
# still around ±12 points, i.e. ~30% in relative terms. A 10% band (fine for a
# yardage line) sits well inside that noise and flags almost everything — at
# VALUE_THRESHOLD it flagged 96% of anytime-TD props. 0.35 is roughly one
# standard error; it is a heuristic, not a tuned value, and the prop-results
# hit rates are what should eventually set it.
BINARY_VALUE_THRESHOLD = 0.35

# Market key → weekly stat column(s) that make up a single game's value for that
# market (used for the "Last 5" column). player_anytime_td has no single raw
# column — a game counts if the player found the end zone rushing or receiving.
PROP_GAME_STAT_COLS = {
    "player_pass_yds":      ("passing_yards",),
    "player_rush_yds":      ("rushing_yards",),
    "player_reception_yds": ("receiving_yards",),
    "player_anytime_td":    ("rushing_tds", "receiving_tds"),
    "player_receptions":    ("receptions",),
    "player_rush_attempts": ("carries",),
}

# Market key → nflverse_team_stats "def_stat_allowed"/"def_stat_rank" stat key
# (used for the opponent-defense column — which defense-allowed stat matches
# the market being displayed)
MARKET_TO_DEF_STAT = {
    "player_pass_yds":      "passing_yards",
    "player_rush_yds":      "rushing_yards",
    "player_reception_yds": "receiving_yards",
    "player_anytime_td":    "rush_rec_tds",
    "player_receptions":    "receptions",
    "player_rush_attempts": "carries",
}

# Player position → nflverse_team_stats defense-vs-position dict key
POS_DEF_KEY = {"QB": "qb", "RB": "rb", "WR": "wr", "TE": "te"}

# Sleeper's team abbreviation → our convention (nflverse/NFL_TEAM_MAP), for the
# few codes where Sleeper's live roster feed disagrees (only the Rams so far)
SLEEPER_TEAM_ABBR_FIX = {"LAR": "LA"}

# Full team name → nflverse abbreviation
NFL_TEAM_MAP = {
    "Arizona Cardinals":    "ARI",
    "Atlanta Falcons":      "ATL",
    "Baltimore Ravens":     "BAL",
    "Buffalo Bills":        "BUF",
    "Carolina Panthers":    "CAR",
    "Chicago Bears":        "CHI",
    "Cincinnati Bengals":   "CIN",
    "Cleveland Browns":     "CLE",
    "Dallas Cowboys":       "DAL",
    "Denver Broncos":       "DEN",
    "Detroit Lions":        "DET",
    "Green Bay Packers":    "GB",
    "Houston Texans":       "HOU",
    "Indianapolis Colts":   "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs":   "KC",
    "Las Vegas Raiders":    "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams":     "LA",
    "Miami Dolphins":       "MIA",
    "Minnesota Vikings":    "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints":   "NO",
    "New York Giants":      "NYG",
    "New York Jets":        "NYJ",
    "Philadelphia Eagles":  "PHI",
    "Pittsburgh Steelers":  "PIT",
    "San Francisco 49ers":  "SF",
    "Seattle Seahawks":     "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans":     "TEN",
    "Washington Commanders": "WAS",
}

# ── In-memory stores ──────────────────────────────────────────────────────────

odds_games: dict = {}               # event_id → game dict
odds_props: list = []               # list of player prop dicts (one per player)
odds_history: dict = {}             # event_id → snapshotted game dict (persisted before games play)
odds_props_history: dict = {}       # "event:player:market" → snapshotted prop line + our projection
odds_credits_remaining: int | None = None
odds_last_updated: str | None = None
odds_last_error: str | None = None       # why the most recent refresh failed, if it did
odds_last_attempt: str | None = None     # when we last tried, successful or not

# ── Helpers ───────────────────────────────────────────────────────────────────

_SUFFIX_RE = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", re.IGNORECASE)
_PUNCT_RE  = re.compile(r"[^a-z0-9 ]")


def _normalize(name: str) -> str:
    name = name.lower().strip()
    name = _SUFFIX_RE.sub("", name)
    name = _PUNCT_RE.sub("", name)
    return name


def _build_name_lookup() -> dict[str, str]:
    """Return {normalized_name: sleeper_id} from nflverse in-memory player stats."""
    import nflverse_stats as ns
    lookup: dict[str, str] = {}
    for sleeper_id, p in ns.nflverse_player_stats.items():
        raw = p.get("name", "")
        if raw:
            lookup[_normalize(raw)] = sleeper_id
    return lookup


def _best_price(outcomes: list, side: str) -> tuple[float | None, str | None]:
    """Return (best_american_price, book_key) for Over or Under outcomes."""
    best_price = None
    best_book  = None
    for o in outcomes:
        if o.get("name") != side:
            continue
        price = o.get("price")
        if price is None:
            continue
        # Better price: for Over, highest positive or least negative
        if best_price is None or price > best_price:
            best_price = price
            best_book  = o.get("_book")
    return best_price, best_book


def _extract_headers(resp: requests.Response) -> None:
    global odds_credits_remaining
    remaining = resp.headers.get("x-requests-remaining")
    if remaining is not None:
        try:
            odds_credits_remaining = int(remaining)
        except ValueError:
            pass


# ── Game odds ─────────────────────────────────────────────────────────────────

def fetch_game_odds(api_key: str) -> dict:
    """Fetch h2h, spreads, totals for all upcoming NFL games."""
    url = f"{BASE_URL}/sports/{SPORT}/odds"
    params = {
        "apiKey":      api_key,
        "regions":     REGIONS,
        "markets":     GAME_MARKETS,
        "oddsFormat":  ODDS_FORMAT,
    }
    resp = requests.get(url, params=params, timeout=15)
    _extract_headers(resp)
    if resp.status_code in FATAL_STATUSES:
        raise OddsApiUnavailable(
            f"game odds fetch rejected with HTTP {resp.status_code} — aborting refresh"
        )
    resp.raise_for_status()
    events = resp.json()

    games = {}
    for event in events:
        event_id     = event["id"]
        home_full    = event.get("home_team", "")
        away_full    = event.get("away_team", "")
        home_abbr    = NFL_TEAM_MAP.get(home_full, home_full)
        away_abbr    = NFL_TEAM_MAP.get(away_full, away_full)
        commence     = event.get("commence_time", "")

        h2h     = {}
        spread  = {}
        total   = {}

        for book in event.get("bookmakers", []):
            book_key = book["key"]
            for market in book.get("markets", []):
                mkey     = market["key"]
                outcomes = market.get("outcomes", [])

                if mkey == "h2h":
                    for o in outcomes:
                        team = NFL_TEAM_MAP.get(o["name"], o["name"])
                        price = o.get("price")
                        if price is None:
                            continue
                        if team == home_abbr:
                            if "home_price" not in h2h or price > h2h["home_price"]:
                                h2h["home_price"] = price
                                h2h["home_book"]  = book_key
                        elif team == away_abbr:
                            if "away_price" not in h2h or price > h2h["away_price"]:
                                h2h["away_price"] = price
                                h2h["away_book"]  = book_key

                elif mkey == "spreads":
                    for o in outcomes:
                        team  = NFL_TEAM_MAP.get(o["name"], o["name"])
                        point = o.get("point")
                        price = o.get("price")
                        if point is None or price is None:
                            continue
                        if team == home_abbr:
                            if "home_spread" not in spread or price > spread.get("home_price", -9999):
                                spread["home_spread"] = point
                                spread["home_price"]  = price
                                spread["home_book"]   = book_key

                elif mkey == "totals":
                    for o in outcomes:
                        side  = o.get("name")
                        point = o.get("point")
                        price = o.get("price")
                        if point is None or price is None:
                            continue
                        if side == "Over":
                            if "line" not in total or price > total.get("over_price", -9999):
                                total["line"]       = point
                                total["over_price"] = price
                                total["over_book"]  = book_key
                        elif side == "Under":
                            if price > total.get("under_price", -9999):
                                total["under_price"] = price
                                total["under_book"]  = book_key

        games[event_id] = {
            "event_id":      event_id,
            "home_team":     home_full,
            "home_abbr":     home_abbr,
            "away_team":     away_full,
            "away_abbr":     away_abbr,
            "commence_time": commence,
            "h2h":           h2h   or None,
            "spread":        spread or None,
            "total":         total  or None,
        }

    logger.info("odds: fetched %d games", len(games))
    return games


# ── Player props ──────────────────────────────────────────────────────────────

# Only fetch props for games within this rolling window. Sized to reach the next
# game day from either scheduled refresh (Thu/Mon 10:00 UTC) with a little slack —
# every game still gets covered before kickoff, but games no longer get re-fetched
# many times over. Each event costs (markets returned × regions) credits, so this
# window is the single biggest lever on monthly credit spend.
PROPS_LOOKAHEAD_DAYS   = 4
PROPS_OPENER_BUFFER_DAYS = 7  # off-season fallback only — see _props_cutoff()
PROPS_REGION = "us"           # single region for props to minimise credit use


def _props_cutoff(now: datetime.datetime, game_times: list) -> datetime.datetime:
    """
    Latest kickoff time we should fetch props for.

    Normally a rolling PROPS_LOOKAHEAD_DAYS from now. Deep in the off-season that
    window can fall entirely before the season starts and catch nothing at all —
    only then do we stretch to the first game plus PROPS_OPENER_BUFFER_DAYS so the
    opening week becomes available as soon as books post it.

    This is deliberately a fallback rather than max(rolling, opener): in-season the
    next game is usually a day or two out, so an unconditional max() would keep the
    cutoff ~7 days ahead and silently cancel out the short rolling window.
    """
    rolling_cutoff = now + datetime.timedelta(days=PROPS_LOOKAHEAD_DAYS)
    if not game_times:
        return rolling_cutoff
    if any(t <= rolling_cutoff for t in game_times):
        return rolling_cutoff
    return min(game_times) + datetime.timedelta(days=PROPS_OPENER_BUFFER_DAYS)

def fetch_player_props(api_key: str, name_lookup: dict[str, str], games: dict, sleeper_players: dict | None = None) -> list:
    """
    Fetch player props per event (the bulk /odds endpoint does not support prop
    markets). Only processes games starting within the lookahead window, to
    avoid burning credits on fixtures that have no lines yet.

    See _props_cutoff() for how the lookahead window is sized.

    sleeper_players (nfl-helper.py's `filtered_players`) is the live Sleeper
    roster feed, refreshed every 4 hours — used to override nflverse's `team`
    field, which is frozen at last completed season's roster and goes stale
    the moment a player is traded in the current offseason.
    """
    import nflverse_stats as ns
    sleeper_players = sleeper_players or {}

    now = datetime.datetime.utcnow()

    dated_games = []  # (game, parsed commence_time)
    for g in games.values():
        try:
            t = datetime.datetime.fromisoformat(g["commence_time"].replace("Z", ""))
            dated_games.append((g, t))
        except Exception:
            pass

    cutoff = _props_cutoff(now, [t for _, t in dated_games])
    upcoming = [g for g, t in dated_games if t <= cutoff]
    lookahead_days = (cutoff - now).days
    logger.info("odds: fetching props for %d events within %d days", len(upcoming), lookahead_days)

    player_data: dict[str, dict] = {}
    player_event: dict[str, dict] = {}
    player_meta: dict[str, dict] = {}

    for g in upcoming:
        event_id  = g["event_id"]
        home_abbr = g["home_abbr"]
        away_abbr = g["away_abbr"]
        commence  = g["commence_time"]

        url = f"{BASE_URL}/sports/{SPORT}/events/{event_id}/odds"
        params = {
            "apiKey":     api_key,
            "regions":    PROPS_REGION,
            "markets":    ",".join(PROP_MARKETS),
            "oddsFormat": ODDS_FORMAT,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            _extract_headers(resp)
            if resp.status_code in FATAL_STATUSES:
                # Out of credits / bad key / rate limited. Abort the whole run —
                # continuing would return a partial (or empty) list that the
                # caller would then use to overwrite good data.
                raise OddsApiUnavailable(
                    f"props fetch rejected with HTTP {resp.status_code} — aborting refresh"
                )
            if resp.status_code in (404, 422):
                # No props available for this event yet
                continue
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            continue

        event = resp.json()

        # Collect all outcomes across all bookmakers, tagged with book key
        # market_outcomes[market_key][player_name_norm] = [{"name":side, "point":..., "price":..., "_book":...}]
        market_outcomes: dict[str, dict[str, list]] = {}

        for book in event.get("bookmakers", []):
            book_key = book["key"]
            for market in book.get("markets", []):
                mkey = market["key"]
                if mkey not in PROP_MARKETS:
                    continue
                market_outcomes.setdefault(mkey, {})
                for o in market.get("outcomes", []):
                    desc  = o.get("description", "")
                    norm  = _normalize(desc)
                    if not norm:
                        continue
                    market_outcomes[mkey].setdefault(norm, []).append({
                        "name":  o.get("name"),   # "Over"/"Under" (yardage) or "Yes"/"No" (anytime TD)
                        "point": o.get("point"),
                        "price": o.get("price"),
                        "_book": book_key,
                    })

        for mkey, players_outcomes in market_outcomes.items():
            for norm_name, outcomes in players_outcomes.items():
                sleeper_id = name_lookup.get(norm_name)
                if not sleeper_id:
                    continue

                # Determine line (use first point value found)
                line = next((o["point"] for o in outcomes if o.get("point") is not None), None)

                # Best over price (highest = best for bettor).
                # Line-based markets (pass/rush/rec yds) use "Over"/"Under".
                # Yes/No markets (anytime TD) have no line — "Yes" maps to the
                # "over" slot so the UI's existing Over/Under columns still work.
                over_outcomes  = [o for o in outcomes if o["name"] in ("Over", "Yes")]
                under_outcomes = [o for o in outcomes if o["name"] in ("Under", "No")]

                best_over_price, best_over_book   = None, None
                best_under_price, best_under_book = None, None

                for o in over_outcomes:
                    if o["price"] is not None:
                        if best_over_price is None or o["price"] > best_over_price:
                            best_over_price = o["price"]
                            best_over_book  = o["_book"]

                for o in under_outcomes:
                    if o["price"] is not None:
                        if best_under_price is None or o["price"] > best_under_price:
                            best_under_price = o["price"]
                            best_under_book  = o["_book"]

                player_data.setdefault(sleeper_id, {})
                existing = player_data[sleeper_id].get(mkey, {})

                # Keep whichever book/line we found first (all books should agree on the line)
                if mkey not in player_data[sleeper_id] or (
                    best_over_price is not None and
                    best_over_price > existing.get("best_over_price", -9999)
                ):
                    player_data[sleeper_id][mkey] = {
                        "line":             line,
                        "best_over_price":  best_over_price,
                        "best_over_book":   best_over_book,
                        "best_under_price": best_under_price,
                        "best_under_book":  best_under_book,
                    }

                # Store event context (first seen wins)
                if sleeper_id not in player_event:
                    player_event[sleeper_id] = {
                        "event_id":      event_id,
                        "home_abbr":     home_abbr,
                        "away_abbr":     away_abbr,
                        "commence_time": commence,
                    }

                # Store meta from nflverse, but prefer Sleeper's live team (nflverse's
                # team is frozen at last completed season and misses offseason trades)
                if sleeper_id not in player_meta:
                    p = ns.nflverse_player_stats.get(sleeper_id, {})
                    live_team = sleeper_players.get(sleeper_id, {}).get("team")
                    live_team = SLEEPER_TEAM_ABBR_FIX.get(live_team, live_team)
                    player_meta[sleeper_id] = {
                        "name":     p.get("name", ""),
                        "position": p.get("position", ""),
                        "team":     live_team or p.get("team", ""),
                    }

    # Compute value flags and assemble final list
    props_list = _compute_value_flags(player_data, player_event, player_meta)
    logger.info("odds: fetched props for %d players", len(props_list))
    return props_list


# ── Value flags ───────────────────────────────────────────────────────────────

VALUE_THRESHOLD = 0.10  # projection must beat the line by >10% to flag

# How hard to lean on the opponent-defence matchup when projecting.
#   projection = recent_form × (1 + DEF_ADJ_DAMPING × (matchup_factor − 1))
# 0.0 disables it entirely; 1.0 applies the raw defence-vs-position ratio.
#
# 0.20 is empirically chosen — see backtest_props.py. Across 2023-2025 the
# defence signal points the right way in all 15 market-seasons, but it is weak:
# the best achievable uniform gain is only ~0.35% MAE, and leaning harder makes
# more market-seasons worse than better. Keep this small and treat the Opp Def
# column as context rather than a strong predictor.
DEF_ADJ_DAMPING = 0.20
DEF_FACTOR_CLIP = (0.65, 1.55)  # stop one lopsided matchup from dominating


def _league_def_averages(team_stats: dict) -> dict:
    """League-wide mean allowed, as {basis: {stat: {pos: mean}}}, for matchup factors."""
    acc: dict = {}
    for t in team_stats.values():
        for basis, stats in (t.get("def_stat_allowed") or {}).items():
            for stat, per_pos in (stats or {}).items():
                for pos, val in (per_pos or {}).items():
                    if val:  # ignore 0.0 / None — a position with no data yet
                        acc.setdefault(basis, {}).setdefault(stat, {}).setdefault(pos, []).append(val)
    return {
        basis: {stat: {pos: sum(v) / len(v) for pos, v in per_pos.items()}
                for stat, per_pos in stats.items()}
        for basis, stats in acc.items()
    }


def _market_game_value(week_entry: dict, mkey: str) -> float | None:
    """
    One game's value for this market. Binary markets collapse to 1/0 — scoring
    twice in a game is still just one hit for an anytime-TD bet.
    """
    cols = PROP_GAME_STAT_COLS.get(mkey)
    if not cols:
        return None
    total = sum(week_entry.get(c, 0.0) or 0.0 for c in cols)
    if mkey in BINARY_MARKETS:
        return 1.0 if total >= 1 else 0.0
    return round(total, 1)


def _implied_probability(decimal_price: float | None) -> float | None:
    """Decimal odds → implied probability (2.00 → 0.50). Vig is not removed."""
    if not decimal_price or decimal_price <= 0:
        return None
    return round(1.0 / decimal_price, 4)


def _opponent_defense(mkey: str, position: str, team: str, event: dict, team_stats: dict,
                      league_avg: dict | None = None) -> dict | None:
    """
    Rank + per-game value the player's opponent allows for this market's stat,
    to the player's own position. Prefers the last-5-games figure, falling
    back to season-long when rolling5 has no games yet (mirrors the has_r5
    fallback pattern in routes_odds.py's _ou_eval).
    """
    home_abbr = event.get("home_abbr")
    away_abbr = event.get("away_abbr")
    opponent  = away_abbr if team == home_abbr else (home_abbr if team == away_abbr else None)
    pos_key   = POS_DEF_KEY.get(position)
    stat_key  = MARKET_TO_DEF_STAT.get(mkey)
    if not (opponent and pos_key and stat_key):
        return None

    opp     = team_stats.get(opponent, {})
    allowed = opp.get("def_stat_allowed", {})
    rank    = opp.get("def_stat_rank", {})

    season_val  = (allowed.get("season", {}).get(stat_key) or {}).get(pos_key)
    r5_val      = (allowed.get("rolling5", {}).get(stat_key) or {}).get(pos_key)
    season_rank = (rank.get("season", {}).get(stat_key) or {}).get(pos_key)
    r5_rank     = (rank.get("rolling5", {}).get(stat_key) or {}).get(pos_key)

    use_r5 = bool(r5_val)
    value  = r5_val if use_r5 else season_val
    display_rank = r5_rank if use_r5 else season_rank
    if value is None or display_rank is None:
        return None

    basis = "rolling5" if use_r5 else "season"

    # Matchup factor: how this defence compares to the league average for the
    # same stat+position. >1 = softer than average, <1 = tougher.
    factor = None
    lg = ((league_avg or {}).get(basis, {}).get(stat_key) or {}).get(pos_key)
    if lg:
        factor = round(min(max(value / lg, DEF_FACTOR_CLIP[0]), DEF_FACTOR_CLIP[1]), 3)

    return {
        "rank":         display_rank,
        "total_teams":  len(team_stats) or 32,
        "value":        value,
        "basis":        basis,
        "factor":       factor,
    }


def _compute_value_flags(
    player_data: dict,
    player_event: dict,
    player_meta: dict,
) -> list:
    import nflverse_stats as ns

    league_avg = _league_def_averages(ns.nflverse_team_stats)

    result = []
    for sleeper_id, markets in player_data.items():
        p = ns.nflverse_player_stats.get(sleeper_id, {})
        rolling = p.get("rolling_5") or p.get("rolling_3") or {}
        meta    = player_meta.get(sleeper_id, {})
        event   = player_event.get(sleeper_id, {})

        # Emit markets in PROP_MARKETS order so a player's rows always appear in
        # the same order in the UI, rather than whatever order the books returned.
        enriched_markets = {}
        ordered = sorted(markets.items(), key=lambda kv: PROP_MARKETS.index(kv[0]) if kv[0] in PROP_MARKETS else len(PROP_MARKETS))
        for mkey, m in ordered:
            entry = dict(m)
            is_binary = mkey in BINARY_MARKETS

            # Last 5 individual games for this market's stat (oldest → newest)
            weekly = p.get("weekly") or []
            last5 = []
            for w in weekly[-5:]:
                v = _market_game_value(w, mkey)
                if v is not None:
                    last5.append({"week": w.get("week"), "value": v})
            entry["last5"] = last5

            if is_binary:
                # Hit rate over *every* game we have, not just the last five —
                # five games only yields rates of 0, .2, .4, .6, .8, 1.0, which is
                # far too coarse to compare against a bookmaker's probability.
                all_games = [_market_game_value(w, mkey) for w in weekly]
                all_games = [v for v in all_games if v is not None]
                rolling_avg = (sum(all_games) / len(all_games)) if all_games else None
                entry["sample_games"] = len(all_games)
                # The "line" is whatever probability the price implies.
                line = _implied_probability(m.get("best_over_price"))
                entry["implied_prob"] = line
                entry["grade_threshold"] = BINARY_THRESHOLD
            else:
                rolling_stat_key = PROP_ROLLING_KEY.get(mkey)
                rolling_avg      = rolling.get(rolling_stat_key) if rolling_stat_key else None
                line             = m.get("line")
                entry["grade_threshold"] = line

            # Opponent defence vs. this player's position, for this market's stat
            opp_def = _opponent_defense(
                mkey, meta.get("position", ""), meta.get("team", ""), event,
                ns.nflverse_team_stats, league_avg,
            )

            # Projection = recent form, nudged by how soft/tough the matchup is.
            # The edge is measured off this projection, not off raw recent form.
            projection = rolling_avg
            factor = (opp_def or {}).get("factor")
            if rolling_avg is not None and factor:
                projection = rolling_avg * (1 + DEF_ADJ_DAMPING * (factor - 1))
                if is_binary:
                    projection = min(projection, 1.0)  # it is a probability

            value_flag = None
            value_pct  = None
            threshold = BINARY_VALUE_THRESHOLD if is_binary else VALUE_THRESHOLD
            if projection is not None and line and line > 0:
                diff = (projection - line) / line
                if diff > threshold:
                    value_flag = "over"
                    value_pct  = round(diff, 3)
                elif diff < -threshold:
                    value_flag = "under"
                    value_pct  = round(diff, 3)

            rnd = 3 if is_binary else 1
            entry["rolling_avg"] = round(rolling_avg, rnd) if rolling_avg is not None else None
            entry["projection"]  = round(projection, rnd) if projection is not None else None
            entry["value_flag"]  = value_flag
            entry["value_pct"]   = value_pct
            entry["opp_defense"] = opp_def

            enriched_markets[mkey] = entry

        result.append({
            "sleeper_id":    sleeper_id,
            "name":          meta.get("name", ""),
            "position":      meta.get("position", ""),
            "team":          meta.get("team", ""),
            "event_id":      event.get("event_id"),
            "home_abbr":     event.get("home_abbr"),
            "away_abbr":     event.get("away_abbr"),
            "commence_time": event.get("commence_time"),
            "props":         enriched_markets,
        })

    return result


# ── History snapshot ─────────────────────────────────────────────────────────

def _week_for_commence(commence_time: str) -> int | None:
    """
    Map a kickoff timestamp to its NFL week via the nflverse schedule.

    commence_time is UTC, so a Sunday-night ET game lands on the following UTC
    date — check the previous day too before giving up.
    """
    import nflverse_stats as ns
    if not commence_time:
        return None
    try:
        d = datetime.datetime.fromisoformat(commence_time.replace("Z", "")).date()
    except Exception:
        return None
    for day in (d.isoformat(), (d - datetime.timedelta(days=1)).isoformat()):
        for week, games in (ns.nflverse_games or {}).items():
            for g in games:
                if g.get("gameday") == day:
                    try:
                        return int(week)
                    except (TypeError, ValueError):
                        return None
    return None


def snapshot_current_props() -> tuple[int, int]:
    """
    Freeze the current prop lines alongside the projection we made, so the call
    can be graded once the game is played. Returns (added, updated).

    Entries stay open to updates until kickoff, so what we keep is the last line
    we saw before the game — the one you could actually have bet. The line first
    observed is preserved separately so line movement stays visible.
    """
    now = datetime.datetime.utcnow()
    added = updated = 0

    for p in odds_props:
        commence = p.get("commence_time")
        try:
            started = datetime.datetime.fromisoformat((commence or "").replace("Z", "")) <= now
        except Exception:
            started = False

        for mkey, m in (p.get("props") or {}).items():
            key = f"{p.get('event_id')}:{p.get('sleeper_id')}:{mkey}"
            existing = odds_props_history.get(key)
            if existing and started:
                continue  # frozen once the game is under way

            snap = {
                "event_id":      p.get("event_id"),
                "sleeper_id":    p.get("sleeper_id"),
                "name":          p.get("name"),
                "position":      p.get("position"),
                "team":          p.get("team"),
                "home_abbr":     p.get("home_abbr"),
                "away_abbr":     p.get("away_abbr"),
                "commence_time": commence,
                "nfl_week":      _week_for_commence(commence),
                "market":        mkey,
                "line":          m.get("line"),
                "grade_threshold": m.get("grade_threshold"),
                "implied_prob":  m.get("implied_prob"),
                "price":         m.get("best_over_price"),
                "projection":    m.get("projection"),
                "rolling_avg":   m.get("rolling_avg"),
                "value_flag":    m.get("value_flag"),
                "value_pct":     m.get("value_pct"),
                "opp_rank":      (m.get("opp_defense") or {}).get("rank"),
                "opp_factor":    (m.get("opp_defense") or {}).get("factor"),
                "snapshotted_at": now.isoformat() + "Z",
            }
            if existing:
                snap["first_line"]    = existing.get("first_line")
                snap["first_seen_at"] = existing.get("first_seen_at")
                updated += 1
            else:
                snap["first_line"]    = m.get("line")
                snap["first_seen_at"] = now.isoformat() + "Z"
                added += 1
            odds_props_history[key] = snap

    return added, updated


def grade_props_history() -> list:
    """
    Join snapshotted prop lines with what actually happened, from the nflverse
    weekly logs. Ungraded entries (game not played, or no stat line yet) come
    back with result=None rather than being dropped.
    """
    import nflverse_stats as ns

    graded = []
    for snap in odds_props_history.values():
        entry = dict(snap)
        actual = None

        # Resolve the week lazily: at snapshot time the schedule for the season
        # in question may not be loaded yet (nflverse only rolls over to the new
        # season in September), and snapshots freeze at kickoff — so a week left
        # unresolved then would strand the record as ungradeable forever.
        wk = snap.get("nfl_week") or _week_for_commence(snap.get("commence_time"))
        entry["nfl_week"] = wk

        p = ns.nflverse_player_stats.get(snap.get("sleeper_id"), {})
        if wk:
            for w in p.get("weekly") or []:
                if w.get("week") == wk:
                    actual = _market_game_value(w, snap.get("market"))
                    break

        entry["actual"] = actual
        flag = snap.get("value_flag")
        # Yardage markets grade against the posted line; yes/no markets against
        # the 0.5 "did it happen" threshold, since they have no line.
        threshold = snap.get("grade_threshold")
        if threshold is None:
            threshold = BINARY_THRESHOLD if snap.get("market") in BINARY_MARKETS else snap.get("line")
        # Our own call is judged against the price's implied probability, not 0.5
        call_ref = snap.get("implied_prob") if snap.get("market") in BINARY_MARKETS else threshold

        if actual is None or threshold is None:
            entry["result"] = None
        else:
            if actual > threshold:
                outcome = "over"
            elif actual < threshold:
                outcome = "under"
            else:
                outcome = "push"
            proj = snap.get("projection")
            entry["result"] = {
                "outcome": outcome,
                # Did our flagged call land? None when we made no call or it pushed.
                "call_correct": (flag == outcome) if (flag and outcome != "push") else None,
                # Did the projection sit on the correct side, flagged or not?
                "projection_side_correct": (
                    None if outcome == "push" or proj is None or call_ref is None
                    else (("over" if proj > call_ref else "under") == outcome)
                ),
            }
        graded.append(entry)

    graded.sort(key=lambda r: (r.get("commence_time") or ""), reverse=True)
    return graded


def snapshot_current_games(ou_eval_fn) -> int:
    """Copy current odds_games into odds_history. Idempotent — skips existing event_ids."""
    added = 0
    for event_id, game in odds_games.items():
        if event_id not in odds_history:
            entry = dict(game)
            total_line = (game.get("total") or {}).get("line")
            entry["ou_eval"] = ou_eval_fn(game.get("home_abbr", ""), game.get("away_abbr", ""), total_line)
            entry["snapshotted_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            odds_history[event_id] = entry
            added += 1
    return added


# ── Refresh orchestrator ──────────────────────────────────────────────────────

def refresh_odds_data(api_key: str | None = None, sleeper_players: dict | None = None) -> None:
    """
    Download and rebuild all odds in-memory data. Safe to call repeatedly.
    sleeper_players (nfl-helper.py's `filtered_players`) is passed through to
    fetch_player_props to keep the player→team mapping accurate across trades.
    """
    global odds_games, odds_props, odds_last_updated, odds_last_error, odds_last_attempt

    odds_last_attempt = datetime.datetime.utcnow().isoformat() + "Z"

    if not api_key:
        odds_last_error = "no ODDS_API_KEY set"
        logger.warning("odds: no ODDS_API_KEY set, skipping refresh")
        return

    logger.info("odds: refreshing")
    try:
        name_lookup = _build_name_lookup()

        # Both fetches complete before anything is swapped in. A failure part-way
        # leaves the previous data untouched rather than half-replacing it.
        games = fetch_game_odds(api_key)
        props = fetch_player_props(api_key, name_lookup, games, sleeper_players)

        odds_games.clear()
        odds_games.update(games)
        odds_props.clear()
        odds_props.extend(props)
        odds_last_updated = datetime.datetime.utcnow().isoformat() + "Z"
        odds_last_error = None

        logger.info(
            "odds: done — %d games, %d players with props, credits_remaining=%s",
            len(odds_games), len(odds_props), odds_credits_remaining,
        )
    except OddsApiUnavailable as e:
        odds_last_error = str(e)
        logger.error(
            "odds: refresh aborted (%s). Keeping existing data: %d games, %d players.",
            e, len(odds_games), len(odds_props),
        )
    except Exception as e:
        odds_last_error = f"{type(e).__name__}: {e}"
        logger.exception("odds: refresh failed")
