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
        NEVER returns showdown slates - only non-showdown slates are considered.
        If no slates found for the given date, tries recent dates.
        
        Args:
            date: Date in format YYYY-MM-DD (defaults to today)
            
        Returns:
            Slate URL string (e.g., "210E7") or None if not found (including if only showdown slates exist)
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
                
                # Filter out showdown slates - NEVER use showdown slates for prices
                non_showdown_slates = [s for s in slates if s.get('showdown_flag', 0) == 0]
                
                if not non_showdown_slates:
                    logger.warning(f"No non-showdown slates found for date {try_date} (only showdown slates available, skipping)")
                    continue
                
                # Find the slate with the most games (only from non-showdown slates)
                # Prioritize game_count over team_count to get the largest slate
                main_slate = max(non_showdown_slates, key=lambda s: (s.get('game_count', 0), s.get('team_count', 0)))
                
                slate_url = main_slate.get('url')
                team_count = main_slate.get('team_count', 0)
                slate_type = main_slate.get('slate_type', 'Unknown')
                
                game_count = main_slate.get('game_count', 0)
                logger.info(f"Selected main slate for {try_date}: {slate_type} with {game_count} games ({team_count} teams) (URL: {slate_url})")
                
                return slate_url
                
            except requests.RequestException as e:
                logger.warning(f"Error fetching slate data for {try_date}: {e}")
                continue
            except (KeyError, ValueError) as e:
                logger.warning(f"Error parsing slate data for {try_date}: {e}")
                continue
        
        logger.error(f"No slates found for any of the tried dates: {dates_to_try}")
        return None
    
    def get_active_main_slate_with_date_info(self, date: str = None) -> tuple:
        """
        Get the active main slate URL and date information from DFF API.
        Always selects the slate with the most teams (typically the main slate).
        NEVER returns showdown slates - only non-showdown slates are considered.
        If no slates found for the given date, tries future dates (tomorrow, day after) for current week slates.
        
        Args:
            date: Date in format YYYY-MM-DD (defaults to today)
            
        Returns:
            Tuple of (slate_url, slate_date_info) or (None, None) if not found (including if only showdown slates exist)
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
                
                # Filter out showdown slates - NEVER use showdown slates for prices
                non_showdown_slates = [s for s in slates if s.get('showdown_flag', 0) == 0]
                
                if not non_showdown_slates:
                    logger.warning(f"No non-showdown slates found for date {try_date} (only showdown slates available, skipping)")
                    continue
                
                # Find the slate with the most games (only from non-showdown slates)
                # Prioritize game_count over team_count to get the largest slate
                main_slate = max(non_showdown_slates, key=lambda s: (s.get('game_count', 0), s.get('team_count', 0)))
                
                slate_url = main_slate.get('url')
                team_count = main_slate.get('team_count', 0)
                slate_type = main_slate.get('slate_type', 'Unknown')
                
                game_count = main_slate.get('game_count', 0)
                logger.info(f"Selected main slate for {try_date}: {slate_type} with {game_count} games ({team_count} teams) (URL: {slate_url})")
                
                # Prepare slate date info
                slate_date_info = {
                    'date': try_date,
                    'slate_type': slate_type,
                    'start_hhmm': main_slate.get('start_hhmm', 'Unknown'),
                    'long_dow_name': main_slate.get('long_dow_name', 'Unknown'),
                    'month_daynum': main_slate.get('month_daynum', 'Unknown'),
                    'team_count': team_count,
                    'game_count': main_slate.get('game_count', 0),
                    'slate_dates': data.get('dates', [])  # Include the dates array from slate data
                }
                
                return slate_url, slate_date_info
                
            except requests.RequestException as e:
                logger.warning(f"Error fetching slate data for {try_date}: {e}")
                continue
            except (KeyError, ValueError) as e:
                logger.warning(f"Error parsing slate data for {try_date}: {e}")
                continue
        
        logger.error(f"No slates found for any of the tried dates: {dates_to_try}")
        return None, None
    
    def is_slate_showdown(self, slate_url: str, date: str) -> bool:
        """
        Check if a slate URL is a showdown slate.
        
        Args:
            slate_url: Slate URL to check (e.g., "21A90")
            date: Date in format YYYY-MM-DD
            
        Returns:
            True if the slate is a showdown, False otherwise
        """
        try:
            params = {'date': date}
            response = self.session.get(self.slates_api_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            slates = data.get('slates', [])
            
            for slate in slates:
                if slate.get('url') == slate_url:
                    return slate.get('showdown_flag', 0) == 1
            
            return False
        except Exception as e:
            logger.warning(f"Error checking if slate {slate_url} is showdown: {e}")
            return False
    
    def get_main_slate_url_for_date(self, date: str) -> Optional[str]:
        """
        Get the main slate URL for a specific date.
        NEVER returns showdown slates - only non-showdown slates are considered.
        
        Args:
            date: Date in format YYYY-MM-DD
            
        Returns:
            Slate URL string (e.g., "21A10") or None if not found (including if only showdown slates exist)
        """
        try:
            params = {'date': date}
            response = self.session.get(self.slates_api_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            slates = data.get('slates', [])
            
            if not slates:
                logger.warning(f"No slates found for date {date}")
                return None
            
            # Filter out showdown slates - NEVER use showdown slates for prices
            non_showdown_slates = [s for s in slates if s.get('showdown_flag', 0) == 0]
            
            if not non_showdown_slates:
                logger.warning(f"No non-showdown slates found for date {date} (only showdown slates available, skipping)")
                return None
            
            # Find the slate with the most games (only from non-showdown slates)
            # Prioritize game_count over team_count to get the largest slate
            main_slate = max(non_showdown_slates, key=lambda s: (s.get('game_count', 0), s.get('team_count', 0)))
            slate_url = main_slate.get('url')
            
            if slate_url:
                logger.info(f"Found main slate URL for {date}: {slate_url} (non-showdown)")
            
            return slate_url
            
        except Exception as e:
            logger.warning(f"Error getting main slate URL for {date}: {e}")
            return None
    
    def get_all_relevant_slate_urls_for_date(self, date: str, initial_slate_url: str = None) -> List[str]:
        """
        Get all non-showdown slate URLs for a specific date that match the date's month_daynum.
        Uses the initial_slate_url to query the API endpoint that returns all slates for that date.
        
        Args:
            date: Date in format YYYY-MM-DD
            initial_slate_url: Optional slate URL to use for querying (if provided, uses API endpoint with url param)
            
        Returns:
            List of slate URL strings (e.g., ["218FF", "21A90"])
        """
        try:
            from datetime import datetime
            
            # Parse the date to get month and day for matching
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            target_month_day = date_obj.strftime('%b %d')  # e.g., "Nov 27"
            
            # If we have an initial slate URL, use the API endpoint with url parameter
            # This gives us all slates for that date
            if initial_slate_url:
                params = {'date': date, 'url': initial_slate_url}
            else:
                params = {'date': date}
            
            response = self.session.get(self.slates_api_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            slates = data.get('slates', [])
            
            if not slates:
                logger.warning(f"No slates found for date {date}")
                return []
            
            # Filter to get all non-showdown slates that match the target date's month_daynum
            relevant_slates = []
            for slate in slates:
                # Skip showdown slates
                if slate.get('showdown_flag', 0) == 1:
                    continue
                
                slate_month_day = slate.get('month_daynum', '')
                slate_url = slate.get('url')
                
                # Check if this slate's month_daynum matches our target date
                if slate_month_day == target_month_day and slate_url:
                    relevant_slates.append(slate_url)
                    logger.info(f"Found relevant slate for {date}: {slate_url} ({slate.get('slate_type', 'Unknown')})")
            
            if not relevant_slates:
                logger.warning(f"No relevant non-showdown slates found for {date} matching {target_month_day}")
                # Fallback: try to get main slate, but NEVER use showdown slates
                non_showdown_slates = [s for s in slates if s.get('showdown_flag', 0) == 0]
                if non_showdown_slates:
                    main_slate = max(non_showdown_slates, key=lambda s: (s.get('game_count', 0), s.get('team_count', 0)))
                    if main_slate.get('url'):
                        logger.info(f"Using fallback main slate: {main_slate.get('url')} (non-showdown)")
                        return [main_slate.get('url')]
                else:
                    logger.warning(f"No non-showdown slates available for {date} (only showdown slates, skipping)")
                    return []
            
            logger.info(f"Found {len(relevant_slates)} relevant slate(s) for {date}: {relevant_slates}")
            return relevant_slates
            
        except Exception as e:
            logger.warning(f"Error getting all relevant slate URLs for {date}: {e}")
            # Fallback to main slate
            main_slate_url = self.get_main_slate_url_for_date(date)
            return [main_slate_url] if main_slate_url else []
    
    def get_game_showdown_info(self, date: str, team: str, opponent: str) -> Optional[Dict]:
        """
        Get specific showdown information for a game between two teams.
        
        Args:
            date: Date in format YYYY-MM-DD
            team: Team abbreviation (e.g., 'GB')
            opponent: Opponent team abbreviation (e.g., 'PIT')
            
        Returns:
            Dict with showdown info or None if not found
        """
        try:
            # First get all slates for the date to find the specific game
            params = {'date': date}
            response = self.session.get(self.slates_api_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            slates = data.get('slates', [])
            
            # Look for showdown slates that match the teams
            for slate in slates:
                if slate.get('showdown_flag', 0) == 1:  # This is a showdown slate
                    slate_type = slate.get('slate_type', '')
                    # Check if this showdown matches our teams
                    if (team in slate_type and opponent in slate_type) or \
                       (opponent in slate_type and team in slate_type):
                        return {
                            'start_hhmm': slate.get('start_hhmm', 'Unknown'),
                            'long_dow_name': slate.get('long_dow_name', 'Unknown'),
                            'month_daynum': slate.get('month_daynum', 'Unknown'),
                            'slate_type': slate_type,
                            'url': slate.get('url', 'Unknown')
                        }
            
            # If no specific showdown found, return None
            return None
            
        except Exception as e:
            logger.debug(f"Error getting showdown info for {team} vs {opponent}: {e}")
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
    
    def scrape_dff_projections(self, slate_url: str = None, date: str = None) -> List[Dict]:
        """
        Scrape DFS salaries and projections from DailyFantasyFuel.
        
        Args:
            slate_url: Specific slate URL (e.g., "210E7"). If None, auto-detects the main slate.
            date: Date for the slate (e.g., "2025-10-26"). If None, uses today.
        
        Returns:
            List of dictionaries containing player data
        """
        # Get the main slate URL and date info if not provided
        if not slate_url or not date:
            slate_url, slate_info = self.get_active_main_slate_with_date_info()
            if not slate_url:
                logger.error("Could not determine active main slate")
                return []
            date = slate_info.get('date', datetime.now().strftime("%Y-%m-%d"))
        
        # Construct the URL with the date and slate parameter
        url = f"{self.base_url}/{date}?slate={slate_url}"
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
            
            # Extract start_date (game date)
            start_date = row.get('data-start_date', '').strip()
            
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
                'injury_status': injury_status,  # Q (Questionable), O (Out), IR (Injured Reserve), or None
                'start_date': start_date  # Game start date from the scraped data
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
        # Get slate URL and date info for the specified date
        slate_url, slate_date_info = self.get_active_main_slate_with_date_info(date)
        if not slate_url:
            logger.error("Could not determine active main slate")
            return []
        
        # Add slate date information to each player
        slate_dates = slate_date_info.get('slate_dates', [])
        
        # Step 1: Find the dates in the main slate
        logger.info(f"All slate_dates from main slate: {[d.get('start_date') for d in slate_dates]}")
        slate_date = slate_date_info.get('date', date)
        logger.info(f"Slate date (filter reference): {slate_date}")
        
        main_slate_dates = []
        for date_info in slate_dates:
            date_str = date_info.get('start_date')
            if date_str:
                # Only include dates that are >= the slate date (current week)
                from datetime import datetime
                slate_datetime = datetime.strptime(slate_date, '%Y-%m-%d')
                date_datetime = datetime.strptime(date_str, '%Y-%m-%d')
                if date_datetime >= slate_datetime:
                    main_slate_dates.append(date_str)
                    logger.info(f"  Including date {date_str} (>= {slate_date})")
                else:
                    logger.info(f"  Excluding date {date_str} (< {slate_date})")
        
        logger.info(f"Final main_slate_dates: {main_slate_dates}")
        
        # Step 1.5: Scrape DFF projections for EACH date in the main slate
        # Each date may have multiple relevant slates (e.g., "Thu" and "Thu-Fri"), so we get all of them
        all_players = []
        for game_date in main_slate_dates:
            logger.info(f"=== Scraping DFF projections for date: {game_date} ===")
            
            # First get the main slate URL to use for querying all slates
            main_slate_url = self.get_main_slate_url_for_date(game_date)
            if not main_slate_url:
                logger.warning(f"⚠️ Could not find main slate URL for {game_date}, skipping")
                continue
            
            # Get all relevant slate URLs for this date (non-showdown slates matching the date)
            relevant_slate_urls = self.get_all_relevant_slate_urls_for_date(game_date, main_slate_url)
            if not relevant_slate_urls:
                logger.warning(f"⚠️ Could not find any relevant slate URLs for {game_date}, skipping")
                continue
            
            # Scrape each relevant slate for this date
            date_players = []
            for slate_url in relevant_slate_urls:
                logger.info(f"Scraping slate {slate_url} for date {game_date}")
                slate_players = self.scrape_dff_projections(slate_url, game_date)
                if slate_players:
                    logger.info(f"✅ Found {len(slate_players)} players from slate {slate_url}")
                    date_players.extend(slate_players)
                else:
                    logger.warning(f"⚠️ No players found for slate {slate_url} on {game_date}")
            
            logger.info(f"Scraping result for {game_date}: {len(date_players)} total players found from {len(relevant_slate_urls)} slate(s)")
            if date_players:
                logger.info(f"✅ Successfully scraped {len(date_players)} players for {game_date}")
                all_players.extend(date_players)
            else:
                logger.warning(f"⚠️ No players found for date {game_date} (this may be normal if data isn't available yet)")
        
        players = all_players
        
        if not players:
            logger.warning("No players scraped from DFF for any date in main slate")
            return []
        
        # Step 2: Make ONE call per date to get all showdowns
        showdown_data = {}  # date -> list of showdowns
        for game_date in main_slate_dates:
            try:
                params = {'date': game_date}
                response = self.session.get(self.slates_api_url, params=params, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                slates = data.get('slates', [])
                
                # Get all showdown slates for this date
                showdowns = [s for s in slates if s.get('showdown_flag', 0) == 1]
                showdown_data[game_date] = showdowns
                
                logger.debug(f"Found {len(showdowns)} showdowns for {game_date}")
                
            except Exception as e:
                logger.debug(f"Error fetching showdowns for {game_date}: {e}")
                showdown_data[game_date] = []
        
        # Step 3: Map showdowns to players
        logger.info(f"Mapping showdowns to players. Main slate dates: {main_slate_dates}")
        logger.info(f"Showdown data summary: {[(date, len(showdowns)) for date, showdowns in showdown_data.items()]}")
        
        # Log all available showdowns for debugging
        for game_date_str in main_slate_dates:
            showdowns = showdown_data.get(game_date_str, [])
            logger.info(f"Showdowns for {game_date_str}:")
            for showdown in showdowns:
                logger.info(f"  - {showdown.get('slate_type', 'Unknown')} (day: {showdown.get('long_dow_name', 'Unknown')})")
        
        for player in players:
            player['slate_date'] = slate_date_info.get('date', date)
            player['slate_type'] = slate_date_info.get('slate_type', 'Unknown')
            player['slate_start_time'] = slate_date_info.get('start_hhmm', 'Unknown')
            player['slate_day'] = slate_date_info.get('long_dow_name', 'Unknown')
            player['slate_month_day'] = slate_date_info.get('month_daynum', 'Unknown')
            
            # Get start_date from scraped data (this is the game date)
            scraped_start_date = player.get('start_date', '')
            team = player.get('team', '')
            opponent = player.get('opponent', '')
            game_date = None
            showdown_info = None
            
            # Use start_date from scraped data if available
            if scraped_start_date:
                game_date = scraped_start_date
                
                # Fetch showdown data for this date if not already fetched
                if game_date not in showdown_data:
                    try:
                        params = {'date': game_date}
                        response = self.session.get(self.slates_api_url, params=params, timeout=10)
                        response.raise_for_status()
                        data = response.json()
                        slates = data.get('slates', [])
                        showdowns = [s for s in slates if s.get('showdown_flag', 0) == 1]
                        showdown_data[game_date] = showdowns
                    except Exception as e:
                        logger.debug(f"Error fetching showdowns for {game_date}: {e}")
                        showdown_data[game_date] = []
                
                # Try to find showdown info for this date
                showdowns_for_date = showdown_data.get(game_date, [])
                
                for showdown in showdowns_for_date:
                    slate_type = showdown.get('slate_type', '')
                    if (team in slate_type and opponent in slate_type) or \
                       (opponent in slate_type and team in slate_type):
                        showdown_info = showdown
                        break
            else:
                # Fallback: Try to find showdown by matching (old method)
                for game_date_str in main_slate_dates:
                    showdowns = showdown_data.get(game_date_str, [])
                    for showdown in showdowns:
                        slate_type = showdown.get('slate_type', '')
                        if (team in slate_type and opponent in slate_type) or \
                           (opponent in slate_type and team in slate_type):
                            game_date = game_date_str
                            showdown_info = showdown
                            break
                    if showdown_info:
                        break
            
            # Update player data with game date and showdown info
            if game_date:
                player['game_date'] = game_date
                player['date'] = game_date  # Update the main date field
                
                # If no showdown found, infer game_day from game_date
                if not showdown_info:
                    try:
                        from datetime import datetime
                        game_datetime = datetime.strptime(game_date, '%Y-%m-%d')
                        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                        player['game_day'] = day_names[game_datetime.weekday()]
                        player['game_month_day'] = game_datetime.strftime('%b %d')
                    except Exception as e:
                        logger.debug(f"Error inferring game_day from game_date {game_date}: {e}")
                
            if showdown_info:
                player['game_start_time'] = showdown_info.get('start_hhmm', 'Unknown')
                player['game_day'] = showdown_info.get('long_dow_name', player.get('game_day', 'Unknown'))
                player['game_month_day'] = showdown_info.get('month_daynum', player.get('game_month_day', 'Unknown'))
                player['game_slate_type'] = showdown_info.get('slate_type', 'Unknown')
        
        # Match to Sleeper IDs if filtered_players provided
        if filtered_players:
            for player in players:
                sleeper_id = self.find_sleeper_id_by_name(
                    player['name'],
                    player['team'],
                    filtered_players
                )
                # Store player's full name if sleeper_id not found, otherwise store the sleeper_id
                player['sleeper_id'] = sleeper_id if sleeper_id else player['name']
        
        # Count matched players (those with numeric sleeper_id, not name)
        matched_count = sum(1 for p in players if p.get('sleeper_id') and p.get('sleeper_id').isdigit())
        logger.info(f"Matched {matched_count}/{len(players)} players to Sleeper IDs (others stored with player name)")
        
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

