#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_sunday_slates():
    scraper = DFFSalariesScraper()
    
    print("Testing Sunday slates...")
    print("=" * 60)
    
    # Test for Sunday date
    sunday_date = '2025-10-26'
    
    try:
        # Get all slates for Sunday
        params = {'date': sunday_date}
        response = scraper.session.get(scraper.slates_api_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        slates = data.get('slates', [])
        
        print(f"Found {len(slates)} slates for {sunday_date}:")
        for i, slate in enumerate(slates):
            print(f"  {i+1}. {slate.get('slate_type', 'Unknown')}")
            print(f"     Teams: {slate.get('team_count', 0)}, Games: {slate.get('game_count', 0)}")
            print(f"     Start: {slate.get('start_hhmm', '')}, Showdown: {slate.get('showdown_flag', 0)}")
            print(f"     URL: {slate.get('url', '')}")
            print()
        
        # Look specifically for Sunday games (not the main Sun-Mon slate)
        sunday_showdowns = [s for s in slates if s.get('showdown_flag', 0) == 1]
        print(f"Sunday showdown slates: {len(sunday_showdowns)}")
        for slate in sunday_showdowns:
            print(f"  {slate.get('slate_type')} - Showdown: {slate.get('showdown_flag')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_sunday_slates()
