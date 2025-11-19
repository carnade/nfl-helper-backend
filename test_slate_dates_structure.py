#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_slate_dates_structure():
    scraper = DFFSalariesScraper()
    
    print("Testing slate dates structure...")
    print("=" * 60)
    
    # Test the Sun-Mon slate
    test_date = '2025-10-26'  # Sunday
    
    try:
        slate_url, slate_info = scraper.get_active_main_slate_with_date_info(test_date)
        
        if slate_url and slate_info:
            print(f"✅ Found slate: {slate_info.get('slate_type')}")
            print(f"   Teams: {slate_info.get('team_count')}")
            print(f"   Games: {slate_info.get('game_count')}")
            print(f"   Slate URL: {slate_url}")
            print(f"   Slate Date: {slate_info.get('date')}")
            
            # Check the slate_dates structure
            slate_dates = slate_info.get('slate_dates', [])
            print(f"\n📅 Slate dates structure:")
            print(f"   Number of dates: {len(slate_dates)}")
            
            for i, date_info in enumerate(slate_dates):
                print(f"   Date {i+1}:")
                print(f"     start_date: {date_info.get('start_date', 'N/A')}")
                print(f"     short_dow_name: {date_info.get('short_dow_name', 'N/A')}")
                print(f"     long_dow_name: {date_info.get('long_dow_name', 'N/A')}")
                print(f"     month_daynum: {date_info.get('month_daynum', 'N/A')}")
                print()
            
            # Test the determine_game_date method
            print("🎯 Testing determine_game_date method:")
            slate_date = slate_info.get('date', test_date)
            monday_date = scraper.determine_game_date('WAS', 'KC', slate_dates, slate_date)
            sunday_date = scraper.determine_game_date('GB', 'PIT', slate_dates, slate_date)  # Example Sunday team
            
            print(f"   WAS vs KC (Monday game): {monday_date}")
            print(f"   GB vs PIT (Sunday game): {sunday_date}")
            
        else:
            print("❌ Could not find slate")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_slate_dates_structure()
