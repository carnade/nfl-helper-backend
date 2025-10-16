import requests
from bs4 import BeautifulSoup
import json
import time
from typing import Dict, List, Optional
import logging
import datetime
from datetime import timezone, timedelta

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FantasyDataScraper:
    """
    Scraper for FantasyData.com NFL fantasy football leaders data.
    Scrapes data for QB, RB, WR, TE, and DST positions.
    """
    
    def __init__(self):
        self.base_url = "https://fantasydata.com/nfl/fantasy-football-leaders"
        self.sleeper_api_url = "https://api.sleeper.app/v1/state/nfl"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
    def get_current_week(self) -> int:
        """
        Get the current NFL week from Sleeper API.
        Uses week 6 until next Tuesday 07:00 CET.
        
        Returns:
            int: Current week number (will be 6 until next Tuesday)
        """
        try:
            logger.info("Fetching current week from Sleeper API")
            response = self.session.get(self.sleeper_api_url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            current_week = data.get('week', 1)
            season_type = data.get('season_type', 'regular')
            
            logger.info(f"Sleeper API returned week {current_week}, season_type: {season_type}")
            
            # Always use week 6 until next Tuesday 07:00 CET
            if self._should_use_week_6():
                logger.info(f"Using week 6 until next Tuesday 07:00 CET rule")
                return 6
            else:
                logger.info(f"Using current week: {current_week}")
                return current_week
                
        except Exception as e:
            logger.error(f"Error fetching current week from Sleeper API: {e}")
            # Fallback to week 6
            logger.info("Using fallback week 6")
            return 6
            
    def _should_use_week_6(self) -> bool:
        """
        Check if we should use week 6 until next Tuesday 07:00 CET.
        
        Returns:
            bool: True if we should use week 6, False otherwise
        """
        try:
            # Get current time in CET
            cet_tz = timezone(timedelta(hours=1))  # CET is UTC+1
            now_cet = datetime.datetime.now(cet_tz)
            
            # Use week 6 until next Tuesday 07:00 CET
            # This means we use week 6 from now until Tuesday 07:00 CET
            # After Tuesday 07:00 CET, we can use the current week
            
            # Check if it's Tuesday and before 07:00 CET
            if now_cet.weekday() == 1:  # Tuesday is weekday 1
                if now_cet.hour < 7:
                    logger.info(f"Current time is Tuesday {now_cet.hour:02d}:{now_cet.minute:02d} CET - using week 6")
                    return True
                else:
                    logger.info(f"Current time is Tuesday {now_cet.hour:02d}:{now_cet.minute:02d} CET - past 07:00, using current week")
                    return False
            else:
                # Not Tuesday yet, so use week 6
                logger.info(f"Current time is {now_cet.strftime('%A %H:%M')} CET - using week 6 until next Tuesday 07:00")
                return True
                    
        except Exception as e:
            logger.error(f"Error checking time for week calculation: {e}")
            return True  # Default to week 6 if there's an error
            
    def _calculate_fallback_week(self) -> int:
        """
        Fallback method to calculate current week if Sleeper API fails.
        This is a simple estimation based on typical NFL season start.
        
        Returns:
            int: Estimated current week
        """
        try:
            # NFL season typically starts first Thursday of September
            # This is a rough estimation - in practice, you'd want to use Sleeper API
            current_date = datetime.datetime.now()
            september_start = datetime.datetime(current_date.year, 9, 1)
            
            # Find first Thursday of September
            days_until_thursday = (3 - september_start.weekday()) % 7
            if days_until_thursday == 0 and september_start.day > 1:
                days_until_thursday = 7
            season_start = september_start + timedelta(days=days_until_thursday)
            
            # Calculate weeks since season start
            weeks_since_start = (current_date - season_start).days // 7
            
            # NFL regular season is 18 weeks
            estimated_week = min(max(1, weeks_since_start + 1), 18)
            
            logger.warning(f"Using fallback week calculation: {estimated_week}")
            return estimated_week
            
        except Exception as e:
            logger.error(f"Error in fallback week calculation: {e}")
            return 1  # Default to week 1
        
    def _make_request(self, url: str, max_retries: int = 3) -> Optional[BeautifulSoup]:
        """
        Make a request to the given URL with retry logic.
        
        Args:
            url (str): The URL to request
            max_retries (int): Maximum number of retry attempts
            
        Returns:
            BeautifulSoup: Parsed HTML content or None if failed
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"Making request to: {url} (attempt {attempt + 1})")
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                return soup
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"All attempts failed for URL: {url}")
                    return None
                    
    def _parse_player_row(self, row, position: str) -> Optional[Dict]:
        """
        Parse a player row from the FantasyData table.
        
        Args:
            row: BeautifulSoup row element
            position (str): Player position (QB, RB, WR, TE, DST)
            
        Returns:
            Dict: Parsed player data or None if parsing failed
        """
        try:
            cells = row.find_all('td')
            if len(cells) < 5:  # Minimum required cells
                return None
                
            # Skip header rows or rows that don't have proper data
            if cells[0].get_text(strip=True) == 'RK' or not cells[0].get_text(strip=True).isdigit():
                return None
                
            # Extract basic player info based on the actual table structure
            rank = self._safe_int(cells[0].get_text(strip=True))  # RK
            
            if position == 'DST':
                # DST table structure: RK, TEAM, WK, OPP, ...
                team_cell = cells[1]  # TEAM
                team_link = team_cell.find('a')
                player_name = team_link.get_text(strip=True) if team_link else team_cell.get_text(strip=True)
                team = team_cell.get_text(strip=True)
                pos = 'DST'
                
                week_cell = cells[2]  # WK
                week = self._safe_int(week_cell.get_text(strip=True))
                
                opp_cell = cells[3]  # OPP
                opponent = opp_cell.get_text(strip=True)
            else:
                # Regular player table structure: RK, NAME, TEAM, POS, WK, OPP
                name_cell = cells[1]  # NAME
                name_link = name_cell.find('a')
                player_name = name_link.get_text(strip=True) if name_link else name_cell.get_text(strip=True)
                
                team_cell = cells[2]  # TEAM
                team = team_cell.get_text(strip=True)
                
                pos_cell = cells[3]  # POS
                pos = pos_cell.get_text(strip=True)
                
                week_cell = cells[4]  # WK
                week = self._safe_int(week_cell.get_text(strip=True))
                
                opp_cell = cells[5]  # OPP
                opponent = opp_cell.get_text(strip=True)
            
            # Initialize player data
            player_data = {
                'rank': rank,
                'name': player_name,
                'team': team,
                'position': pos,
                'week': week,
                'opponent': opponent,
                'position_type': position
            }
            
            # Parse position-specific stats
            if position == 'QB':
                player_data.update(self._parse_qb_stats(cells))
            elif position == 'RB':
                player_data.update(self._parse_rb_stats(cells))
            elif position == 'WR':
                player_data.update(self._parse_wr_stats(cells))
            elif position == 'TE':
                player_data.update(self._parse_te_stats(cells))
            elif position == 'DST':
                player_data.update(self._parse_dst_stats(cells))
                
            return player_data
            
        except Exception as e:
            logger.error(f"Error parsing player row: {e}")
            return None
            
    def _parse_qb_stats(self, cells: List) -> Dict:
        """Parse QB-specific statistics from table cells."""
        stats = {}
        try:
            # Map cell indices to QB stats (adjust based on actual table structure)
            if len(cells) > 10:
                stats.update({
                    'passing_attempts': self._safe_int(cells[6].get_text(strip=True)),
                    'passing_completions': self._safe_int(cells[7].get_text(strip=True)),
                    'passing_yards': self._safe_int(cells[8].get_text(strip=True)),
                    'passing_tds': self._safe_int(cells[9].get_text(strip=True)),
                    'interceptions': self._safe_int(cells[10].get_text(strip=True)),
                    'rushing_attempts': self._safe_int(cells[11].get_text(strip=True)),
                    'rushing_yards': self._safe_int(cells[12].get_text(strip=True)),
                    'rushing_tds': self._safe_int(cells[13].get_text(strip=True)),
                    'fantasy_points': self._safe_float(cells[-1].get_text(strip=True))  # Usually last column
                })
        except Exception as e:
            logger.error(f"Error parsing QB stats: {e}")
        return stats
        
    def _parse_rb_stats(self, cells: List) -> Dict:
        """Parse RB-specific statistics from table cells."""
        stats = {}
        try:
            if len(cells) > 10:
                stats.update({
                    'rushing_attempts': self._safe_int(cells[6].get_text(strip=True)),
                    'rushing_yards': self._safe_int(cells[7].get_text(strip=True)),
                    'rushing_tds': self._safe_int(cells[8].get_text(strip=True)),
                    'targets': self._safe_int(cells[9].get_text(strip=True)),
                    'receptions': self._safe_int(cells[10].get_text(strip=True)),
                    'receiving_yards': self._safe_int(cells[11].get_text(strip=True)),
                    'receiving_tds': self._safe_int(cells[12].get_text(strip=True)),
                    'fantasy_points': self._safe_float(cells[-1].get_text(strip=True))
                })
        except Exception as e:
            logger.error(f"Error parsing RB stats: {e}")
        return stats
        
    def _parse_wr_stats(self, cells: List) -> Dict:
        """Parse WR-specific statistics from table cells."""
        stats = {}
        try:
            if len(cells) > 10:
                stats.update({
                    'targets': self._safe_int(cells[6].get_text(strip=True)),
                    'receptions': self._safe_int(cells[7].get_text(strip=True)),
                    'catch_rate': self._safe_float(cells[8].get_text(strip=True)),
                    'receiving_yards': self._safe_int(cells[9].get_text(strip=True)),
                    'receiving_tds': self._safe_int(cells[10].get_text(strip=True)),
                    'long_reception': self._safe_int(cells[11].get_text(strip=True)),
                    'fantasy_points': self._safe_float(cells[-1].get_text(strip=True))
                })
        except Exception as e:
            logger.error(f"Error parsing WR stats: {e}")
        return stats
        
    def _parse_te_stats(self, cells: List) -> Dict:
        """Parse TE-specific statistics from table cells."""
        stats = {}
        try:
            if len(cells) >= 21:  # Based on the actual table structure
                stats.update({
                    'targets': self._safe_int(cells[6].get_text(strip=True)),      # TGTS
                    'receptions': self._safe_int(cells[7].get_text(strip=True)),   # REC
                    'catch_rate': self._safe_float(cells[8].get_text(strip=True)), # CATCH%
                    'receiving_yards': self._safe_int(cells[9].get_text(strip=True)), # YDS
                    'receiving_tds': self._safe_int(cells[10].get_text(strip=True)), # TD
                    'long_reception': self._safe_int(cells[11].get_text(strip=True)), # LONG
                    'yards_per_target': self._safe_float(cells[12].get_text(strip=True)), # YDS/TGT
                    'yards_per_reception': self._safe_float(cells[13].get_text(strip=True)), # YDS/REC
                    'rushing_attempts': self._safe_int(cells[14].get_text(strip=True)), # ATT
                    'rushing_yards': self._safe_int(cells[15].get_text(strip=True)), # YDS
                    'rushing_avg': self._safe_float(cells[16].get_text(strip=True)), # AVG
                    'rushing_tds': self._safe_int(cells[17].get_text(strip=True)), # TD
                    'fumbles': self._safe_int(cells[18].get_text(strip=True)), # FUM
                    'fumbles_lost': self._safe_int(cells[19].get_text(strip=True)), # LOST
                    'fantasy_points': self._safe_float(cells[20].get_text(strip=True)) # FPTS
                })
        except Exception as e:
            logger.error(f"Error parsing TE stats: {e}")
        return stats
        
    def _parse_dst_stats(self, cells: List) -> Dict:
        """Parse DST-specific statistics from table cells."""
        stats = {}
        try:
            if len(cells) >= 14:  # DST table has 14 columns
                stats.update({
                    'tackles_for_loss': self._safe_int(cells[4].get_text(strip=True)),  # LOSS
                    'sacks': self._safe_int(cells[5].get_text(strip=True)),            # SCK
                    'qb_hits': self._safe_int(cells[6].get_text(strip=True)),          # QB HITS
                    'interceptions': self._safe_int(cells[7].get_text(strip=True)),    # INT
                    'fumble_recoveries': self._safe_int(cells[8].get_text(strip=True)), # FR
                    'safety': self._safe_int(cells[9].get_text(strip=True)),           # SFTY
                    'defensive_tds': self._safe_int(cells[10].get_text(strip=True)),   # DEF TD
                    'return_tds': self._safe_int(cells[11].get_text(strip=True)),      # RET TD
                    'points_allowed': self._safe_int(cells[12].get_text(strip=True)),  # OPP PTS
                    'fantasy_points': self._safe_float(cells[13].get_text(strip=True)) # FPTS
                })
        except Exception as e:
            logger.error(f"Error parsing DST stats: {e}")
        return stats
        
    def _safe_int(self, value: str) -> Optional[int]:
        """Safely convert string to integer."""
        try:
            return int(value) if value and value != '-' else None
        except (ValueError, TypeError):
            return None
            
    def _safe_float(self, value: str) -> Optional[float]:
        """Safely convert string to float."""
        try:
            return float(value) if value and value != '-' else None
        except (ValueError, TypeError):
            return None
            
    def scrape_position(self, position: str, week_from: Optional[int] = None, week_to: Optional[int] = None, 
                       season: str = "2025_REG", scoring: str = "fpts_ppr") -> List[Dict]:
        """
        Scrape fantasy data for a specific position.
        
        Args:
            position (str): Position to scrape (QB, RB, WR, TE, DST)
            week_from (Optional[int]): Starting week (defaults to current week from Sleeper API)
            week_to (Optional[int]): Ending week (defaults to current week from Sleeper API)
            season (str): Season identifier
            scoring (str): Scoring format
            
        Returns:
            List[Dict]: List of player data dictionaries
        """
        # Use current week from Sleeper API if not specified
        if week_from is None or week_to is None:
            current_week = self.get_current_week()
            week_from = week_from or current_week
            week_to = week_to or current_week
            
        # Build URL based on the pattern from the example
        url = f"{self.base_url}?scope=game&sp={season}&week_from={week_from}&week_to={week_to}&position={position.lower()}&scoring={scoring}&order_by={scoring}&sort_dir=desc"
        
        logger.info(f"Scraping {position} data from week {week_from} to {week_to}")
        
        soup = self._make_request(url)
        if not soup:
            logger.error(f"Failed to retrieve data for {position}")
            return []
            
        # Find the data table
        table = soup.find('table')
        if not table:
            logger.error(f"No table found for {position}")
            return []
            
        # Parse table rows
        players = []
        rows = table.find_all('tr')[1:]  # Skip header row
        
        for row in rows:
            player_data = self._parse_player_row(row, position)
            if player_data:
                players.append(player_data)
                
        logger.info(f"Successfully scraped {len(players)} {position} players")
        return players
        
    def scrape_all_positions(self, week_from: Optional[int] = None, week_to: Optional[int] = None, 
                           season: str = "2025_REG", scoring: str = "fpts_ppr") -> Dict[str, List[Dict]]:
        """
        Scrape fantasy data for all positions.
        
        Args:
            week_from (Optional[int]): Starting week (defaults to current week from Sleeper API)
            week_to (Optional[int]): Ending week (defaults to current week from Sleeper API)
            season (str): Season identifier
            scoring (str): Scoring format
            
        Returns:
            Dict[str, List[Dict]]: Dictionary with position as key and player data as value
        """
        positions = ['QB', 'RB', 'WR', 'TE', 'DST']
        all_data = {}
        
        for position in positions:
            try:
                players = self.scrape_position(position, week_from, week_to, season, scoring)
                all_data[position] = players
                
                # Add delay between requests to be respectful
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error scraping {position}: {e}")
                all_data[position] = []
                
        return all_data
        
    def scrape_qb(self, week_from: Optional[int] = None, week_to: Optional[int] = None, 
                  season: str = "2025_REG", scoring: str = "fpts_ppr") -> List[Dict]:
        """Scrape QB data."""
        return self.scrape_position('QB', week_from, week_to, season, scoring)
        
    def scrape_rb(self, week_from: Optional[int] = None, week_to: Optional[int] = None, 
                  season: str = "2025_REG", scoring: str = "fpts_ppr") -> List[Dict]:
        """Scrape RB data."""
        return self.scrape_position('RB', week_from, week_to, season, scoring)
        
    def scrape_wr(self, week_from: Optional[int] = None, week_to: Optional[int] = None, 
                  season: str = "2025_REG", scoring: str = "fpts_ppr") -> List[Dict]:
        """Scrape WR data."""
        return self.scrape_position('WR', week_from, week_to, season, scoring)
        
    def scrape_te(self, week_from: Optional[int] = None, week_to: Optional[int] = None, 
                  season: str = "2025_REG", scoring: str = "fpts_ppr") -> List[Dict]:
        """Scrape TE data."""
        return self.scrape_position('TE', week_from, week_to, season, scoring)
        
    def scrape_dst(self, week_from: Optional[int] = None, week_to: Optional[int] = None, 
                   season: str = "2025_REG", scoring: str = "fpts_ppr") -> List[Dict]:
        """Scrape DST data."""
        return self.scrape_position('DST', week_from, week_to, season, scoring)
        
    def save_to_json(self, data: Dict, filename: str = "fantasy_data.json"):
        """
        Save scraped data to JSON file.
        
        Args:
            data (Dict): Data to save
            filename (str): Output filename
        """
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Data saved to {filename}")
        except Exception as e:
            logger.error(f"Error saving data to {filename}: {e}")


# Example usage
if __name__ == "__main__":
    scraper = FantasyDataScraper()
    
    # Get current week from Sleeper API
    current_week = scraper.get_current_week()
    print(f"Current week: {current_week}")
    
    # Scrape all positions using current week
    all_data = scraper.scrape_all_positions()
    
    # Save to JSON file
    scraper.save_to_json(all_data, f"fantasy_data_week{current_week}.json")
    
    # Print summary
    for position, players in all_data.items():
        print(f"{position}: {len(players)} players scraped")
