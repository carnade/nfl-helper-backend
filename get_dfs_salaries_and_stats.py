"""
DFS Salaries and Stats Scraper for DailyFantasyFuel (DraftKings)

This scraper fetches DFS salaries and projections from DailyFantasyFuel.com
for DraftKings NFL contests.
"""

import requests
from bs4 import BeautifulSoup
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DFFSalariesScraper:
    """Scraper for DailyFantasyFuel DraftKings NFL projections and salaries"""
    
    def __init__(self):
        self.base_url = "https://www.dailyfantasyfuel.com/nfl/projections/draftkings"
        self.slates_api_url = "https://www.dailyfantasyfuel.com/data/slates/recent/NFL/draftkings"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def get_active_main_slate(self, date: str = None) -> Optional[str]:
        """
        Get the active main slate URL from DFF API.
        Always selects the slate with the most teams (typically the main slate).
        If no slates found for the given date, tries recent dates.
        
        Args:
            date: Date in format YYYY-MM-DD (defaults to today)
            
        Returns:
            Slate URL string (e.g., "210E7") or None if not found
        """
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # Try the requested date first, then try future dates (tomorrow, day after) for current week slates
        dates_to_try = [date]
        
        # Add future dates to find current week's main slate
        from datetime import timedelta
        current_date = datetime.strptime(date, "%Y-%m-%d")
        for i in range(1, 4):  # Try next 3 days
            dates_to_try.append((current_date + timedelta(days=i)).strftime("%Y-%m-%d"))
        
        # Also try recent dates as fallback
        for i in range(1, 4):
            dates_to_try.append((current_date - timedelta(days=i)).strftime("%Y-%m-%d"))
        
        for try_date in dates_to_try:
            try:
                # Make request to slates API
                params = {'date': try_date}
                response = self.session.get(self.slates_api_url, params=params, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                slates = data.get('slates', [])
                
                if not slates:
                    logger.warning(f"No slates found for date {try_date}")
                    continue
                
                # Find the slate with the most teams (excludes showdown slates)
                main_slate = max(slates, key=lambda s: s.get('team_count', 0))
                
                slate_url = main_slate.get('url')
                team_count = main_slate.get('team_count', 0)
                slate_type = main_slate.get('slate_type', 'Unknown')
                
                logger.info(f"Selected main slate for {try_date}: {slate_type} with {team_count} teams (URL: {slate_url})")
                
                return slate_url
                
            except requests.RequestException as e:
                logger.warning(f"Error fetching slate data for {try_date}: {e}")
                continue
            except (KeyError, ValueError) as e:
                logger.warning(f"Error parsing slate data for {try_date}: {e}")
                continue
        
        logger.error(f"No slates found for any of the tried dates: {dates_to_try}")
        return None
    
    def normalize_name(self, name: str) -> str:
        """
        Normalize player names for matching.
        
        Args:
            name: Player name to normalize
            
        Returns:
            Normalized name in lowercase without special characters
        """
        # Remove suffixes like Jr., Sr., III, etc.
        name = re.sub(r'\s+(Jr\.?|Sr\.?|III|IV|V)$', '', name, flags=re.IGNORECASE)
        # Remove periods and special characters
        name = re.sub(r'[.\']', '', name)
        # Convert to lowercase and strip whitespace
        return name.lower().strip()
    
    def find_sleeper_id_by_name(self, dff_name: str, dff_team: str, filtered_players: Dict) -> Optional[str]:
        """
        Find Sleeper ID by matching DFF player name and team.
        
        Args:
            dff_name: Player name from DailyFantasyFuel
            dff_team: Team abbreviation from DailyFantasyFuel
            filtered_players: Dictionary of Sleeper players
            
        Returns:
            Sleeper ID if found, None otherwise
        """
        if not filtered_players:
            return None
        
        normalized_dff_name = self.normalize_name(dff_name)
        
        # Team name to abbreviation mapping for DST
        team_name_to_abbr = {
            'arizona cardinals': 'ARI', 'atlanta falcons': 'ATL', 'baltimore ravens': 'BAL',
            'buffalo bills': 'BUF', 'carolina panthers': 'CAR', 'chicago bears': 'CHI',
            'cincinnati bengals': 'CIN', 'cleveland browns': 'CLE', 'dallas cowboys': 'DAL',
            'denver broncos': 'DEN', 'detroit lions': 'DET', 'green bay packers': 'GB',
            'houston texans': 'HOU', 'indianapolis colts': 'IND', 'jacksonville jaguars': 'JAX',
            'kansas city chiefs': 'KC', 'las vegas raiders': 'LV', 'los angeles chargers': 'LAC',
            'los angeles rams': 'LAR', 'miami dolphins': 'MIA', 'minnesota vikings': 'MIN',
            'new england patriots': 'NE', 'new orleans saints': 'NO', 'new york giants': 'NYG',
            'new york jets': 'NYJ', 'philadelphia eagles': 'PHI', 'pittsburgh steelers': 'PIT',
            'san francisco 49ers': 'SF', 'seattle seahawks': 'SEA', 'tampa bay buccaneers': 'TB',
            'tennessee titans': 'TEN', 'washington commanders': 'WAS'
        }
        
        # Try DST team matching first
        if normalized_dff_name in team_name_to_abbr:
            team_abbr = team_name_to_abbr[normalized_dff_name]
            for sleeper_id, player_data in filtered_players.items():
                if (player_data.get('position') == 'DEF' and 
                    player_data.get('team') == team_abbr):
                    return sleeper_id
        
        # Try exact match with team
        for sleeper_id, player_data in filtered_players.items():
            sleeper_name = self.normalize_name(
                f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}"
            )
            
            if (normalized_dff_name == sleeper_name and 
                player_data.get('team') == dff_team):
                return sleeper_id
        
        # Try partial match with team
        for sleeper_id, player_data in filtered_players.items():
            sleeper_name = self.normalize_name(
                f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}"
            )
            
            if (normalized_dff_name in sleeper_name or sleeper_name in normalized_dff_name) and \
               player_data.get('team') == dff_team:
                return sleeper_id
        
        return None
    
    def scrape_dff_projections(self, slate_url: str = None) -> List[Dict]:
        """
        Scrape DFS salaries and projections from DailyFantasyFuel.
        
        Args:
            slate_url: Specific slate URL (e.g., "210E7"). If None, auto-detects the main slate.
        
        Returns:
            List of dictionaries containing player data
        """
        # Get the main slate URL if not provided
        if not slate_url:
            slate_url = self.get_active_main_slate()
            if not slate_url:
                logger.error("Could not determine active main slate")
                return []
        
        # Construct the URL with the slate parameter
        url = f"{self.base_url}?slate={slate_url}"
        logger.info(f"Scraping DFF projections from {url}")
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            players = []
            
            # Find rows with class "projections-listing" - these contain player data in data-* attributes
            player_rows = soup.find_all('tr', class_='projections-listing')
            
            logger.info(f"Found {len(player_rows)} player rows")
            
            for row in player_rows:
                try:
                    player_data = self._parse_player_row(row)
                    if player_data:
                        players.append(player_data)
                except Exception as e:
                    logger.debug(f"Error parsing player row: {e}")
                    continue
            
            logger.info(f"Successfully scraped {len(players)} players from DFF slate {slate_url}")
            return players
            
        except requests.RequestException as e:
            logger.error(f"Error fetching DFF projections: {e}")
            return []
    
    def _parse_player_row(self, row) -> Optional[Dict]:
        """
        Parse a player row from the DFF table using data-* attributes.
        
        Args:
            row: BeautifulSoup row element
            
        Returns:
            Dictionary with player data or None
        """
        try:
            # Extract data from data-* attributes
            player_name = row.get('data-name', '').strip()
            if not player_name:
                return None
            
            position = row.get('data-pos', '').strip()
            team = row.get('data-team', '').strip()
            
            # Extract salary
            salary_str = row.get('data-salary', '0')
            try:
                salary = int(salary_str)
            except ValueError:
                salary = 0
            
            # Extract projected fantasy points
            ppg_proj_str = row.get('data-ppg_proj', '0')
            try:
                projected_points = float(ppg_proj_str)
            except ValueError:
                projected_points = 0.0
            
            # Extract value projection
            value_proj_str = row.get('data-value_proj', '0')
            try:
                value_proj = float(value_proj_str)
            except ValueError:
                value_proj = 0.0
            
            # Extract opponent
            opponent = row.get('data-opp', '').strip()
            
            # Extract season average
            szn_avg_str = row.get('data-szn_avg', '0')
            try:
                season_avg = float(szn_avg_str)
            except ValueError:
                season_avg = 0.0
            
            # Extract L5 average
            l5_avg_str = row.get('data-l5_avg', '0')
            try:
                l5_avg = float(l5_avg_str)
            except ValueError:
                l5_avg = 0.0
            
            # Extract L10 average
            l10_avg_str = row.get('data-l10_avg', '0')
            try:
                l10_avg = float(l10_avg_str)
            except ValueError:
                l10_avg = 0.0
            
            # Extract week
            week_str = row.get('data-week', '0')
            try:
                week = int(week_str)
            except ValueError:
                week = 0
            
            # Extract spread
            spread_str = row.get('data-spread', '0')
            try:
                spread = float(spread_str)
            except ValueError:
                spread = 0.0
            
            # Extract over/under
            ou_str = row.get('data-ou', '0')
            try:
                over_under = float(ou_str)
            except ValueError:
                over_under = 0.0
            
            # Extract projected team score
            proj_score_str = row.get('data-proj_score', '0')
            try:
                proj_team_score = float(proj_score_str)
            except ValueError:
                proj_team_score = 0.0
            
            # Extract opponent rank (DvP)
            opp_rank_str = row.get('data-opp_rank', '0')
            try:
                opp_rank = int(opp_rank_str)
            except ValueError:
                opp_rank = 0
            
            # Extract injury status
            injury_status = row.get('data-inj', '').strip()
            # Convert empty string to None for cleaner API responses
            if not injury_status:
                injury_status = None
            
            # Map DEF to DST
            if position == 'DEF':
                position = 'DST'
            
            return {
                'name': player_name,
                'position': position,
                'team': team,
                'salary': salary,
                'projected_points': projected_points,
                'value_proj': value_proj,
                'opponent': opponent,
                'season_avg': season_avg,
                'l5_avg': l5_avg,
                'l10_avg': l10_avg,
                'week': week,
                'spread': spread,
                'over_under': over_under,
                'proj_team_score': proj_team_score,
                'opp_rank': opp_rank,  # Defense vs Position rank (1-32, lower is worse matchup)
                'injury_status': injury_status  # Q (Questionable), O (Out), IR (Injured Reserve), or None
            }
            
        except Exception as e:
            logger.debug(f"Error parsing player row: {e}")
            return None
    
    def get_salaries_with_sleeper_ids(self, filtered_players: Dict = None, date: str = None) -> List[Dict]:
        """
        Scrape DFF projections and match to Sleeper IDs.
        
        Args:
            filtered_players: Dictionary of Sleeper players to match against
            date: Date for slate selection (defaults to today)
            
        Returns:
            List of player dictionaries with Sleeper IDs
        """
        # Get slate URL for the specified date
        slate_url = self.get_active_main_slate(date)
        if not slate_url:
            logger.error("Could not determine active main slate")
            return []
        
        players = self.scrape_dff_projections(slate_url)
        
        if not players:
            logger.warning("No players scraped from DFF")
            return []
        
        # Match to Sleeper IDs if filtered_players provided
        if filtered_players:
            for player in players:
                sleeper_id = self.find_sleeper_id_by_name(
                    player['name'],
                    player['team'],
                    filtered_players
                )
                player['sleeper_id'] = sleeper_id
        
        # Count matched players
        matched_count = sum(1 for p in players if p.get('sleeper_id'))
        logger.info(f"Matched {matched_count}/{len(players)} players to Sleeper IDs")
        
        return players


def main():
    """Test the DFF scraper"""
    scraper = DFFSalariesScraper()
    
    # Test scraping without Sleeper matching
    players = scraper.scrape_dff_projections()
    
    print(f"\n=== DFF Scraper Test ===")
    print(f"Total players scraped: {len(players)}")
    
    if players:
        print("\nSample players (first 10):")
        print(f"{'POS':<4} {'NAME':<25} {'TEAM':<4} {'SALARY':<7} {'PROJ':<6} {'VALUE':<6} {'OPP':<4} {'DvP':<4} {'O/U':<5} {'SPREAD':<7}")
        print("-" * 95)
        for player in players[:10]:
            print(f"{player['position']:<4} {player['name']:<25} {player['team']:<4} "
                  f"${player['salary']:<6} {player['projected_points']:<6.1f} "
                  f"{player['value_proj']:<6.2f} {player['opponent']:<4} "
                  f"{player['opp_rank']:<4} {player['over_under']:<5.1f} {player['spread']:<+7.1f}")
        
        # Count by position
        positions = {}
        for player in players:
            pos = player['position']
            positions[pos] = positions.get(pos, 0) + 1
        
        print("\nPlayers by position:")
        for pos, count in sorted(positions.items()):
            print(f"  {pos}: {count}")
        
        # Show week
        if players:
            print(f"\nProjections for Week: {players[0]['week']}")
    else:
        print("ERROR: No players scraped!")


if __name__ == '__main__':
    main()

