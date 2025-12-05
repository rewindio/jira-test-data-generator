#!/bin/bash
# Example usage scenarios for the Jira Data Generator

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check for required env var or .env file
if [ -z "$JIRA_API_TOKEN" ]; then
    if [ -f ".env" ]; then
        echo "Loading environment from .env file..."
        source .env
    else
        echo "Error: JIRA_API_TOKEN not set and .env file not found"
        echo ""
        echo "Option 1: Create .env file (recommended)"
        echo "  cp .env.example .env"
        echo "  # Edit .env and add your token"
        echo ""
        echo "Option 2: Export environment variable"
        echo "  export JIRA_API_TOKEN=your_token_here"
        exit 1
    fi
fi

# Configuration - CHANGE THESE
JIRA_URL="https://mycompany.atlassian.net"
JIRA_EMAIL="your.email@company.com"

echo -e "${GREEN}Jira Data Generator - Example Scenarios${NC}\n"

# Scenario 1: Dry run to see what would be created
echo -e "${YELLOW}Scenario 1: Dry Run (50 issues, small instance)${NC}"
echo "This will show you what would be created without actually creating anything"
echo ""
read -p "Press enter to continue..."

python jira_data_generator.py \
  --url "$JIRA_URL" \
  --email "$JIRA_EMAIL" \
  --prefix DRYRUN \
  --count 50 \
  --size small \
  --dry-run

echo -e "\n${GREEN}✓ Scenario 1 complete${NC}\n"
sleep 2

# Scenario 2: Small quick test
echo -e "${YELLOW}Scenario 2: Quick Test (25 issues, small instance)${NC}"
echo "This creates a small dataset for quick testing"
echo "Estimated time: ~1 minute with async"
echo ""
read -p "Press enter to continue (or Ctrl+C to skip)..."

python jira_data_generator.py \
  --url "$JIRA_URL" \
  --email "$JIRA_EMAIL" \
  --prefix QUICK \
  --count 25 \
  --size small \
  --verbose

echo -e "\n${GREEN}✓ Scenario 2 complete${NC}"
echo "Search in Jira with: labels = QUICK"
echo ""
sleep 2

# Scenario 3: Medium load test with higher concurrency
echo -e "${YELLOW}Scenario 3: Medium Load Test (100 issues, medium instance, concurrency=10)${NC}"
echo "This simulates a medium-sized Jira instance with faster generation"
echo "Estimated time: 2-3 minutes with concurrency=10"
echo ""
read -p "Press enter to continue (or Ctrl+C to skip)..."

python jira_data_generator.py \
  --url "$JIRA_URL" \
  --email "$JIRA_EMAIL" \
  --prefix MEDIUM \
  --count 100 \
  --size medium \
  --concurrency 10

echo -e "\n${GREEN}✓ Scenario 3 complete${NC}"
echo "Search in Jira with: labels = MEDIUM"
echo ""
sleep 2

# Scenario 4: Performance test with high concurrency
echo -e "${YELLOW}Scenario 4: Large Performance Test (500 issues, large instance, concurrency=15)${NC}"
echo "This creates a substantial dataset for performance testing"
echo "Estimated time: 5-10 minutes with concurrency=15"
echo ""
read -p "Press enter to continue (or Ctrl+C to skip)..."

python jira_data_generator.py \
  --url "$JIRA_URL" \
  --email "$JIRA_EMAIL" \
  --prefix PERF \
  --count 500 \
  --size large \
  --concurrency 15 \
  --verbose

echo -e "\n${GREEN}✓ Scenario 4 complete${NC}"
echo "Search in Jira with: labels = PERF"
echo ""
sleep 2

# Scenario 5: Sequential mode (no async)
echo -e "${YELLOW}Scenario 5: Sequential Mode (50 issues, debugging/fallback)${NC}"
echo "Use this if you encounter async-related issues"
echo "Estimated time: 3-5 minutes (slower than async)"
echo ""
read -p "Press enter to continue (or Ctrl+C to skip)..."

python jira_data_generator.py \
  --url "$JIRA_URL" \
  --email "$JIRA_EMAIL" \
  --prefix SEQ \
  --count 50 \
  --size small \
  --no-async \
  --verbose

echo -e "\n${GREEN}✓ Scenario 5 complete${NC}"
echo "Search in Jira with: labels = SEQ"
echo ""

echo -e "${GREEN}All scenarios complete!${NC}\n"
echo "To clean up, use Jira's bulk delete feature:"
echo "1. Search with: labels = QUICK OR labels = MEDIUM OR labels = PERF OR labels = SEQ"
echo "2. Tools -> Bulk Change -> Select all -> Delete"
