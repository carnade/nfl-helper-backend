from tqdm import tqdm
import requests
from bs4 import BeautifulSoup
import json  # Add this import at the top of the file if not already present
from flask import Flask, jsonify  # Add Flask imports

app = Flask(__name__)  # Initialize Flask app

def translate_name(player_name):
    """
    Translates specific player names to their desired format.

    Args:
        player_name (str): The original player name.

    Returns:
        str: The translated player name if a match is found, otherwise the original name.
    """
    name_translations = {
        "Brian Thomas Jr.": "Brian Thomas",
        "Marvin Harrison Jr": "Marvin Harrison",
        "Kenneth Walker III": "Kenneth Walker",
        "D.J. Moore": "DJ Moore",
        "Michael Penix Jr.": "Michael Penix",
        "Marquise Brown": "Hollywood Brown",
        "Chigoziem Okonkwo": "Chig Okonkwo",
        "Gabriel Davis": "Gabe Davis",
        "Calvin Austin III": "Calvin Austin",
        "K.J. Osborn": "KJ Osborn",                 
    }
    return name_translations.get(player_name, player_name)

def scrape_ktc():
    # universal vars
    URL = "https://keeptradecut.com/dynasty-rankings?page={0}&filters=QB|WR|RB|TE|RDP&format={1}"
    all_elements = []
    players = []

    for format in [1,0]:
        if format == 1:
            # find all elements with class "onePlayer"
            for page in tqdm(range(10), desc="Linking to keeptradecut.com's 1QB rankings...",unit="page"):
                page = requests.get(URL.format(page,format))
                soup = BeautifulSoup(page.content, "html.parser")
                player_elements = soup.find_all(class_="onePlayer")
                for player_element in player_elements:
                    all_elements.append(player_element)

            # player information
            for player_element in all_elements:

                # find elements within the player container
                player_name_element = player_element.find(class_="player-name")
                player_position_element = player_element.find(class_="position")
                player_value_element = player_element.find(class_="value")
                player_age_element = player_element.find(class_="position hidden-xs")

                # extract player information
                player_name = player_name_element.get_text(strip=True)
                team_suffix = (player_name[-3:] if player_name[-3:] == 'RFA' else player_name[-4:] if player_name[-4] == 'R' else player_name[-2:] if player_name[-2:] == 'FA' else player_name[-3:] if player_name[-3:].isupper() else "")

                # remove the team suffix
                player_name = player_name.replace(team_suffix, "").strip()
                player_position_rank = player_position_element.get_text(strip=True)
                player_value = player_value_element.get_text(strip=True)
                player_value = int(player_value)
                player_position = player_position_rank[:2]

                # handle NoneType for player_age_element
                if player_age_element:
                    player_age_text = player_age_element.get_text(strip=True)
                    player_age = float(player_age_text[:4]) if player_age_text else 0
                else:
                    player_age = 0

                # split team and rookie
                if team_suffix[0] == 'R':
                    player_team = team_suffix[1:]
                    player_rookie = "Yes"
                else:
                    player_team = team_suffix
                    player_rookie = "No"

                if player_position == "PI":
                    pick_info = {
                        "Player Name": player_name,
                        "Position Rank": None,
                        "Position": player_position,
                        "Team": None,
                        "Value": player_value,
                        "Age": None,
                        "Rookie": None,
                        "SFPosition Rank": None,
                        "SFValue": 0,
                        "RdrftPosition Rank": None,
                        "RdrftValue": 0,
                        "SFRdrftPosition Rank": None,
                        "SFRdrftValue": 0
                    }
                    players.append(pick_info)

                else:
                    player_info = {
                        "Player Name": translate_name(player_name),
                        "Position Rank": player_position_rank,
                        "Position": player_position,
                        "Team": player_team,
                        "Value": player_value,
                        "Age": player_age,
                        "Rookie": player_rookie,
                        "SFPosition Rank": None,
                        "SFValue": 0,
                        "RdrftPosition Rank": None,
                        "RdrftValue": 0,
                        "SFRdrftPosition Rank": None,
                        "SFRdrftValue": 0
                    }
                    players.append(player_info)
        else:
            # find all elements with class "onePlayer"
            for page in tqdm(range(10), desc="Linking to keeptradecut.com's Superflex rankings...",unit="page"):
                page = requests.get(URL.format(page,format))
                soup = BeautifulSoup(page.content, "html.parser")
                player_elements = soup.find_all(class_="onePlayer")
                for player_element in player_elements:
                    all_elements.append(player_element)

            for player_element in all_elements:

                # find elements within the player container
                player_name_element = player_element.find(class_="player-name")
                player_position_element = player_element.find(class_="position")
                player_value_element = player_element.find(class_="value")
                player_age_element = player_element.find(class_="position hidden-xs")

                # extract and print player information
                player_name = player_name_element.get_text(strip=True)
                team_suffix = (player_name[-3:] if player_name[-3:] == 'RFA' else player_name[-4:] if player_name[-4] == 'R' else player_name[-2:] if player_name[-2:] == 'FA' else player_name[-3:] if player_name[-3:].isupper() else "")

                # remove the team suffix
                player_name = player_name.replace(team_suffix, "").strip()
                player_position_rank = player_position_element.get_text(strip=True)
                player_position = player_position_rank[:2]
                player_value = player_value_element.get_text(strip=True)
                player_value = int(player_value)

                if player_position == "PI":
                    for pick in players:
                        if pick["Player Name"] == player_name:
                            pick["SFValue"] = player_value
                            break
                else:
                    for player in players:
                        if player["Player Name"] == player_name:
                            player["SFPosition Rank"] = player_position_rank
                            player["SFValue"] = player_value
                            break

    return players

def scrape_fantasy_calc(players):
    # universal vars
    URL = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs={0}&numTeams=12&ppr=1&includeAdp=false"

    for numQBs in [1,2]:
        if numQBs == 1:
            # pull fantasycalc player values json
            print("Linking to fantasycalc.com's 1QB rankings...")
            json = requests.get(URL.format(numQBs)).json()
            for fc_player in json:
                player_name = fc_player['player']['name']
                player_sleeper_id = fc_player['player']['sleeperId']
                player_position_rank = fc_player['player']['position'] + str(fc_player['positionRank'])
                player_value = fc_player['value']
                player_redraft_value = fc_player['redraftValue']
                for player in players:
                    if player["Player Name"] == player_name:
                        player["FantasyCalc 1QB Position Rank"] = player_position_rank
                        player["FantasyCalc 1QB Value"] = player_value
                        player["FantasyCalc 1QB Redraft Value"] = player_redraft_value
                        player["Sleeper ID"] = player_sleeper_id
                        break

        else:
            # pull fantasycalc player values json
            print("Linking to fantasycalc.com's Superflex rankings...")
            json = requests.get(URL.format(numQBs)).json()
            for fc_player in json:
                player_name = fc_player['player']['name']
                player_name = translate_name(player_name)  # Apply the translation
                player_sleeper_id = fc_player['player']['sleeperId']
                player_position_rank = fc_player['player']['position'] + str(fc_player['positionRank'])
                player_value = fc_player['value']
                player_redraft_value = fc_player['redraftValue']
                for player in players:
                    if player["Player Name"] == player_name:
                        player["FantasyCalc SF Position Rank"] = player_position_rank
                        player["FantasyCalc SF Value"] = player_value
                        player["FantasyCalc SF Redraft Value"] = player_redraft_value
                        player["Sleeper ID"] = player_sleeper_id
                        break

    return players

def tep_adjust(players, tep):
    """
    Adjusts player values based on Tight End Premium (TEP) level.

    Args:
        players (list): List of player dictionaries.
        tep (int): TEP level (0, 1, 2, or 3).

    Returns:
        list: Updated list of players with adjusted values.
    """
    # Base case: no adjustment needed
    if tep == 0:
        return players

    # Define TEP constants
    tep_constants = {
        1: {"t_mult": 1.1, "r": 250},
        2: {"t_mult": 1.2, "r": 350},
        3: {"t_mult": 1.3, "r": 450},
    }

    # Validate TEP level
    if tep not in tep_constants:
        raise ValueError(f"Invalid TEP value: {tep}")

    # Extract constants for the given TEP level
    t_mult = tep_constants[tep]["t_mult"]
    r = tep_constants[tep]["r"]
    s = 0.2  # Scaling factor

    # Adjust tight end values
    rank = 0
    max_player_val = max(player["SFValue"] for player in players)  # Fetch the maximum SFValue
    for player in players:
        if player["Position"] == "TE":  # Use the correct key for position
            t = t_mult * player["SFValue"]
            n = rank / (len(players) - 25) * r + s * r
            player["SFValue"] = min(max_player_val - 1, round(t + n, 0))
        rank += 1

    return players

"""
if __name__ == "__main__":
    # Test TEP adjustment
    tep_level = 1  # Change this to test different TEP levels
    players = scrape_ktc()
    players = scrape_fantasy_calc(players)
    adjusted_players = tep_adjust(players, tep_level)

    # Get the top 50 players
    top_50_players = adjusted_players[:50]  # Slicing the list to get the top 50

    # Write the top 50 players to a JSON file
    with open("top_50_players.json", "w") as file:
        json.dump(top_50_players, file, indent=4)

    print("Top 50 players have been written to 'top_50_players.json'.")
    """