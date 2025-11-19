#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper

def test_enhanced_salary_fetch():
    scraper = DFFSalariesScraper()
    today = '2025-10-22'
    print(f'Testing enhanced salary fetching with match date info for date: {today}')

    # Test the enhanced process
    players = scraper.get_salaries_with_sleeper_ids(date=today)
    print(f'Found {len(players)} players')

    if players:
        print('\nSample players with match date info:')
        for i, player in enumerate(players[:3]):
            name = player.get('name', 'Unknown')
            team = player.get('team', 'Unknown')
            salary = player.get('salary', 0)
            position = player.get('position', 'Unknown')
            
            # New match date fields
            slate_date = player.get('slate_date', 'Unknown')
            slate_type = player.get('slate_type', 'Unknown')
            slate_start_time = player.get('slate_start_time', 'Unknown')
            slate_day = player.get('slate_day', 'Unknown')
            slate_month_day = player.get('slate_month_day', 'Unknown')
            
            print(f'{i+1}. {name} ({team}) - ${salary} - {position}')
            print(f'   Main Slate: {slate_type} on {slate_day} {slate_month_day} at {slate_start_time}')
            print(f'   Slate Date: {slate_date}')
            
            # Show game-specific info if available
            game_start_time = player.get('game_start_time', 'N/A')
            game_slate_type = player.get('game_slate_type', 'N/A')
            if game_start_time != 'N/A' and game_slate_type != 'N/A':
                print(f'   Game Specific: {game_slate_type} at {game_start_time}')
            else:
                print(f'   Game Specific: No individual showdown slate')
            print()
    else:
        print('No players found')

if __name__ == "__main__":
    test_enhanced_salary_fetch()
