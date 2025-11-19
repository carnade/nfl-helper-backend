#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_slate_preservation():
    scraper = DFFSalariesScraper()
    
    print("Testing slate preservation logic...")
    
    # Simulate Thursday update (Thu-Mon slate)
    print("\n=== Thursday Update (Thu-Mon slate) ===")
    thursday_players = scraper.get_salaries_with_sleeper_ids(date='2025-10-23')
    print(f"Thursday: Found {len(thursday_players)} players")
    
    # Check for MIN @ LAC players (should be in Thu-Mon slate)
    min_lac_players = [p for p in thursday_players if p.get('team') in ['MIN', 'LAC']]
    print(f"MIN/LAC players in Thursday slate: {len(min_lac_players)}")
    
    # Simulate Friday update (Fri-Mon slate) 
    print("\n=== Friday Update (Fri-Mon slate) ===")
    friday_players = scraper.get_salaries_with_sleeper_ids(date='2025-10-24')
    print(f"Friday: Found {len(friday_players)} players")
    
    # Check for MIN @ LAC players (should NOT be in Fri-Mon slate)
    min_lac_players_friday = [p for p in friday_players if p.get('team') in ['MIN', 'LAC']]
    print(f"MIN/LAC players in Friday slate: {len(min_lac_players_friday)}")
    
    print("\n=== Key Format Test ===")
    if thursday_players:
        sample_player = thursday_players[0]
        sleeper_id = sample_player.get('sleeper_id', '12345')
        week = sample_player.get('week', 7)
        date = sample_player.get('slate_date', '2025-10-23')
        
        # New key format
        new_key = f"{sleeper_id}_W{week}_D{date}"
        print(f"New key format: {new_key}")
        
        # Old key format (for comparison)
        old_key = f"{sleeper_id}_W{week}"
        print(f"Old key format: {old_key}")
        
        print(f"Keys are different: {new_key != old_key}")

if __name__ == "__main__":
    test_slate_preservation()
