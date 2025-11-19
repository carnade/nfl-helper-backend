#!/bin/bash

# Script to test the new admin endpoint for updating fantasy points for a specific week

echo "Testing fantasy points update for specific week..."

# Test updating week 6 (example)
echo "Updating fantasy points for week 6..."
curl -X POST http://localhost:5000/admin/fantasy-points/update-week/6

echo ""
echo "Done! Check the application logs for results."

# Optional: Check fantasy points data
echo ""
echo "Checking fantasy points data..."
curl -s http://localhost:5000/fantasy-points/data | jq 'keys | length' 2>/dev/null || echo "Could not parse JSON response"
