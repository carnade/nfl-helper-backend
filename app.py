from flask import Flask, request, jsonify, make_response
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import json
import os
from flask_cors import CORS

app = Flask(__name__)

# Allowed IP prefix and specific domain
ALLOWED_IP_PREFIX = "81.235."
ALLOWED_DOMAIN = "https://nfl-draft-helper.netlify.app"

# Initialize CORS to allow any origin by default
CORS(app, supports_credentials=True)

def custom_cors_origin(origin):
    if origin is None:
        return False
    if origin.startswith(f"http://{ALLOWED_IP_PREFIX}") or origin.startswith(f"https://{ALLOWED_IP_PREFIX}"):
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
        response.headers.add('Access-Control-Allow-Origin', 'null')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# The rest of your existing code...

# Dictionary to store filtered player data
filtered_players = {}

# URL to fetch data from
DATA_URL = "https://api.sleeper.app/v1/players/nfl"

# File to read data from when mocking
MOCK_DATA_FILE = "sleeper_data.json"

# Toggle to switch between fetching data from the API or reading from the file
USE_MOCK_DATA = False  # Set to True to use the mock data from the file, False to fetch from the API

# Valid fantasy positions to keep
VALID_FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "DEF", "K"}

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
        return response.json()

def fetch_and_filter_data():
    data = fetch_data()

    global filtered_players
    filtered_players.clear()

    for player_id, player_data in data.items():
        fantasy_positions = player_data.get("fantasy_positions")

        # Ensure fantasy_positions is a list and not None
        if fantasy_positions is None:
            fantasy_positions = []

        # Check if the player is active and has a valid fantasy position
        if player_data.get("status") == "Active" and \
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
                "injury_status": player_data.get("injury_status")  # Added injury_status
            }

# Schedule the data fetch task once per day
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_and_filter_data, trigger="interval", days=1)
scheduler.start()

# Ensure the scheduler is shut down when the app exits
atexit.register(lambda: scheduler.shutdown())

@app.route('/getplayers', methods=['POST'])
def get_players():
    request_data = request.json
    response_data = []

    for league in request_data:
        league_id = league.get("league_id")
        player_ids = league.get("playerlist", [])
        players_info = {pid: filtered_players.get(pid) for pid in player_ids if pid in filtered_players}

        response_data.append({
            "league_id": league_id,
            "players": players_info
        })

    return jsonify(response_data)

if __name__ == '__main__':
    fetch_and_filter_data()  # Initial fetch on startup
