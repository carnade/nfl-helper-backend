# Data Persistence Setup Guide

This guide walks you through setting up data persistence using GitHub Gist for your Koyeb deployment, while keeping local development using local files.

## How It Works

- **Locally**: Uses local JSON files in `./data/` directory (no Gist needed)
- **On Koyeb**: Uses GitHub Gist if `GITHUB_TOKEN` and `GIST_ID` are set, otherwise falls back to local files (ephemeral)

## Step-by-Step Setup

### Step 1: Create a GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. Click **"Generate new token (classic)"**
3. Give it a name like "NFL Helper Backend Gist"
4. Select the **`gist`** scope (checkbox)
5. Click **"Generate token"**
6. **Copy the token immediately** (you won't see it again!)
   - Save it somewhere safe temporarily (you'll need it for Step 2)

### Step 2: Create the Gist

1. Open your terminal in the project directory
2. Run the helper script:
   ```bash
   python create_gist.py <your_github_token>
   ```
   Replace `<your_github_token>` with the token you copied in Step 1.

3. The script will output:
   - The **Gist ID** (save this!)
   - The Gist URL
   - Instructions for next steps

4. **Save the Gist ID** - you'll need it for Koyeb

### Step 3: Set Up Koyeb Environment Variables

1. Go to your Koyeb dashboard: https://app.koyeb.com
2. Navigate to your service
3. Go to **Settings** → **Environment Variables**
4. Add these two environment variables:

   | Variable Name | Value |
   |--------------|-------|
   | `GITHUB_TOKEN` | Your GitHub token from Step 1 |
   | `GIST_ID` | The Gist ID from Step 2 |

5. Click **Save** or **Update**

### Step 4: Redeploy on Koyeb

1. After adding the environment variables, Koyeb should automatically redeploy
2. If not, go to **Deployments** and trigger a new deployment
3. Check the logs to verify:
   - You should see: `Loaded tinyurl_data from Gist (X entries)`
   - You should see: `Loaded tournament_data from Gist (X entries)`

### Step 5: Verify It's Working

1. Create some test data via your API endpoints
2. Check the logs - you should see: `Saved tinyurl_data to Gist`
3. Restart your service (or wait for a restart)
4. Verify the data persists after restart

## Local Development

**No setup needed!** When running locally:
- The code automatically detects that `GITHUB_TOKEN` and `GIST_ID` are not set
- It uses local files in `./data/` directory
- No Gist API calls are made
- Data persists in `./data/tinyurl_data.json` and `./data/tournament_data.json`

## Troubleshooting

### "Error loading tinyurl_data from Gist"
- Check that `GITHUB_TOKEN` and `GIST_ID` are set correctly in Koyeb
- Verify the token has `gist` scope
- Check that the Gist ID is correct
- The code will automatically fall back to local files (ephemeral on Koyeb)

### "Error saving tinyurl_data to Gist"
- Check your GitHub token is still valid
- Verify you haven't exceeded GitHub API rate limits (5,000/hour)
- The code will automatically fall back to local files

### Data not persisting on Koyeb
- Verify environment variables are set correctly
- Check the deployment logs for Gist-related messages
- Make sure the Gist was created successfully (check the Gist URL)

## Security Notes

- **Never commit your GitHub token to git** - it's in `.gitignore` but double-check
- The Gist is private by default (only you can access it)
- The token is stored securely in Koyeb environment variables
- Local development doesn't use the token at all

## Testing Locally

To test the Gist functionality locally (optional):

```bash
# Set environment variables temporarily
export GITHUB_TOKEN="your_token_here"
export GIST_ID="your_gist_id_here"

# Run your app
python nfl-helper.py

# The app will now use Gist instead of local files
```

To go back to local files:
```bash
unset GITHUB_TOKEN
unset GIST_ID
```

## Summary

- ✅ **Local**: Uses `./data/` files (automatic, no config needed)
- ✅ **Koyeb**: Uses Gist if env vars are set (persists across restarts)
- ✅ **Fallback**: Always falls back to local files if Gist fails
- ✅ **Security**: Token never committed to git, stored in Koyeb env vars

