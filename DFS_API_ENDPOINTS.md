# DFS Salaries API Endpoints

## Overview
The DFS salaries system now supports **multi-week storage** (keeps current and previous week in memory).

---

## Storage Format
- **Key Format**: `{sleeper_id}_W{week}` (e.g., `10229_W7`)
- **Weeks Kept**: Current week + Previous week (auto-cleanup of older data)
- **Memory Usage**: ~292 KB for 2 weeks (negligible)

---

## API Endpoints

### 1. Get All DFS Data
```http
GET /dfs-salaries/data
```
Returns all DFS data for all weeks in memory.

**Response:**
```json
{
  "10229_W7": {
    "sleeper_id": "10229",
    "name": "Rashee Rice",
    "position": "WR",
    "team": "KC",
    "salary": 5600,
    "projected_points": 16.5,
    "value_proj": 2.94,
    "opponent": "LV",
    "season_avg": 0.0,
    "l5_avg": 16.3,
    "l10_avg": 16.5,
    "week": 7,
    "spread": -12.5,
    "over_under": 45.5,
    "proj_team_score": 29.0,
    "opp_rank": 10,
    "date": "2025-10-16"
  },
  "10229_W6": { ... }
}
```

---

### 2. Get Player DFS Data (All Weeks)
```http
GET /dfs-salaries/player/{sleeper_id}
```
Returns all available weeks for a specific player.

**Example:**
```bash
curl "http://localhost:5000/dfs-salaries/player/10229"
```

**Response:**
```json
{
  "10229_W7": { ... },
  "10229_W6": { ... }
}
```

---

### 3. Get Player DFS Data (Specific Week)
```http
GET /dfs-salaries/player/{sleeper_id}?week={week}
```
Returns DFS data for a specific player in a specific week.

**Example:**
```bash
curl "http://localhost:5000/dfs-salaries/player/10229?week=7"
```

**Response:**
```json
{
  "sleeper_id": "10229",
  "name": "Rashee Rice",
  "week": 7,
  "salary": 5600,
  "projected_points": 16.5,
  ...
}
```

---

### 4. Get All DFS Data by Week
```http
GET /dfs-salaries/week/{week}
```
Returns all DFS data for all players in a specific week.

**Example:**
```bash
curl "http://localhost:5000/dfs-salaries/week/7"
```

**Response:**
```json
{
  "10229_W7": { ... },
  "9226_W7": { ... },
  ...
}
```

---

### 5. Statistics Endpoint
```http
GET /statistics
```
Shows which weeks are currently in memory.

**Response:**
```json
{
  "total_dfs_salaries": 778,
  "dfs_salaries_weeks": [6, 7],
  "dfs_salaries_dates": ["2025-10-09", "2025-10-16"],
  ...
}
```

---

### 6. Manual Update Trigger
```http
POST /admin/dfs-salaries/update
```
Manually triggers a DFS salaries update.

**Example:**
```bash
curl -X POST "http://localhost:5000/admin/dfs-salaries/update"
```

---

## Data Fields

| Field | Type | Description |
|-------|------|-------------|
| `sleeper_id` | string | Sleeper player ID |
| `name` | string | Player name |
| `position` | string | Position (QB, RB, WR, TE, DST) |
| `team` | string | Team abbreviation |
| `salary` | int | DraftKings salary |
| `projected_points` | float | Projected fantasy points |
| `value_proj` | float | Value (points per $1000) |
| `opponent` | string | Opponent team abbreviation |
| `season_avg` | float | Season average fantasy points |
| `l5_avg` | float | Last 5 games average |
| `l10_avg` | float | Last 10 games average |
| `week` | int | NFL week number |
| `spread` | float | Point spread (negative = favored) |
| `over_under` | float | Total points O/U |
| `proj_team_score` | float | Projected team score |
| `opp_rank` | int | Opponent rank vs position (1-32, lower = easier) |
| `injury_status` | string/null | Injury status: Q, O, IR, or null (healthy) |
| `date` | string | Date of data (YYYY-MM-DD) |

---

## Auto-Cleanup Behavior

When a new week's data is fetched:
1. New week data is added with keys like `{sleeper_id}_W{new_week}`
2. Old data is checked: if `week < current_week - 1`, it's deleted
3. Result: Only current week and previous week remain in memory

**Example:**
- Week 6 loaded → Keys: `10229_W6`, `9226_W6`, etc.
- Week 7 loaded → Keys: `10229_W7`, `10229_W6`, `9226_W7`, `9226_W6`, etc.
- Week 8 loaded → Keys: `10229_W8`, `10229_W7`, `9226_W8`, `9226_W7` (W6 deleted)

---

## Use Cases

### Compare Week-over-Week Salary Changes
```bash
# Get both weeks for a player
curl "http://localhost:5000/dfs-salaries/player/10229"

# Calculate: salary_change = week7_salary - week6_salary
```

### Find Value Plays This Week
```bash
# Get all week 7 data
curl "http://localhost:5000/dfs-salaries/week/7" | jq 'to_entries | sort_by(.value.value_proj) | reverse | .[0:10]'
```

### Check Matchup Rankings
```bash
# Lower opp_rank = easier matchup
curl "http://localhost:5000/dfs-salaries/week/7" | jq '[.[] | select(.position == "RB")] | sort_by(.opp_rank) | .[0:10]'
```

### Find Injured Players
```bash
# Get all injured/questionable players
curl "http://localhost:5000/dfs-salaries/week/7" | jq '[.[] | select(.injury_status != null)] | .[] | {name, position, injury_status, salary}'
```

### Find High-Value Plays with Good Matchups
```bash
# RBs with opp_rank > 25 (easy matchup) and value_proj > 2.5
curl "http://localhost:5000/dfs-salaries/week/7" | jq '[.[] | select(.position == "RB" and .opp_rank > 25 and .value_proj > 2.5)] | sort_by(.value_proj) | reverse'
```

