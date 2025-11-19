#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_monday_game_dates():
    scraper = DFFSalariesScraper()
    
    print("Testing Monday game date handling...")
    print("=" * 60)
    
    # Test scraping on different days to see how dates are handled
    test_dates = ['2025-10-25', '2025-10-26', '2025-10-27']  # Fri, Sat, Sun
    
    for test_date in test_dates:
        print(f"\n--- Testing scrape for {test_date} ---")
        
        try:
            players = scraper.get_salaries_with_sleeper_ids(date=test_date)
            
            if players:
                # Look for Monday game players (WAS vs KC example)
                monday_players = [p for p in players if p.get('team') in ['WAS', 'KC']]
                
                print(f"Found {len(players)} total players")
                print(f"Found {len(monday_players)} Monday game players (WAS/KC)")
                
                if monday_players:
                    sample_player = monday_players[0]
                    print(f"Sample Monday player: {sample_player.get('name')} ({sample_player.get('team')})")
                    print(f"  Scrape date: {test_date}")
                    print(f"  Player date: {sample_player.get('date', 'N/A')}")
                    print(f"  Slate date: {sample_player.get('slate_date', 'N/A')}")
                    print(f"  Slate type: {sample_player.get('slate_type', 'N/A')}")
                    print(f"  Slate start: {sample_player.get('slate_start_time', 'N/A')}")
                    print(f"  Game start: {sample_player.get('game_start_time', 'N/A')}")
                    print(f"  Game slate: {sample_player.get('game_slate_type', 'N/A')}")
                else:
                    print("No Monday game players found")
            else:
                print("No players found")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_monday_game_dates()
