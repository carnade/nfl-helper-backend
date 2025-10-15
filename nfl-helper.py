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
from get_dfs_salaries import DFSSalariesScraper
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
filtered_players = {}
scraped_ranks = {}
teams_data = {}
picks_data = {}  # Dictionary to store draft pick data
fantasy_points_data = {}  # Dictionary to store fantasy points data with Sleeper IDs
dfs_salaries_data = {}  # Dictionary to store DFS salaries data with Sleeper IDs

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
    "HOU": 6, "IND": 11, "JAX": 8, "KC": 10, "LAC": 11, "LAR": 8,
    "LV": 8, "MIA": 12, "MIN": 6, "NE": 13, "NO": 11, "NYG": 12,
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
        'amon-ra st brown': 'amon-ra st. brown'
    }
    
    return name_variations.get(normalized, normalized)


def find_sleeper_id_by_name(fantasy_data_name, filtered_players):
    """
    Find Sleeper ID by matching FantasyData name to Sleeper player data.
    
    Args:
        fantasy_data_name (str): Name from FantasyData
        filtered_players (dict): Dictionary of Sleeper players
        
    Returns:
        str: Sleeper ID if found, None otherwise
    """
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
    
    return None


def update_fantasy_points_data():
    """
    Update fantasy points data by scraping FantasyData and matching to Sleeper IDs.
    Stores data with key format: "sleeper_id_week" to support multiple weeks.
    """
    global fantasy_points_data, last_fantasy_points_update
    
    print(f"{datetime.datetime.now()} - Starting fantasy points data update...")
    
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
    Update DFS salaries data by fetching from RapidAPI and matching to Sleeper IDs.
    Tries current day first, then previous day if no data available.
    Stores only one entry per player (most recent data).
    """
    global dfs_salaries_data, last_dfs_salaries_update
    
    print(f"{datetime.datetime.now()} - Starting DFS salaries data update...")
    
    try:
        # Initialize scraper
        scraper = DFSSalariesScraper()
        
        # Try current day first
        today = datetime.datetime.now().strftime("%Y%m%d")
        print(f"Trying to fetch DFS salaries for today: {today}")
        
        dfs_data = scraper.get_dfs_salaries(today)
        
        # Check if we got valid data
        if "error" in dfs_data or dfs_data.get("statusCode") != 200:
            print(f"No DFS data for today ({today}), trying previous day...")
            
            # Try previous day
            yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d")
            print(f"Trying to fetch DFS salaries for yesterday: {yesterday}")
            
            dfs_data = scraper.get_dfs_salaries(yesterday)
            
            if "error" in dfs_data or dfs_data.get("statusCode") != 200:
                print(f"No DFS data available for {today} or {yesterday}. Aborting DFS salaries update.")
                return
            
            # Use yesterday's date for storage
            date_to_use = yesterday
        else:
            date_to_use = today
        
        # Parse and match to Sleeper IDs
        parsed_salaries = scraper.parse_dfs_data(dfs_data, filtered_players)
        
        if not parsed_salaries:
            print(f"No DFS salary data parsed for {date_to_use}. Aborting DFS salaries update.")
            return
        
        # Clear existing data and store new data (one entry per player)
        global dfs_salaries_data
        dfs_salaries_data = {}
        for player in parsed_salaries:
            # Use sleeper_id as key if available, otherwise use name+team as fallback
            if player.get("sleeper_id"):
                key = player["sleeper_id"]
            else:
                key = f"{player['name']}_{player['team']}"
            
            # Add date to the player data
            player_with_date = player.copy()
            player_with_date["date"] = date_to_use
            
            dfs_salaries_data[key] = player_with_date
        
        last_dfs_salaries_update = datetime.datetime.now()
        
        # Count matched players
        matched_count = sum(1 for p in dfs_salaries_data.values() if p.get("sleeper_id") is not None)
        
        print(f"DFS salaries updated at {last_dfs_salaries_update}")
        print(f"Total DFS salary entries: {len(dfs_salaries_data)}")
        print(f"Matched to Sleeper IDs: {matched_count}")
        print(f"Date: {date_to_use}")
        
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
    global filtered_players, scraped_ranks, teams_data, last_players_update

    data = fetch_data()
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
                "KTC Position Rank": player["Position Rank"],
                "KTC Value": player["SFValue"] if player["SFValue"] != 0 else player["Value"],
                "KTC Delta": ktc_delta,
                "FC Position Rank": player["FantasyCalc SF Position Rank"],
                "FC Value": player["FantasyCalc SF Value"],
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

# Schedule fantasy points updates on Fridays, Mondays, and Tuesdays at 06:30
scheduler.add_job(
    func=update_fantasy_points_data,
    trigger=CronTrigger(day_of_week="fri,mon,tue", hour=6, minute=30)
)

# Schedule DFS salaries update daily at 14:00 CET
scheduler.add_job(
    func=update_dfs_salaries_data,
    trigger=CronTrigger(hour=14, minute=0)
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
        
        # Get the date from the first player (all players should have the same date)
        dfs_date = None
        if dfs_salaries_data:
            first_player = next(iter(dfs_salaries_data.values()))
            dfs_date = first_player.get("date")
        
        # Prepare the response
        response = {
            "uptime": str(uptime),  # Format uptime as a string
            "total_requests": total_requests,
            "average_requests_per_day": average_requests_per_day,
            "requests_per_endpoint": request_statistics["endpoints"],
            "total_dfs_salaries": total_dfs_salaries,
            "dfs_salaries_date": dfs_date,
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

    Returns:
        JSON response containing DFS salaries data for the player.
    """
    try:
        # Look up player by sleeper_id
        player_data = dfs_salaries_data.get(sleeper_id)
        
        if player_data:
            return jsonify(player_data), 200
        else:
            return jsonify({"error": "Player not found"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


if __name__ == '__main__':
    # 1. Parse command-line arguments
    parser = argparse.ArgumentParser(description="Run NFL Fantasy Helper")
    parser.add_argument('--mock', action='store_true', default=False,
                        help="Use mock data from file instead of fetching from Sleeper API.")
    args = parser.parse_args()

    # 2. Override global USE_MOCK_DATA if --mock flag is provided
    USE_MOCK_DATA = args.mock

    # 3. Fetch data once on startup
    fetch_and_filter_data()
    update_filtered_players_with_scraped_data()
    
    # Now that filtered_players is populated, update fantasy points and DFS salaries
    print(f"filtered_players populated with {len(filtered_players)} players, proceeding with fantasy points and DFS salaries updates")
    update_fantasy_points_data()
    update_dfs_salaries_data()

    # 4. Run the Flask app
    port = int(os.environ.get("PORT", 5000))  # Default to port 5000 if not set
    app.run(host='0.0.0.0', port=port)
