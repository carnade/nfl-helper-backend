# TinyURL API Endpoints

All endpoints are prefixed with `/tinyurl`. Maximum 10 entries (cleared every Thursday at 19:00 CET).

## 1. Create TinyURL (with data)
**POST** `/tinyurl/create`

Create a new TinyURL entry with data immediately.

**Request:**
```json
{
  "name": "my_entry",
  "data": "8|MIQwTgdiAmCmBcBGAnAWgKwBYAM2A0y62aA..."
}
```

**Response (200):**
```json
{
  "name": "my_entry",
  "data": "8|MIQwTgdiAmCmBcBGAnAWgKwBYAM2A0y62aA...",
  "created_at": "2025-11-05T10:30:00.123456",
  "total_entries": 3
}
```

**Errors:**
- `400`: Missing name/data, name already exists, or max entries reached

---

## 2. Create Empty TinyURL (with allowed usernames)
**POST** `/tinyurl/create/empty`

Create an empty TinyURL entry that can be populated later by allowed usernames.

**Request:**
```json
{
  "name": "shared_entry",
  "names": ["user1", "user2", "user3"],
  "week": 8,
  "reveal": "2025-11-10T14:30:00.000Z"
}
```

**Response (200):**
```json
{
  "name": "shared_entry",
  "allowed_names": ["user1", "user2", "user3"],
  "week": 8,
  "reveal": "2025-11-10T14:30:00.000Z",
  "created_at": "2025-11-05T10:30:00.123456",
  "total_entries": 3
}
```

**Note:** 
- `week` parameter is optional
- `reveal` parameter is optional, ISO 8601 UTC format timestamp (e.g., "2025-11-10T14:30:00.000Z")

**Errors:**
- `400`: Missing name/names, names not a list, names empty, name already exists, or max entries reached

---

## 3. Get Entry Data
**GET** `/tinyurl/<name>/data`

Retrieve data for a specific entry by name.

**Example:** `GET /tinyurl/my_entry/data`

**Response (200):**
```json
{
  "name": "my_entry",
  "data": "8|MIQwTgdiAmCmBcBGAnAWgKwBYAM2A0y62aA...",
  "created_at": "2025-11-05T10:30:00.123456",
  "allowed_names": ["user1", "user2"],
  "week": 8,
  "reveal": "2025-11-10T14:30:00.000Z",
  "updated_at": "2025-11-05T11:00:00.123456",
  "updated_by": "user1",
  "user_submissions": {
    "user1": {
      "data": "8|MIQwTgdiAmCmBcBGAnAWgKwBYAM2A0y62aA...",
      "created_at": "2025-11-05T10:30:00.123456",
      "update_count": 2,
      "updated_at": "2025-11-05T11:00:00.123456"
    },
    "user2": {
      "data": "8|MIQwTgdiAmCmBcBGAnAWgKwBYAM2A0y62aA...",
      "created_at": "2025-11-05T10:35:00.123456",
      "update_count": 1,
      "updated_at": "2025-11-05T10:35:00.123456"
    }
  }
}
```

**Note:** 
- `allowed_names`, `week`, `reveal`, `updated_at`, `updated_by`, and `user_submissions` are optional fields that appear if present
- `reveal` is an ISO 8601 UTC timestamp indicating when the entry should be revealed
- `user_submissions` contains per-user submission history with `created_at` (first submission time), `update_count` (number of submissions), and `updated_at` (last update time)

**Response (404):**
```json
{
  "error": "Data with name 'my_entry' not found"
}
```

---

## 3b. Get Entry Details (Submission Status)
**GET** `/tinyurl/<name>/details`

Get detailed submission information for an entry, showing all allowed names and their submission status with update counts.

**Example:** `GET /tinyurl/shared_entry/details`

**Response (200):**
```json
{
  "name": "shared_entry",
  "created_at": "2025-11-05T10:30:00.123456",
  "week": 8,
  "reveal": "2025-11-10T14:30:00.000Z",
  "allowed_names": ["user1", "user2", "user3"],
  "submissions": {
    "user1": {
      "has_submitted": true,
      "update_count": 2,
      "created_at": "2025-11-05T10:30:00.123456",
      "updated_at": "2025-11-05T11:00:00.123456"
    },
    "user2": {
      "has_submitted": true,
      "update_count": 1,
      "created_at": "2025-11-05T10:35:00.123456",
      "updated_at": "2025-11-05T10:35:00.123456"
    },
    "user3": {
      "has_submitted": false,
      "update_count": 0
    }
  },
  "updated_at": "2025-11-05T11:00:00.123456",
  "updated_by": "user1"
}
```

**Note:**
- `allowed_names`: List of all users who can submit data to this entry
- `submissions`: Object with one entry per allowed name showing:
  - `has_submitted`: Boolean indicating if the user has submitted data
  - `update_count`: Number of times the user has submitted/updated (0 if never submitted)
  - `created_at`: Timestamp of first submission (only if `has_submitted` is true)
  - `updated_at`: Timestamp of last update (only if `has_submitted` is true)
- `week`, `reveal`, `updated_at`, and `updated_by` are optional fields
- `reveal` is an ISO 8601 UTC timestamp indicating when the entry should be revealed

**Response (404):**
```json
{
  "error": "Data with name 'shared_entry' not found"
}
```

---

## 4. Get Available Entries for Username
**GET** `/tinyurl/<username>/available`

Get all entry names where the username is in the allowed_names list. Includes a flag indicating if each entry already has data.

**Example:** `GET /tinyurl/user1/available`

**Response (200):**
```json
{
  "username": "user1",
  "entries": [
    {
      "name": "shared_entry",
      "has_data": true,
      "week": 8
    },
    {
      "name": "another_entry",
      "has_data": false,
      "week": 9
    }
  ],
  "count": 2
}
```

**Note:** `week` is optional and only appears if it was set when creating the entry.

---

## 5. Check if Entry Name Exists
**GET** `/tinyurl/name/<name>`

Check if an entry with the given name already exists.

**Example:** `GET /tinyurl/name/my_entry`

**Response if exists (200):**
```json
{
  "name": "my_entry",
  "exists": true,
  "created_at": "2025-11-05T10:30:00.123456",
  "has_allowed_names": true,
  "allowed_names": ["user1", "user2"],
  "week": 8,
  "has_data": true
}
```

**Note:** `has_allowed_names`, `allowed_names`, `week`, and `has_data` are optional fields that appear if present.

**Response if not exists (200):**
```json
{
  "name": "my_entry",
  "exists": false
}
```

---

## 6. Add Data to Entry
**POST** `/tinyurl/<tinyurl_name>/add`

Add data to an existing entry. Only usernames in the allowed_names list can add data.

**Example:** `POST /tinyurl/shared_entry/add`

**Request:**
```json
{
  "name": "user1",
  "data": "8|MIQwTgdiAmCmBcBGAnAWgKwBYAM2A0y62aA..."
}
```

**Response (200):**
```json
{
  "message": "Data added to 'shared_entry' successfully",
  "name": "shared_entry",
  "updated_by": "user1",
  "updated_at": "2025-11-05T11:00:00.123456",
  "update_count": 1,
  "created_at": "2025-11-05T11:00:00.123456"
}
```

**Note:** 
- `update_count` starts at 1 for the first submission, increments with each subsequent submission (2 = first overwrite, 3 = second overwrite, etc.)
- `created_at` is the timestamp when this user first submitted data to this entry
- If the same user submits again, `update_count` will increment but `created_at` remains the same

**Errors:**
- `400`: Missing name/data, entry doesn't have allowed_names, or entry not found
- `401`: Username not in allowed_names list
- `404`: Entry not found

---

## 7. Get Entry Count
**GET** `/tinyurl/count`

Get the current number of entries and remaining capacity.

**Response (200):**
```json
{
  "count": 3,
  "max_entries": 10,
  "remaining": 7
}
```

---

## 8. List All Entries
**GET** `/tinyurl/list`

Get a list of all stored entries with metadata.

**Response (200):**
```json
{
  "total_entries": 3,
  "entries": [
    {
      "name": "my_entry",
      "created_at": "2025-11-05T10:30:00.123456",
      "has_data": true,
      "week": 8,
      "reveal": "2025-11-10T14:30:00.000Z",
      "allowed_names": ["user1", "user2"],
      "user_submissions_count": 2,
      "updated_at": "2025-11-05T11:00:00.123456",
      "updated_by": "user1"
    },
    {
      "name": "shared_entry",
      "created_at": "2025-11-05T10:35:00.123456",
      "has_data": false,
      "week": 9,
      "allowed_names": ["user1", "user2", "user3"],
      "user_submissions_count": 0
    },
    {
      "name": "old_entry",
      "created_at": "2025-11-05T10:40:00.123456",
      "has_data": true
    }
  ]
}
```

**Note:** 
- `has_data`: Boolean indicating if the entry has data
- `week`: Optional, only appears if set when creating the entry
- `reveal`: Optional, ISO 8601 UTC timestamp indicating when the entry should be revealed (only appears if set when creating the entry)
- `allowed_names`: Optional, only appears for entries created via `/create/empty`
- `user_submissions_count`: Optional, number of users who have submitted data (only appears if `user_submissions` exists)
- `updated_at` and `updated_by`: Optional, only appear if the entry has been updated via `/add` endpoint

---

## 9. Delete Entry
**DELETE** `/tinyurl/<name>`

Delete a specific entry by name.

**Example:** `DELETE /tinyurl/my_entry`

**Response (200):**
```json
{
  "message": "Entry 'my_entry' deleted successfully",
  "remaining_entries": 2
}
```

**Response (404):**
```json
{
  "error": "Data with name 'my_entry' not found"
}
```

---

## Usage Flow Examples

### Simple Create & Retrieve
1. `POST /tinyurl/create` with name and data
2. `GET /tinyurl/<name>/data` to retrieve

### Multi-User Shared Entry
1. `POST /tinyurl/create/empty` with name and allowed usernames
2. `GET /tinyurl/<username>/available` to see which entries a user can access
3. `POST /tinyurl/<entry_name>/add` with username and data (must be in allowed_names)
4. `GET /tinyurl/<entry_name>/data` to retrieve the data

