#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_url_construction():
    scraper = DFFSalariesScraper()
    today = '2025-10-22'
    
    print(f"Testing URL construction for date: {today}")
    print("=" * 60)
    
    # Test our current URL construction
    slate_url, slate_info = scraper.get_active_main_slate_with_date_info(today)
    
    if slate_url:
        print(f"✅ Found slate: {slate_info.get('slate_type')}")
        print(f"   Teams: {slate_info.get('team_count')}")
        print(f"   Games: {slate_info.get('game_count')}")
        print(f"   Slate URL: {slate_url}")
        print(f"   Slate Date: {slate_info.get('date')}")
        
        # Show what URL we would construct
        current_url = f"{scraper.base_url}?slate={slate_url}"
        print(f"\n🔗 Current URL construction:")
        print(f"   {current_url}")
        
        # Show what URL we SHOULD construct
        correct_url = f"{scraper.base_url}/{slate_info.get('date')}?slate={slate_url}"
        print(f"\n✅ Correct URL should be:")
        print(f"   {correct_url}")
        
        print(f"\n❌ Missing date in URL: {slate_info.get('date')}")
        
    else:
        print("❌ No slate found")

if __name__ == "__main__":
    test_url_construction()
