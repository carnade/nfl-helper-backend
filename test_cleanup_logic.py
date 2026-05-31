#!/usr/bin/env python3
"""
Test script to check current week from Sleeper and simulate cleanup logic
for TinyURL and Tournament data.
"""

import sys
from fantasydatascraper import FantasyDataScraper
from datetime import datetime

def test_cleanup_logic():
    """Test the cleanup logic to see what would be deleted"""
    
    print("=" * 80)
    print("Testing Cleanup Logic")
    print("=" * 80)
    
    # Get current week from Sleeper
    print("\n1. Fetching current week from Sleeper API...")
    scraper = FantasyDataScraper()
    current_week = scraper.get_current_week()
    
    print(f"   Current week from Sleeper: {current_week}")
    print(f"   Current time: {datetime.now()}")
    
    # Test cleanup logic for week 17 data
    print("\n2. Testing cleanup logic for week 17 data...")
    test_week = 17
    
    print(f"\n   Test scenario: We have data from week {test_week}")
    print(f"   Current week: {current_week}")
    
    if test_week < current_week:
        print(f"   ✅ Week {test_week} < {current_week} → WOULD BE DELETED")
    elif test_week == current_week:
        print(f"   ⚠️  Week {test_week} == {current_week} → WOULD BE KEPT (current week)")
    else:
        print(f"   ✅ Week {test_week} >= {current_week} → WOULD BE KEPT (future week)")
    
    # Test cleanup logic for various weeks
    print("\n3. Testing cleanup logic for various weeks:")
    print(f"   Current week: {current_week}")
    print(f"\n   Week | Action | Reason")
    print(f"   -----|--------|-------")
    
    for week in [current_week - 2, current_week - 1, current_week, current_week + 1, current_week + 2]:
        if week < current_week:
            action = "DELETE"
            reason = f"Older than current week ({current_week})"
        elif week == current_week:
            action = "KEEP"
            reason = f"Current week"
        else:
            action = "KEEP"
            reason = f"Future week"
        
        print(f"   {week:4d} | {action:6s} | {reason}")
    
    # Show the actual cleanup logic
    print("\n4. Cleanup logic (from code):")
    print("   - Keep: week >= current_week (current week and all future weeks)")
    print("   - Delete: week < current_week (only older weeks)")
    print("   - Delete: week is None (missing week field)")
    
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"Current week: {current_week}")
    print(f"Week 17 data would be: {'DELETED' if 17 < current_week else 'KEPT'}")
    if 17 < current_week:
        print(f"  → Week 17 is {current_week - 17} week(s) older than current week")
    elif 17 == current_week:
        print(f"  → Week 17 is the current week")
    else:
        print(f"  → Week 17 is {17 - current_week} week(s) in the future")
    
    print("\n" + "=" * 80)

if __name__ == '__main__':
    try:
        test_cleanup_logic()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

