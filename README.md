# Jira Test Data Generator

A Python tool to generate realistic test data for Jira instances based on production data multipliers. Intelligently handles rate limiting and uses bulk APIs and async concurrency for optimal performance.

## Features

- **Bulk API Support** - Uses Jira's bulk creation APIs (50 issues per call)
- **Async Concurrency** - Concurrent API requests for 2-4x faster generation
- **Parallel Issue Creation** - Issues created concurrently across multiple projects
- **Intelligent Rate Limiting** - Automatically backs off when hitting rate limits
- **Production-Based Multipliers** - Creates realistic data distributions from CSV config
- **Dynamic Project Creation** - Automatically creates projects based on multipliers
- **Auto Admin Role** - Automatically grants Project Administrator role for watcher permissions
- **Easy Cleanup** - All items tagged with searchable labels for easy JQL queries
- **Size-Based Generation** - Supports Small/Medium/Large/XLarge instance profiles
- **Dry Run Mode** - Preview what will be created without making changes
- **Checkpointing** - Resume interrupted runs for large-scale data generation (18M+ issues)
- **Benchmarking** - Track timing per phase with extrapolation for large datasets
- **Custom Fields** - Create custom fields with various types (text, select, date, etc.)
- **User Generator** - Helper script to invite sandbox users and create groups
- **Performance Optimized** - Connection pooling, text pooling, memory-efficient batching

## What Gets Created

Based on the size bucket you choose, the tool creates:

**Configuration Items:**
- **Custom Fields** (~0.01x - various field types: text, number, date, select, etc.)

**Project Items:**
- **Projects** (automatically created based on multipliers)
- **Project Categories** (~0.0003x - organize projects into categories)
- **Project Versions** (1.76x for small)
- **Project Components** (0.49x for small)
- **Project Properties** (~0.48x - custom key-value metadata on projects)

**Issue Items:**
- **Issues** (base count you specify)
- **Comments** (4.8x for small instances, varies by size)
- **Worklogs** (7.27x for small, decreases for larger)
- **Issue Links** (~0.3x)
- **Watchers** (2.51x for small, 3.95x for medium)
- **Attachments** (2.1x for small, pooled 1-5KB files for fast uploads)
- **Votes** (~0.003x - votes from authenticated user)
- **Issue Properties** (~0.89x - custom key-value metadata)
- **Remote Links** (~0.56x - links to external resources)

**Agile Items:**
- **Boards** (~0.003x - Scrum and Kanban boards)
- **Sprints** (~0.07x - created on scrum boards only, with past, current, and future dates)

**Other Items:**
- **Filters** (~0.02x - saved JQL searches)
- **Dashboards** (~0.002x - private or authenticated user sharing)

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

### Resume from Checkpoint

```bash
# Resume an interrupted run
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email your.email@company.com \
  --prefix BIGRUN \
  --count 1000000 \
  --size large \
  --resume
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
| `--request-delay` | No | Delay between requests in seconds (0.05-0.1 recommended) | `0` |
| `--no-async` | No | Disable async mode (sequential) | `false` |
| `--dry-run` | No | Preview only, no API calls | `false` |
| `--verbose` | No | Enable debug logging | `false` |
| `--resume` | No | Resume from existing checkpoint | `false` |
| `--no-checkpoint` | No | Disable checkpointing entirely | `false` |

\* Token can also be set via `JIRA_API_TOKEN` environment variable or `.env` file

## Concurrency & Performance

The tool uses async I/O to make concurrent API requests, optimized for 18M+ issue scale.

### How It Works

- **Projects, Categories**: Created sequentially (low volume even at scale)
- **Issues**: Created via bulk API (50 per call), **parallelized across projects** for significant speedup
- **Versions, Components, Project Properties**: Created concurrently (high volume at scale: 25.9M versions, 3.8M components at 18M issues)
- **Comments, Worklogs, Issue Links, Watchers, Attachments, Votes, Issue Properties, Remote Links**: Created concurrently using asyncio
- **Attachments**: Use pre-generated pool of small files (1-5KB) with session reuse for fast uploads
- **Boards**: Created sequentially (requires filter creation first)
- **Sprints**: Created concurrently on scrum boards only (kanban boards don't support sprints)
- **Filters, Dashboards**: Created concurrently
- **Rate Limiting**: Shared across all concurrent requests with thread-safe tracking

### Performance Optimizations

The tool includes several optimizations for large-scale runs (18M+ issues):

- **Connection Pooling**: Reuses HTTP connections to reduce TCP handshake overhead
- **Pre-Generated Text Pool**: 3,000 random text strings pre-generated at startup (~38x faster)
- **Memory-Efficient Batching**: Tasks created per-batch, not upfront (reduces memory from GBs to MBs)
- **Attachment Session Reuse**: Single session for all attachment uploads (eliminates session overhead)
- **Attachment File Pooling**: 20 pre-generated small files reused across uploads

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
6. **Adaptive throttling** - automatically slows down when hitting rate limits
7. **Jitter on backoff** - prevents thundering herd after cooldown

### Request Delay (Smoothing)

Use `--request-delay` to add a small delay between requests, which smooths out the request rate and reduces rate limit hits:

```bash
# Add 50ms delay between requests (recommended for heavy rate limiting)
python jira_data_generator.py ... --request-delay 0.05

# Add 100ms delay for very aggressive rate limiting
python jira_data_generator.py ... --request-delay 0.1
```

The effective delay is: `request_delay + adaptive_delay + jitter`

- **request_delay**: Your configured base delay (default: 0)
- **adaptive_delay**: Automatically increases when hitting 429s, decreases on success (0-1s)
- **jitter**: ±10% randomization to prevent synchronized bursts

You'll see messages like:
```
Rate limited. Waiting 30.0s (adaptive delay now 0.20s)
```

The tool will automatically slow down and continue when allowed.

## Checkpointing (Resume Support)

For large-scale data generation (designed for 18M+ issues), the tool automatically saves progress to a checkpoint file. If interrupted, you can resume from where you left off.

### How It Works

1. **Automatic Saving** - Progress saved to `{PREFIX}-checkpoint.json` after each phase
2. **Resume** - Use `--resume` flag to continue from last checkpoint
3. **Archive** - On completion, checkpoint renamed to `{run_id}-checkpoint.json`

### Checkpoint File

The checkpoint tracks:
- Run configuration (URL, prefix, size, target counts)
- Created projects and their IDs
- Issue keys created per project
- Phase completion status (pending/in_progress/complete)
- Item counts for each phase

### Usage

```bash
# Start a large run (checkpoint auto-created)
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix BIGRUN \
  --count 1000000 \
  --size large

# If interrupted (Ctrl+C, error, etc.), resume with:
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix BIGRUN \
  --count 1000000 \
  --size large \
  --resume

# Disable checkpointing for small runs
python jira_data_generator.py ... --no-checkpoint
```

### Resume Behavior

When resuming:
- Completed phases are skipped entirely
- Partial phases continue from last saved count
- Original run_id is restored (same JQL labels)
- Issue keys are fetched from Jira if needed

### Checkpoint Warnings

If a checkpoint exists when starting a new run:
- You'll be prompted to confirm overwriting
- Use `--resume` to continue instead
- Delete the checkpoint file to start fresh

## Benchmarking & Time Extrapolation

The tool tracks timing for each phase and provides benchmark summaries with time extrapolations for larger datasets.

### How It Works

1. **Phase Timing** - Each generation phase is timed and logged with items/second rate
2. **Summary Report** - At completion, a detailed benchmark summary is displayed
3. **Extrapolation** - Times are extrapolated to show how long 18M issues would take

### Sample Output

```
============================================================
BENCHMARK SUMMARY
============================================================
Total duration: 3.2 minutes
Total items created: 1,247

Phase breakdown:
------------------------------------------------------------------------------------------
Phase                          Items   Duration         Rate         429s     Errs
------------------------------------------------------------------------------------------
Project Categories                 1       0.2s        4.9/s            -        -
Projects                           1       0.3s        3.3/s            -        -
Project Properties                24       0.4s       59.1/s            -        -
Issues                            50      23.1s        2.2/s    2 (4.0%)        -
Comments                         240      24.5s        9.8/s    8 (3.3%)        -
Worklogs                         364      38.2s        9.5/s   12 (3.3%)        -
Issue Links                       15       1.5s       10.0/s            -        -
Watchers                         126      12.8s        9.8/s    3 (2.4%)        -
Attachments                      105      35.2s        3.0/s    5 (4.8%)        -
Votes                              1       0.1s       10.0/s            -        -
Issue Properties                  45       4.6s        9.8/s            -        -
Remote Links                      29       2.9s       10.0/s            -        -
Boards                             1       0.3s        3.3/s            -        -
Sprints                            4       0.8s        5.0/s            -        -
Filters                            2       0.2s       10.0/s            -        -
Dashboards                         1       0.1s       10.0/s            -        -
------------------------------------------------------------------------------------------

Key rates for extrapolation:
  Issues: 2.17/sec (0.46s per issue)
  Comments: 9.80/sec

Request statistics:
  Total requests: 1,247
  Rate limited (429): 30 (2.4%)
  Errors: 0 (0.0%)

============================================================
TIME EXTRAPOLATION FOR 18,000,000 ISSUES
============================================================
Based on current run: 50 issues
Scale factor: 360000.0x

Estimated time per phase:
  Project Categories: 360,000 items @ 4.9/s = 20.4h
  Projects: 360,000 items @ 3.3/s = 30.3h
  Issues: 18,000,000 items @ 2.2/s = 96.1d
  Comments: 86,400,000 items @ 9.8/s = 102.1d
  ...

------------------------------------------------------------
TOTAL ESTIMATED TIME: 428 days, 12 hours
------------------------------------------------------------

Note: Actual time may vary based on:
  - Rate limiting (may add 20-50% overhead)
  - Network latency
  - Jira instance performance
  - Concurrency settings
```

### Using Benchmarks

Run a small test (50-100 issues) to get baseline rates, then extrapolate:

```bash
# Run small benchmark test
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix BENCH \
  --count 100 \
  --size small

# The output will show:
# - Per-phase timing and rates
# - Extrapolation for 18M issues
```

### Key Metrics

| Metric | Description |
|--------|-------------|
| **Items/second** | Average creation rate for each phase |
| **Seconds/item** | Time per item (useful for planning) |
| **Scale factor** | Multiplier from test run to target |
| **Total estimated** | Projected total time for 18M issues |
| **Total requests** | Number of API requests made |
| **Rate limited (429)** | Requests that hit rate limits (count and percentage) |
| **Errors** | Failed requests (count and percentage) |

### Request Statistics

The benchmark summary includes API request statistics to help you understand:
- **Total requests**: How many API calls were made during the run
- **Rate limited**: How often Jira's rate limits were hit (429 responses)
- **Errors**: How many requests failed (non-rate-limit errors)

These stats help you:
- Tune `--concurrency` settings (high rate limit % = reduce concurrency)
- Identify connectivity issues (high error % = network problems)
- Plan capacity for large runs

Note: In `--dry-run` mode, no actual requests are made, so statistics show "(No requests recorded - dry-run mode)".

### Accuracy Notes

- Extrapolations are linear estimates from small runs
- Actual times typically 20-50% higher due to rate limiting
- Higher concurrency improves rates but hits limits faster
- Test with 100-500 issues for more accurate baselines

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

  Configuration items:
    issue_field: 1

  Project items:
    project: 1
    project_category: 1
    project_component: 49
    project_version: 176
    project_property: 48

  Issue items:
    comment: 480
    issue_worklog: 727
    issue_link: 30
    issue_watcher: 251
    issue_attachment: 210
    issue_vote: 1
    issue_properties: 89
    issue_remote_link: 56

  Agile items:
    board: 1
    sprint: 7

  Other items:
    filter: 3
    dashboard: 1

Creating 1 custom fields...
Created custom field 1/1: PERF Text Field (single line) 1 (textfield)

Creating 1 project categories...
Created category 1/1: PERF Development 1

Creating 1 projects...
Created project 1/1: PERF1

Assigning 1 projects to 1 categories...

Creating 48 project properties...

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

- Uses `aiohttp` for async HTTP requests with optimized connection pooling
- Semaphore controls max concurrent requests
- Rate limit state shared via asyncio.Lock
- Graceful session cleanup on completion
- Memory-efficient task batching (tasks created per-batch, not upfront)
- Pre-generated text pool for fast random text generation

### What Runs Async vs Sequential

| Operation | Mode | Reason |
|-----------|------|--------|
| Custom Fields | **Async** | Configuration items, created first |
| Projects | Sequential | Low volume, dependencies |
| Project Categories | Sequential | Low volume, created before projects |
| Project Properties | **Async** | High volume at scale (1.6M at 18M issues) |
| Issues (bulk) | **Parallel** | Async across projects (50/call per project) |
| Components | **Async** | High volume at scale (3.8M at 18M issues) |
| Versions | **Async** | Very high volume at scale (25.9M at 18M issues) |
| Boards | Sequential | Low volume, filter dependency |
| Sprints | **Async** | Scrum boards only (kanban doesn't support sprints) |
| Filters | **Async** | Medium-high volume at scale |
| Dashboards | **Async** | Private or authenticated sharing (global disabled) |
| Comments | **Async** | High volume |
| Worklogs | **Async** | High volume |
| Issue Links | **Async** | Medium-high volume |
| Watchers | **Async** | Medium-high volume |
| Attachments | **Async** | Pooled small files (1-5KB) for fast uploads |
| Votes | **Async** | Medium volume |
| Issue Properties | **Async** | High volume |
| Remote Links | **Async** | Medium volume |

### Error Handling

- Retries on 5xx errors (via urllib3 for sync, manual for async)
- Intelligent 429 handling with shared state
- Graceful degradation on failures
- Detailed logging with `--verbose`

## User Generator

A helper script to create sandbox test users and groups in your Jira instance.

### Why Use This?

- Create multiple test users with a single command
- Users are created with plus-addressing format (`user+sandbox1@domain.com`)
- All emails route to your inbox for easy management
- Automatically grants Jira product access

### Basic Usage

```bash
# Invite 5 sandbox users with Jira Software access
python jira_user_generator.py \
  --url https://mycompany.atlassian.net \
  --email admin@company.com \
  --base-email dave.north@rewind.io \
  --users 5
```

### With Groups

```bash
# Create users and groups
python jira_user_generator.py \
  --url https://mycompany.atlassian.net \
  --email admin@company.com \
  --base-email dave.north@rewind.io \
  --users 10 \
  --groups "Test Team 1" "Test Team 2"
```

### User Generator Options

| Option | Required | Description | Default |
|--------|----------|-------------|---------|
| `--url` | Yes | Jira instance URL | - |
| `--email` | Yes | Your Jira admin email | - |
| `--token` | No* | API token | From env |
| `--base-email` | Yes | Base email for sandbox users | - |
| `--users` | Yes | Number of users to create | - |
| `--groups` | No | Group names to create | None |
| `--products` | No | Jira products to grant access | `jira-software` |
| `--user-prefix` | No | Display name prefix | `Sandbox` |
| `--dry-run` | No | Preview only | `false` |

### Available Products

- `jira-software` (default)
- `jira-core`
- `jira-servicedesk`
- `jira-product-discovery`

### Generated Email Format

```
dave.north+sandbox1@rewind.io
dave.north+sandbox2@rewind.io
dave.north+sandbox3@rewind.io
...
```

### Output Example

```
============================================================
Starting Jira user/group generation
Base email: dave.north@rewind.io
User count: 5
Products: jira-software
Groups: Test Team 1, Test Team 2
============================================================

Groups created: 2
  - Test Team 1
  - Test Team 2

Users invited: 5
  - dave.north+sandbox1@rewind.io (accountId: abc123)
  - dave.north+sandbox2@rewind.io (accountId: def456)
  ...

Summary:
  Users:  0 existing, 5 invited, 0 failed
  Groups: 0 existing, 2 created
```

### Permissions Required

Your API token needs:
- **Site admin** or **User access admin** permissions to invite users
- **Browse users and groups** permission to check existing users

---

## Project Structure

The codebase is organized into modular generators for maintainability:

```
jira-test-data-generator/
├── jira_data_generator.py     # Main orchestrator
├── jira_user_generator.py     # User/group creation helper
├── generators/                 # Modular generators
│   ├── __init__.py
│   ├── base.py                # API client, rate limiting
│   ├── projects.py            # Projects, categories, versions, components, properties
│   ├── issues.py              # Issues, attachments
│   ├── issue_items.py         # Comments, worklogs, links, watchers, votes, properties, remote links
│   ├── agile.py               # Boards, sprints
│   ├── filters.py             # Filters, dashboards
│   ├── custom_fields.py       # Custom fields, contexts, options
│   ├── checkpoint.py          # Checkpoint management for resume support
│   └── benchmark.py           # Performance tracking and time extrapolation
├── item_type_multipliers.csv  # Multiplier configuration
├── requirements.txt           # Python dependencies
└── CLAUDE.md                  # AI agent documentation
```

## Contributing

Feel free to extend this! Some ideas:

- [x] Add attachment generation
- [x] Sprint creation
- [x] Board configuration
- [x] Issue votes
- [x] Issue properties
- [x] Remote links
- [x] Filters and dashboards
- [x] Project categories
- [x] Project properties
- [x] Checkpointing / Resume from failure
- [x] Custom fields (20 types: text, number, date, select, multiselect, etc.)
- [x] Parallel issue creation across projects
- [x] Optimized attachments (pooled small files)
- [x] Connection pooling optimization
- [x] Pre-generated text pool
- [x] Memory-efficient task batching
- [ ] Progress bar (tqdm)
- [ ] Jira Service Management (requests, queues, organizations)
- [ ] Jira Assets (objects, schemas)

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

Questions? Contact the Cloud Ops team or check the Confluence page:
https://rewind.atlassian.net/wiki/spaces/DEV/pages/4143612121
