#!/usr/bin/env python3

import logging
import sys
from get_dfs_salaries_and_stats import DFFSalariesScraper

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('det_gb_debug.log')
    ]
)

logger = logging.getLogger(__name__)

def test_det_gb_players():
    scraper = DFFSalariesScraper()
    
    print("=" * 80)
    print("Testing DFS Salaries for DET and GB Players")
    print("Date: 2025-11-05 (Wednesday)")
    print("=" * 80)
    
    # Get players
    test_date = '2025-11-05'
    logger.info(f"Fetching salaries for date: {test_date}")
    
    players = scraper.get_salaries_with_sleeper_ids(date=test_date)
    
    if not players:
        print("No players found")
        return
    
    print(f"\nTotal players found: {len(players)}")
    
    # Filter for DET and GB players
    det_players = [p for p in players if p.get('team') == 'DET']
    gb_players = [p for p in players if p.get('team') == 'GB']
    
    print(f"\nDET players: {len(det_players)}")
    print(f"GB players: {len(gb_players)}")
    
    # Analyze DET players
    print("\n" + "=" * 80)
    print("DET PLAYERS ANALYSIS")
    print("=" * 80)
    for player in det_players[:10]:  # Show first 10
        print(f"\nPlayer: {player.get('name')} ({player.get('position')})")
        print(f"  Team: {player.get('team')} vs {player.get('opponent')}")
        print(f"  game_date: {player.get('game_date', 'MISSING')}")
        print(f"  game_day: {player.get('game_day', 'MISSING')}")
        print(f"  game_start_time: {player.get('game_start_time', 'MISSING')}")
        print(f"  game_slate_type: {player.get('game_slate_type', 'MISSING')}")
        print(f"  slate_date: {player.get('slate_date', 'MISSING')}")
        print(f"  slate_type: {player.get('slate_type', 'MISSING')}")
    
    # Analyze GB players
    print("\n" + "=" * 80)
    print("GB PLAYERS ANALYSIS")
    print("=" * 80)
    for player in gb_players[:10]:  # Show first 10
        print(f"\nPlayer: {player.get('name')} ({player.get('position')})")
        print(f"  Team: {player.get('team')} vs {player.get('opponent')}")
        print(f"  game_date: {player.get('game_date', 'MISSING')}")
        print(f"  game_day: {player.get('game_day', 'MISSING')}")
        print(f"  game_start_time: {player.get('game_start_time', 'MISSING')}")
        print(f"  game_slate_type: {player.get('game_slate_type', 'MISSING')}")
        print(f"  slate_date: {player.get('slate_date', 'MISSING')}")
        print(f"  slate_type: {player.get('slate_type', 'MISSING')}")
    
    # Check what opponents DET and GB have
    print("\n" + "=" * 80)
    print("OPPONENT ANALYSIS")
    print("=" * 80)
    det_opponents = set(p.get('opponent') for p in det_players if p.get('opponent'))
    gb_opponents = set(p.get('opponent') for p in gb_players if p.get('opponent'))
    
    print(f"DET opponents: {sorted(det_opponents)}")
    print(f"GB opponents: {sorted(gb_opponents)}")
    
    # Check game dates for these players
    print("\n" + "=" * 80)
    print("GAME DATE ANALYSIS")
    print("=" * 80)
    det_dates = {}
    for p in det_players:
        game_date = p.get('game_date', 'MISSING')
        if game_date not in det_dates:
            det_dates[game_date] = []
        det_dates[game_date].append(p.get('opponent'))
    
    gb_dates = {}
    for p in gb_players:
        game_date = p.get('game_date', 'MISSING')
        if game_date not in gb_dates:
            gb_dates[game_date] = []
        gb_dates[game_date].append(p.get('opponent'))
    
    print(f"DET game dates: {det_dates}")
    print(f"GB game dates: {gb_dates}")
    
    # Check which players are missing game_day
    print("\n" + "=" * 80)
    print("PLAYERS MISSING game_day")
    print("=" * 80)
    missing_game_day = []
    for player in det_players + gb_players:
        if not player.get('game_day') or player.get('game_day') == 'Unknown':
            missing_game_day.append(player)
    
    print(f"Total missing game_day: {len(missing_game_day)}")
    for p in missing_game_day[:10]:
        print(f"  - {p.get('name')} ({p.get('team')} vs {p.get('opponent')}) - game_date: {p.get('game_date', 'MISSING')}")

if __name__ == "__main__":
    test_det_gb_players()
