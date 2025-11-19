#!/usr/bin/env python3

from get_dfs_salaries_and_stats import DFFSalariesScraper
from datetime import datetime

def debug_current_week_dates():
    scraper = DFFSalariesScraper()
    
    print("Debugging current week dates logic...")
    print("=" * 60)
    
    # Test the Sun-Mon slate
    test_date = '2025-10-26'  # Sunday
    
    try:
        slate_url, slate_info = scraper.get_active_main_slate_with_date_info(test_date)
        
        if slate_url and slate_info:
            slate_dates = slate_info.get('slate_dates', [])
            slate_date = slate_info.get('date', test_date)  # 2025-10-26
            
            print(f"Slate date: {slate_date}")
            print(f"Slate dates count: {len(slate_dates)}")
            
            # Simulate the logic from determine_game_date
            slate_datetime = datetime.strptime(slate_date, '%Y-%m-%d')
            print(f"Slate datetime: {slate_datetime}")
            
            # Find dates that are >= the slate date (current week)
            current_week_dates = []
            for date_info in slate_dates:
                date_str = date_info.get('start_date')
                if date_str:
                    date_datetime = datetime.strptime(date_str, '%Y-%m-%d')
                    print(f"  Checking {date_str} ({date_datetime}) >= {slate_date} ({slate_datetime}): {date_datetime >= slate_datetime}")
                    if date_datetime >= slate_datetime:
                        current_week_dates.append(date_info)
            
            print(f"\nCurrent week dates: {len(current_week_dates)}")
            for date_info in current_week_dates:
                print(f"  {date_info.get('start_date')} ({date_info.get('short_dow_name')})")
            
            # Test the game date logic
            print(f"\nTesting game date logic:")
            
            # For Monday games
            if 'MON' in [d.get('short_dow_name', '') for d in current_week_dates]:
                for date_info in current_week_dates:
                    if date_info.get('short_dow_name') == 'MON':
                        print(f"  Monday game date: {date_info.get('start_date')}")
            
            # For Sunday games  
            if 'SUN' in [d.get('short_dow_name', '') for d in current_week_dates]:
                for date_info in current_week_dates:
                    if date_info.get('short_dow_name') == 'SUN':
                        print(f"  Sunday game date: {date_info.get('start_date')}")
            
        else:
            print("❌ Could not find slate")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_current_week_dates()
