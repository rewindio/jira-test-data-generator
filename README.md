# Jira Test Data Generator

A Python tool to generate realistic test data for Jira instances based on production data multipliers. Intelligently handles rate limiting and uses bulk APIs and async concurrency for optimal performance.

## Features

- **Bulk API Support** - Uses Jira's bulk creation APIs (50 issues per call)
- **Async Concurrency** - Concurrent API requests for 2-4x faster generation
- **Intelligent Rate Limiting** - Automatically backs off when hitting rate limits
- **Production-Based Multipliers** - Creates realistic data distributions from CSV config
- **Dynamic Project Creation** - Automatically creates projects based on multipliers
- **Easy Cleanup** - All items tagged with searchable labels for easy JQL queries
- **Size-Based Generation** - Supports Small/Medium/Large/XLarge instance profiles
- **Dry Run Mode** - Preview what will be created without making changes

## What Gets Created

Based on the size bucket you choose, the tool creates:

- **Projects** (automatically created based on multipliers)
- **Issues** (base count you specify)
- **Comments** (4.8x for small instances, varies by size)
- **Worklogs** (7.27x for small, decreases for larger)
- **Issue Links** (~0.3x)
- **Watchers** (2.51x for small, 3.95x for medium)
- **Project Versions** (1.76x for small)
- **Project Components** (0.49x for small)
- And more...

Multipliers are loaded from `item_type_multipliers.csv` for easy customization.

## Installation

```bash
# Clone or download the script
cd /path/to/script

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

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
  --url https://mycompany.atlassian.net \
  --email your.email@company.com \
  --prefix PERF \
  --count 100 \
  --size small
```

### Dry Run (Recommended First!)

```bash
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email your.email@company.com \
  --prefix LOAD \
  --count 500 \
  --size medium \
  --dry-run
```

### Faster Generation with Higher Concurrency

```bash
# Use more concurrent requests for faster generation
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email your.email@company.com \
  --prefix LOAD \
  --count 1000 \
  --size medium \
  --concurrency 10
```

### Sequential Mode (No Async)

```bash
# Disable async if you encounter issues
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email your.email@company.com \
  --prefix TEST \
  --count 100 \
  --size small \
  --no-async
```

## Command Line Options

| Option | Required | Description | Default |
|--------|----------|-------------|---------|
| `--url` | Yes | Jira instance URL | - |
| `--email` | Yes | Your Jira email | - |
| `--token` | No* | API token | From env |
| `--prefix` | Yes | Prefix for items and project keys | - |
| `--count` | Yes | Number of issues to create | - |
| `--size` | No | Instance size bucket | `small` |
| `--concurrency` | No | Number of concurrent API requests | `5` |
| `--no-async` | No | Disable async mode (sequential) | `false` |
| `--dry-run` | No | Preview only, no API calls | `false` |
| `--verbose` | No | Enable debug logging | `false` |

\* Token can also be set via `JIRA_API_TOKEN` environment variable or `.env` file

## Concurrency & Performance

The tool uses async I/O to make concurrent API requests, significantly speeding up generation of high-volume items like comments, worklogs, and watchers.

### How It Works

- **Projects, Issues, Components, Versions**: Created sequentially (low volume or already bulk-optimized)
- **Comments, Worklogs, Issue Links, Watchers**: Created concurrently using asyncio
- **Rate Limiting**: Shared across all concurrent requests with thread-safe tracking

### Concurrency Guidelines

| Concurrency | Use Case | Notes |
|-------------|----------|-------|
| `1-3` | Conservative, shared instances | Minimal rate limit risk |
| `5` (default) | Balanced performance | Good for most cases |
| `10-15` | Faster generation | May hit rate limits more often |
| `20+` | Maximum speed | Only for dedicated test instances |

### Performance Comparison

| Issues | Sequential (~) | Async (concurrency=5) | Async (concurrency=10) |
|--------|---------------|----------------------|------------------------|
| 100 | 5-7 min | 2-3 min | 1-2 min |
| 500 | 20-30 min | 8-12 min | 5-8 min |
| 1,000 | 45-60 min | 15-25 min | 10-15 min |

*Times vary based on rate limits and network latency*

## Size Buckets

Choose the size that matches your testing needs:

| Size | Issue Range | Characteristics | Use Case |
|------|-------------|-----------------|----------|
| **Small** | 1-1K | High activity per issue | Quick tests, dev environments |
| **Medium** | 1K-10K | Balanced | Staging, moderate load tests |
| **Large** | 10K-100K | Moderate activity | Production-like scenarios |
| **XLarge** | 100K+ | Low activity per issue | Enterprise testing |

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
# 1. Find all issues using JQL: labels = YOUR-PREFIX-TIMESTAMP
# 2. Bulk delete in Jira UI: Tools -> Bulk Change -> Select all -> Delete
```

## Rate Limiting

The tool handles rate limiting intelligently:

1. **Respects `Retry-After` headers** from Jira
2. **Exponential backoff** when rate limited (1s → 60s max)
3. **Shared rate limit tracking** across concurrent requests
4. **Automatic retries** (5 attempts per request)
5. **Semaphore-based concurrency control**

You'll see messages like:
```
Rate limit hit (1 consecutive). Waiting 30.0s
```

The tool will automatically slow down and continue when allowed.

## Troubleshooting

### "Rate limit hit" messages

**Normal!** The tool is working as designed. It will automatically wait and continue. If you see many consecutive rate limits, try reducing `--concurrency`.

### Authentication errors

```bash
# Check your credentials
curl -u "your.email@company.com:YOUR_TOKEN" \
  https://your-domain.atlassian.net/rest/api/3/myself
```

### Project creation fails

Make sure:
1. Your API token has project creation permissions
2. The prefix creates valid project keys (uppercase, max 10 chars)
3. No existing projects conflict with generated keys

### "Could not get account ID"

Check that:
1. Your API token is valid
2. You have "Browse Users" permission
3. Your account is active

### Async errors

If you encounter async-related issues, try:
```bash
python jira_data_generator.py ... --no-async
```

## Examples

### Example 1: Quick Test

```bash
# Generate 25 issues with minimal data
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix TEST \
  --count 25 \
  --size small \
  --dry-run
```

### Example 2: Staging Environment

```bash
# Realistic medium instance data with faster generation
export JIRA_API_TOKEN="your_token"

python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix STAGE \
  --count 500 \
  --size medium \
  --concurrency 10 \
  --verbose
```

### Example 3: Large Performance Test

```bash
# Large dataset for load testing
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix LOAD2K \
  --count 2000 \
  --size large \
  --concurrency 15
```

## Output Example

```
============================================================
Starting Jira data generation (async mode)
Size bucket: small
Target issues: 100
Prefix: PERF
Concurrency: 5
Run ID (for JQL): labels = PERF-20241204-143022
Dry run: False
============================================================

Planned creation counts:
  Issues: 100
  project: 1
  comment: 480
  issue_link: 30
  issue_watcher: 251
  issue_worklog: 727
  project_component: 49
  project_version: 176

Creating 1 projects...
Created project 1/1: PERF1

Creating 100 issues in project PERF1...
Creating 100 issues in batches of 50...
Created issue: PERF1-1
Created issue: PERF1-2
...

Creating 480 comments (concurrency: 5)...
Created 50/480 comments
Created 100/480 comments
...

============================================================
Data generation complete!
============================================================

To find all generated data in JQL:
  labels = PERF-20241204-143022
  OR
  labels = PERF

Created 1 projects
Created 100 issues
```

## Customizing Multipliers

Multipliers are loaded from `item_type_multipliers.csv`. Edit this file to customize:

```csv
Item Type,Small,Medium,Large,XLarge
comment,4.80,4.75,2.69,0.26
issue_worklog,7.27,1.49,0.24,0.06
project,0.00249,0.00066,0.00032,0.00001
...
```

## Architecture Notes

### Async Implementation

- Uses `aiohttp` for async HTTP requests
- Semaphore controls max concurrent requests
- Rate limit state shared via asyncio.Lock
- Graceful session cleanup on completion

### What Runs Async vs Sequential

| Operation | Mode | Reason |
|-----------|------|--------|
| Projects | Sequential | Low volume, dependencies |
| Issues (bulk) | Sequential | Already optimized (50/call) |
| Components | Sequential | Low volume |
| Versions | Sequential | Low volume |
| Comments | **Async** | High volume |
| Worklogs | **Async** | High volume |
| Issue Links | **Async** | Medium-high volume |
| Watchers | **Async** | Medium-high volume |

### Error Handling

- Retries on 5xx errors (via urllib3 for sync, manual for async)
- Intelligent 429 handling with shared state
- Graceful degradation on failures
- Detailed logging with `--verbose`

## Contributing

Feel free to extend this! Some ideas:

- [ ] Add attachment generation
- [ ] Support for custom fields
- [ ] Sprint creation
- [ ] Board configuration
- [ ] Resume from failure
- [ ] Progress bar (tqdm)

## License

Internal Rewind tool - use for testing purposes only!

## Support

Questions? Contact the Cloud Ops team or check the Confluence page:
https://rewind.atlassian.net/wiki/spaces/DEV/pages/4143612121
