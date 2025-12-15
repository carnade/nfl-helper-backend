import argparse
import requests
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import json
import os
from flask_cors import CORS
import datetime
from get_dynasty_ranks import scrape_ktc, scrape_fantasy_calc, tep_adjust
from fantasydatascraper import FantasyDataScraper
from get_dfs_salaries_and_stats import DFFSalariesScraper
import random  # Import random for generating random deltas


app = Flask(__name__)

# Allowed IP prefix and specific domain
ALLOWED_IP_PREFIX = "81.235."
ALLOWED_DOMAIN = "https://nfl-draft-helper.netlify.app"
ALLOW_LOCAL = "http://localhost:3000"


# Initialize CORS to allow any origin by default
CORS(app, supports_credentials=True)


def custom_cors_origin(origin):
    if origin is None:
        return False
    if origin.startswith(f"http://{ALLOWED_IP_PREFIX}") or origin.startswith(f"https://{ALLOWED_IP_PREFIX}"):
        return True
    # USE_MOCK_DATA will be modified via command line, so we need to check it here
    if USE_MOCK_DATA and origin == ALLOW_LOCAL:
        return True
    if origin == ALLOWED_DOMAIN:
        return True
    return False


@app.after_request
def after_request(response):

    origin = request.headers.get('Origin')
    if origin and custom_cors_origin(origin):
        response.headers.add('Access-Control-Allow-Origin', origin)
        response.headers.add('Access-Control-Allow-Credentials', 'true')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


@app.before_request
def track_request_statistics():
    """
    Middleware to track request statistics for each endpoint.
    """
    global request_statistics

    # Get the endpoint being accessed
    endpoint = request.endpoint

    # Increment the request count for the endpoint
    if endpoint not in request_statistics["endpoints"]:
        request_statistics["endpoints"][endpoint] = 0
    request_statistics["endpoints"][endpoint] += 1


# Dictionary to store filtered player data
all_players = {}  # Full unfiltered Sleeper player data for matching
filtered_players = {}
scraped_ranks = {}
teams_data = {}
picks_data = {}  # Dictionary to store draft pick data
fantasy_points_data = {}  # Dictionary to store fantasy points data with Sleeper IDs
dfs_salaries_data = {}  # Dictionary to store DFS salaries data with Sleeper IDs
tinyurl_data = {}  # Dictionary to store data: {name: {data: str, created_at: str, allowed_names: List[str], user_submissions: Dict[str, {data: str, created_at: str, update_count: int, updated_at: str}]}}
tournament_data = {}  # Dictionary to store tournament data: {id: {week: int, name: str, games: list, created_at: str}}

# Global variables to track the last update times
last_players_update = None
last_rankings_update = None
last_fantasy_points_update = None
last_dfs_salaries_update = None

# URL to fetch data from
DATA_URL = "https://api.sleeper.app/v1/players/nfl"

# File to read data from when mocking
MOCK_DATA_FILE = "sleeper_data.json"

# Toggle to switch between fetching data from the API or reading from the file
USE_MOCK_DATA = False  # Will be overridden by command-line flag if set

DO_THIS_ONCE = True

# Valid fantasy positions to keep
VALID_FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "DEF", "K"}

BYE_WEEKS_2024 = {
    "ARI": 11, "ATL": 12, "BAL": 14, "BUF": 12, "CAR": 11, "CHI": 7,
    "CIN": 12, "CLE": 10, "DAL": 7, "DEN": 14, "DET": 5, "GB": 10,
    "HOU": 14, "IND": 14, "JAX": 12, "KC": 6, "LAC": 5, "LAR": 6,
    "LV": 10, "MIA": 6, "MIN": 6, "NE": 14, "NO": 12, "NYG": 11,
    "NYJ": 12, "PHI": 5, "PIT": 9, "SEA": 10, "SF": 9, "TB": 11,
    "TEN": 5, "WAS": 14
}
BYE_WEEKS_2025 = {
    "ARI": 8, "ATL": 5, "BAL": 7, "BUF": 7, "CAR": 14, "CHI": 5,
    "CIN": 10, "CLE": 9, "DAL": 10, "DEN": 12, "DET": 8, "GB": 5,
    "HOU": 6, "IND": 11, "JAX": 8, "KC": 10, "LAC": 12, "LAR": 8,
    "LV": 8, "MIA": 12, "MIN": 6, "NE": 14, "NO": 11, "NYG": 14,
    "NYJ": 9, "PHI": 9, "PIT": 5, "SF": 14, "SEA": 8, "TB": 9,
    "TEN": 10, "WAS": 12
}

WIN_OU_2025 = {
    "ARI": 8.5, "ATL": 7.5, "BAL": 11.5, "BUF": 11.5, "CAR": 6.5, "CHI": 8.5,
    "CIN": 9.5, "CLE": 5.5, "DAL": 7.5, "DEN": 9.5, "DET": 11.5, "GB": 9.5,
    "HOU": 9.5, "IND": 7.5, "JAX": 7.5, "KC": 11.5, "LAC": 9.5, "LAR": 9.5,
    "LV": 6.5, "MIA": 8.5, "MIN": 8.5, "NE": 7.5, "NO": 5.5, "NYG": 5.5,
    "NYJ": 5.5, "PHI": 11.5, "PIT": 8.5, "SF": 10.5, "SEA": 7.5, "TB": 9.5,
    "TEN": 5.5, "WAS": 9.5
}

TEAM_SCHEDULES_2025 = {
    "ARI": ["@NO", "CAR", "@SF", "SEA", "TEN", "@IND", "GB", "BYE", "@DAL", "@SEA", "SF", "JAX", "@TB", "LAR", "@HOU", "ATL", "@CIN", "@LAR"],
    "ATL": ["TB", "@MIN", "@CAR", "WSH", "BYE", "BUF", "@SF", "MIA", "@NE", "@IND", "CAR", "@NO", "@NYJ", "SEA", "@TB", "@ARI", "LAR", "NO"],
    "BAL": ["@BUF", "CLE", "DET", "@KC", "HOU", "LAR", "BYE", "CHI", "@MIA", "@MIN", "@CLE", "NYJ", "CIN", "PIT", "@CIN", "NE", "@GB", "@PIT"],
    "BUF": ["BAL", "@NYJ", "MIA", "NO", "NE", "@ATL", "BYE", "@CAR", "KC", "@MIA", "TB", "@HOU", "@PIT", "CIN", "@NE", "@CLE", "PHI", "NYJ"],
    "CAR": ["@JAX", "@ARI", "ATL", "@NE", "MIA", "DAL", "@NYJ", "BUF", "@GB", "NO", "@ATL", "@SF", "LAR", "BYE", "@NO", "TB", "SEA", "@TB"],
    "CHI": ["MIN", "@DET", "DAL", "@LV", "BYE", "@WSH", "NO", "@BAL", "@CIN", "NYG", "@MIN", "PIT", "@PHI", "@GB", "CLE", "GB", "@SF", "DET"],
    "CIN": ["@CLE", "JAX", "@MIN", "@DEN", "DET", "@GB", "PIT", "NYJ", "CHI", "BYE", "@PIT", "NE", "@BAL", "@BUF", "BAL", "@MIA", "ARI", "CLE"],
    "CLE": ["CIN", "@BAL", "GB", "@DET", "MIN", "@PIT", "MIA", "@NE", "BYE", "@NYJ", "BAL", "@LV", "SF", "TEN", "@CHI", "BUF", "PIT", "@CIN"],
    "DAL": ["@PHI", "NYG", "@CHI", "GB", "@NYJ", "@CAR", "WSH", "@DEN", "ARI", "BYE", "@LV", "PHI", "KC", "@DET", "MIN", "LAC", "@WSH", "@NYG"],
    "DEN": ["TEN", "@IND", "@LAC", "CIN", "@PHI", "@NYJ", "NYG", "DAL", "@HOU", "LV", "KC", "BYE", "@WSH", "@LV", "GB", "JAX", "@KC", "LAC"],
    "DET": ["@GB", "CHI", "@BAL", "CLE", "@CIN", "@KC", "TB", "BYE", "MIN", "@WSH", "@PHI", "NYG", "GB", "DAL", "@LAR", "PIT", "@MIN", "@CHI"],
    "GB": ["DET", "WSH", "@CLE", "@DAL", "BYE", "CIN", "@ARI", "@PIT", "CAR", "PHI", "@NYG", "MIN", "@DET", "CHI", "@DEN", "@CHI", "BAL", "@MIN"],
    "HOU": ["@LAR", "TB", "@JAX", "TEN", "@BAL", "BYE", "@SEA", "SF", "DEN", "JAX", "@TEN", "BUF", "@IND", "@KC", "ARI", "LV", "@LAC", "IND"],
    "IND": ["MIA", "DEN", "@TEN", "@LAR", "LV", "ARI", "@LAC", "TEN", "@PIT", "ATL", "BYE", "@KC", "HOU", "@JAX", "@SEA", "SF", "JAX", "@HOU"],
    "JAX": ["CAR", "@CIN", "HOU", "@SF", "KC", "SEA", "LAR", "BYE", "@LV", "@HOU", "LAC", "@ARI", "@TEN", "IND", "NYJ", "@DEN", "@IND", "TEN"],
    "KC": ["@LAC", "PHI", "@NYG", "BAL", "@JAX", "DET", "LV", "WSH", "@BUF", "BYE", "@DEN", "IND", "@DAL", "HOU", "LAC", "@TEN", "DEN", "@LV"],
    "LV": ["@NE", "LAC", "@WSH", "CHI", "@IND", "TEN", "@KC", "BYE", "JAX", "@DEN", "DAL", "CLE", "@LAC", "DEN", "@PHI", "@HOU", "NYG", "KC"],
    "LAR": ["HOU", "@TEN", "@PHI", "IND", "SF", "@BAL", "@JAX", "BYE", "NO", "@SF", "SEA", "TB", "@CAR", "@ARI", "DET", "@SEA", "@ATL", "ARI"],
    "LAC": ["KC", "@LV", "DEN", "@NYG", "WSH", "@MIA", "IND", "MIN", "@TEN", "PIT", "@JAX", "BYE", "LV", "PHI", "@KC", "@DAL", "HOU", "@DEN"],
    "MIA": ["@IND", "NE", "@BUF", "NYJ", "@CAR", "LAC", "@CLE", "@ATL", "BAL", "BUF", "WSH", "BYE", "NO", "@NYJ", "@PIT", "CIN", "TB", "@NE"],
    "MIN": ["@CHI", "ATL", "CIN", "@PIT", "@CLE", "BYE", "PHI", "@LAC", "@DET", "BAL", "CHI", "@GB", "@SEA", "WSH", "@DAL", "@NYG", "DET", "GB"],
    "NE": ["LV", "@MIA", "PIT", "CAR", "@BUF", "@NO", "@TEN", "CLE", "ATL", "@TB", "NYJ", "@CIN", "NYG", "BYE", "BUF", "@BAL", "@NYJ", "MIA"],
    "NO": ["ARI", "SF", "@SEA", "@BUF", "NYG", "NE", "@CHI", "TB", "@LAR", "@CAR", "BYE", "ATL", "@MIA", "@TB", "CAR", "NYJ", "@TEN", "@ATL"],
    "NYG": ["@WSH", "@DAL", "KC", "LAC", "@NO", "PHI", "@DEN", "@PHI", "SF", "@CHI", "GB", "@DET", "@NE", "BYE", "WSH", "MIN", "@LV", "DAL"],
    "NYJ": ["PIT", "BUF", "@TB", "@MIA", "DAL", "DEN", "CAR", "@CIN", "BYE", "CLE", "@NE", "@BAL", "ATL", "MIA", "@JAX", "@NO", "NE", "@BUF"],
    "PHI": ["DAL", "@KC", "LAR", "@TB", "DEN", "@NYG", "@MIN", "NYG", "BYE", "@GB", "DET", "@DAL", "CHI", "@LAC", "LV", "@WSH", "@BUF", "WSH"],
    "PIT": ["@NYJ", "SEA", "@NE", "MIN", "BYE", "CLE", "@CIN", "GB", "IND", "@LAC", "CIN", "@CHI", "BUF", "@BAL", "MIA", "@DET", "@CLE", "BAL"],
    "SF": ["@SEA", "@NO", "ARI", "JAX", "@LAR", "@TB", "ATL", "@HOU", "@NYG", "LAR", "@ARI", "CAR", "@CLE", "BYE", "TEN", "@IND", "CHI", "SEA"],
    "SEA": ["SF", "@PIT", "NO", "@ARI", "TB", "@JAX", "HOU", "BYE", "@WSH", "ARI", "@LAR", "@TEN", "MIN", "@ATL", "IND", "LAR", "@CAR", "@SF"],
    "TB": ["@ATL", "@HOU", "NYJ", "PHI", "@SEA", "SF", "@DET", "@NO", "BYE", "NE", "@BUF", "@LAR", "ARI", "NO", "ATL", "@CAR", "@MIA", "CAR"],
    "TEN": ["@DEN", "LAR", "IND", "@HOU", "@ARI", "@LV", "NE", "@IND", "LAC", "BYE", "HOU", "SEA", "JAX", "@CLE", "@SF", "KC", "NO", "@JAX"],
    "WAS": ["NYG", "@GB", "LV", "@ATL", "@LAC", "CHI", "@DAL", "@KC", "SEA", "DET", "@MIA", "BYE", "DEN", "@MIN", "@NYG", "PHI", "DAL", "@PHI"]
}

# Global variable to track the startup time
startup_time = datetime.datetime.now()

# Global dictionary to track request counts per endpoint
request_statistics = {
    "endpoints": {}  # Tracks request counts per endpoint
}


def get_nfl_gameweek(date):
    # Gameweek 1 started on September 5th, 2024 (a Tuesday)
    gameweek_1_start = datetime.date(2025, 9, 3)
    days_since_start = (date - gameweek_1_start).days
    # Each gameweek is effectively a 7-day window starting on Tuesdays
    gameweek = (days_since_start // 7) + 1
    return gameweek


def normalize_name(name):
    """
    Normalize player names for better matching between FantasyData and Sleeper.
    
    Args:
        name (str): Player name to normalize
        
    Returns:
        str: Normalized name
    """
    if not name:
        return ""
    
    # Convert to lowercase and remove extra spaces
    normalized = name.lower().strip()
    
    # Remove common suffixes and prefixes
    suffixes_to_remove = ['jr.', 'jr', 'sr.', 'sr', 'iii', 'ii', 'iv', 'v']
    for suffix in suffixes_to_remove:
        if normalized.endswith(' ' + suffix):
            normalized = normalized[:-len(suffix)-1].strip()
    
    # Remove periods and apostrophes
    normalized = normalized.replace('.', '').replace("'", "")
    
    # Handle common name variations
    name_variations = {
        'dj moore': 'd.j. moore',
        'aj brown': 'a.j. brown',
        'tj hockenson': 't.j. hockenson',
        'jk dobbins': 'j.k. dobbins',
        'dk metcalf': 'd.k. metcalf',
        'aj dillon': 'a.j. dillon',
        'cj stroud': 'c.j. stroud',
        'tj watt': 't.j. watt',
        'jj watt': 'j.j. watt',
        'aj green': 'a.j. green',
        'tj yeldon': 't.j. yeldon',
        'cj anderson': 'c.j. anderson',
        'dj chark': 'd.j. chark',
        'kj hamler': 'k.j. hamler',
        'aj terrell': 'a.j. terrell',
        'tj edwards': 't.j. edwards',
        'jj mccarthy': 'j.j. mccarthy',
        'brian thomas jr': 'brian thomas',
        'marvin harrison jr': 'marvin harrison jr',
        'kenneth walker iii': 'kenneth walker',
        'michael penix jr': 'michael penix',
        'marquise brown': 'hollywood brown',
        'chigoziem okonkwo': 'chig okonkwo',
        'gabriel davis': 'gabe davis',
        'calvin austin iii': 'calvin austin',
        'kj osborn': 'k.j. osborn',
        'amon-ra st brown': 'amon-ra st. brown',
        'bam knight': 'zonovan knight',
        'mitchell tinsley': 'mitch tinsley'
    }
    
    return name_variations.get(normalized, normalized)


def find_sleeper_id_by_name(fantasy_data_name, filtered_players):
    """
    Find Sleeper ID by matching FantasyData name to Sleeper player data.
    Searches filtered_players first, then all_players as fallback.
    
    Args:
        fantasy_data_name (str): Name from FantasyData
        filtered_players (dict): Dictionary of Sleeper players
    
    Returns:
        str: Sleeper ID if found, None otherwise
    """
    global all_players
    normalized_fantasy_name = normalize_name(fantasy_data_name)
    
    # Team name to abbreviation mapping for DST
    team_name_to_abbr = {
        'arizona cardinals': 'ARI',
        'atlanta falcons': 'ATL', 
        'baltimore ravens': 'BAL',
        'buffalo bills': 'BUF',
        'carolina panthers': 'CAR',
        'chicago bears': 'CHI',
        'cincinnati bengals': 'CIN',
        'cleveland browns': 'CLE',
        'dallas cowboys': 'DAL',
        'denver broncos': 'DEN',
        'detroit lions': 'DET',
        'green bay packers': 'GB',
        'houston texans': 'HOU',
        'indianapolis colts': 'IND',
        'jacksonville jaguars': 'JAX',
        'kansas city chiefs': 'KC',
        'las vegas raiders': 'LV',
        'los angeles chargers': 'LAC',
        'los angeles rams': 'LAR',
        'miami dolphins': 'MIA',
        'minnesota vikings': 'MIN',
        'new england patriots': 'NE',
        'new orleans saints': 'NO',
        'new york giants': 'NYG',
        'new york jets': 'NYJ',
        'philadelphia eagles': 'PHI',
        'pittsburgh steelers': 'PIT',
        'san francisco 49ers': 'SF',
        'seattle seahawks': 'SEA',
        'tampa bay buccaneers': 'TB',
        'tennessee titans': 'TEN',
        'washington commanders': 'WAS'
    }
    
    # First try exact match
    for sleeper_id, player_data in filtered_players.items():
        sleeper_name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
        if normalize_name(sleeper_name) == normalized_fantasy_name:
            return sleeper_id
    
    # Try DST team matching
    if normalized_fantasy_name in team_name_to_abbr:
        team_abbr = team_name_to_abbr[normalized_fantasy_name]
        # Look for DST players with matching team abbreviation
        for sleeper_id, player_data in filtered_players.items():
            if (player_data.get('position') == 'DEF' and 
                player_data.get('team') == team_abbr):
                return sleeper_id
    
    # Try partial matches (first name + last name variations)
    fantasy_parts = normalized_fantasy_name.split()
    if len(fantasy_parts) >= 2:
        first_name = fantasy_parts[0]
        last_name = ' '.join(fantasy_parts[1:])
        
        for sleeper_id, player_data in filtered_players.items():
            sleeper_first = normalize_name(player_data.get('first_name', ''))
            sleeper_last = normalize_name(player_data.get('last_name', ''))
            
            # Check if first and last names match
            if sleeper_first == first_name and sleeper_last == last_name:
                return sleeper_id
            
            # Check if last name matches and first name is similar
            if sleeper_last == last_name and first_name in sleeper_first:
                return sleeper_id
    
    # If not found in filtered_players, try all_players as fallback (for edge cases like DT players)
    if all_players:
        # First try exact match in all_players
        for sleeper_id, player_data in all_players.items():
            sleeper_name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
            if normalize_name(sleeper_name) == normalized_fantasy_name:
                return sleeper_id
        
        # Then try partial matches
        fantasy_parts = normalized_fantasy_name.split()
        if len(fantasy_parts) >= 2:
            first_name = fantasy_parts[0]
            last_name = ' '.join(fantasy_parts[1:])
            
            for sleeper_id, player_data in all_players.items():
                sleeper_first = normalize_name(player_data.get('first_name', ''))
                sleeper_last = normalize_name(player_data.get('last_name', ''))
                
                # Check if first and last names match
                if sleeper_first == first_name and sleeper_last == last_name:
                    return sleeper_id
                
                # Check if last name matches and first name is similar
                if sleeper_last == last_name and first_name in sleeper_first:
                    return sleeper_id
    
    return None


def update_fantasy_points_data():
    """
    Update fantasy points data by scraping FantasyData and matching to Sleeper IDs.
    Stores data with key format: "sleeper_id_week" to support multiple weeks.
    """
    global fantasy_points_data, last_fantasy_points_update
    
    print(f"{datetime.datetime.now()} - Starting fantasy points data update...")
    
    if USE_MOCK_DATA:
        print("Using mock mode - skipping FantasyData scraping")
        last_fantasy_points_update = datetime.datetime.now()
        print(f"Fantasy points skipped in mock mode at {last_fantasy_points_update}")
        return
    
    try:
        # Initialize scraper
        scraper = FantasyDataScraper()
        
        # Scrape all positions
        all_fantasy_data = scraper.scrape_all_positions()
        
        # Get current week for this update
        current_week = scraper.get_current_week()
        
        # Process each position
        for position, players in all_fantasy_data.items():
            for player in players:
                player_name = player.get('name', '')
                fantasy_points = player.get('fantasy_points', 0)
                week = player.get('week', current_week)
                
                if player_name and fantasy_points is not None:
                    # Find matching Sleeper ID
                    sleeper_id = find_sleeper_id_by_name(player_name, filtered_players)
                    
                    if sleeper_id:
                        # Create key with sleeper_id and week
                        key = f"{sleeper_id}_{week}"
                        fantasy_points_data[key] = {
                            'sleeper_id': sleeper_id,
                            'name': player_name,
                            'fantasy_points': fantasy_points,
                            'position': position,
                            'week': week,
                            'team': player.get('team', None)
                        }
                    else:
                        print(f"No Sleeper ID found for: {player_name} ({position})")
        
        # Update timestamp
        last_fantasy_points_update = datetime.datetime.now()
        print(f"Fantasy points updated at {last_fantasy_points_update}")
        print(f"Total fantasy points entries: {len(fantasy_points_data)}")
        print(f"Current week data: {current_week}")
        
    except Exception as e:
        print(f"Error updating fantasy points data: {e}")


def update_dfs_salaries_data():
    """
    Update DFS salaries data by fetching from DailyFantasyFuel and matching to Sleeper IDs.
    Uses dynamic slate detection to always get the main slate with the most teams.
    Stores only one entry per player (most recent data).
    """
    global dfs_salaries_data, last_dfs_salaries_update, all_players
    
    print(f"{datetime.datetime.now()} - Starting DFS salaries data update...")
    
    if USE_MOCK_DATA:
        print("Using mock mode - skipping DFF scraping")
        last_dfs_salaries_update = datetime.datetime.now()
        print(f"DFS salaries skipped in mock mode at {last_dfs_salaries_update}")
        return
    
    try:
        # Initialize DFF scraper
        scraper = DFFSalariesScraper()
        
        # Get current date for slate detection
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        print(f"Fetching DFS salaries for date: {today}")
        print(f"all_players count: {len(all_players)}")
        
        # Scrape DFF projections with Sleeper ID matching (use all_players, not filtered_players)
        parsed_salaries = scraper.get_salaries_with_sleeper_ids(all_players, date=today)
        
        if not parsed_salaries:
            print(f"No DFS salary data scraped for {today}. Aborting DFS salaries update.")
            return
        
        # Get current week from the scraped data
        current_week = parsed_salaries[0].get('week', 0) if parsed_salaries else 0
        
        # Clean up old data (keep only current and previous week)
        weeks_to_keep = {current_week, current_week - 1}
        keys_to_delete = []
        
        for key in list(dfs_salaries_data.keys()):
            # Extract week from existing entries
            existing_week = dfs_salaries_data[key].get('week', 0)
            if existing_week not in weeks_to_keep:
                keys_to_delete.append(key)
        
        for key in keys_to_delete:
            del dfs_salaries_data[key]
        
        if keys_to_delete:
            print(f"Cleaned up {len(keys_to_delete)} old entries, keeping weeks {weeks_to_keep}")
        
        # Add new data with week in the key (supports multi-week storage)
        # Note: Scheduled updates do NOT update salaries - they only log differences
        salary_differences = []
        added_count = 0
        updated_count = 0
        
        for player in parsed_salaries:
            # Use sleeper_id + week as composite key if available, otherwise use name+team+week
            if player.get("sleeper_id"):
                key = f"{player['sleeper_id']}_W{player.get('week', 0)}"
            else:
                key = f"{player['name']}_{player['team']}_W{player.get('week', 0)}"
            
            # Check if player already exists
            existing_player = dfs_salaries_data.get(key)
            new_salary = player.get('salary', 0)
            
            # Log salary differences if player exists
            if existing_player:
                existing_salary = existing_player.get('salary', 0)
                if existing_salary != new_salary:
                    salary_differences.append({
                        "name": player.get('name'),
                        "team": player.get('team'),
                        "sleeper_id": player.get('sleeper_id'),
                        "existing_salary": existing_salary,
                        "new_salary": new_salary,
                        "difference": new_salary - existing_salary
                    })
            
            # Add date to the player data
            player_with_date = player.copy()
            player_with_date["date"] = today
            
            # Keep existing salary if player already exists (scheduled updates don't update salaries)
            if existing_player:
                player_with_date["salary"] = existing_player.get('salary', new_salary)
                updated_count += 1
            else:
                added_count += 1
            
            dfs_salaries_data[key] = player_with_date
        
        # Log salary differences
        if salary_differences:
            print(f"{datetime.datetime.now()} - Salary differences found (scheduled update - salaries NOT updated):")
            for diff in salary_differences[:20]:  # Log first 20
                print(f"  {diff['name']} ({diff['team']}): ${diff['existing_salary']:,} -> ${diff['new_salary']:,} (diff: ${diff['difference']:+,})")
            if len(salary_differences) > 20:
                print(f"  ... and {len(salary_differences) - 20} more differences")
            print(f"Total salary differences: {len(salary_differences)} (salaries NOT updated in scheduled run)")
        
        last_dfs_salaries_update = datetime.datetime.now()
        
        # Count matched players
        matched_count = sum(1 for p in dfs_salaries_data.values() if p.get("sleeper_id") is not None)
        
        print(f"DFS salaries updated at {last_dfs_salaries_update}")
        print(f"Added {added_count} new players, updated {updated_count} existing players (salaries preserved) for week {current_week}")
        print(f"Total DFS salary entries in memory: {len(dfs_salaries_data)}")
        print(f"Matched to Sleeper IDs: {matched_count}")
        print(f"Date: {today}")
        
    except Exception as e:
        print(f"Error updating DFS salaries data: {e}")


def get_fantasy_points_for_player(sleeper_id, week=None):
    """
    Get fantasy points data for a specific player and week.
    
    Args:
        sleeper_id (str): Sleeper player ID
        week (int, optional): Week number. If None, returns all weeks for the player.
        
    Returns:
        dict or list: Fantasy points data for the player
    """
    if week is not None:
        # Get specific week data
        key = f"{sleeper_id}_{week}"
        return fantasy_points_data.get(key, None)
    else:
        # Get all weeks for the player
        player_data = []
        for key, data in fantasy_points_data.items():
            if data.get('sleeper_id') == sleeper_id:
                player_data.append(data)
        return player_data


def get_fantasy_points_by_week(week):
    """
    Get all fantasy points data for a specific week.
    
    Args:
        week (int): Week number
        
    Returns:
        dict: Fantasy points data for the week, keyed by sleeper_id
    """
    week_data = {}
    for key, data in fantasy_points_data.items():
        if data.get('week') == week:
            sleeper_id = data.get('sleeper_id')
            if sleeper_id:
                week_data[sleeper_id] = data
    return week_data


def fetch_data():
    if USE_MOCK_DATA:
        # Read data from the file
        if os.path.exists(MOCK_DATA_FILE):
            with open(MOCK_DATA_FILE, 'r') as file:
                return json.load(file)
        else:
            print(f"Mock data file {MOCK_DATA_FILE} not found.")
            return {}
    else:
        # Fetch data from the API
        response = requests.get(DATA_URL)
        print(str(datetime.datetime.now()) + " Fetched Data - response code: ", response.status_code)
        response.raise_for_status()  # Raises an exception for HTTP errors
        return response.json()


def fetch_and_filter_data():
    global all_players, filtered_players, scraped_ranks, teams_data, last_players_update

    data = fetch_data()
    
    # Store the full unfiltered data for matching purposes
    all_players = data
    filtered_players.clear()
    teams_data.clear()

    for player_id, player_data in data.items():
        on_bye = False
        fantasy_positions = player_data.get("fantasy_positions")

        if player_data.get("team") is not None:
            try:
                # Compare the player's team bye to today's gameweek
                if (BYE_WEEKS_2025[player_data.get("team")]
                        == get_nfl_gameweek(datetime.date.today())):
                    on_bye = True
            except:
                print(f"Team not found in BYE_WEEKS_2025: {player_data.get('team')}")

        if fantasy_positions is None:
            fantasy_positions = []

        # Check if the player is active and has a valid fantasy position
        if not ((player_data.get("status") == "Inactive")
                and (player_data.get("injury_status") is None or on_bye)) \
                and any(pos in VALID_FANTASY_POSITIONS for pos in fantasy_positions):

            filtered_players[player_id] = {
                "status": player_data.get("status"),
                "first_name": player_data.get("first_name"),
                "last_name": player_data.get("last_name"),
                "age": player_data.get("age"),
                "position": player_data.get("position"),
                "competitions": player_data.get("competitions"),
                "sportradar_id": player_data.get("sportradar_id"),
                "oddsjam_id": player_data.get("oddsjam_id"),
                "swish_id": player_data.get("swish_id"),
                "espn_id": player_data.get("espn_id"),
                "fantasy_data_id": player_data.get("fantasy_data_id"),
                "yahoo_id": player_data.get("yahoo_id"),
                "rotowire_id": player_data.get("rotowire_id"),
                "injury_status": player_data.get("injury_status")
                if player_data.get("injury_status") is not None
                else ("Bye" if on_bye else None)
            }

            # Collect data by team for the /teams endpoint
            team_abbr = player_data.get("team")
            if team_abbr:
                if team_abbr not in teams_data:
                    teams_data[team_abbr] = []
                if player_data.get("injury_status"):
                    teams_data[team_abbr].append({
                        "first_name": player_data.get("first_name"),
                        "last_name": player_data.get("last_name"),
                        "injury_status": player_data.get("injury_status")
                    })

    # Fetch projections and update filtered_players
    projections = get_player_projections()
    for projection in projections:
        player_id = projection.get("player_id")
        if player_id in filtered_players:
            stats = projection.get("stats", {})
            filtered_players[player_id].update({
                "adp_2qb": stats.get("adp_2qb", None),
                "adp_dynasty_2qb": stats.get("adp_dynasty_2qb", None),
                "adp_half_ppr": stats.get("adp_half_ppr", None),
                "adp_ppr": stats.get("adp_ppr", None)
            })

    # Calculate ADP ranks within each position
    calculate_adp_ranks()

    # Fetch stats and update filtered_players
    stats = get_player_stats()
    for stat in stats:
        player_id = stat.get("player_id")
        if player_id in filtered_players:
            player_stats = stat.get("stats", {})
            filtered_players[player_id].update({
                "pos_rank_std": player_stats.get("pos_rank_std", None),
                "gp": player_stats.get("gp", None),
                "rank_half_ppr": player_stats.get("rank_half_ppr", None),
                "pos_rank_half_ppr": player_stats.get("pos_rank_half_ppr", None),
                "pos_rank_ppr": player_stats.get("pos_rank_ppr", None),
                "rank_ppr": player_stats.get("rank_ppr", None),
                "pts_half_ppr": player_stats.get("pts_half_ppr", None),
                "pts_ppr": player_stats.get("pts_ppr", None)
            })

    # Update the last players update timestamp
    last_players_update = datetime.datetime.now()
    print(f"Players updated at {last_players_update}")

    if scraped_ranks:
        print(f"{datetime.datetime.now()} - Updated filtered_players with old scraped data.")
        update_players_with_old_data()


def calculate_adp_ranks():
    """
    Calculate ADP ranks for each player within their position.
    """
    # Group players by position
    positions = {"QB": [], "RB": [], "WR": [], "TE": []}
    for player_id, player_data in filtered_players.items():
        position = player_data.get("position")
        if position in positions:
            positions[position].append((player_id, player_data))

    # ADP types to calculate ranks for
    adp_types = ["adp_2qb", "adp_dynasty_2qb", "adp_half_ppr", "adp_ppr"]

    # Calculate ranks for each position and ADP type
    for position, players in positions.items():
        for adp_type in adp_types:
            # Sort players by the current ADP type (ignoring None values)
            sorted_players = sorted(
                [p for p in players if p[1].get(adp_type) is not None],
                key=lambda x: x[1][adp_type]
            )

            # Assign ranks
            for rank, (player_id, _) in enumerate(sorted_players, start=1):
                if player_id in filtered_players:
                    filtered_players[player_id][f"{adp_type}_rank"] = rank


def update_players_with_old_data():
    """Update filtered_players with pre-scraped data stored in scraped_ranks."""
    global filtered_players, scraped_ranks

    print(f"{datetime.datetime.now()} - Updating filtered_players with old scraped data...")

    for sleeper_id, player in scraped_ranks.items():
        if sleeper_id in filtered_players:
            existing_player = filtered_players[sleeper_id]

            filtered_players[sleeper_id].update({
                "KTC Position Rank": player["Position Rank"],
                "KTC Value": player["SFValue"] if player["SFValue"] != 0 else player["Value"],
                "KTC Delta": player["KTC Delta"],
                "FC Position Rank": player["FantasyCalc SF Position Rank"],
                "FC Value": player["FantasyCalc SF Value"],
                "FC Delta": player["FC Delta"],
            })
        else:
            print(f"No match found for Sleeper ID: {sleeper_id}")

    print(f"{datetime.datetime.now()} - Finished updating filtered_players with old data.")


def update_filtered_players_with_scraped_data():
    global filtered_players, scraped_ranks, last_rankings_update, picks_data

    print(f"{datetime.datetime.now()} - Starting data scraping and updating filtered_players...")

    if USE_MOCK_DATA:
        print("Using mock mode - skipping KTC and FantasyCalc scraping")
        # In mock mode, just use empty rankings
        adjusted_players = []
    else:
        print("Scraping data from KTC and FantasyCalc...")
        tep_level = 1  # TEP adjustment level (0=none, 1=standard, 2=high, 3=very high)
        ktc_players = scrape_ktc()
        ktc_players = scrape_fantasy_calc(ktc_players)
        adjusted_players = tep_adjust(ktc_players, tep_level)

    # Save scraped ranks as a dictionary with sleeper_id as the key
    scraped_ranks = {player["Sleeper ID"]: player for player in adjusted_players if "Sleeper ID" in player and player["Sleeper ID"] is not None}
    
    # Save picks data as a dictionary with pick_id as the key
    picks_data = {player["Pick ID"]: player for player in adjusted_players if "Pick ID" in player and player.get("Is Future Pick", False)}

    # Update filtered_players with the provided or scraped data
    for sleeper_id, player in scraped_ranks.items():
        if sleeper_id in filtered_players:
            existing_player = filtered_players[sleeper_id]

            if "KTC Delta" not in existing_player:
                ktc_delta = 0
            else:
                ktc_delta = player.get("SFValue", 0) - existing_player.get("KTC Value", 0)
            if "FC Delta" not in existing_player:
                fc_delta = 0
            else:
                fc_delta = player.get("FantasyCalc SF Value", 0) - existing_player.get("FC Value", 0)

            updated_data = {
                "KTC Position Rank": player.get("Position Rank", 0),
                "KTC Value": player.get("SFValue", 0) if player.get("SFValue", 0) != 0 else player.get("Value", 0),
                "KTC Delta": ktc_delta,
                "FC Position Rank": player.get("FantasyCalc SF Position Rank", 0),
                "FC Value": player.get("FantasyCalc SF Value", 0),
                "FC Delta": fc_delta,
            }

            # Update filtered_players
            filtered_players[sleeper_id].update(updated_data)

            # Update scraped_ranks
            scraped_ranks[sleeper_id].update(updated_data)
        else:
            print(f"No match found for Sleeper ID: {sleeper_id}")

    # Update the last rankings update timestamp
    last_rankings_update = datetime.datetime.now()
    print(f"Rankings updated at {last_rankings_update}")

    print(f"{datetime.datetime.now()} - Finished updating filtered_players.")


# Schedule the data fetch task
scheduler = BackgroundScheduler()

# Schedule the default job to run every 4 hours
scheduler.add_job(func=fetch_and_filter_data, trigger="interval", hours=4)

# Schedule the job to run on Thursdays, Sundays, Mondays between 12:00 PM and 11:59 PM
scheduler.add_job(
    func=fetch_and_filter_data,
    trigger=CronTrigger(day_of_week="thu,sun,mon", hour="12-23", minute=0)
)

# Schedule the new job to run every Wednesday at 08:00
scheduler.add_job(
    func=update_filtered_players_with_scraped_data,
    trigger=CronTrigger(day_of_week="wed", hour=8, minute=0)
)

# Schedule fantasy points updates on Wednesday at 15:00, 16:00, 17:00, 18:00, 19:00
scheduler.add_job(
    func=update_fantasy_points_data,
    trigger=CronTrigger(day_of_week="sun", hour=23, minute=0)
)
scheduler.add_job(
    func=update_fantasy_points_data,
    trigger=CronTrigger(day_of_week="tue", hour=6, minute=0)
)
scheduler.add_job(
    func=update_fantasy_points_data,
    trigger=CronTrigger(day_of_week="tue", hour=7, minute=0)
)
scheduler.add_job(
    func=update_fantasy_points_data,
    trigger=CronTrigger(day_of_week="tue", hour=8, minute=0)
)


# Schedule fantasy points updates on Thursday, Friday, Saturday, Sunday, Monday at 17:00
scheduler.add_job(
    func=update_fantasy_points_data,
    trigger=CronTrigger(day_of_week="fri,mon", hour=8, minute=0)
)
scheduler.add_job(
    func=update_fantasy_points_data,
    trigger=CronTrigger(day_of_week="fri,mon", hour=7, minute=0)
)

# Schedule DFS salaries update daily at 14:00 CET
scheduler.add_job(
    func=update_dfs_salaries_data,
    trigger=CronTrigger(hour=15, minute=0)
)

# Schedule DFS salaries update on Wednesdays at 19:00 CET
scheduler.add_job(
    func=update_dfs_salaries_data,
    trigger=CronTrigger(day_of_week="wed", hour=19, minute=0)
)

def clear_tinyurl_data():
    """Clear tinyurl_data entries for weeks that are older than the current week"""
    global tinyurl_data
    
    try:
        # Get current week from Sleeper
        scraper = FantasyDataScraper()
        current_week = scraper.get_current_week()
        
        # Ensure current_week is an integer
        if current_week is None:
            print(f"{datetime.datetime.now()} - Error: Could not determine current week. Skipping cleanup.")
            return
        
        current_week = int(current_week)
        
        # Keep current week and all future weeks, delete only weeks older than current
        entries_to_delete = []
        entries_to_keep = []
        
        for name, entry in tinyurl_data.items():
            entry_week = entry.get('week')
            entry_name = entry.get('name', name)
            
            # Log the raw entry_week value for debugging
            print(f"{datetime.datetime.now()} - Processing entry '{entry_name}': raw week value = {entry_week} (type: {type(entry_week).__name__})")
            
            # Convert entry_week to int if it's not None
            if entry_week is not None:
                try:
                    entry_week = int(entry_week)
                    print(f"{datetime.datetime.now()} - Entry '{entry_name}': converted week to int: {entry_week}")
                except (ValueError, TypeError) as e:
                    print(f"{datetime.datetime.now()} - Warning: Entry '{entry_name}' has invalid week value: {entry_week} (type: {type(entry_week).__name__}). Error: {e}. Treating as None.")
                    entry_week = None
            
            # Keep entries where entry_week >= current_week (current week and all future weeks)
            # Delete entries where entry_week < current_week (older weeks) or entry_week is None
            if entry_week is None:
                print(f"{datetime.datetime.now()} - Marking entry '{entry_name}' for deletion (no week field)")
                entries_to_delete.append(name)
            elif entry_week < current_week:
                print(f"{datetime.datetime.now()} - Marking entry '{entry_name}' (week {entry_week}) for deletion (older than current week {current_week})")
                entries_to_delete.append(name)
            else:
                # entry_week >= current_week, so keep it
                print(f"{datetime.datetime.now()} - Keeping entry '{entry_name}' (week {entry_week}) (current week: {current_week}, condition: {entry_week} >= {current_week})")
                entries_to_keep.append((name, entry_week))
        
        # Delete entries that are older than current week
        for name in entries_to_delete:
            del tinyurl_data[name]
        
        print(f"{datetime.datetime.now()} - TinyURL data cleared: removed {len(entries_to_delete)} entries older than week {current_week} (kept {len(tinyurl_data)} entries for week {current_week} and future weeks)")
        if entries_to_keep:
            kept_weeks = [week for _, week in entries_to_keep]
            print(f"{datetime.datetime.now()} - Kept entries with weeks: {kept_weeks}")
    except Exception as e:
        print(f"{datetime.datetime.now()} - Error clearing TinyURL data: {e}")
        import traceback
        traceback.print_exc()
        # Fallback: clear all if we can't get current week
        tinyurl_data.clear()
        print(f"{datetime.datetime.now()} - TinyURL data cleared (fallback: all entries)")

def clear_tournament_data():
    """Clear tournament_data entries for weeks that are older than the previous week (keep current and previous week)"""
    global tournament_data
    
    try:
        # Get current week from Sleeper
        scraper = FantasyDataScraper()
        current_week = scraper.get_current_week()
        
        # Ensure current_week is an integer
        if current_week is None:
            print(f"{datetime.datetime.now()} - Error: Could not determine current week. Skipping tournament cleanup.")
            return
        
        current_week = int(current_week)
        
        # Keep current and previous week, delete older weeks (same logic as DFS)
        weeks_to_keep = {current_week, current_week - 1}
        keys_to_delete = []
        
        for tour_id, tour in tournament_data.items():
            tour_week = tour.get('week')
            if tour_week is not None:
                try:
                    tour_week = int(tour_week)
                    if tour_week not in weeks_to_keep:
                        keys_to_delete.append(tour_id)
                except (ValueError, TypeError):
                    print(f"{datetime.datetime.now()} - Warning: Tournament '{tour_id}' has invalid week value: {tour_week}")
        
        # Delete old tournaments
        for key in keys_to_delete:
            del tournament_data[key]
        
        if keys_to_delete:
            print(f"{datetime.datetime.now()} - Tournament data cleared: removed {len(keys_to_delete)} tournaments older than week {current_week - 1} (kept {len(tournament_data)} tournaments for weeks {weeks_to_keep})")
    except Exception as e:
        print(f"{datetime.datetime.now()} - Error clearing tournament data: {e}")
        import traceback
        traceback.print_exc()

# Schedule TinyURL data clearing every Thursday at 19:00 CET
scheduler.add_job(
    func=clear_tinyurl_data,
    trigger=CronTrigger(day_of_week="thu", hour=9, minute=0)
)

# Schedule tournament data clearing every Thursday at 19:00 CET (same as TinyURL)
scheduler.add_job(
    func=clear_tournament_data,
    trigger=CronTrigger(day_of_week="thu", hour=9, minute=0)
)

scheduler.start()

# Ensure the scheduler is shut down when the app exits
atexit.register(lambda: scheduler.shutdown())


@app.route('/getplayers', methods=['POST'])
def get_players():
    request_data = request.json
    response_data = []
    username = request_data.get("username")
    leagues = request_data.get("league", [])

    print(f"{datetime.datetime.now()} Fetch injury report for user: {username}")

    if isinstance(leagues, list):
        for league in leagues:
            if isinstance(league, dict):
                league_id = league.get("league_id")
                player_ids = league.get("playerlist", [])
                players_info = {
                    pid: filtered_players.get(pid)
                    for pid in player_ids if pid in filtered_players
                }
                response_data.append({
                    "league_id": league_id,
                    "players": players_info
                })
            else:
                print(f"Unexpected league format: {league}")
    else:
        print("Leagues data is not a list")

    return jsonify(response_data)

@app.route('/getplayers/bestball', methods=['POST'])
def get_bestball_players():
    request_data = request.json
    player_ids = request_data.get("playerlist", [])

    if not isinstance(player_ids, list):
        return jsonify({"error": "Invalid player IDs"}), 400

    players_info = {
        pid: filtered_players.get(pid)

        for pid in player_ids if pid in filtered_players
    }

    players_data = [{"id": pid, "name": f"{player.get('first_name')} {player.get('last_name')}", "position": player.get("position")} for pid, player in players_info.items()]

    return jsonify({"players": players_data})

@app.route('/getplayers/data', methods=['POST'])
def get_all_players():
    """
    Endpoint to return filtered players based on a list of Sleeper IDs.
    Can also include draft picks when requested.

    Request Body:
        {
            "playerlist": [12345, 67890, ...],
            "include_picks": true/false (optional, defaults to false)
        }

    Returns:
        JSON response containing the filtered players matching the Sleeper IDs.
        If include_picks is true, also includes draft picks.
    """
    request_data = request.json
    player_ids = request_data.get("playerlist", [])
    include_picks = request_data.get("include_picks", False)

    if not isinstance(player_ids, list):
        return jsonify({"error": "Invalid player_list format. Must be a list of Sleeper IDs."}), 400

    # Filter players based on the provided Sleeper IDs
    players_info = {
        pid: filtered_players.get(pid)
        for pid in player_ids if pid in filtered_players
    }

    # Add picks if requested
    if include_picks:
        # Add all picks to the response
        players_info.update(picks_data)

    return jsonify(players_info), 200

@app.route('/picks/data', methods=['GET'])
def get_all_picks():
    """
    Endpoint to return all draft picks data.

    Returns:
        JSON response containing all draft picks with their values and metadata.
    """
    return jsonify(picks_data), 200


@app.route('/fantasy-points/data', methods=['GET'])
def get_fantasy_points_data():
    """
    Endpoint to return all fantasy points data.

    Returns:
        JSON response containing fantasy points data with Sleeper IDs.
    """
    return jsonify(fantasy_points_data), 200


@app.route('/fantasy-points/week/<int:week>', methods=['GET'])
def get_fantasy_points_by_week_endpoint(week):
    """
    Endpoint to return fantasy points data for a specific week.

    Args:
        week (int): Week number

    Returns:
        JSON response containing fantasy points data for the specified week.
    """
    try:
        week_data = get_fantasy_points_by_week(week)
        return jsonify(week_data), 200
    except Exception as e:
        print(f"Error in get_fantasy_points_by_week_endpoint: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/fantasy-points/player/<sleeper_id>', methods=['GET'])
def get_fantasy_points_for_player_endpoint(sleeper_id):
    """
    Endpoint to return fantasy points data for a specific player.

    Args:
        sleeper_id (str): Sleeper player ID

    Query Parameters:
        week (int, optional): Week number. If not provided, returns all weeks.

    Returns:
        JSON response containing fantasy points data for the player.
    """
    week = request.args.get('week', type=int)
    player_data = get_fantasy_points_for_player(sleeper_id, week)
    return jsonify(player_data), 200

@app.route('/teams', methods=['GET'])
def get_teams():
    return jsonify(teams_data)


@app.route('/teams/schedules', methods=['GET'])
def get_team_schedules():
    """
    Endpoint to return the 2025 NFL team schedules.

    Returns:
        JSON response containing the team schedules for 2025.
    """
    return jsonify(TEAM_SCHEDULES_2025), 200


@app.route('/statistics', methods=['GET'])
def get_statistics():
    """
    Endpoint to return request statistics.

    Returns:
        JSON response containing uptime, request counts per endpoint, and average requests per day.
    """
    global request_statistics, startup_time, last_players_update, last_rankings_update, last_fantasy_points_update, last_dfs_salaries_update, dfs_salaries_data

    try:
        # Calculate uptime
        current_time = datetime.datetime.now()
        uptime = current_time - startup_time

        # Calculate the total number of requests
        total_requests = sum(request_statistics["endpoints"].values())

        # Calculate the number of days since startup
        days_since_startup = max(uptime.days + 1, 1)  # Add 1 to avoid division by zero

        # Calculate the average requests per day
        average_requests_per_day = total_requests / days_since_startup

        # Count DFS salaries entries
        total_dfs_salaries = len(dfs_salaries_data)
        
        # Get weeks and dates from DFS data
        dfs_weeks = set()
        dfs_dates = set()
        if dfs_salaries_data:
            for player_data in dfs_salaries_data.values():
                week = player_data.get("week")
                date = player_data.get("date")
                if week:
                    dfs_weeks.add(week)
                if date:
                    dfs_dates.add(date)
        
        # Prepare the response
        response = {
            "uptime": str(uptime),  # Format uptime as a string
            "total_requests": total_requests,
            "average_requests_per_day": average_requests_per_day,
            "requests_per_endpoint": request_statistics["endpoints"],
            "total_dfs_salaries": total_dfs_salaries,
            "dfs_salaries_weeks": sorted(list(dfs_weeks)) if dfs_weeks else [],
            "dfs_salaries_dates": sorted(list(dfs_dates)) if dfs_dates else [],
            "last_players_update": str(last_players_update) if last_players_update else "Never",
            "last_rankings_update": str(last_rankings_update) if last_rankings_update else "Never",
            "last_fantasy_points_update": str(last_fantasy_points_update) if last_fantasy_points_update else "Never",
            "last_dfs_salaries_update": str(last_dfs_salaries_update) if last_dfs_salaries_update else "Never"
        }

        # Filter valid endpoints
        valid_endpoints = {
            str(key): int(value) for key, value in request_statistics["endpoints"].items()
            if isinstance(key, str) and isinstance(value, int)
        }
        response["requests_per_endpoint"] = valid_endpoints

        return jsonify(response), 200

    except Exception as e:
        # Debugging: Log the error
        print(f"Error in /statistics endpoint: {e}")
        # Debugging: Log the response data
        print("Response data:", response)
        return jsonify({"error": str(e)}), 500


@app.route('/admin/rankings/update', methods=['POST'])
def admin_update_rankings():
    """
    Admin endpoint to manually trigger a rankings update.

    Request Body (optional):
        {
            "input_data": [...]  # Optional list of player dictionaries to update rankings
        }

    Returns:
        JSON response indicating success or failure.
    """
    try:


        # Call the rankings update method
        update_filtered_players_with_scraped_data()

        return jsonify({"message": "Rankings update triggered successfully."}), 200
    except Exception as e:
        print(f"Error while triggering rankings update: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/admin/fantasy-points/update', methods=['POST'])
def admin_update_fantasy_points():
    """
    Admin endpoint to manually trigger a fantasy points update.

    Returns:
        JSON response indicating success or failure.
    """
    try:
        # Call the fantasy points update method
        update_fantasy_points_data()

        return jsonify({"message": "Fantasy points update triggered successfully."}), 200
    except Exception as e:
        print(f"Error while triggering fantasy points update: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/admin/fantasy-points/update-week/<int:week>', methods=['POST'])
def update_fantasy_points_for_week(week):
    """
    Admin endpoint to update fantasy points data for a specific week.
    
    Args:
        week (int): The week number to update (e.g., 1-18)
        
    Returns:
        JSON response indicating success or failure.
    """
    try:
        print(f"{datetime.datetime.now()} - Starting fantasy points update for week {week}...")
        
        if USE_MOCK_DATA:
            print("Using mock mode - skipping FantasyData scraping")
            return jsonify({"message": f"Fantasy points update for week {week} skipped in mock mode."}), 200
        
        # Initialize scraper
        scraper = FantasyDataScraper()
        
        # Scrape all positions for the specific week
        all_fantasy_data = scraper.scrape_all_positions(week_from=week, week_to=week)
        
        if not all_fantasy_data:
            return jsonify({"error": f"No fantasy data found for week {week}"}), 404
        
        # Process each position
        players_updated = 0
        for position, players in all_fantasy_data.items():
            for player in players:
                player_name = player.get('name', '')
                fantasy_points = player.get('fantasy_points', 0)
                player_week = player.get('week', week)
                
                if player_name and fantasy_points is not None:
                    # Find matching Sleeper ID
                    sleeper_id = find_sleeper_id_by_name(player_name, filtered_players)
                    
                    if sleeper_id:
                        # Create key with sleeper_id and week
                        key = f"{sleeper_id}_{player_week}"
                        fantasy_points_data[key] = {
                            'sleeper_id': sleeper_id,
                            'name': player_name,
                            'fantasy_points': fantasy_points,
                            'position': position,
                            'week': player_week,
                            'team': player.get('team', None)
                        }
                        players_updated += 1
                    else:
                        print(f"No Sleeper ID found for: {player_name} ({position})")
        
        print(f"Fantasy points updated for week {week} at {datetime.datetime.now()}")
        print(f"Updated {players_updated} players for week {week}")
        print(f"Total fantasy points entries: {len(fantasy_points_data)}")
        
        return jsonify({
            "message": f"Fantasy points update for week {week} completed successfully.",
            "players_updated": players_updated,
            "total_entries": len(fantasy_points_data)
        }), 200
        
    except Exception as e:
        print(f"Error while updating fantasy points for week {week}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/dfs-salaries/data', methods=['GET'])
def get_dfs_salaries_data():
    """
    Endpoint to return all DFS salaries data.

    Returns:
        JSON response containing DFS salaries data with Sleeper IDs.
    """
    return jsonify(dfs_salaries_data), 200


@app.route('/dfs-salaries/player/<sleeper_id>', methods=['GET'])
def get_dfs_salaries_for_player_endpoint(sleeper_id):
    """
    Endpoint to return DFS salaries data for a specific player.
    
    Args:
        sleeper_id (str): Sleeper player ID
        
    Query Parameters:
        week (int, optional): Specific week to query. If not provided, returns all weeks.

    Returns:
        JSON response containing DFS salaries data for the player.
    """
    try:
        week = request.args.get('week', type=int)
        
        if week:
            # Get specific week data
            key = f"{sleeper_id}_W{week}"
            player_data = dfs_salaries_data.get(key)
            
            if player_data:
                return jsonify(player_data), 200
            else:
                return jsonify({"error": f"No DFS data for player {sleeper_id} in week {week}"}), 404
        else:
            # Get all weeks for this player
            player_weeks = {k: v for k, v in dfs_salaries_data.items() 
                           if k.startswith(f"{sleeper_id}_W")}
            
            if player_weeks:
                return jsonify(player_weeks), 200
            else:
                return jsonify({"error": "Player not found"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/dfs-salaries/week/<int:week>', methods=['GET'])
def get_dfs_salaries_by_week_endpoint(week):
    """
    Endpoint to return all DFS salaries data for a specific week.
    
    Args:
        week (int): Week number
        
    Returns:
        JSON response containing all DFS salaries data for the specified week.
    """
    try:
        # Filter data by week
        week_data = {k: v for k, v in dfs_salaries_data.items() 
                     if v.get('week') == week}
        
        if week_data:
            return jsonify(week_data), 200
        else:
            return jsonify({"error": f"No DFS data found for week {week}"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin/debug', methods=['GET'])
def debug_info():
    """Debug endpoint to check global variables"""
    return jsonify({
        "all_players_count": len(all_players),
        "filtered_players_count": len(filtered_players),
        "dfs_salaries_count": len(dfs_salaries_data),
        "fantasy_points_count": len(fantasy_points_data)
    }), 200


@app.route('/admin/dfs-salaries/update', methods=['POST'])
def admin_update_dfs_salaries():
    """
    Admin endpoint to manually trigger a DFS salaries update.

    Returns:
        JSON response indicating success or failure.
    """
    try:
        # Call the DFS salaries update method
        update_dfs_salaries_data()

        return jsonify({"message": "DFS salaries update triggered successfully."}), 200
    except Exception as e:
        print(f"Error while triggering DFS salaries update: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/admin/dfs-salaries/scrape-slate', methods=['POST'])
def admin_scrape_specific_slate():
    """
    Admin endpoint to scrape a specific slate by date and slate URL.
    
    Request Body:
        {
            "date": "2025-11-27",           # Date in YYYY-MM-DD format
            "slate_url": "21A90",           # Slate URL (e.g., "21A90")
            "update_salaries": true         # Optional: If false, logs salary differences but doesn't update salaries (default: true)
        }
    
    OR
    
    Request Body:
        {
            "date_slate": "2025-11-27?slate=21A90",  # Combined format
            "update_salaries": false         # Optional: If false, logs salary differences but doesn't update salaries
        }
    
    Returns:
        JSON response indicating success or failure with player count and salary differences if update_salaries is false.
    """
    global dfs_salaries_data, all_players
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body is required"}), 400
        
        # Parse input - support both formats
        date = None
        slate_url = None
        
        if 'date_slate' in data:
            # Parse format like "2025-11-27?slate=21A90"
            date_slate = data.get('date_slate', '')
            if '?slate=' in date_slate:
                parts = date_slate.split('?slate=')
                date = parts[0]
                slate_url = parts[1] if len(parts) > 1 else None
            else:
                return jsonify({"error": "Invalid date_slate format. Expected 'YYYY-MM-DD?slate=SLATE_URL'"}), 400
        else:
            # Parse separate date and slate_url
            date = data.get('date')
            slate_url = data.get('slate_url')
        
        if not date:
            return jsonify({"error": "date is required"}), 400
        if not slate_url:
            return jsonify({"error": "slate_url is required"}), 400
        
        # Validate date format
        try:
            datetime.datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return jsonify({"error": f"Invalid date format. Expected YYYY-MM-DD, got: {date}"}), 400
        
        # Get update_salaries flag (default: true)
        update_salaries = data.get('update_salaries', True)
        
        print(f"{datetime.datetime.now()} - Admin scraping specific slate: {date}?slate={slate_url}, update_salaries={update_salaries}")
        
        if USE_MOCK_DATA:
            return jsonify({"message": "Mock mode enabled - skipping DFF scraping"}), 200
        
        # Initialize DFF scraper
        scraper = DFFSalariesScraper()
        
        # Validate that the slate is not a showdown (we should never scrape prices from showdowns)
        if scraper.is_slate_showdown(slate_url, date):
            return jsonify({
                "error": f"Slate {slate_url} is a showdown slate. Showdown slates should not be used for prices. Only main slates should be scraped for salary data."
            }), 400
        
        # Scrape the specific slate
        players = scraper.scrape_dff_projections(slate_url, date)
        
        if not players:
            return jsonify({
                "message": f"No players found for slate {slate_url} on {date}",
                "players_scraped": 0
            }), 200
        
        # Match to Sleeper IDs
        matched_count = 0
        for player in players:
            sleeper_id = scraper.find_sleeper_id_by_name(
                player['name'],
                player['team'],
                all_players
            )
            player['sleeper_id'] = sleeper_id
            if sleeper_id:
                matched_count += 1
        
        # Add players to dfs_salaries_data
        added_count = 0
        updated_count = 0
        salary_differences = []
        
        for player in players:
            # Use sleeper_id + week as composite key if available, otherwise use name+team+week
            if player.get("sleeper_id"):
                key = f"{player['sleeper_id']}_W{player.get('week', 0)}"
            else:
                key = f"{player['name']}_{player['team']}_W{player.get('week', 0)}"
            
            # Check if player already exists
            existing_player = dfs_salaries_data.get(key)
            new_salary = player.get('salary', 0)
            
            # Log salary differences if update_salaries is false and player exists
            if not update_salaries and existing_player:
                existing_salary = existing_player.get('salary', 0)
                if existing_salary != new_salary:
                    salary_differences.append({
                        "name": player.get('name'),
                        "team": player.get('team'),
                        "sleeper_id": player.get('sleeper_id'),
                        "existing_salary": existing_salary,
                        "new_salary": new_salary,
                        "difference": new_salary - existing_salary
                    })
            
            # Add date to the player data
            player_with_date = player.copy()
            player_with_date["date"] = date
            
            # If update_salaries is false and player exists, keep the existing salary
            if not update_salaries and existing_player:
                player_with_date["salary"] = existing_player.get('salary', new_salary)
                updated_count += 1
            else:
                added_count += 1
            
            dfs_salaries_data[key] = player_with_date
        
        # Log salary differences
        if salary_differences:
            print(f"{datetime.datetime.now()} - Salary differences found (update_salaries={update_salaries}):")
            for diff in salary_differences[:10]:  # Log first 10
                print(f"  {diff['name']} ({diff['team']}): ${diff['existing_salary']:,} -> ${diff['new_salary']:,} (diff: ${diff['difference']:+,})")
            if len(salary_differences) > 10:
                print(f"  ... and {len(salary_differences) - 10} more differences")
        
        response = {
            "message": f"Successfully scraped and added players from slate {slate_url}",
            "date": date,
            "slate_url": slate_url,
            "players_scraped": len(players),
            "players_added": added_count,
            "players_updated": updated_count if not update_salaries else 0,
            "matched_to_sleeper_ids": matched_count,
            "week": players[0].get('week', 0) if players else None,
            "update_salaries": update_salaries
        }
        
        if salary_differences:
            response["salary_differences_count"] = len(salary_differences)
            response["salary_differences"] = salary_differences
        
        return jsonify(response), 200
        
    except Exception as e:
        print(f"Error scraping specific slate: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/admin/dfs-salaries/check/<sleeper_id>/<int:week>', methods=['GET'])
def admin_check_test_data(sleeper_id, week):
    """
    Admin endpoint to check if test data exists for a player.
    
    Returns:
        JSON response with the player data if found, or error if not found.
    """
    global dfs_salaries_data
    
    key = f"{sleeper_id}_W{week}"
    player_data = dfs_salaries_data.get(key)
    
    if player_data:
        return jsonify({
            "found": True,
            "key": key,
            "data": player_data
        }), 200
    else:
        available_keys = [k for k in dfs_salaries_data.keys() if k.startswith(f"{sleeper_id}_")]
        return jsonify({
            "found": False,
            "key": key,
            "available_keys_for_player": available_keys[:10],
            "total_keys": len(dfs_salaries_data)
        }), 404


@app.route('/admin/dfs-salaries/add-test-data', methods=['POST'])
def admin_add_test_data():
    """
    Admin endpoint to manually add test data to dfs_salaries_data.
    
    Request body should contain the player data as JSON.
    Example:
    {
        "sleeper_id": "12547",
        "week": 11,
        "data": {
            "date": "2025-11-13",
            "game_date": "2025-11-13",
            ...
        }
    }
    
    Returns:
        JSON response indicating success or failure.
    """
    global dfs_salaries_data
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body is required"}), 400
        
        sleeper_id = data.get('sleeper_id')
        week = data.get('week')
        player_data = data.get('data')
        
        if not sleeper_id or not week or not player_data:
            return jsonify({"error": "sleeper_id, week, and data are required"}), 400
        
        # Ensure sleeper_id and week are in the data
        player_data['sleeper_id'] = str(sleeper_id)
        player_data['week'] = int(week)
        
        # Create the key
        key = f"{sleeper_id}_W{week}"
        
        # Add to dfs_salaries_data
        dfs_salaries_data[key] = player_data
        
        return jsonify({
            "message": f"Test data added successfully for {key}",
            "key": key,
            "data": player_data
        }), 200
        
    except Exception as e:
        print(f"Error while adding test data: {e}")
        return jsonify({"error": str(e)}), 500


def normalize_tinyurl_name(name):
    """
    Normalize TinyURL entry name to lowercase for case-insensitive lookups.
    Returns the normalized name.
    """
    return name.lower() if name else name


def _localize_datetime(naive_dt, tz):
    """
    Localize a naive datetime to a timezone.
    Handles both zoneinfo (Python 3.9+) and pytz.
    
    Args:
        naive_dt: naive datetime object
        tz: timezone object (zoneinfo or pytz)
        
    Returns:
        timezone-aware datetime
    """
    # Check if it's pytz (has localize method)
    if hasattr(tz, 'localize'):
        return tz.localize(naive_dt)
    else:
        # zoneinfo or timezone - use replace
        return naive_dt.replace(tzinfo=tz)


def validate_lineup_players_not_started(lineup_data):
    """
    Validate that no players in the lineup have started their games yet.
    Uses EST/EDT timezone for game times (NFL games are typically in ET).
    
    Args:
        lineup_data: String in format "week|base64_encoded_string"
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None, players_started: list)
    """
    import base64
    from datetime import datetime, time as dt_time, timezone, timedelta
    
    global dfs_salaries_data
    
    try:
        # Get current time in EST/EDT (Eastern Time)
        # EST is UTC-5, EDT is UTC-4 (daylight saving)
        try:
            # Try to use zoneinfo (Python 3.9+)
            from zoneinfo import ZoneInfo
            et_tz = ZoneInfo('America/New_York')
        except ImportError:
            # Fallback: use pytz (handles DST properly)
            try:
                import pytz
                et_tz = pytz.timezone('America/New_York')
            except ImportError:
                # Last resort: use fixed UTC-5 offset (EST)
                # Note: This doesn't handle DST, but is better than nothing
                et_tz = timezone(timedelta(hours=-5))
        
        current_time_et = datetime.now(et_tz)
        
        # Parse the data string (format: "week|base64_encoded_string")
        if '|' not in lineup_data:
            return False, "Invalid lineup data format. Expected 'week|base64_data'", []
        
        parts = lineup_data.split('|', 1)
        if len(parts) != 2:
            return False, "Invalid lineup data format. Expected 'week|base64_data'", []
        
        week_str = parts[0]
        base64_data = parts[1]
        
        # Decode base64 to get player list
        sleeper_ids = []
        try:
            # Preserve original base64_data for LZString (before any modifications)
            original_base64_data = base64_data
            
            # Add padding if needed (base64 strings must be multiple of 4)
            missing_padding = len(base64_data) % 4
            if missing_padding:
                base64_data += '=' * (4 - missing_padding)
            
            # Decode base64 to bytes first
            # Try standard base64 first, then URL-safe base64 if that fails
            try:
                decoded_bytes = base64.b64decode(base64_data)
            except Exception:
                # If standard base64 fails, try URL-safe base64 (uses - and _ instead of + and /)
                try:
                    decoded_bytes = base64.urlsafe_b64decode(base64_data)
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Could not decode base64 (standard or URL-safe): {str(e)}. Base64 data (first 100 chars): {base64_data[:100]}. Skipping game time validation.")
                    return True, None, []
            
            # Try to decode as UTF-8
            try:
                decoded_string = decoded_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # If UTF-8 fails, try LZString decompression (common for frontend compression)
                decoded_string = None
                try:
                    # Try lzstring package (most common)
                    try:
                        import lzstring
                        lzs = lzstring.LZString()
                        # LZString expects the base64 string, not the decoded bytes
                        # Use original_base64_data (before padding was added)
                        # Try with original first
                        try:
                            decoded_string = lzs.decompressFromBase64(original_base64_data)
                        except:
                            # If that fails, try converting URL-safe base64 to standard base64
                            # URL-safe uses - and _ instead of + and /
                            if '-' in original_base64_data or '_' in original_base64_data:
                                # Convert URL-safe to standard base64
                                standard_base64 = original_base64_data.replace('-', '+').replace('_', '/')
                                # Re-add padding if needed
                                missing_padding = len(standard_base64) % 4
                                if missing_padding:
                                    standard_base64 += '=' * (4 - missing_padding)
                                decoded_string = lzs.decompressFromBase64(standard_base64)
                    except ImportError:
                        # Try alternative package name
                        try:
                            from lz_string import LZString
                            lzs = LZString()
                            try:
                                decoded_string = lzs.decompressFromBase64(original_base64_data)
                            except:
                                # Try URL-safe conversion
                                if '-' in original_base64_data or '_' in original_base64_data:
                                    standard_base64 = original_base64_data.replace('-', '+').replace('_', '/')
                                    missing_padding = len(standard_base64) % 4
                                    if missing_padding:
                                        standard_base64 += '=' * (4 - missing_padding)
                                    decoded_string = lzs.decompressFromBase64(standard_base64)
                        except ImportError:
                            # Neither package available
                            pass
                except Exception as e:
                    # LZString decompression failed, will try zlib as fallback
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.debug(f"LZString decompression failed: {str(e)}, trying zlib fallback")
                    pass
                
                # If LZString didn't work, try zlib decompression
                if not decoded_string:
                    import zlib
                    try:
                        decompressed = zlib.decompress(decoded_bytes)
                        decoded_string = decompressed.decode('utf-8')
                    except:
                        # If all decompression methods fail, log and skip validation
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Could not decode base64 as UTF-8, LZString, or zlib. Base64 length: {len(base64_data)}, decoded bytes length: {len(decoded_bytes)}, first 20 bytes (hex): {decoded_bytes[:20].hex()}. Skipping game time validation.")
                        return True, None, []
            
            # Parse player list
            # Format can be:
            # - "sleeper_id:salary,sleeper_id:salary,..." 
            # - "sleeper_id-salary,sleeper_id-salary,..."
            # - "username:sleeper_id-salary,sleeper_id-salary,..." (with username prefix)
            
            # Check if there's a username prefix (format: "username:player_list")
            # Username prefix would be at the start, all letters, followed by a colon
            if ':' in decoded_string:
                first_colon_idx = decoded_string.index(':')
                before_colon = decoded_string[:first_colon_idx].strip()
                # If the part before the first colon is all letters (username), extract player list
                if before_colon.isalpha() and len(before_colon) > 0:
                    player_list = decoded_string[first_colon_idx + 1:]  # Get everything after "username:"
                else:
                    player_list = decoded_string
            else:
                player_list = decoded_string
            
            player_pairs = player_list.split(',')
            
            for pair in player_pairs:
                # Handle both colon and dash delimiters
                if ':' in pair:
                    sleeper_id = pair.split(':')[0].strip()
                elif '-' in pair:
                    sleeper_id = pair.split('-')[0].strip()
                else:
                    continue
                
                # Only add numeric sleeper IDs (skip usernames and team abbreviations like "HOU")
                if sleeper_id and sleeper_id.isdigit():
                    sleeper_ids.append(sleeper_id)
        except Exception as e:
            # If base64 decoding fails, we can't validate player game times
            # This might be compressed data or a different format
            # Log the error but don't block the request - just skip validation
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not decode base64 lineup data for validation: {str(e)}. Base64 data (first 100 chars): {base64_data[:100] if 'base64_data' in locals() else 'N/A'}. Skipping game time validation.")
            # Return True to allow the request through without validation
            return True, None, []
        
        if not sleeper_ids:
            # No valid players found, but don't block - might be a different format
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"No sleeper_ids extracted from lineup data. Decoded string: {decoded_string[:100] if 'decoded_string' in locals() else 'N/A'}")
            return True, None, []
        
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Validating lineup with {len(sleeper_ids)} players for week {week_str}: {sleeper_ids}")
        
        # Check each player's game status
        players_started = []
        
        for sleeper_id in sleeper_ids:
            # Look up player in dfs_salaries_data
            week = int(week_str) if week_str.isdigit() else None
            if week is None:
                continue
            
            # Try to find player data (key format: sleeper_id_W{week})
            key = f"{sleeper_id}_W{week}"
            player_data = dfs_salaries_data.get(key)
            
            if not player_data:
                # Player not found in salary data, skip validation for this player
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Player {sleeper_id} (week {week}, key: {key}) not found in dfs_salaries_data. Available keys: {list(dfs_salaries_data.keys())[:10]}")
                continue
            
            # Check if game has started
            game_date_str = player_data.get('game_date') or player_data.get('start_date')
            game_start_time_str = player_data.get('game_start_time', '')
            game_day = player_data.get('game_day', '')  # e.g., "Monday", "Sunday"
            
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Validating player {sleeper_id}: game_date={game_date_str}, game_start_time={game_start_time_str}, game_day={game_day}")
            
            if not game_date_str:
                # No game date, skip validation
                logger.debug(f"Player {sleeper_id} has no game_date, skipping validation")
                continue
            
            # Parse game date
            try:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
            except:
                continue
            
            # Parse game start time (format: "1:00PM", "4:05PM", etc.)
            game_datetime_et = None
            if game_start_time_str and game_start_time_str != 'Unknown':
                try:
                    # Parse time like "1:00PM" or "4:05PM" (assumed to be ET)
                    time_str = game_start_time_str.replace('PM', '').replace('AM', '').strip()
                    hour, minute = map(int, time_str.split(':'))
                    
                    # Adjust for PM/AM
                    if 'PM' in game_start_time_str and hour != 12:
                        hour += 12
                    elif 'AM' in game_start_time_str and hour == 12:
                        hour = 0
                    
                    game_time = dt_time(hour=hour, minute=minute)
                    game_datetime_naive = datetime.combine(game_date, game_time)
                    # Assume game time is in ET - use helper to handle pytz vs zoneinfo
                    game_datetime_et = _localize_datetime(game_datetime_naive, et_tz)
                except:
                    # If time parsing fails, use default based on game day
                    game_datetime_et = _get_default_game_time(game_date, game_day, et_tz)
            else:
                # No time available, use smart default based on game day
                game_datetime_et = _get_default_game_time(game_date, game_day, et_tz)
            
            # Check if game has started (compare in ET timezone)
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Comparing times for player {sleeper_id}: current_time_et={current_time_et}, game_datetime_et={game_datetime_et}, has_started={game_datetime_et and current_time_et >= game_datetime_et}")
            
            if game_datetime_et and current_time_et >= game_datetime_et:
                player_name = player_data.get('name', sleeper_id)
                logger.info(f"Player {sleeper_id} ({player_name}) game has started - adding to reject list")
                players_started.append({
                    'sleeper_id': sleeper_id,
                    'name': player_name,
                    'team': player_data.get('team', ''),
                    'game_date': game_date_str,
                    'game_start_time': game_start_time_str or 'Unknown'
                })
        
        if players_started:
            player_names = [f"{p['name']} ({p['team']})" for p in players_started]
            error_msg = f"Lineup contains players whose games have already started: {', '.join(player_names)}"
            return False, error_msg, players_started
        
        return True, None, []
        
    except Exception as e:
        return False, f"Error validating lineup: {str(e)}", []


def _get_default_game_time(game_date, game_day, et_tz):
    """
    Get default game start time based on game day.
    NFL games typically:
    - Thursday: 8:00 PM ET
    - Sunday: 1:00 PM ET (early games)
    - Monday: 8:00 PM ET
    - Saturday: 1:00 PM ET (late season)
    - Other: 6:00 PM ET (conservative default)
    
    Args:
        game_date: date object
        game_day: string like "Monday", "Sunday", etc.
        et_tz: Eastern timezone
        
    Returns:
        datetime object in ET timezone
    """
    from datetime import time as dt_time, datetime
    
    game_day_lower = game_day.lower() if game_day else ''
    
    # Default times based on day of week
    if 'monday' in game_day_lower or 'thursday' in game_day_lower:
        # Primetime games: 8:00 PM ET
        default_time = dt_time(20, 0)
    elif 'sunday' in game_day_lower or 'saturday' in game_day_lower:
        # Early games: 1:00 PM ET
        default_time = dt_time(13, 0)
    else:
        # Conservative default: 6:00 PM ET
        default_time = dt_time(18, 0)
    
    game_datetime_naive = datetime.combine(game_date, default_time)
    return _localize_datetime(game_datetime_naive, et_tz)


@app.route('/tinyurl/create', methods=['POST'])
def create_tinyurl():
    """
    Create a new TinyURL entry with multiple user entries in a single request.
    
    Request body:
    {
        "name": "league_name",
        "week": 10,
        "entries": [
            {"name": "user1", "data": "10|compressed..."},
            {"name": "user2", "data": null}
        ]
    }
    
    Returns:
        JSON response with created entry information
    """
    global tinyurl_data
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body is required"}), 400
        
        name = data.get('name')
        week = data.get('week')
        entries = data.get('entries')
        
        # Validate required fields
        if not name:
            return jsonify({"error": "name is required"}), 400
        if week is None:
            return jsonify({"error": "week is required"}), 400
        if not isinstance(week, int):
            return jsonify({"error": "week must be an integer"}), 400
        if not entries:
            return jsonify({"error": "entries is required"}), 400
        if not isinstance(entries, list):
            return jsonify({"error": "entries must be an array"}), 400
        if len(entries) == 0:
            return jsonify({"error": "entries array cannot be empty"}), 400
        
        # Validate name length (max 20 chars)
        if len(name) > 20:
            return jsonify({"error": "name cannot exceed 20 characters"}), 400
        
        # Normalize name for case-insensitive storage
        normalized_name = normalize_tinyurl_name(name)
        
        # Check if we already have 10 entries
        if len(tinyurl_data) >= 10:
            return jsonify({"error": "Maximum of 10 entries reached. Data will be cleared Thursday at 19:00 CET."}), 400
        
        # Check if name already exists (case-insensitive)
        if normalized_name in tinyurl_data:
            return jsonify({"error": f"Name '{name}' already exists. Use a different name or update the existing entry."}), 400
        
        # Extract all usernames and validate entries
        allowed_names = []
        normalized_allowed_names = set()  # Track normalized names for case-insensitive duplicate detection
        entries_with_data = []
        
        for entry in entries:
            if not isinstance(entry, dict):
                return jsonify({"error": "Each entry must be an object"}), 400
            
            entry_name = entry.get('name')
            entry_data = entry.get('data')
            
            if not entry_name:
                return jsonify({"error": "Each entry must have a 'name' field"}), 400
            if 'data' not in entry:
                return jsonify({"error": "Each entry must have a 'data' field (can be null)"}), 400
            
            # Normalize entry name for case-insensitive duplicate detection
            normalized_entry_name = normalize_tinyurl_name(entry_name)
            
            # Add to allowed_names (case-insensitive duplicate detection)
            # Keep the first occurrence's case for display
            if normalized_entry_name not in normalized_allowed_names:
                allowed_names.append(entry_name)
                normalized_allowed_names.add(normalized_entry_name)
            
            # Track entries with data (even if duplicate, we want to process the data)
            if entry_data is not None:
                if not isinstance(entry_data, str):
                    return jsonify({"error": "entry data must be a string or null"}), 400
                # Use the original entry_name from allowed_names if it's a duplicate
                # Find the matching name from allowed_names (case-insensitive)
                matching_name = entry_name
                for allowed_name in allowed_names:
                    if normalize_tinyurl_name(allowed_name) == normalized_entry_name:
                        matching_name = allowed_name
                        break
                entries_with_data.append({
                    'name': matching_name,  # Use the name from allowed_names to maintain consistency
                    'data': entry_data
                })
        
        # Create the entry
        current_time = datetime.datetime.now().isoformat()
        tinyurl_entry = {
            'name': name,  # Store original case
            'data': None,  # Will be set if any entries have data
            'created_at': current_time,
            'allowed_names': allowed_names,
            'week': week,
            'user_submissions': {}
        }
        
        # Process entries with data (validation removed for bulk creation)
        entries_added = 0
        latest_data = None
        latest_updated_by = None
        
        for entry in entries_with_data:
            entry_name = entry['name']
            entry_data_value = entry['data']
            normalized_entry_name = normalize_tinyurl_name(entry_name)
            
            # Add to user_submissions
            tinyurl_entry['user_submissions'][normalized_entry_name] = {
                'username': entry_name,  # Store original case
                'data': entry_data_value,
                'created_at': current_time,
                'update_count': 1,
                'updated_at': current_time
            }
            
            entries_added += 1
            latest_data = entry_data_value
            latest_updated_by = entry_name
        
        # Set main data to latest entry's data (if any)
        if latest_data:
            tinyurl_entry['data'] = latest_data
            tinyurl_entry['updated_at'] = current_time
            tinyurl_entry['updated_by'] = latest_updated_by
        
        # Store the entry
        tinyurl_data[normalized_name] = tinyurl_entry
        
        # Build response
        response = {
            "name": name,
            "week": week,
            "created_at": current_time,
            "total_entries": len(tinyurl_data),
            "entries_added": entries_added,
            "allowed_names": allowed_names
        }
        
        return jsonify(response), 200
            
    except Exception as e:
        print(f"Error creating TinyURL: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/tinyurl/<name>/data', methods=['GET'])
def get_tinyurl_data(name):
    """
    Get stored data by entry name.
    If a username is provided, returns data only for that specific user.
    If the entry has a PIN, it must be provided as a query parameter to access the data.
    Use action=results to bypass PIN requirements for results display.
    
    Args:
        name: The name of the stored entry
        username: Optional query parameter - if provided, returns data only for that username
        pin: Optional query parameter - required if entry/user has a PIN (unless action=results)
        action: Optional query parameter - set to "results" to bypass PIN requirements for results display
    
    Returns:
        JSON response with stored data or error message. Returns no data if PIN is required but missing/incorrect.
    """
    global tinyurl_data
    
    # Normalize name for case-insensitive lookup
    normalized_name = normalize_tinyurl_name(name)
    
    if normalized_name not in tinyurl_data:
        return jsonify({"error": f"Data with name '{name}' not found"}), 404
    
    entry = tinyurl_data[normalized_name]
    
    # Get optional query parameters
    username = request.args.get('username')
    provided_pin = request.args.get('pin')
    action = request.args.get('action')
    
    # Check if action=results (bypasses PIN requirements for results display)
    is_results_view = action == 'results'
    
    # If username is provided, return data for that specific user
    if username:
        normalized_username = normalize_tinyurl_name(username)
        user_submissions = entry.get('user_submissions', {})
        
        if normalized_username not in user_submissions:
            # Get list of available usernames for debugging
            available_usernames = [user_data.get('username', key) for key, user_data in user_submissions.items()]
            return jsonify({
                "name": entry.get('name', name),
                "username": username,
                "data": None,
                "message": f"No data found for username '{username}'",
                "available_usernames": available_usernames if available_usernames else []
            }), 200
        
        user_data = user_submissions[normalized_username]
        
        # Check if this user's submission has a PIN (unless results view bypasses it)
        if 'pin' in user_data and not is_results_view:
            user_pin = user_data.get('pin')
            if not provided_pin:
                return jsonify({
                    "name": entry.get('name', name),
                    "username": username,
                    "data": None,
                    "pin_required": True,
                    "message": "PIN required to access this user's data"
                }), 200
            
            # Validate PIN format
            provided_pin = str(provided_pin).strip()
            if not provided_pin.isdigit() or len(provided_pin) < 2 or len(provided_pin) > 8:
                return jsonify({
                    "name": entry.get('name', name),
                    "username": username,
                    "data": None,
                    "pin_required": True,
                    "message": "Invalid PIN format"
                }), 200
            
            # Check if PIN matches
            if provided_pin != user_pin:
                return jsonify({
                    "name": entry.get('name', name),
                    "username": username,
                    "data": None,
                    "pin_required": True,
                    "message": "Incorrect PIN"
                }), 200
        
        # Return user-specific data
        return jsonify({
            "name": entry.get('name', name),
            "username": user_data.get('username', username),
            "data": user_data.get('data'),
            "created_at": user_data.get('created_at'),
            "updated_at": user_data.get('updated_at'),
            "update_count": user_data.get('update_count', 0),
            "week": entry.get('week')
        }), 200
    
    # No username provided - return main entry data (existing behavior)
    # Check if entry has a PIN (stored in user_submissions)
    # We need to check all user submissions to see if any have a PIN
    user_submissions = entry.get('user_submissions', {})
    stored_pins = set()
    
    # Collect all stored PINs from user submissions
    for user_data in user_submissions.values():
        if 'pin' in user_data:
            stored_pins.add(user_data.get('pin'))
    
    entry_has_pin = len(stored_pins) > 0
    
    # If entry has a PIN, validate it (unless results view bypasses it)
    if entry_has_pin and not is_results_view:
        if not provided_pin:
            # PIN required but not provided - return no data
            return jsonify({
                "name": entry.get('name', name),
                "data": None,
                "pin_required": True,
                "message": "PIN required to access this data"
            }), 200
        
        # Validate PIN format
        provided_pin = str(provided_pin).strip()
        if not provided_pin.isdigit() or len(provided_pin) < 2 or len(provided_pin) > 8:
            return jsonify({
                "name": entry.get('name', name),
                "data": None,
                "pin_required": True,
                "message": "Invalid PIN format"
            }), 200
        
        # Check if PIN matches any stored PIN
        if provided_pin not in stored_pins:
            # PIN doesn't match any stored PIN - return no data
            return jsonify({
                "name": entry.get('name', name),
                "data": None,
                "pin_required": True,
                "message": "Incorrect PIN"
            }), 200
    
    # Use original name from entry if stored, otherwise use the provided name
    display_name = entry.get('name', name)
    response = {
        "name": display_name,
        "data": entry.get('data'),
        "created_at": entry.get('created_at')
    }
    
    # Include allowed_names if present (created via /create/empty)
    if 'allowed_names' in entry:
        response['allowed_names'] = entry['allowed_names']
    
    # Include week if present
    if 'week' in entry:
        response['week'] = entry['week']
    
    # Include reveal if present
    if 'reveal' in entry:
        response['reveal'] = entry['reveal']
    
    # Include update info if present
    if 'updated_at' in entry:
        response['updated_at'] = entry['updated_at']
    if 'updated_by' in entry:
        response['updated_by'] = entry['updated_by']
    
    # Include user_submissions if present (tracks per-user submission history)
    if 'user_submissions' in entry:
        response['user_submissions'] = entry['user_submissions']
    
    return jsonify(response), 200


@app.route('/tinyurl/<name>/details', methods=['GET'])
def get_tinyurl_details(name):
    """
    Get detailed submission information for an entry.
    Shows all allowed names and their submission status with update counts.
    
    Args:
        name: The name of the stored entry
    
    Returns:
        JSON response with detailed submission information or error message
    """
    global tinyurl_data
    
    # Normalize name for case-insensitive lookup
    normalized_name = normalize_tinyurl_name(name)
    
    if normalized_name not in tinyurl_data:
        return jsonify({"error": f"Data with name '{name}' not found"}), 404
    
    entry = tinyurl_data[normalized_name]
    # Use original name from entry if stored, otherwise use the provided name
    display_name = entry.get('name', name)
    response = {
        "name": display_name,
        "created_at": entry.get('created_at')
    }
    
    # Include week if present
    if 'week' in entry:
        response['week'] = entry['week']
    
    # Include reveal if present
    if 'reveal' in entry:
        response['reveal'] = entry['reveal']
    
    # Get allowed names
    allowed_names = entry.get('allowed_names', [])
    if allowed_names:
        response['allowed_names'] = allowed_names
        
        # Build submission details for each allowed name
        submissions = {}
        user_submissions = entry.get('user_submissions', {})
        
        for username in allowed_names:
            # Normalize username for case-insensitive lookup in user_submissions
            normalized_username = normalize_tinyurl_name(username)
            if normalized_username in user_submissions:
                user_data = user_submissions[normalized_username]
                # Use original username from allowed_names for display
                submissions[username] = {
                    "has_submitted": True,
                    "update_count": user_data.get('update_count', 0),
                    "created_at": user_data.get('created_at'),
                    "updated_at": user_data.get('updated_at')
                }
            else:
                submissions[username] = {
                    "has_submitted": False,
                    "update_count": 0
                }
        
        response['submissions'] = submissions
    else:
        # Entry created via old /create method (no allowed_names)
        response['allowed_names'] = []
        response['submissions'] = {}
    
    # Include overall update info if present
    if 'updated_at' in entry:
        response['updated_at'] = entry['updated_at']
    if 'updated_by' in entry:
        response['updated_by'] = entry['updated_by']
    
    return jsonify(response), 200


@app.route('/tinyurl/<username>/available', methods=['GET'])
def get_tinyurls_by_username(username):
    """
    Get all TinyURL entry names where the username is in the allowed_names list.
    Includes a flag indicating if each entry already has data.
    
    Args:
        username: The username to search for
    
    Returns:
        JSON response with list of TinyURL entries with metadata
    """
    global tinyurl_data
    
    # Normalize username for case-insensitive comparison
    normalized_username = normalize_tinyurl_name(username)
    
    matching_entries = []
    for entry_name, entry_data in tinyurl_data.items():
            allowed_names = entry_data.get('allowed_names', [])
            # Case-insensitive comparison: normalize all allowed names and compare
            normalized_allowed_names = [normalize_tinyurl_name(n) for n in allowed_names]
            if normalized_username in normalized_allowed_names:
                # Use original name from entry if stored, otherwise use entry_name
                display_name = entry_data.get('name', entry_name)
                
                user_submissions = entry_data.get('user_submissions', {})
                
                # Check if this specific username has data in user_submissions
                # If user_submissions exists and has this username, check their data
                # Otherwise, fall back to main entry data
                user_has_data = False
                has_pin = False
                if normalized_username in user_submissions:
                    user_data = user_submissions[normalized_username]
                    user_has_data = user_data.get('data') is not None
                    # Check if THIS specific username has a PIN
                    has_pin = 'pin' in user_data
                else:
                    # Fall back to main entry data if no user-specific data
                    user_has_data = entry_data.get('data') is not None
                    # No user-specific submission, so no PIN
                    has_pin = False
                
                entry_info = {
                    "name": display_name,
                    "has_data": user_has_data,
                    "has_pin": has_pin
                }
                # Include week if present
                if 'week' in entry_data:
                    entry_info['week'] = entry_data['week']
                matching_entries.append(entry_info)
    
    return jsonify({
        "username": username,
        "entries": matching_entries,
        "count": len(matching_entries)
    }), 200


@app.route('/tinyurl/count', methods=['GET'])
def get_tinyurl_count():
    """
    Get the count of current TinyURL entries.
    
    Returns:
        JSON response with count and max capacity
    """
    global tinyurl_data
    
    return jsonify({
        "count": len(tinyurl_data),
        "max_entries": 10,
        "remaining": 10 - len(tinyurl_data)
    }), 200


@app.route('/tinyurl/list', methods=['GET'])
def list_tinyurls():
    """
    List all stored entries.
    
    Returns:
        JSON response with all stored entries
    """
    global tinyurl_data
    
    entries = []
    for name, data in tinyurl_data.items():
        # Use original name from entry if stored, otherwise use the key
        display_name = data.get('name', name)
        entry_info = {
            "name": display_name,
            "created_at": data['created_at'],
            "has_data": data.get('data') is not None
        }
        
        # Include week if present
        if 'week' in data:
            entry_info['week'] = data['week']
        
        # Include reveal if present
        if 'reveal' in data:
            entry_info['reveal'] = data['reveal']
        
        # Include allowed_names if present
        if 'allowed_names' in data:
            entry_info['allowed_names'] = data['allowed_names']
        
        # Include user_submissions count if present
        if 'user_submissions' in data:
            entry_info['user_submissions_count'] = len(data['user_submissions'])
        
        # Include update info if present
        if 'updated_at' in data:
            entry_info['updated_at'] = data['updated_at']
        if 'updated_by' in data:
            entry_info['updated_by'] = data['updated_by']
        
        entries.append(entry_info)
    
    return jsonify({
        "total_entries": len(entries),
        "entries": entries
    }), 200


@app.route('/tinyurl/<name>', methods=['DELETE'])
def delete_tinyurl(name):
    """
    Delete a stored entry by name.
    
    Args:
        name: The name of the stored entry to delete
    
    Returns:
        JSON response indicating success or error
    """
    global tinyurl_data
    
    # Normalize name for case-insensitive lookup
    normalized_name = normalize_tinyurl_name(name)
    
    if normalized_name not in tinyurl_data:
        return jsonify({"error": f"Data with name '{name}' not found"}), 404
    
    del tinyurl_data[normalized_name]
    return jsonify({
        "message": f"Entry '{name}' deleted successfully",
        "remaining_entries": len(tinyurl_data)
    }), 200


@app.route('/tinyurl/create/empty', methods=['POST'])
def create_empty_tinyurl():
    """
    Create an empty TinyURL entry with allowed usernames.
    
    Request body:
    {
        "name": "unique_name",
        "names": ["username1", "username2", "username3"],
        "week": 8,
        "reveal": "2025-11-10T14:30:00.000Z"  // Optional, ISO 8601 UTC format
    }
    
    Returns:
        JSON response with created entry or error message
    """
    global tinyurl_data
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body is required"}), 400
        
        name = data.get('name')
        allowed_names = data.get('names', [])
        week = data.get('week')
        reveal = data.get('reveal')
        
        if not name:
            return jsonify({"error": "name is required"}), 400
        if not isinstance(allowed_names, list):
            return jsonify({"error": "names must be a list"}), 400
        if not allowed_names:
            return jsonify({"error": "names list cannot be empty"}), 400
        
        # Normalize name for case-insensitive storage
        normalized_name = normalize_tinyurl_name(name)
        
        # Check if we already have 10 entries
        if len(tinyurl_data) >= 10:
            return jsonify({"error": "Maximum of 10 entries reached. Data will be cleared Thursday at 19:00 CET."}), 400
        
        # Check if name already exists (case-insensitive)
        if normalized_name in tinyurl_data:
            return jsonify({"error": f"Name '{name}' already exists. Use a different name or update the existing entry."}), 400
        
        # Store empty entry with allowed names, week, and reveal
        # Use normalized name as key, but keep original name and allowed_names in data
        entry_data = {
            'name': name,  # Store original case
            'data': None,  # No data yet
            'created_at': datetime.datetime.now().isoformat(),
            'allowed_names': allowed_names  # Keep original case for display
        }
        
        if week is not None:
            entry_data['week'] = week
        
        if reveal is not None:
            entry_data['reveal'] = reveal
        
        tinyurl_data[normalized_name] = entry_data
        
        response = {
            "name": name,
            "allowed_names": allowed_names,
            "created_at": tinyurl_data[normalized_name]['created_at'],
            "total_entries": len(tinyurl_data)
        }
        
        if week is not None:
            response['week'] = week
        
        if reveal is not None:
            response['reveal'] = reveal
        
        return jsonify(response), 200
            
    except Exception as e:
        print(f"Error creating empty TinyURL: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/tinyurl/<tinyurl_name>/add', methods=['POST'])
def add_to_tinyurl(tinyurl_name):
    """
    Add data to an existing TinyURL entry.
    Only allowed usernames (from the names list) can add data.
    
    Request body:
    {
        "name": "username",
        "data": "8|MIQwTgdi...",
        "pin": "1234"  # Optional: 2-8 digit PIN code (numbers only)
    }
    
    Args:
        tinyurl_name: The name of the TinyURL entry to add data to
    
    Returns:
        JSON response indicating success or error
    """
    global tinyurl_data
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body is required"}), 400
        
        username = data.get('name')
        url_data = data.get('data')
        pin = data.get('pin')
        
        if not username:
            return jsonify({"error": "name is required"}), 400
        if not url_data:
            return jsonify({"error": "data is required"}), 400
        
        # Validate PIN if provided (2-8 digits, numbers only)
        if pin is not None:
            if not isinstance(pin, str) and not isinstance(pin, int):
                return jsonify({"error": "pin must be a string or number"}), 400
            
            pin_str = str(pin).strip()
            if not pin_str.isdigit():
                return jsonify({"error": "pin must contain only numbers"}), 400
            
            if len(pin_str) < 2 or len(pin_str) > 8:
                return jsonify({"error": "pin must be between 2 and 8 digits"}), 400
            
            pin = pin_str  # Store as string
        
        # Normalize names for case-insensitive lookup and comparison
        normalized_tinyurl_name = normalize_tinyurl_name(tinyurl_name)
        normalized_username = normalize_tinyurl_name(username)
        
        # Check if TinyURL entry exists
        if normalized_tinyurl_name not in tinyurl_data:
            return jsonify({"error": f"TinyURL '{tinyurl_name}' not found"}), 404
        
        entry = tinyurl_data[normalized_tinyurl_name]
        
        # Check if entry has allowed_names (created via /create/empty)
        allowed_names = entry.get('allowed_names', [])
        if not allowed_names:
            # Entry was created via /create (old method), cannot use /add endpoint
            return jsonify({"error": f"TinyURL '{tinyurl_name}' was not created with allowed names. Use /tinyurl/create to update."}), 400
        
        # Check if username is in allowed_names (case-insensitive comparison)
        normalized_allowed_names = [normalize_tinyurl_name(n) for n in allowed_names]
        if normalized_username not in normalized_allowed_names:
            return jsonify({"error": "Not allowed username"}), 401
        
        # Initialize user_submissions if it doesn't exist
        if 'user_submissions' not in entry:
            entry['user_submissions'] = {}
        
        # Check if this is an overwrite (user already has submitted data)
        if normalized_username in entry['user_submissions']:
            existing_data = entry['user_submissions'][normalized_username].get('data')
            if existing_data:
                # Validate that no players in the EXISTING lineup have started their games yet
                # This prevents overwriting a lineup that has players whose games have started
                is_valid_existing, error_msg_existing, players_started_existing = validate_lineup_players_not_started(existing_data)
                if not is_valid_existing:
                    return jsonify({
                        "error": f"Cannot overwrite lineup: {error_msg_existing}",
                        "players_started": players_started_existing,
                        "message": "The existing lineup contains players whose games have already started. You cannot overwrite it."
                    }), 400
        
        # Validate that no players in the NEW lineup have started their games yet
        is_valid, error_msg, players_started = validate_lineup_players_not_started(url_data)
        if not is_valid:
            return jsonify({
                "error": error_msg,
                "players_started": players_started
            }), 400
        
        current_time = datetime.datetime.now().isoformat()
        
        # Check if this is the user's first submission (use normalized username as key)
        if normalized_username not in entry['user_submissions']:
            # First submission - create entry with created_at and update_count = 1
            # Use normalized_username as key for case-insensitive lookups
            user_submission_data = {
                'username': username,  # Store original case for display
                'data': url_data,
                'created_at': current_time,
                'update_count': 1,
                'updated_at': current_time
            }
            # Store PIN if provided
            if pin:
                user_submission_data['pin'] = pin
            entry['user_submissions'][normalized_username] = user_submission_data
        else:
            # Subsequent submission - increment update_count
            user_submission = entry['user_submissions'][normalized_username]
            user_submission['data'] = url_data
            user_submission['update_count'] = user_submission.get('update_count', 0) + 1
            user_submission['updated_at'] = current_time
            # Update username if case changed
            user_submission['username'] = username
            # Update PIN if provided (can be set or changed)
            if pin:
                user_submission['pin'] = pin
        
        # Update main entry data (keep latest submission or aggregate as needed)
        entry['data'] = url_data
        entry['updated_at'] = current_time
        entry['updated_by'] = username  # Keep original case for display
        
        return jsonify({
            "message": f"Data added to '{tinyurl_name}' successfully",
            "name": tinyurl_name,
            "updated_by": username,
            "updated_at": entry['updated_at'],
            "update_count": entry['user_submissions'][normalized_username]['update_count'],
            "created_at": entry['user_submissions'][normalized_username]['created_at']
        }), 200
            
    except Exception as e:
        print(f"Error adding data to TinyURL: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/admin/tinyurl/<name>/data', methods=['GET'])
def admin_get_tinyurl_data(name):
    """
    Admin endpoint to get TinyURL entry data, bypassing all PIN requirements.
    Returns all data including user_submissions without requiring any PINs.
    
    Args:
        name: The name of the stored entry
        username: Optional query parameter - if provided, returns data only for that username
    
    Returns:
        JSON response with stored data (bypasses PIN checks)
    """
    global tinyurl_data
    
    # Normalize name for case-insensitive lookup
    normalized_name = normalize_tinyurl_name(name)
    
    if normalized_name not in tinyurl_data:
        return jsonify({"error": f"Data with name '{name}' not found"}), 404
    
    entry = tinyurl_data[normalized_name]
    
    # Get optional username parameter
    username = request.args.get('username')
    
    # If username is provided, return data for that specific user (bypass PIN)
    if username:
        normalized_username = normalize_tinyurl_name(username)
        user_submissions = entry.get('user_submissions', {})
        
        if normalized_username not in user_submissions:
            # Get list of available usernames for debugging
            available_usernames = [user_data.get('username', key) for key, user_data in user_submissions.items()]
            return jsonify({
                "name": entry.get('name', name),
                "username": username,
                "data": None,
                "message": f"No data found for username '{username}'",
                "available_usernames": available_usernames if available_usernames else []
            }), 200
        
        user_data = user_submissions[normalized_username]
        
        # Return user-specific data (PIN bypassed for admin)
        return jsonify({
            "name": entry.get('name', name),
            "username": user_data.get('username', username),
            "data": user_data.get('data'),
            "created_at": user_data.get('created_at'),
            "updated_at": user_data.get('updated_at'),
            "update_count": user_data.get('update_count', 0),
            "week": entry.get('week'),
            "pin": user_data.get('pin')  # Include PIN in admin response
        }), 200
    
    # No username provided - return main entry data (PIN bypassed for admin)
    display_name = entry.get('name', name)
    response = {
        "name": display_name,
        "data": entry.get('data'),
        "created_at": entry.get('created_at')
    }
    
    # Include allowed_names if present
    if 'allowed_names' in entry:
        response['allowed_names'] = entry['allowed_names']
    
    # Include week if present
    if 'week' in entry:
        response['week'] = entry['week']
    
    # Include reveal if present
    if 'reveal' in entry:
        response['reveal'] = entry['reveal']
    
    # Include update info if present
    if 'updated_at' in entry:
        response['updated_at'] = entry['updated_at']
    if 'updated_by' in entry:
        response['updated_by'] = entry['updated_by']
    
    # Include user_submissions (all data, including PINs for admin access)
    if 'user_submissions' in entry:
        response['user_submissions'] = entry['user_submissions']
    
    return jsonify(response), 200


@app.route('/tinyurl/<name>/<username>/check', methods=['GET'])
def check_username_data_in_league(name, username):
    """
    Check if a specific username has data stored in a specific league (TinyURL entry).
    
    Args:
        name: The TinyURL entry name (league name)
        username: The username to check
    
    Returns:
        JSON response indicating if the username has data in this league
    """
    global tinyurl_data
    
    # Normalize names for case-insensitive lookup
    normalized_name = normalize_tinyurl_name(name)
    normalized_username = normalize_tinyurl_name(username)
    
    # Check if the league exists
    if normalized_name not in tinyurl_data:
        return jsonify({"error": f"League '{name}' not found"}), 404
    
    entry = tinyurl_data[normalized_name]
    
    # Check if username has data in user_submissions
    has_data = False
    has_pin = False
    user_submissions = entry.get('user_submissions', {})
    
    if normalized_username in user_submissions:
        user_data = user_submissions[normalized_username]
        # Check if the user has actual data (not just an empty entry)
        has_data = user_data.get('data') is not None
        # Check if user has a PIN
        has_pin = 'pin' in user_data
    
    response = {
        "name": entry.get('name', name),
        "username": username,
        "has_data": has_data,
        "has_pin": has_pin
    }
    
    # Include additional info if data exists
    if has_data:
        user_data = user_submissions[normalized_username]
        response["update_count"] = user_data.get('update_count', 0)
        response["created_at"] = user_data.get('created_at')
        response["updated_at"] = user_data.get('updated_at')
    
    return jsonify(response), 200


@app.route('/tournament', methods=['POST'])
def create_tournament():
    """
    Create a new tournament.
    
    Request Body:
        {
            "week": 15,
            "name": "Duo Showdown",
            "games": [
                {
                    "player1": {
                        "league_name": "otherleague",
                        "leagie_position": "2",
                        "league": "1258067708054863872",
                        "playername": "carnade",
                        "playerid": "872150198389014528"
                    },
                    "player2": {
                        "league_name": "examplenameleague",
                        "leagie_position": "1",
                        "league": "1258066982851330048",
                        "playername": "peterpants",
                        "playerid": "458662325709172736"
                    }
                }
            ]
        }
    
    Returns:
        JSON response with tournament data including generated ID
    """
    global tournament_data
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body is required"}), 400
        
        # Validate required fields
        week = data.get('week')
        name = data.get('name')
        games = data.get('games')
        
        if week is None:
            return jsonify({"error": "week is required"}), 400
        if not isinstance(week, int):
            return jsonify({"error": "week must be an integer"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400
        if not isinstance(name, str):
            return jsonify({"error": "name must be a string"}), 400
        if not games:
            return jsonify({"error": "games is required"}), 400
        if not isinstance(games, list):
            return jsonify({"error": "games must be an array"}), 400
        if len(games) == 0:
            return jsonify({"error": "games array cannot be empty"}), 400
        
        # Validate games structure
        for i, game in enumerate(games):
            if not isinstance(game, dict):
                return jsonify({"error": f"games[{i}] must be an object"}), 400
            if 'player1' not in game or 'player2' not in game:
                return jsonify({"error": f"games[{i}] must have player1 and player2"}), 400
            
            for player_key in ['player1', 'player2']:
                player = game.get(player_key)
                if not isinstance(player, dict):
                    return jsonify({"error": f"games[{i}].{player_key} must be an object"}), 400
                
                required_fields = ['league_name', 'leagie_position', 'league', 'playername', 'playerid']
                for field in required_fields:
                    if field not in player:
                        return jsonify({"error": f"games[{i}].{player_key}.{field} is required"}), 400
        
        # Check max limit (10 tournaments)
        if len(tournament_data) >= 10:
            # Clean up old tournaments first (keep current and previous week)
            scraper = FantasyDataScraper()
            current_week = scraper.get_current_week()
            if current_week is not None:
                current_week = int(current_week)
                weeks_to_keep = {current_week, current_week - 1}
                
                # Delete tournaments older than previous week
                keys_to_delete = []
                for tour_id, tour in tournament_data.items():
                    tour_week = tour.get('week')
                    if tour_week is not None and tour_week not in weeks_to_keep:
                        keys_to_delete.append(tour_id)
                
                for key in keys_to_delete:
                    del tournament_data[key]
                
                if keys_to_delete:
                    print(f"{datetime.datetime.now()} - Cleaned up {len(keys_to_delete)} old tournaments, keeping weeks {weeks_to_keep}")
            
            # If still at limit after cleanup, return error
            if len(tournament_data) >= 10:
                return jsonify({"error": "Maximum of 10 tournaments reached. Old tournaments will be cleared automatically."}), 400
        
        # Generate unique tournament ID (format: T + timestamp + random suffix)
        import time
        timestamp = int(time.time() * 1000)  # milliseconds
        random_suffix = random.randint(1000, 9999)
        tournament_id = f"T{timestamp}{random_suffix}"
        
        # Ensure ID is unique (very unlikely but check anyway)
        while tournament_id in tournament_data:
            random_suffix = random.randint(1000, 9999)
            tournament_id = f"T{timestamp}{random_suffix}"
        
        # Create tournament entry
        created_at = datetime.datetime.now().isoformat()
        tournament_entry = {
            'id': tournament_id,
            'week': week,
            'name': name,
            'games': games,
            'created_at': created_at
        }
        
        # Store tournament
        tournament_data[tournament_id] = tournament_entry
        
        print(f"{datetime.datetime.now()} - Created tournament {tournament_id}: {name} (week {week}, {len(games)} games)")
        
        return jsonify(tournament_entry), 201
        
    except Exception as e:
        print(f"Error creating tournament: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/tournament/list', methods=['GET'])
def list_tournaments():
    """
    List all tournaments with simplified information.
    
    Returns:
        JSON response with list of tournaments containing id, name, week, and number of participants
    """
    global tournament_data
    
    try:
        # Build simplified tournament list
        tournaments_list = []
        
        for tour_id, tournament in tournament_data.items():
            games = tournament.get('games', [])
            
            # Count unique participants across all games
            participants = set()
            for game in games:
                player1 = game.get('player1', {})
                player2 = game.get('player2', {})
                
                # Add player IDs to set (unique participants)
                if player1.get('playerid'):
                    participants.add(player1.get('playerid'))
                if player2.get('playerid'):
                    participants.add(player2.get('playerid'))
            
            tournaments_list.append({
                'id': tournament.get('id', tour_id),
                'name': tournament.get('name'),
                'week': tournament.get('week'),
                'participants': len(participants)
            })
        
        return jsonify({
            "tournaments": tournaments_list,
            "count": len(tournaments_list)
        }), 200
        
    except Exception as e:
        print(f"Error listing tournaments: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/tournament/<id>', methods=['GET'])
def get_tournament(id):
    """
    Get a specific tournament by ID.
    
    Args:
        id: The tournament ID
    
    Returns:
        JSON response with tournament data or error message
    """
    global tournament_data
    
    try:
        if id not in tournament_data:
            return jsonify({"error": f"Tournament '{id}' not found"}), 404
        
        tournament = tournament_data[id]
        return jsonify(tournament), 200
        
    except Exception as e:
        print(f"Error getting tournament: {e}")
        return jsonify({"error": str(e)}), 500


"""
@app.route('/admin/assign-random-deltas', methods=['POST'])
def assign_random_deltas():
    global filtered_players, scraped_ranks

    for player_id, player_data in filtered_players.items():
        ktc_delta = random.randint(-50, 50)
        fc_delta = random.randint(-50, 50)

        player_data['KTC Delta'] = ktc_delta
        player_data['FC Delta'] = fc_delta

        # Update KTC Value and FC Value by adding the deltas
        if 'KTC Value' in player_data:
            player_data['KTC Value'] = player_data.get('KTC Value', 0) + ktc_delta
        if 'FC Value' in player_data:
            player_data['FC Value'] = player_data.get('FC Value', 0) + fc_delta

        # Update scraped_ranks if the player exists there
        if player_id in scraped_ranks:
            scraped_ranks[player_id]['KTC Delta'] = ktc_delta
            scraped_ranks[player_id]['FC Delta'] = fc_delta
            if 'KTC Value' in scraped_ranks[player_id]:
                scraped_ranks[player_id]['KTC Value'] = scraped_ranks[player_id].get('KTC Value', 0) + ktc_delta
            if 'FC Value' in scraped_ranks[player_id]:
                scraped_ranks[player_id]['FC Value'] = scraped_ranks[player_id].get('FC Value', 0) + fc_delta

    return jsonify({"message": "Random deltas assigned and values updated for all filtered players and scraped ranks."}), 200


@app.route('/admin/trigger-fetch', methods=['POST'])
def trigger_fetch_and_filter():
    try:
        fetch_and_filter_data()
        return jsonify({"message": "fetch_and_filter_data triggered successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
"""

@app.route('/', methods=['GET'])
def health_check():
    return "Health check passed", 200


def get_player_projections():
    """
    Fetch player projections for the 2025 NFL regular season.

    Returns:
        dict: JSON response containing player projections.
    """
    url = "https://api.sleeper.com/projections/nfl/2025?season_type=regular&position[]=QB&position[]=RB&position[]=TE&position[]=WR&order_by=adp_2qb"
    response = requests.get(url)
    response.raise_for_status()  # Raise an exception for HTTP errors
    return response.json()


def get_player_stats():
    """
    Fetch player stats for the 2024 NFL regular season.

    Returns:
        dict: JSON response containing player stats.
    """
    url = "https://api.sleeper.com/stats/nfl/2025?season_type=regular&position%5B%5D=QB&position%5B%5D=RB&position%5B%5D=TE&position%5B%5D=WR&order_by=pts_dynasty_2qb"
    response = requests.get(url)
    response.raise_for_status()  # Raise an exception for HTTP errors
    return response.json()


def initialize_data_in_background():
    """
    Initialize all data in the background after the Flask app has started.
    This allows the service to start listening immediately.
    """
    import threading
    
    def _initialize():
        print(f"{datetime.datetime.now()} - Starting background data initialization...")
        
        # 1. Fetch and filter player data
        print(f"{datetime.datetime.now()} - Fetching and filtering player data...")
        fetch_and_filter_data()
        
        # 2. Update with scraped dynasty rankings
        print(f"{datetime.datetime.now()} - Updating with scraped dynasty rankings...")
        update_filtered_players_with_scraped_data()
        
        # 3. Update fantasy points and DFS salaries (requires filtered_players)
        print(f"{datetime.datetime.now()} - filtered_players populated with {len(filtered_players)} players, proceeding with fantasy points and DFS salaries updates")
        update_fantasy_points_data()
        update_dfs_salaries_data()
        
        print(f"{datetime.datetime.now()} - Background data initialization completed!")
    
    # Start initialization in a background thread
    init_thread = threading.Thread(target=_initialize, daemon=True)
    init_thread.start()
    print(f"{datetime.datetime.now()} - Flask app starting, data initialization running in background...")


if __name__ == '__main__':
    # 1. Parse command-line arguments
    parser = argparse.ArgumentParser(description="Run NFL Fantasy Helper")
    parser.add_argument('--mock', action='store_true', default=False,
                        help="Use mock data from file instead of fetching from Sleeper API.")
    args = parser.parse_args()

    # 2. Override global USE_MOCK_DATA if --mock flag is provided
    USE_MOCK_DATA = args.mock

    # 3. Start Flask app immediately
    port = int(os.environ.get("PORT", 5000))  # Default to port 5000 if not set
    
    # 4. Initialize data in background thread (non-blocking)
    initialize_data_in_background()
    
    # 5. Run the Flask app (this will block, but app is already listening)
    app.run(host='0.0.0.0', port=port)
