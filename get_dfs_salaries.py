#!/usr/bin/env python3
"""
DFS Salaries Scraper

This module handles fetching DFS salary data from RapidAPI.
It retrieves DraftKings salary information for NFL players.
"""

import requests
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os
import sys

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables for DFS salaries data
dfs_salaries_data = {}
last_dfs_update = None


class DFSSalariesScraper:
    """
    Scraper for DFS salary data from RapidAPI.
    """
    
    def __init__(self):
        self.base_url = "https://tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com/getNFLDFS"
        self.headers = {
            'x-rapidapi-host': 'tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com',
            'x-rapidapi-key': 'PUT_KEY_HERE'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # Global storage for DFS salary data
        self.dfs_salaries_data = {}
        self.last_dfs_update = None
    
    def normalize_name(self, name: str) -> str:
        """
        Normalize player names for better matching between DFS and Sleeper.
        
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
    
    def find_sleeper_id_by_name(self, dfs_name: str, filtered_players: Dict) -> Optional[str]:
        """
        Find Sleeper ID by matching DFS name to Sleeper player data.
        
        Args:
            dfs_name (str): Name from DFS data
            filtered_players (dict): Dictionary of Sleeper players
            
        Returns:
            str: Sleeper ID if found, None otherwise
        """
        normalized_dfs_name = self.normalize_name(dfs_name)
        
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
            if self.normalize_name(sleeper_name) == normalized_dfs_name:
                return sleeper_id
        
        # Try DST team matching
        if normalized_dfs_name in team_name_to_abbr:
            team_abbr = team_name_to_abbr[normalized_dfs_name]
            # Look for DST players with matching team abbreviation
            for sleeper_id, player_data in filtered_players.items():
                if (player_data.get('position') == 'DEF' and 
                    player_data.get('team') == team_abbr):
                    return sleeper_id
        
        # Try partial matches (first name + last name variations)
        dfs_parts = normalized_dfs_name.split()
        if len(dfs_parts) >= 2:
            first_name = dfs_parts[0]
            last_name = ' '.join(dfs_parts[1:])
            
            for sleeper_id, player_data in filtered_players.items():
                sleeper_first = self.normalize_name(player_data.get('first_name', ''))
                sleeper_last = self.normalize_name(player_data.get('last_name', ''))
                
                # Check if first and last names match
                if sleeper_first == first_name and sleeper_last == last_name:
                    return sleeper_id
                
                # Check if last name matches and first name is similar
                if sleeper_last == last_name and first_name in sleeper_first:
                    return sleeper_id
        
        return None
    
    def get_dfs_salaries(self, date: Optional[str] = None) -> Dict:
        """
        Get DFS salary data for a specific date.
        
        Args:
            date (str, optional): Date in YYYYMMDD format. If None, uses today's date.
            
        Returns:
            dict: DFS salary data from the API
        """
        if date is None:
            date = datetime.now().strftime("%Y%m%d")
        
        params = {
            'date': date,
            'includeTeamDefense': 'true'
        }
        
        try:
            logger.info(f"Fetching DFS salaries for date: {date}")
            response = self.session.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched DFS salaries. Status: {data.get('statusCode', 'unknown')}")
            
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching DFS salaries: {e}")
            return {"error": str(e), "statusCode": 500}
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            return {"error": f"JSON decode error: {e}", "statusCode": 500}
        except Exception as e:
            logger.error(f"Unexpected error fetching DFS salaries: {e}")
            return {"error": str(e), "statusCode": 500}
    
    def parse_dfs_data(self, dfs_data: Dict, filtered_players: Dict = None) -> List[Dict]:
        """
        Parse DFS data into a standardized format with Sleeper IDs.
        
        Args:
            dfs_data (dict): Raw DFS data from API
            filtered_players (dict): Dictionary of Sleeper players for matching
            
        Returns:
            list: List of parsed player salary data with Sleeper IDs
        """
        if "error" in dfs_data or dfs_data.get("statusCode") != 200:
            logger.error(f"Invalid DFS data: {dfs_data}")
            return []
        
        parsed_players = []
        draftkings_data = dfs_data.get("body", {}).get("draftkings", [])
        
        for player in draftkings_data:
            try:
                # Standardize position (DEF -> DST)
                position = player.get("pos", "").upper()
                if position == "DEF":
                    position = "DST"
                
                player_name = player.get("longName", "")
                
                # Find matching Sleeper ID if filtered_players is provided
                sleeper_id = None
                if filtered_players:
                    sleeper_id = self.find_sleeper_id_by_name(player_name, filtered_players)
                
                parsed_player = {
                    "sleeper_id": sleeper_id,
                    "name": player_name,
                    "position": position,
                    "team": player.get("team", ""),
                    "salary": int(player.get("salary", 0)) if player.get("salary") else 0,
                    "date": dfs_data.get("body", {}).get("date", "")
                }
                
                parsed_players.append(parsed_player)
                
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing player data: {player}, error: {e}")
                continue
        
        # Count matched players
        matched_count = sum(1 for p in parsed_players if p["sleeper_id"] is not None)
        logger.info(f"Parsed {len(parsed_players)} DFS salary entries, {matched_count} matched to Sleeper IDs")
        
        return parsed_players
    
    def get_salaries_for_date(self, date: Optional[str] = None, filtered_players: Dict = None) -> List[Dict]:
        """
        Get parsed DFS salaries for a specific date.
        
        Args:
            date (str, optional): Date in YYYYMMDD format. If None, uses today's date.
            filtered_players (dict, optional): Dictionary of Sleeper players for matching
            
        Returns:
            list: List of parsed player salary data
        """
        dfs_data = self.get_dfs_salaries(date)
        return self.parse_dfs_data(dfs_data, filtered_players)
    
    def update_dfs_salaries_data(self, filtered_players: Dict = None) -> None:
        """
        Update DFS salaries data by fetching from API and matching to Sleeper IDs.
        Stores data in the global dfs_salaries_data dictionary.
        
        Args:
            filtered_players (dict, optional): Dictionary of Sleeper players for matching
        """
        global dfs_salaries_data, last_dfs_update
        
        print(f"{datetime.now()} - Starting DFS salaries data update...")
        
        try:
            # Get today's date
            today = datetime.now().strftime("%Y%m%d")
            
            # Fetch DFS data
            dfs_data = self.get_dfs_salaries(today)
            
            if "error" in dfs_data:
                print(f"Error fetching DFS data: {dfs_data['error']}")
                return
            
            # Parse and match to Sleeper IDs
            parsed_salaries = self.parse_dfs_data(dfs_data, filtered_players)
            
            # Store in global dictionary with date as key
            self.dfs_salaries_data[today] = parsed_salaries
            self.last_dfs_update = datetime.now()
            
            # Count matched players
            matched_count = sum(1 for p in parsed_salaries if p["sleeper_id"] is not None)
            
            print(f"DFS salaries updated at {self.last_dfs_update}")
            print(f"Total DFS salary entries: {len(parsed_salaries)}")
            print(f"Matched to Sleeper IDs: {matched_count}")
            print(f"Date: {today}")
            
        except Exception as e:
            print(f"Error updating DFS salaries data: {e}")
    
    def get_dfs_salaries_for_date(self, date: str) -> List[Dict]:
        """
        Get DFS salaries data for a specific date from local storage.
        
        Args:
            date (str): Date in YYYYMMDD format
            
        Returns:
            list: List of DFS salary data for the date, empty if not found
        """
        return self.dfs_salaries_data.get(date, [])
    
    def get_all_dfs_salaries(self) -> Dict:
        """
        Get all DFS salaries data from local storage.
        
        Returns:
            dict: All DFS salary data keyed by date
        """
        return self.dfs_salaries_data


def main():
    """
    Test function to demonstrate the DFS salaries scraper.
    """
    scraper = DFSSalariesScraper()
    
    # Test with today's date
    print("Testing DFS salaries scraper...")
    salaries = scraper.get_salaries_for_date()
    
    if salaries:
        print(f"\nFound {len(salaries)} players with DFS salaries:")
        
        # Show first 5 players
        for i, player in enumerate(salaries[:5]):
            sleeper_id = player.get('sleeper_id', 'No match')
            print(f"{i+1}. {player['name']} ({player['position']}) - {player['team']} - ${player['salary']} - Sleeper: {sleeper_id}")
        
        # Show position breakdown
        positions = {}
        for player in salaries:
            pos = player['position']
            positions[pos] = positions.get(pos, 0) + 1
        
        print(f"\nPosition breakdown:")
        for pos, count in sorted(positions.items()):
            print(f"  {pos}: {count} players")
        
        # Show matching stats
        matched = sum(1 for p in salaries if p.get('sleeper_id') is not None)
        print(f"\nSleeper ID matching: {matched}/{len(salaries)} ({matched/len(salaries)*100:.1f}%)")
    else:
        print("No DFS salary data found")


if __name__ == "__main__":
    main()
