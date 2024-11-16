from flask import Flask, request, jsonify
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import json
import os
from flask_cors import CORS
import datetime

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
    else:
        response.headers.add('Access-Control-Allow-Origin', 'null')  # Consider removing this or logging
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Dictionary to store filtered player data
filtered_players = {}
teams_data = {}

# URL to fetch data from
DATA_URL = "https://api.sleeper.app/v1/players/nfl"

# File to read data from when mocking
MOCK_DATA_FILE = "sleeper_data.json"

# Toggle to switch between fetching data from the API or reading from the file
USE_MOCK_DATA = False  # Set to True to use the mock data from the file, False to fetch from the API

DO_THIS_ONCE = False

# Valid fantasy positions to keep
VALID_FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "DEF", "K"}

BYE_WEEKS_2024 = {
    "ARI": 11,
    "ATL": 12,
    "BAL": 14,
    "BUF": 12,
    "CAR": 11,
    "CHI": 7,
    "CIN": 12,
    "CLE": 10,
    "DAL": 7,
    "DEN": 14,
    "DET": 5,
    "GB": 10,
    "HOU": 14,
    "IND": 14,
    "JAX": 12,
    "KC": 6,
    "LAC": 5,
    "LAR": 6,
    "LV": 10,
    "MIA": 6,
    "MIN": 6,
    "NE": 14,
    "NO": 12,
    "NYG": 11,
    "NYJ": 12,
    "PHI": 5,
    "PIT": 9,
    "SEA": 10,
    "SF": 9,
    "TB": 11,
    "TEN": 5,
    "WAS": 14
}
def get_nfl_gameweek(date):
    # Gameweek 1 started on September 5th, 2023 (a Tuesday)
    gameweek_1_start = datetime.date(2024, 9, 3)

    # Calculate the number of days since the first gameweek
    days_since_start = (date - gameweek_1_start).days

    # Each gameweek starts on a Tuesday (7-day interval)
    gameweek = (days_since_start // 7) + 1

    return gameweek

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
    data = fetch_data()
    global filtered_players, teams_data
    filtered_players.clear()
    teams_data.clear()

    for player_id, player_data in data.items():
        on_bye = False
        fantasy_positions = player_data.get("fantasy_positions")

        if (player_data.get("team") is not None):
            try:
                if(BYE_WEEKS_2024[player_data.get("team")] == get_nfl_gameweek(datetime.date.today())):
                    on_bye = True
            except:
                print(player_data.get("team"))
        # Ensure fantasy_positions is a list and not None
        if fantasy_positions is None:
            fantasy_positions = []

        # Check if the player is active and has a valid fantasy position
        if not ((player_data.get("status") == "Inactive") and (player_data.get("injury_status") is None or on_bye)) and \
           any(pos in VALID_FANTASY_POSITIONS for pos in fantasy_positions):
            filtered_players[player_id] = {
                "status": player_data.get("status"),
                "first_name": player_data.get("first_name"),
                "last_name": player_data.get("last_name"),
                "position": player_data.get("position"),
                "competitions": player_data.get("competitions"),
                "sportradar_id": player_data.get("sportradar_id"),
                "oddsjam_id": player_data.get("oddsjam_id"),
                "swish_id": player_data.get("swish_id"),
                "espn_id": player_data.get("espn_id"),
                "fantasy_data_id": player_data.get("fantasy_data_id"),
                "yahoo_id": player_data.get("yahoo_id"),
                "rotowire_id": player_data.get("rotowire_id"),
                "injury_status": player_data.get("injury_status") if player_data.get("injury_status") is not None else "Bye" if on_bye else None    # Added injury_status
            }
            
            # Collect data by teams for the new endpoint
            team_abbr = player_data.get("team")            
            if team_abbr:
                if team_abbr not in teams_data:
                    teams_data[team_abbr] = []
                if player_data.get("injury_status") :
                    teams_data[team_abbr].append({
                        "first_name": player_data.get("first_name"),
                        "last_name": player_data.get("last_name"),
                        "injury_status": player_data.get("injury_status")
                    })

# Schedule the data fetch task once per day
scheduler = BackgroundScheduler()

# Schedule the default job to run every 4 hours
scheduler.add_job(func=fetch_and_filter_data, trigger="interval", hours=4)

# Schedule the job to run every hour on Sundays and Mondays between 12:00 PM and 11:59 PM
scheduler.add_job(
    func=fetch_and_filter_data,
    trigger=CronTrigger(day_of_week="thu,sun,mon", hour="12-23", minute=0)
)
scheduler.start()

if DO_THIS_ONCE:
    fetch_and_filter_data()  # Initial fetch on startup
    DO_THIS_ONCE = False

# Ensure the scheduler is shut down when the app exits
atexit.register(lambda: scheduler.shutdown())

@app.route('/getplayers', methods=['POST'])
def get_players():
    request_data = request.json

    # Print the entire request_data to understand its structure

    response_data = []
    username = request_data.get("username")
    leagues = request_data.get("league", [])

    print(f"{datetime.datetime.now()} Fetch injury report for user: {username}")

    # Ensure that leagues is indeed a list
    if isinstance(leagues, list):
        for league in leagues:
            if isinstance(league, dict):
                league_id = league.get("league_id")
                player_ids = league.get("playerlist", [])
                players_info = {pid: filtered_players.get(pid) for pid in player_ids if pid in filtered_players}

                response_data.append({
                    "league_id": league_id,
                    "players": players_info
                })
            else:
                print(f"Unexpected league format: {league}")
    else:
        print("Leagues data is not a list")

    return jsonify(response_data)


@app.route('/teams', methods=['GET'])
def get_teams():
    return jsonify(teams_data)


@app.route('/', methods=['GET'])
def health_check():
    return "Health check passed", 200

if __name__ == '__main__':
    # Fetch data once on startup
    fetch_and_filter_data()
    
    # Get the PORT environment variable from the platform (like Render)
    port = int(os.environ.get("PORT", 5000))  # Default to 5000 if PORT is not set
    
    # Bind the Flask app to 0.0.0.0 to allow external access, and use the assigned port
    app.run(host='0.0.0.0', port=port)
