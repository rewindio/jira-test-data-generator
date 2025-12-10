# Quick Reference Card

## Installation
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup .env file with your token
cp .env.example .env
# Edit .env and add: JIRA_API_TOKEN=your_token_here
```

## Most Common Commands

### Dry Run (Always Do This First!)
```bash
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix TEST \
  --count 50 \
  --size small \
  --dry-run
```

### Quick Test (25 issues)
```bash
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix QUICK \
  --count 25 \
  --size small
```

### Faster Generation with Higher Concurrency
```bash
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix LOAD \
  --count 500 \
  --size medium \
  --concurrency 10
```

### Large Performance Test
```bash
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix PERF \
  --count 1000 \
  --size large \
  --concurrency 15 \
  --verbose
```

### Sequential Mode (No Async)
```bash
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix TEST \
  --count 100 \
  --size small \
  --no-async
```

### Resume from Checkpoint
```bash
# Resume an interrupted large run
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix BIGRUN \
  --count 1000000 \
  --size large \
  --resume
```

### Disable Checkpointing (Small Runs)
```bash
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix QUICK \
  --count 50 \
  --size small \
  --no-checkpoint
```

## JQL Search Patterns

```jql
# Find everything from a run
labels = PREFIX-20241204-143022

# Find everything with a prefix
labels = PREFIX

# Find only open issues
labels = PREFIX AND status = Open

# Find issues created today
labels = PREFIX AND created >= startOfDay()
```

## Cleanup

```bash
# In Jira:
# 1. Search: labels = YOUR-PREFIX
# 2. Tools -> Bulk Change
# 3. Select All -> Delete
```

## Size Buckets Quick Reference

| Size | Use For | Issues | Comments | Worklogs | Attachments | Links | Properties |
|------|---------|--------|----------|----------|-------------|-------|------------|
| small | Dev/Quick | 1x | 4.8x | 7.3x | 2.1x | 0.3x | 0.89x |
| medium | Staging | 1x | 4.8x | 1.5x | 1.6x | 0.2x | 0.80x |
| large | Production | 1x | 2.7x | 0.2x | 1.5x | 0.2x | 0.74x |
| xlarge | Enterprise | 1x | 0.3x | 0.06x | 0.15x | 0.08x | 1.05x |

## Concurrency Quick Reference

| Concurrency | Use Case | Speed |
|-------------|----------|-------|
| `1-3` | Conservative, shared instances | Slower |
| `5` (default) | Balanced performance | Normal |
| `10-15` | Faster generation | 2-3x faster |
| `20+` | Dedicated test instances | 3-4x faster |

## Time Estimates

| Issues | Sequential | Async (c=5) | Async (c=10) |
|--------|------------|-------------|--------------|
| 25 | 2 min | 1 min | 30s |
| 100 | 6 min | 2-3 min | 1-2 min |
| 500 | 25 min | 10 min | 5-8 min |
| 1000 | 50 min | 20 min | 10-15 min |

## Common Options

| Flag | What It Does |
|------|--------------|
| `--dry-run` | Preview only, don't create |
| `--verbose` | Show detailed progress |
| `--concurrency N` | Concurrent requests (default: 5) |
| `--request-delay N` | Delay between requests in seconds (try 0.05-0.1) |
| `--no-async` | Sequential mode (debugging) |
| `--resume` | Resume from checkpoint |
| `--no-checkpoint` | Disable checkpointing |
| `--size small` | Use small instance multipliers |
| `--size medium` | Use medium instance multipliers |
| `--size large` | Use large instance multipliers |
| `--size xlarge` | Use xlarge instance multipliers |

## Troubleshooting Quick Fixes

### Rate Limited
Normal! Tool will auto-retry with adaptive throttling. If excessive:
- Add `--request-delay 0.05` to smooth request rate
- Or reduce `--concurrency`

### Auth Error
```bash
# Test credentials
curl -u "you@company.com:$JIRA_API_TOKEN" \
  https://mycompany.atlassian.net/rest/api/3/myself
```

### Project Creation Fails
- Check API token has project creation permissions
- Verify prefix is valid (uppercase, max 6 chars for key)

### Async Issues
```bash
# Fallback to sequential mode
python jira_data_generator.py ... --no-async
```

### Checkpoint Issues
```bash
# View checkpoint status
cat PREFIX-checkpoint.json | python -m json.tool

# Delete checkpoint to start fresh
rm PREFIX-checkpoint.json

# Resume interrupted run
python jira_data_generator.py ... --resume
```

---

## Checkpointing Quick Reference

| Scenario | Command |
|----------|---------|
| Start large run | Auto-creates `{PREFIX}-checkpoint.json` |
| Resume after interrupt | Add `--resume` flag |
| Disable for small runs | Add `--no-checkpoint` |
| Delete stale checkpoint | `rm PREFIX-checkpoint.json` |
| View checkpoint | `cat PREFIX-checkpoint.json \| python -m json.tool` |

**Checkpoint tracks:** Custom fields, projects, issues, comments, worklogs, links, watchers, attachments, votes, properties, remote links, boards, sprints, filters, dashboards

---

## Benchmarking Quick Reference

After a run completes, you'll see benchmark output showing:
- Per-phase timing with items/second rates
- Per-phase rate limiting (429s) with percentages
- Total duration and items created
- Request statistics (total requests, rate limited %, errors %)
- Time extrapolation for 18M issues

### Run a Benchmark Test
```bash
# Small run to get baseline rates
python jira_data_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --prefix BENCH \
  --count 100 \
  --size small
```

### Key Rates to Watch

| Phase | Good Rate | Notes |
|-------|-----------|-------|
| Issues | 2-5/s | Bulk API, 50 per call, parallel across projects |
| Comments | 8-15/s | Async, high volume, memory-efficient batching |
| Worklogs | 8-15/s | Async, high volume, memory-efficient batching |
| Attachments | 10-30/s | Pooled 1-5KB files, session reuse |

### Performance Features

- **Connection Pooling**: HTTP connections reused (50 per host)
- **Text Pool**: 3,000 pre-generated strings (~38x faster)
- **Memory Batching**: Tasks created per-batch, not upfront
- **Session Reuse**: Single session for all attachments

### Request Statistics

| Metric | What It Means |
|--------|---------------|
| Total requests | Number of API calls made |
| Rate limited (429) | Requests that hit Jira's rate limits |
| Errors | Failed requests (non-rate-limit) |

**Interpreting stats:**
- High rate limit % (>5%) → Add `--request-delay 0.05` or reduce `--concurrency`
- Per-phase 429% helps identify which operations hit limits most
- High error % (>1%) → Check network/credentials
- In `--dry-run` mode → Shows "(No requests recorded)"

### Extrapolation Accuracy

| Test Size | Accuracy | Recommendation |
|-----------|----------|----------------|
| 25-50 | Low | Quick sanity check |
| 100-200 | Medium | Good for planning |
| 500+ | High | Most accurate baseline |

---

## User Generator

### Invite Sandbox Users
```bash
python jira_user_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --base-email you@company.com \
  --users 5
```

### With Groups
```bash
python jira_user_generator.py \
  --url https://mycompany.atlassian.net \
  --email you@company.com \
  --base-email you@company.com \
  --users 10 \
  --groups "Test Team 1" "Test Team 2"
```

### User Generator Options

| Flag | What It Does |
|------|--------------|
| `--base-email` | Email for plus-addressing (you@domain → you+sandbox1@domain) |
| `--users N` | Number of sandbox users to create |
| `--groups "A" "B"` | Groups to create |
| `--products X` | Products to grant: `jira-software` (default), `jira-core`, `jira-servicedesk` |
| `--user-prefix` | Display name prefix (default: Sandbox) |
| `--dry-run` | Preview only |

### Generated Emails
```
you+sandbox1@company.com
you+sandbox2@company.com
you+sandbox3@company.com
```

---

## What Gets Created

**Configuration Items:**
- Custom Fields (20 types: text, number, date, select, multiselect, user picker, etc.)

**Project Items:**
- Projects, Categories, Versions, Components, Properties

**Issue Items:**
- Issues (parallel across projects), Comments, Worklogs, Links, Watchers
- Attachments (pooled 1-5KB files), Votes, Issue Properties, Remote Links

**Agile Items:**
- Boards (Scrum/Kanban), Sprints (scrum boards only)

**Other:**
- Filters, Dashboards

---

## Need Help?

See the full README.md for detailed documentation!
