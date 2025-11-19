#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_player_game_info():
    scraper = DFFSalariesScraper()
    
    print("Testing player game information...")
    print("=" * 60)
    
    # Test the Sun-Mon slate
    test_date = '2025-10-26'  # Sunday
    
    try:
        players = scraper.get_salaries_with_sleeper_ids(date=test_date)
        
        if players:
            print(f"Found {len(players)} players")
            
            # Look for Monday game players (WAS vs KC)
            monday_players = [p for p in players if p.get('team') in ['WAS', 'KC']]
            sunday_players = [p for p in players if p.get('team') not in ['WAS', 'KC']]
            
            print(f"\nMonday game players (WAS/KC): {len(monday_players)}")
            if monday_players:
                sample = monday_players[0]
                print(f"Sample Monday player: {sample.get('name')} ({sample.get('team')})")
                print(f"  Date: {sample.get('date')}")
                print(f"  Game date: {sample.get('game_date')}")
                print(f"  Slate date: {sample.get('slate_date')}")
                print(f"  Slate type: {sample.get('slate_type')}")
                print(f"  Game start time: {sample.get('game_start_time')}")
                print(f"  Game day: {sample.get('game_day')}")
                print(f"  Game slate type: {sample.get('game_slate_type')}")
            
            print(f"\nSunday game players (others): {len(sunday_players)}")
            if sunday_players:
                sample = sunday_players[0]
                print(f"Sample Sunday player: {sample.get('name')} ({sample.get('team')})")
                print(f"  Date: {sample.get('date')}")
                print(f"  Game date: {sample.get('game_date')}")
                print(f"  Slate date: {sample.get('slate_date')}")
                print(f"  Slate type: {sample.get('slate_type')}")
                print(f"  Game start time: {sample.get('game_start_time')}")
                print(f"  Game day: {sample.get('game_day')}")
                print(f"  Game slate type: {sample.get('game_slate_type')}")
        else:
            print("No players found")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_player_game_info()
