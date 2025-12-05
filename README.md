# Jira Test Data Generator

A Python tool to generate realistic test data for Jira instances based on production data multipliers. Intelligently handles rate limiting and uses bulk APIs for optimal performance.

## Features

- 🚀 **Bulk API Support** - Uses Jira's bulk creation APIs (50 issues per call)
- ⚡ **Intelligent Rate Limiting** - Automatically backs off when hitting rate limits
- 📊 **Production-Based Multipliers** - Creates realistic data distributions based on actual Jira instances
- 🏷️ **Easy Cleanup** - All items tagged with searchable labels for easy JQL queries
- 🔍 **Size-Based Generation** - Supports Small/Medium/Large/XLarge instance profiles
- 🧪 **Dry Run Mode** - Preview what will be created without making changes

## What Gets Created

Based on the size bucket you choose, the tool creates:

- **Issues** (base count you specify)
- **Comments** (4.8x for small instances, varies by size)
- **Worklogs** (7.27x for small, decreases for larger)
- **Issue Links** (~0.3x)
- **Watchers** (2.51x for small, 3.95x for medium)
- **Project Versions** (1.76x for small)
- **Project Components** (0.49x for small)
- **Issue Properties** (~0.89x)
- And more...

## Installation

```bash
# Clone or download the script
cd /path/to/script

# Install dependencies
pip install -r requirements.txt

# Make executable (optional)
chmod +x jira_data_generator.py
```

## Setup

### 1. Generate a Jira API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Give it a name (e.g., "Data Generator")
4. Copy the token (you won't see it again!)

### 2. Configure Your API Token

**Option 1: Use a .env file (Recommended)**

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your token
# JIRA_API_TOKEN=your_actual_token_here
```

The `.env` file is already in `.gitignore` so it won't be committed to git.

**Option 2: Set as environment variable**

```bash
export JIRA_API_TOKEN='your_api_token_here'
```

**Option 3: Pass directly in command**

```bash
python jira_data_generator.py --token 'your_api_token_here' ...
```

> **Note**: The tool checks in this order: `--token` flag → `.env` file → environment variable

## Usage

### Basic Usage

```bash
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email your.email@rewind.com \
  --project TEST \
  --prefix PERF \
  --count 100 \
  --size small
```

### Dry Run (Recommended First!)

```bash
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email your.email@rewind.com \
  --project TEST \
  --prefix LOAD \
  --count 500 \
  --size medium \
  --dry-run
```

### Load Testing Scenario

```bash
# Generate 1000 issues with medium instance characteristics
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email your.email@rewind.com \
  --project STAGING \
  --prefix LOAD1K \
  --count 1000 \
  --size medium \
  --verbose
```

### Performance Testing

```bash
# Small batch for quick tests
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email your.email@rewind.com \
  --project SANDBOX \
  --prefix QUICK \
  --count 50 \
  --size small
```

## Command Line Options

| Option | Required | Description | Example |
|--------|----------|-------------|---------|
| `--url` | Yes | Jira instance URL | `https://company.atlassian.net` |
| `--email` | Yes | Your Jira email | `user@company.com` |
| `--token` | No* | API token | `abc123...` |
| `--project` | Yes | Project key | `TEST` |
| `--prefix` | Yes | Prefix for items | `PERF` |
| `--count` | Yes | Number of issues | `100` |
| `--size` | No | Instance size | `small`, `medium`, `large`, `xlarge` |
| `--dry-run` | No | Preview only | Flag |
| `--verbose` | No | Detailed logs | Flag |

\* Token can also be set via `JIRA_API_TOKEN` environment variable

## Size Buckets

Choose the size that matches your testing needs:

| Size | Issue Range | Total Objects | Use Case |
|------|-------------|---------------|----------|
| **Small** | < 150K | ~600K | Quick tests, dev environments |
| **Medium** | 150K - 600K | ~6.5M | Staging, moderate load tests |
| **Large** | 600K - 2M | ~14.5M | Production-like scenarios |
| **XLarge** | > 2M | ~13.5M | Enterprise testing |

The multipliers adjust automatically based on size to create realistic distributions.

## Finding Your Generated Data

All created items are tagged with labels for easy searching.

### JQL Queries

```jql
# Find everything from a specific run
labels = PERF-20241204-143022

# Find everything with your prefix
labels = PERF

# Combine with other criteria
labels = PERF-20241204-143022 AND status = Open

# Find issues only
labels = PERF AND issuetype = Task
```

### Cleaning Up

```bash
# 1. Find all issues
# Use JQL: labels = YOUR-PREFIX-TIMESTAMP

# 2. Bulk delete in Jira UI
# Tools -> Bulk Change -> Select all -> Delete
```

## Rate Limiting

The tool handles rate limiting intelligently:

1. **Respects `Retry-After` headers** from Jira
2. **Exponential backoff** when rate limited
3. **Automatic retries** with delays
4. **Batch processing** to minimize API calls
5. **Strategic delays** between operations

You'll see messages like:
```
Rate limit hit (1 consecutive). Waiting 30.0s
```

The tool will automatically slow down and continue when allowed.

## Performance Tips

### For Fastest Generation

1. Use **bulk operations** (already enabled)
2. Run during **off-peak hours**
3. Start with **small counts** to test
4. Use `--dry-run` first to verify
5. Monitor with `--verbose`

### Estimated Times

Approximate times (can vary based on rate limits):

| Issues | Items Created | Est. Time |
|--------|---------------|-----------|
| 50 | ~500 | 2-3 min |
| 100 | ~1,000 | 5-7 min |
| 500 | ~5,000 | 20-30 min |
| 1,000 | ~10,000 | 45-60 min |

## Troubleshooting

### "Rate limit hit" messages

**Normal!** The tool is working as designed. It will automatically wait and continue.

### Authentication errors

```bash
# Check your credentials
curl -u "your.email@company.com:YOUR_TOKEN" \
  https://your-domain.atlassian.net/rest/api/3/myself
```

### Project not found

Make sure:
1. Project key is correct (usually 3-4 uppercase letters)
2. You have permission to create issues in the project
3. Project exists and is accessible

### "Could not get account ID"

Check that:
1. Your API token is valid
2. You have "Browse Users" permission
3. Your account is active

## Examples

### Example 1: Quick Test

```bash
# Generate 25 issues with minimal data
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email you@rewind.com \
  --project SANDBOX \
  --prefix TEST \
  --count 25 \
  --size small \
  --dry-run
```

### Example 2: Staging Environment

```bash
# Realistic medium instance data
export JIRA_API_TOKEN="your_token"

python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email you@rewind.com \
  --project STAGING \
  --prefix STAGE \
  --count 500 \
  --size medium \
  --verbose
```

### Example 3: Performance Test

```bash
# Large dataset for load testing
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email you@rewind.com \
  --project PERF \
  --prefix LOAD2K \
  --count 2000 \
  --size large
```

## Output Example

```
============================================================
Starting Jira data generation
Size bucket: small
Target issues: 100
Project: TEST
Prefix: PERF
Run ID (for JQL): labels = PERF-20241204-143022
Dry run: False
============================================================

Planned creation counts:
  Issues: 100
  comment: 480
  issue_attachment: 210
  issue_link: 30
  issue_watcher: 251
  issue_worklog: 727
  project_component: 49
  project_version: 176

Creating 100 issues in batches of 50...
Created issue: TEST-1001
Created issue: TEST-1002
...

Creating 480 comments...
Created 10/480 comments
Created 20/480 comments
...

============================================================
Data generation complete!
============================================================

To find all generated data in JQL:
  labels = PERF-20241204-143022
  OR
  labels = PERF

Created 100 issues
```

## Advanced Usage

### Targeting Specific Multipliers

Edit the `MULTIPLIERS` dict in the script to customize:

```python
MULTIPLIERS = {
    'custom': {
        'comment': 10.0,      # 10 comments per issue
        'issue_worklog': 2.0,  # 2 worklogs per issue
        # ... etc
    }
}
```

Then use `--size custom`

### Integrating with CI/CD

```bash
#!/bin/bash
# test-data-setup.sh

set -e

echo "Generating test data..."
python jira_data_generator.py \
  --url "$JIRA_URL" \
  --email "$JIRA_EMAIL" \
  --project TEST \
  --prefix "CI-${BUILD_ID}" \
  --count 100 \
  --size small

echo "Test data ready!"
```

## Architecture Notes

### Rate Limiting Strategy

1. **Retry-After Header**: Primary mechanism
2. **Exponential Backoff**: Starts at 1s, doubles each 429, max 60s
3. **Success Reset**: Resets to 1s on successful request
4. **Max Retries**: 5 attempts per request

### Bulk Operations

- Issues: 50 per bulk create call
- Other items: Individual creation (no bulk API available)
- Strategic delays between batches

### Error Handling

- Retries on 5xx errors (via urllib3)
- Intelligent 429 handling
- Graceful degradation
- Detailed logging

## Contributing

Feel free to extend this! Some ideas:

- [ ] Add attachment generation
- [ ] Support for custom fields
- [ ] Sprint creation
- [ ] Board configuration
- [ ] More sophisticated link patterns
- [ ] Parallel batch processing
- [ ] Resume from failure
- [ ] Progress bar (tqdm)

## License

Internal Rewind tool - use for testing purposes only!

## Support

Questions? Contact the Cloud Ops team or check the Confluence page:
https://rewind.atlassian.net/wiki/spaces/DEV/pages/4143612121
