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

PROPS_LOOKAHEAD_DAYS = 14   # only fetch props for games within this window
PROPS_REGION = "us"         # single region for props to minimise credit use

def fetch_player_props(api_key: str, name_lookup: dict[str, str], games: dict) -> list:
    """
    Fetch player props per event (the bulk /odds endpoint does not support prop
    markets). Only processes games starting within PROPS_LOOKAHEAD_DAYS to
    avoid burning credits on fixtures that have no lines yet.
    """
    import nflverse_stats as ns

    cutoff = datetime.datetime.utcnow() + datetime.timedelta(days=PROPS_LOOKAHEAD_DAYS)
    upcoming = []
    for g in games.values():
        try:
            t = datetime.datetime.fromisoformat(g["commence_time"].replace("Z", ""))
            if t <= cutoff:
                upcoming.append(g)
        except Exception:
            pass

    logger.info("odds: fetching props for %d events within %d days", len(upcoming), PROPS_LOOKAHEAD_DAYS)

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
                        "name":  o.get("name"),   # "Over" / "Under" / player name
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

                # Best over price (highest = best for bettor)
                over_outcomes  = [o for o in outcomes if o["name"] == "Over"]
                under_outcomes = [o for o in outcomes if o["name"] == "Under"]

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

                # Store meta from nflverse (authoritative)
                if sleeper_id not in player_meta:
                    p = ns.nflverse_player_stats.get(sleeper_id, {})
                    player_meta[sleeper_id] = {
                        "name":     p.get("name", ""),
                        "position": p.get("position", ""),
                        "team":     p.get("team", ""),
                    }

    # Compute value flags and assemble final list
    props_list = _compute_value_flags(player_data, player_event, player_meta)
    logger.info("odds: fetched props for %d players", len(props_list))
    return props_list


# ── Value flags ───────────────────────────────────────────────────────────────

VALUE_THRESHOLD = 0.10  # rolling avg must exceed line by >10% to flag

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

def refresh_odds_data(api_key: str | None = None) -> None:
    """Download and rebuild all odds in-memory data. Safe to call repeatedly."""
    global odds_games, odds_props, odds_last_updated

    if not api_key:
        logger.warning("odds: no ODDS_API_KEY set, skipping refresh")
        return

    logger.info("odds: refreshing")
    try:
        name_lookup = _build_name_lookup()

        games = fetch_game_odds(api_key)
        props = fetch_player_props(api_key, name_lookup, games)

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
