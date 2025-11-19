#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_updated_scraper():
    scraper = DFFSalariesScraper()
    today = '2025-10-22'
    
    print(f"Testing updated scraper with date in URL for: {today}")
    print("=" * 70)
    
    # Test the updated scraper
    players = scraper.get_salaries_with_sleeper_ids(date=today)
    
    print(f"✅ Found {len(players)} players")
    
    if players:
        print("\nSample players:")
        for i, player in enumerate(players[:5]):
            name = player.get('name', 'Unknown')
            team = player.get('team', 'Unknown')
            salary = player.get('salary', 0)
            position = player.get('position', 'Unknown')
            slate_date = player.get('slate_date', 'Unknown')
            slate_type = player.get('slate_type', 'Unknown')
            
            print(f"{i+1}. {name} ({team}) - ${salary} - {position}")
            print(f"   Slate: {slate_type} on {slate_date}")
        
        # Check for different teams to see slate composition
        teams = set(player.get('team', '') for player in players)
        print(f"\n📊 Slate composition:")
        print(f"   Total teams: {len(teams)}")
        print(f"   Teams: {sorted(teams)}")
        
        # Check if we have Monday games (teams that might be in Monday games)
        monday_teams = ['GB', 'PIT']  # Example Monday teams
        monday_found = [team for team in monday_teams if team in teams]
        print(f"   Monday games found: {monday_found}")
        
    else:
        print("❌ No players found")

if __name__ == "__main__":
    test_updated_scraper()
