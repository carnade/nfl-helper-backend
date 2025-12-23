#!/usr/bin/env python3
"""
One-time script to create a GitHub Gist for data persistence.
Run this once to create the Gist, then use the Gist ID in Koyeb environment variables.

Usage:
    python create_gist.py <your_github_token>

The script will:
1. Create a private Gist with empty JSON files
2. Print the Gist ID (save this for Koyeb)
3. Print instructions for next steps
"""

import sys
import requests
import json

def create_gist(token):
    """Create a new Gist with empty data files"""
    
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    data = {
        'description': 'NFL Helper Backend Data Persistence',
        'public': False,  # Private Gist
        'files': {
            'tinyurl_data.json': {
                'content': json.dumps({}, indent=2)
            },
            'tournament_data.json': {
                'content': json.dumps({}, indent=2)
            }
        }
    }
    
    try:
        response = requests.post('https://api.github.com/gists', headers=headers, json=data)
        response.raise_for_status()
        
        gist_data = response.json()
        gist_id = gist_data['id']
        gist_url = gist_data['html_url']
        
        print("\n" + "="*60)
        print("✅ Gist created successfully!")
        print("="*60)
        print(f"\nGist ID: {gist_id}")
        print(f"Gist URL: {gist_url}")
        print("\n" + "="*60)
        print("Next steps:")
        print("="*60)
        print("\n1. Save these values:")
        print(f"   GITHUB_TOKEN = {token[:10]}...{token[-4:]} (already have this)")
        print(f"   GIST_ID = {gist_id}")
        print("\n2. In Koyeb:")
        print("   - Go to your service settings")
        print("   - Add environment variables:")
        print(f"     GITHUB_TOKEN = {token}")
        print(f"     GIST_ID = {gist_id}")
        print("\n3. Redeploy your service")
        print("\n" + "="*60)
        
        return gist_id
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("❌ Error: Invalid GitHub token. Please check your token.")
        elif e.response.status_code == 403:
            print("❌ Error: Token doesn't have 'gist' scope. Please create a new token with 'gist' permission.")
        else:
            print(f"❌ Error: {e.response.status_code} - {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error creating Gist: {e}")
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python create_gist.py <your_github_token>")
        print("\nTo get a GitHub token:")
        print("1. Go to https://github.com/settings/tokens")
        print("2. Click 'Generate new token (classic)'")
        print("3. Select 'gist' scope")
        print("4. Generate and copy the token")
        sys.exit(1)
    
    token = sys.argv[1].strip()
    
    if not token:
        print("❌ Error: Token cannot be empty")
        sys.exit(1)
    
    create_gist(token)

