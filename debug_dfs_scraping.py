#!/usr/bin/env python3
"""
Debug script to scrape DFS salaries for week 17 and track what happens to each player.
This will help identify why Saturday players aren't being stored.
"""

import sys
import json
from get_dfs_salaries_and_stats import DFFSalariesScraper
from datetime import datetime

def debug_scrape_week_17(all_players_dict):
    """Scrape week 17 DFS salaries with extensive debugging"""
    
    print("=" * 80)
    print("DEBUG: Starting DFS salary scraping for week 17")
    print("=" * 80)
    
    print(f"\n1. Using {len(all_players_dict)} players for Sleeper ID matching")
    
    print("\n2. Initializing scraper...")
    scraper = DFFSalariesScraper()
    
    # Get current date
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"   Today's date: {today}")
    
    print("\n3. Getting salaries with Sleeper IDs...")
    try:
        parsed_salaries = scraper.get_salaries_with_sleeper_ids(all_players_dict, date=today)
        print(f"   ✅ Successfully scraped {len(parsed_salaries)} players total")
    except Exception as e:
        print(f"   ❌ Error scraping: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n" + "=" * 80)
    print("4. ANALYZING SCRAPED PLAYERS")
    print("=" * 80)
    
    # Group players by game_date
    players_by_game_date = {}
    players_without_game_date = []
    players_by_scrape_date = {}
    
    for i, player in enumerate(parsed_salaries):
        game_date = player.get('game_date')
        start_date = player.get('start_date')
        scraped_from = player.get('_scraped_from_date', 'unknown')
        name = player.get('name', 'unknown')
        team = player.get('team', 'unknown')
        sleeper_id = player.get('sleeper_id', 'unknown')
        week = player.get('week', 'unknown')
        
        # Track by game_date
        if game_date:
            if game_date not in players_by_game_date:
                players_by_game_date[game_date] = []
            players_by_game_date[game_date].append({
                'name': name,
                'team': team,
                'sleeper_id': sleeper_id,
                'week': week,
                'start_date': start_date,
                'scraped_from': scraped_from
            })
        else:
            players_without_game_date.append({
                'name': name,
                'team': team,
                'sleeper_id': sleeper_id,
                'week': week,
                'start_date': start_date,
                'scraped_from': scraped_from
            })
        
        # Track by scraped_from_date
        if scraped_from != 'unknown':
            if scraped_from not in players_by_scrape_date:
                players_by_scrape_date[scraped_from] = []
            players_by_scrape_date[scraped_from].append({
                'name': name,
                'team': team,
                'game_date': game_date,
                'start_date': start_date
            })
    
    print(f"\nTotal players scraped: {len(parsed_salaries)}")
    print(f"Players with game_date: {len(parsed_salaries) - len(players_without_game_date)}")
    print(f"Players without game_date: {len(players_without_game_date)}")
    
    print(f"\nPlayers by game_date:")
    for date in sorted(players_by_game_date.keys()):
        count = len(players_by_game_date[date])
        print(f"  {date}: {count} players")
        # Show first 5 players for Saturday
        if date == '2025-12-27':
            print(f"    First 5 Saturday players:")
            for p in players_by_game_date[date][:5]:
                print(f"      - {p['name']} ({p['team']}) - sleeper_id: {p['sleeper_id']}, week: {p['week']}, start_date: {p['start_date']}, scraped_from: {p['scraped_from']}")
    
    if players_without_game_date:
        print(f"\n⚠️  Players without game_date ({len(players_without_game_date)}):")
        for p in players_without_game_date[:10]:
            print(f"  - {p['name']} ({p['team']}) - start_date: {p['start_date']}, scraped_from: {p['scraped_from']}")
        if len(players_without_game_date) > 10:
            print(f"  ... and {len(players_without_game_date) - 10} more")
    
    print(f"\nPlayers by scraped_from_date:")
    for date in sorted(players_by_scrape_date.keys()):
        count = len(players_by_scrape_date[date])
        print(f"  {date}: {count} players scraped")
        # Show game_date distribution for this scrape date
        game_date_counts = {}
        for p in players_by_scrape_date[date]:
            gd = p['game_date'] or 'None'
            game_date_counts[gd] = game_date_counts.get(gd, 0) + 1
        print(f"    game_date distribution:")
        for gd, count in sorted(game_date_counts.items()):
            print(f"      {gd}: {count} players")
        # Show first 3 players
        print(f"    Sample players:")
        for p in players_by_scrape_date[date][:3]:
            print(f"      - {p['name']} ({p['team']}) - game_date: {p['game_date']}, start_date: {p['start_date']}")
    
    print("\n" + "=" * 80)
    print("5. SIMULATING STORAGE (showing what keys would be generated)")
    print("=" * 80)
    
    # Simulate the storage key generation
    storage_keys_by_game_date = {}
    storage_keys = []
    
    for player in parsed_salaries:
        sleeper_id = player.get("sleeper_id")
        game_date = player.get('game_date', player.get('date', ''))
        week = player.get('week', 0)
        name = player.get('name', 'unknown')
        team = player.get('team', 'unknown')
        
        if sleeper_id and str(sleeper_id).isdigit():
            if game_date:
                key = f"{sleeper_id}_W{week}_D{game_date}"
            else:
                key = f"{sleeper_id}_W{week}"
        else:
            if game_date:
                key = f"{name}_{team}_W{week}_D{game_date}"
            else:
                key = f"{name}_{team}_W{week}"
        
        storage_keys.append(key)
        
        if game_date:
            if game_date not in storage_keys_by_game_date:
                storage_keys_by_game_date[game_date] = []
            storage_keys_by_game_date[game_date].append({
                'key': key,
                'name': name,
                'team': team,
                'sleeper_id': sleeper_id
            })
    
    print(f"\nTotal storage keys that would be created: {len(storage_keys)}")
    print(f"Unique keys: {len(set(storage_keys))}")
    
    print(f"\nStorage keys by game_date:")
    for date in sorted(storage_keys_by_game_date.keys()):
        keys = storage_keys_by_game_date[date]
        unique_keys = len(set(k['key'] for k in keys))
        print(f"  {date}: {len(keys)} players, {unique_keys} unique keys")
        
        # Show potential duplicates
        key_counts = {}
        for k in keys:
            key_counts[k['key']] = key_counts.get(k['key'], 0) + 1
        
        duplicates = {k: v for k, v in key_counts.items() if v > 1}
        if duplicates:
            print(f"    ⚠️  {len(duplicates)} duplicate keys found!")
            for dup_key, count in list(duplicates.items())[:5]:
                print(f"      {dup_key}: {count} players")
                players_with_key = [k for k in keys if k['key'] == dup_key]
                for p in players_with_key:
                    print(f"        - {p['name']} ({p['team']}) sleeper_id: {p['sleeper_id']}")
    
    # Check for Saturday specifically
    sat_keys = storage_keys_by_game_date.get('2025-12-27', [])
    print(f"\n📅 Saturday (2025-12-27) players:")
    print(f"   Total: {len(sat_keys)} players")
    print(f"   Unique keys: {len(set(k['key'] for k in sat_keys))}")
    if sat_keys:
        print(f"   First 10 keys:")
        for k in sat_keys[:10]:
            print(f"     {k['key']} - {k['name']} ({k['team']})")
    else:
        print(f"   ⚠️  NO SATURDAY PLAYERS FOUND!")
    
    print("\n" + "=" * 80)
    print("6. FULL PLAYER DATA (first 50 players, showing all relevant fields)")
    print("=" * 80)
    
    for i, player in enumerate(parsed_salaries[:50]):
        print(f"\nPlayer {i+1}:")
        print(f"  name: {player.get('name')}")
        print(f"  team: {player.get('team')}")
        print(f"  sleeper_id: {player.get('sleeper_id')}")
        print(f"  week: {player.get('week')}")
        print(f"  start_date: {player.get('start_date')}")
        print(f"  game_date: {player.get('game_date')}")
        print(f"  date: {player.get('date')}")
        print(f"  _scraped_from_date: {player.get('_scraped_from_date')}")
        
        # Show what key would be generated
        sleeper_id = player.get("sleeper_id")
        game_date = player.get('game_date', player.get('date', ''))
        week = player.get('week', 0)
        name = player.get('name', 'unknown')
        team = player.get('team', 'unknown')
        
        if sleeper_id and str(sleeper_id).isdigit():
            if game_date:
                key = f"{sleeper_id}_W{week}_D{game_date}"
            else:
                key = f"{sleeper_id}_W{week}"
        else:
            if game_date:
                key = f"{name}_{team}_W{week}_D{game_date}"
            else:
                key = f"{name}_{team}_W{week}"
        
        print(f"  storage_key: {key}")
    
    print("\n" + "=" * 80)
    print("DEBUG COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    # We need to load players first
    print("Loading players...")
    try:
        # Import without triggering Flask app startup
        import sys
        # Temporarily disable USE_MOCK_DATA check
        sys.path.insert(0, '.')
        
        from nfl_helper import fetch_and_filter_data, all_players
        print("Fetching player data...")
        fetch_and_filter_data()
        print(f"Loaded {len(all_players)} players")
        
        # Now run the debug scrape
        debug_scrape_week_17(all_players)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print("\nTrying with empty player list (Sleeper ID matching won't work)...")
        # Create empty dict for all_players
        empty_players = {}
        try:
            debug_scrape_week_17(empty_players)
        except Exception as e2:
            print(f"Error even with empty players: {e2}")
            traceback.print_exc()

