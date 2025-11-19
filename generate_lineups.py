#!/usr/bin/env python3

import random
import base64
import json
from get_dfs_salaries_and_stats import DFFSalariesScraper

def generate_lineups():
    scraper = DFFSalariesScraper()
    
    print("Generating DFS lineups...")
    print("=" * 60)
    
    # Get player data
    players = scraper.get_salaries_with_sleeper_ids(date='2025-11-09')
    
    if not players:
        print("No player data available")
        return
    
    print(f"Found {len(players)} players")
    
    # Filter players with valid data
    valid_players = []
    for player in players:
        if (player.get('salary') and 
            player.get('position') and 
            player.get('name') and 
            player.get('team')):
            valid_players.append(player)
    
    print(f"Valid players: {len(valid_players)}")
    
    # Group players by position
    qb_players = [p for p in valid_players if p.get('position') == 'QB']
    rb_players = [p for p in valid_players if p.get('position') == 'RB']
    wr_players = [p for p in valid_players if p.get('position') == 'WR']
    te_players = [p for p in valid_players if p.get('position') == 'TE']
    dst_players = [p for p in valid_players if p.get('position') == 'DST']
    flex_players = rb_players + wr_players + te_players  # Flex can be RB, WR, or TE
    
    print(f"Position counts: QB={len(qb_players)}, RB={len(rb_players)}, WR={len(wr_players)}, TE={len(te_players)}, DST={len(dst_players)}")
    
    # Generate 12 lineups
    lineups = []
    for i in range(18):
        lineup = generate_single_lineup(qb_players, rb_players, wr_players, te_players, dst_players, flex_players)
        if lineup:
            lineups.append(lineup)
    
    # Display lineups and generate output files
    lineup_codes = []
    lineup_base64_codes = []
    
    for i, lineup in enumerate(lineups, 1):
        print(f"\n--- Lineup {i} ---")
        total_salary = sum(player['salary'] for player in lineup)
        print(f"Total Salary: ${total_salary:,}")
        
        for player in lineup:
            print(f"{player['position']}: {player['name']} ({player['team']}) - ${player['salary']:,}")
        
        # Generate lineup code (simplified format)
        lineup_code = generate_lineup_code(lineup)
        print(f"Lineup Code: {lineup_code}")
        lineup_codes.append(f"Lineup {i}: {lineup_code}")
        
        # Generate base64 encoded lineup
        base64_code = generate_base64_lineup(lineup, f"Lineup_{i}")
        print(f"Base64 Code: {base64_code}")
        lineup_base64_codes.append(base64_code)
    
    # Write lineup codes to file
    with open('lineup_codes.txt', 'w') as f:
        for code in lineup_codes:
            f.write(f"{code}\n")
    
    # Write base64 codes to file
    with open('lineup_base64_codes.txt', 'w') as f:
        for code in lineup_base64_codes:
            f.write(f"{code}\n")
    
    print(f"\n✅ Generated {len(lineups)} lineups")
    print("📁 Files created:")
    print("   - lineup_codes.txt (position codes)")
    print("   - lineup_base64_codes.txt (base64 encoded format)")

def generate_single_lineup(qb_players, rb_players, wr_players, te_players, dst_players, flex_players):
    """Generate a single valid lineup following DraftKings rules"""
    
    # DraftKings lineup requirements:
    # 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 DST
    # Salary cap: $50,000
    
    max_attempts = 1000
    for attempt in range(max_attempts):
        lineup = []
        total_salary = 0
        
        # Select QB
        qb = random.choice(qb_players)
        lineup.append(qb)
        total_salary += qb['salary']
        
        # Select 2 RBs
        selected_rbs = random.sample(rb_players, 2)
        lineup.extend(selected_rbs)
        total_salary += sum(rb['salary'] for rb in selected_rbs)
        
        # Select 3 WRs
        selected_wrs = random.sample(wr_players, 3)
        lineup.extend(selected_wrs)
        total_salary += sum(wr['salary'] for wr in selected_wrs)
        
        # Select 1 TE
        te = random.choice(te_players)
        lineup.append(te)
        total_salary += te['salary']
        
        # Select 1 FLEX (RB/WR/TE) - can't be same as already selected
        available_flex = [p for p in flex_players if p not in lineup]
        if not available_flex:
            continue
        flex = random.choice(available_flex)
        lineup.append(flex)
        total_salary += flex['salary']
        
        # Select 1 DST
        dst = random.choice(dst_players)
        lineup.append(dst)
        total_salary += dst['salary']
        
        # Check salary cap
        if total_salary <= 50000:
            return lineup
    
    return None  # Couldn't generate valid lineup

def generate_lineup_code(lineup):
    """Generate a lineup code for the lineup"""
    # Simple lineup code format: QB-RB1-RB2-WR1-WR2-WR3-TE-FLEX-DST
    positions = ['QB', 'RB', 'RB', 'WR', 'WR', 'WR', 'TE', 'FLEX', 'DST']
    
    code_parts = []
    for i, player in enumerate(lineup):
        pos = positions[i] if i < len(positions) else 'UNK'
        # Create a short code: position + first 3 letters of name + team
        name_code = player['name'].replace(' ', '')[:3].upper()
        team_code = player['team']
        code_parts.append(f"{pos}:{name_code}:{team_code}")
    
    return "|".join(code_parts)

def generate_base64_lineup(lineup, username):
    """
    Generate base64 encoded lineup in the format: "username":base64_encoded_string
    The string contains players in format: sleeper_id:salary
    """
    # Create player data in sleeper_id:salary format
    player_strings = []
    for player in lineup:
        sleeper_id = player.get('sleeper_id', '')
        salary = player.get('salary', 0)
        if sleeper_id:  # Only include players with sleeper_id
            player_strings.append(f"{sleeper_id}:{salary}")
    
    # Join all players with a delimiter (e.g., comma)
    players_string = ",".join(player_strings)
    
    # Encode to base64
    base64_encoded = base64.b64encode(players_string.encode('utf-8')).decode('utf-8')
    
    # Return in the format: "username":base64_encoded_string
    return f'"{username}":"{base64_encoded}"'

if __name__ == "__main__":
    generate_lineups()
