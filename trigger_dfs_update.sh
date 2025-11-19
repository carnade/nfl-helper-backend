#!/bin/bash

# Script to trigger DFS salary update
echo "Triggering DFS salary update..."

# Trigger the DFS salary update
curl -X POST http://localhost:5000/admin/dfs-salaries/update

echo ""
echo "DFS salary update triggered. Check the application logs for results."

# Optional: Check DFS salaries data
echo ""
echo "Checking DFS salaries data..."
curl -s http://localhost:5000/dfs-salaries/data | jq 'keys | length' 2>/dev/null || echo "Could not parse JSON response"
