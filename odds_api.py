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

BASE_URL  = "https://api.the-odds-api.com/v4"
SPORT     = "americanfootball_nfl"
REGIONS   = "us,eu"
ODDS_FORMAT = "decimal"

GAME_MARKETS = "h2h,spreads,totals"

PROP_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_anytime_td",
]

# Market key → nflverse rolling_5 stat key used for value flag comparison
PROP_ROLLING_KEY = {
    "player_pass_yds":      "passing_yards",
    "player_rush_yds":      "rushing_yards",
    "player_reception_yds": "receiving_yards",
}

# Market key → weekly stat column(s) that make up a single game's value for that
# market (used for the "Last 5" column). player_anytime_td has no single raw
# column — a game counts if the player found the end zone rushing or receiving.
PROP_GAME_STAT_COLS = {
    "player_pass_yds":      ("passing_yards",),
    "player_rush_yds":      ("rushing_yards",),
    "player_reception_yds": ("receiving_yards",),
    "player_anytime_td":    ("rushing_tds", "receiving_tds"),
}

# Market key → nflverse_team_stats "def_stat_allowed"/"def_stat_rank" stat key
# (used for the opponent-defense column — which defense-allowed stat matches
# the market being displayed)
MARKET_TO_DEF_STAT = {
    "player_pass_yds":      "passing_yards",
    "player_rush_yds":      "rushing_yards",
    "player_reception_yds": "receiving_yards",
    "player_anytime_td":    "rush_rec_tds",
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
odds_credits_remaining: int | None = None
odds_last_updated: str | None = None

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

PROPS_LOOKAHEAD_DAYS   = 14   # only fetch props for games within this rolling window
PROPS_OPENER_BUFFER_DAYS = 7  # in the off-season, extend the window to cover the opening week
PROPS_REGION = "us"           # single region for props to minimise credit use

def fetch_player_props(api_key: str, name_lookup: dict[str, str], games: dict, sleeper_players: dict | None = None) -> list:
    """
    Fetch player props per event (the bulk /odds endpoint does not support prop
    markets). Only processes games starting within the lookahead window, to
    avoid burning credits on fixtures that have no lines yet.

    The window is normally a rolling PROPS_LOOKAHEAD_DAYS from now. But deep in
    the off-season, "now + 14 days" can fall before the season even starts,
    which would fetch nothing. In that case we extend the cutoff to the first
    game of the season plus PROPS_OPENER_BUFFER_DAYS, so props for the opening
    week become available once the book actually posts them.

    sleeper_players (nfl-helper.py's `filtered_players`) is the live Sleeper
    roster feed, refreshed every 4 hours — used to override nflverse's `team`
    field, which is frozen at last completed season's roster and goes stale
    the moment a player is traded in the current offseason.
    """
    import nflverse_stats as ns
    sleeper_players = sleeper_players or {}

    now = datetime.datetime.utcnow()
    rolling_cutoff = now + datetime.timedelta(days=PROPS_LOOKAHEAD_DAYS)

    dated_games = []  # (game, parsed commence_time)
    for g in games.values():
        try:
            t = datetime.datetime.fromisoformat(g["commence_time"].replace("Z", ""))
            dated_games.append((g, t))
        except Exception:
            pass

    cutoff = rolling_cutoff
    if dated_games:
        opener_cutoff = min(t for _, t in dated_games) + datetime.timedelta(days=PROPS_OPENER_BUFFER_DAYS)
        cutoff = max(rolling_cutoff, opener_cutoff)

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

VALUE_THRESHOLD = 0.10  # rolling avg must exceed line by >10% to flag


def _market_game_value(week_entry: dict, mkey: str) -> float | None:
    """Sum the stat column(s) that make up one game's value for this market."""
    cols = PROP_GAME_STAT_COLS.get(mkey)
    if not cols:
        return None
    return round(sum(week_entry.get(c, 0.0) or 0.0 for c in cols), 1)


def _opponent_defense(mkey: str, position: str, team: str, event: dict, team_stats: dict) -> dict | None:
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

    return {
        "rank":         display_rank,
        "total_teams":  len(team_stats) or 32,
        "value":        value,
        "basis":        "rolling5" if use_r5 else "season",
    }


def _compute_value_flags(
    player_data: dict,
    player_event: dict,
    player_meta: dict,
) -> list:
    import nflverse_stats as ns

    result = []
    for sleeper_id, markets in player_data.items():
        p = ns.nflverse_player_stats.get(sleeper_id, {})
        rolling = p.get("rolling_5") or p.get("rolling_3") or {}
        meta    = player_meta.get(sleeper_id, {})
        event   = player_event.get(sleeper_id, {})

        enriched_markets = {}
        for mkey, m in markets.items():
            entry = dict(m)
            rolling_stat_key = PROP_ROLLING_KEY.get(mkey)
            rolling_avg      = rolling.get(rolling_stat_key) if rolling_stat_key else None
            line             = m.get("line")

            value_flag = None
            value_pct  = None
            if rolling_avg is not None and line and line > 0:
                diff = (rolling_avg - line) / line
                if diff > VALUE_THRESHOLD:
                    value_flag = "over"
                    value_pct  = round(diff, 3)
                elif diff < -VALUE_THRESHOLD:
                    value_flag = "under"
                    value_pct  = round(diff, 3)

            entry["rolling_avg"] = round(rolling_avg, 1) if rolling_avg is not None else None
            entry["value_flag"]  = value_flag
            entry["value_pct"]   = value_pct

            # Last 5 individual games for this market's stat (oldest → newest)
            weekly = p.get("weekly") or []
            last5 = []
            for w in weekly[-5:]:
                v = _market_game_value(w, mkey)
                if v is not None:
                    last5.append({"week": w.get("week"), "value": v})
            entry["last5"] = last5

            # Opponent defense vs. this player's position, for this market's stat
            entry["opp_defense"] = _opponent_defense(
                mkey, meta.get("position", ""), meta.get("team", ""), event, ns.nflverse_team_stats
            )

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
    global odds_games, odds_props, odds_last_updated

    if not api_key:
        logger.warning("odds: no ODDS_API_KEY set, skipping refresh")
        return

    logger.info("odds: refreshing")
    try:
        name_lookup = _build_name_lookup()

        games = fetch_game_odds(api_key)
        props = fetch_player_props(api_key, name_lookup, games, sleeper_players)

        odds_games.clear()
        odds_games.update(games)
        odds_props.clear()
        odds_props.extend(props)
        odds_last_updated = datetime.datetime.utcnow().isoformat() + "Z"

        logger.info(
            "odds: done — %d games, %d players with props, credits_remaining=%s",
            len(odds_games), len(odds_props), odds_credits_remaining,
        )
    except Exception:
        logger.exception("odds: refresh failed")
