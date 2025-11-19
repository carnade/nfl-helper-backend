#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper
import requests
import json

def test_slate_detection():
    scraper = DFFSalariesScraper()
    today = '2025-10-22'
    
    print(f"Testing slate detection for date: {today}")
    print("=" * 60)
    
    # Test the slates API directly
    slates_api_url = 'https://www.dailyfantasyfuel.com/data/slates/recent/NFL/draftkings'
    
    # Try different dates to see what slates are available
    test_dates = ['2025-10-22', '2025-10-23', '2025-10-24', '2025-10-25', '2025-10-26']
    
    for test_date in test_dates:
        print(f"\n--- Checking slates for {test_date} ---")
        try:
            params = {'date': test_date}
            response = requests.get(slates_api_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                slates = data.get('slates', [])
                
                print(f"Found {len(slates)} slates:")
                for i, slate in enumerate(slates):
                    slate_type = slate.get('slate_type', 'Unknown')
                    team_count = slate.get('team_count', 0)
                    game_count = slate.get('game_count', 0)
                    start_time = slate.get('start_hhmm', 'Unknown')
                    showdown_flag = slate.get('showdown_flag', 0)
                    
                    print(f"  {i+1}. {slate_type}")
                    print(f"     Teams: {team_count}, Games: {game_count}")
                    print(f"     Start: {start_time}, Showdown: {showdown_flag}")
                    print(f"     URL: {slate.get('url', 'N/A')}")
                    print()
                
                # Find the slate with most teams (excluding showdowns)
                non_showdown_slates = [s for s in slates if s.get('showdown_flag', 0) == 0]
                if non_showdown_slates:
                    main_slate = max(non_showdown_slates, key=lambda s: s.get('team_count', 0))
                    print(f"🎯 MAIN SLATE: {main_slate.get('slate_type')} with {main_slate.get('team_count')} teams")
                else:
                    print("❌ No non-showdown slates found")
                    
            else:
                print(f"❌ API Error: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("Testing our scraper's slate detection logic:")
    
    # Test our scraper's logic
    slate_url, slate_info = scraper.get_active_main_slate_with_date_info(today)
    
    if slate_url:
        print(f"✅ Scraper found slate: {slate_info.get('slate_type')}")
        print(f"   Teams: {slate_info.get('team_count')}")
        print(f"   Games: {slate_info.get('game_count')}")
        print(f"   URL: {slate_url}")
    else:
        print("❌ Scraper found no slate")

if __name__ == "__main__":
    test_slate_detection()
