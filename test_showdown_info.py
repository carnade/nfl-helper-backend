#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_showdown_info():
    scraper = DFFSalariesScraper()
    
    print("Testing showdown info method...")
    print("=" * 60)
    
    # Test for Sunday games
    sunday_date = '2025-10-26'
    
    # Test some Sunday games
    test_games = [
        ('TEN', 'IND'),  # 4:25PM game
        ('GB', 'PIT'),   # 8:20PM game
        ('SF', 'HOU'),   # 1:00PM game
    ]
    
    for team, opponent in test_games:
        print(f"\nTesting {team} vs {opponent} on {sunday_date}:")
        showdown_info = scraper.get_game_showdown_info(sunday_date, team, opponent)
        if showdown_info:
            print(f"  ✅ Found showdown: {showdown_info.get('slate_type')}")
            print(f"     Start: {showdown_info.get('start_hhmm')}")
            print(f"     Day: {showdown_info.get('long_dow_name')}")
        else:
            print(f"  ❌ No showdown found")
    
    # Test Monday game
    monday_date = '2025-10-27'
    print(f"\nTesting WAS vs KC on {monday_date}:")
    showdown_info = scraper.get_game_showdown_info(monday_date, 'WAS', 'KC')
    if showdown_info:
        print(f"  ✅ Found showdown: {showdown_info.get('slate_type')}")
        print(f"     Start: {showdown_info.get('start_hhmm')}")
        print(f"     Day: {showdown_info.get('long_dow_name')}")
    else:
        print(f"  ❌ No showdown found")

if __name__ == "__main__":
    test_showdown_info()
