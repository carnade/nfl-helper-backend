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
scraped_ranks = []
teams_data = {}

# Global variables to track the last update times
last_players_update = None
last_rankings_update = None

# URL to fetch data from
DATA_URL = "https://api.sleeper.app/v1/players/nfl"

# File to read data from when mocking
MOCK_DATA_FILE = "sleeper_data.json"

# Toggle to switch between fetching data from the API or reading from the file
#USE_MOCK_DATA = False  # Will be overridden by command-line flag if set

DO_THIS_ONCE = False

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

# Global variable to track the startup time
startup_time = datetime.datetime.now()

# Global dictionary to track request counts per endpoint
request_statistics = {
    "endpoints": {}  # Tracks request counts per endpoint
}


def get_nfl_gameweek(date):
    # Gameweek 1 started on September 5th, 2024 (a Tuesday)
    gameweek_1_start = datetime.date(2024, 9, 3)
    days_since_start = (date - gameweek_1_start).days
    # Each gameweek is effectively a 7-day window starting on Tuesdays
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
                if (BYE_WEEKS_2024[player_data.get("team")]
                        == get_nfl_gameweek(datetime.date.today())):
                    on_bye = True
            except:
                print(f"Team not found in BYE_WEEKS_2024: {player_data.get('team')}")

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

    # Update the last players update timestamp
    last_players_update = datetime.datetime.now()
    print(f"Players updated at {last_players_update}")

    if scraped_ranks is not None:
        print(f"{datetime.datetime.now()} - Updated filtered_players with old scraped data.")
        update_filtered_players_with_scraped_data(scraped_ranks)


def update_filtered_players_with_scraped_data(input_data=None):
    global filtered_players, scraped_ranks, last_rankings_update

    print(f"{datetime.datetime.now()} - Starting data scraping and updating filtered_players...")

    # Use input_data if provided, otherwise scrape data
    if input_data is not None:
        print("Using provided input data to update filtered_players.")
        adjusted_players = input_data
    else:
        print("Scraping data from KTC and FantasyCalc...")
        tep_level = 1
        ktc_players = scrape_ktc()
        ktc_players = scrape_fantasy_calc(ktc_players)
        adjusted_players = tep_adjust(ktc_players, tep_level)
        scraped_ranks = adjusted_players

    # Update filtered_players with the provided or scraped data
    for player in adjusted_players:
        if "Sleeper ID" in player and player["Sleeper ID"] is not None:
            sleeper_id = player["Sleeper ID"]

            if sleeper_id in filtered_players:
                existing_player = filtered_players[sleeper_id]

                if input_data is not None: 
                    if "KTC Delta" not in existing_player:
                        ktc_delta = 0
                    else:
                        ktc_delta = player.get("SFValue", 0) - existing_player.get("KTC Value", 0)
                    if "FC Delta" not in existing_player:
                        fc_delta = 0
                    else:
                        fc_delta = player.get("FantasyCalc SF Value", 0) - existing_player.get("FC Value", 0)
                else:
                    ktc_delta = player.get("KTC Delta", 0)
                    fc_delta = player.get("FC Delta", 0)

                filtered_players[sleeper_id].update({
                    "KTC Position Rank": player["Position Rank"],
                    "KTC Value": player["SFValue"] if player["SFValue"] != 0 else player["Value"],
                    "KTC Delta": ktc_delta,
                    "FC Position Rank": player["FantasyCalc SF Position Rank"],
                    "FC Value": player["FantasyCalc SF Value"],
                    "FC Delta": fc_delta,
                })
            else:
                print(f"No match found for Sleeper ID: {sleeper_id}")
        else:
            print(f"Missing Sleeper ID for player: {player.get('Player Name')}")

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

scheduler.start()

if DO_THIS_ONCE:
    fetch_and_filter_data()
    update_filtered_players_with_scraped_data()
    DO_THIS_ONCE = False

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

    Request Body:
        {
            "player_list": [12345, 67890, ...]
        }

    Returns:
        JSON response containing the filtered players matching the Sleeper IDs.
    """
    request_data = request.json
    player_ids = request_data.get("playerlist", [])

    if not isinstance(player_ids, list):
        return jsonify({"error": "Invalid player_list format. Must be a list of Sleeper IDs."}), 400

    # Filter players based on the provided Sleeper IDs
    players_info = {
        pid: filtered_players.get(pid)
        for pid in player_ids if pid in filtered_players
    }

    return jsonify(players_info), 200

@app.route('/teams', methods=['GET'])
def get_teams():
    return jsonify(teams_data)


@app.route('/statistics', methods=['GET'])
def get_statistics():
    """
    Endpoint to return request statistics.

    Returns:
        JSON response containing uptime, request counts per endpoint, and average requests per day.
    """
    global request_statistics, startup_time, last_players_update, last_rankings_update

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

        # Prepare the response
        response = {
            "uptime": str(uptime),  # Format uptime as a string
            "total_requests": total_requests,
            "average_requests_per_day": average_requests_per_day,
            "requests_per_endpoint": request_statistics["endpoints"],
            "last_players_update": str(last_players_update) if last_players_update else "Never",
            "last_rankings_update": str(last_rankings_update) if last_rankings_update else "Never"
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
        # Handle optional input data
        request_data = request.get_json(silent=True) or {}
        input_data = request_data.get("input_data")

        if input_data:
            print("Admin triggered rankings update with provided input data...")
        else:
            print("Admin triggered rankings update with scraped data...")

        # Call the rankings update method
        update_filtered_players_with_scraped_data(input_data=input_data)

        return jsonify({"message": "Rankings update triggered successfully."}), 200
    except Exception as e:
        print(f"Error while triggering rankings update: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/', methods=['GET'])
def health_check():
    return "Health check passed", 200


if __name__ == '__main__':
    # 1. Parse command-line arguments
    parser = argparse.ArgumentParser(description="Run NFL Fantasy Helper")
    parser.add_argument('--mock', action='store_true', default=False,
                        help="Use mock data from file instead of fetching from Sleeper API.")
    args = parser.parse_args()

    # 2. Override global USE_MOCK_DATA if --mock flag is provided
    global USE_MOCK_DATA
    USE_MOCK_DATA = args.mock

    # 3. Fetch data once on startup
    fetch_and_filter_data()
    update_filtered_players_with_scraped_data()

    # 4. Run the Flask app
    port = int(os.environ.get("PORT", 5000))  # Default to port 5000 if not set
    app.run(host='0.0.0.0', port=port)
