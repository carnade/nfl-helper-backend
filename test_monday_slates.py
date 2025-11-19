#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_monday_slates():
    scraper = DFFSalariesScraper()
    
    print("Testing Monday slates...")
    print("=" * 60)
    
    # Test for Monday date
    monday_date = '2025-10-27'
    
    try:
        # Get all slates for Monday
        params = {'date': monday_date}
        response = scraper.session.get(scraper.slates_api_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        slates = data.get('slates', [])
        
        print(f"Found {len(slates)} slates for {monday_date}:")
        for i, slate in enumerate(slates):
            print(f"  {i+1}. {slate.get('slate_type', 'Unknown')}")
            print(f"     Teams: {slate.get('team_count', 0)}, Games: {slate.get('game_count', 0)}")
            print(f"     Start: {slate.get('start_hhmm', '')}, Showdown: {slate.get('showdown_flag', 0)}")
            print(f"     URL: {slate.get('url', '')}")
            print()
        
        # Look specifically for WAS vs KC
        was_kc_slates = [s for s in slates if 'WAS' in s.get('slate_type', '') and 'KC' in s.get('slate_type', '')]
        print(f"WAS vs KC slates: {len(was_kc_slates)}")
        for slate in was_kc_slates:
            print(f"  {slate.get('slate_type')} - Showdown: {slate.get('showdown_flag')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_monday_slates()
