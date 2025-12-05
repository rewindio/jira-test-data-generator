# Quick Reference Card

## Installation
```bash
pip install -r requirements.txt

# Setup .env file with your token
cp .env.example .env
# Edit .env and add: JIRA_API_TOKEN=your_token_here
```

## Most Common Commands

### Dry Run (Always Do This First!)
```bash
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email you@rewind.com \
  --project TEST \
  --prefix TEST \
  --count 50 \
  --size small \
  --dry-run
```

### Quick Test (25 issues)
```bash
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email you@rewind.com \
  --project TEST \
  --prefix QUICK \
  --count 25 \
  --size small
```

### Medium Load Test (100 issues)
```bash
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email you@rewind.com \
  --project TEST \
  --prefix LOAD \
  --count 100 \
  --size medium
```

### Large Performance Test (500 issues)
```bash
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email you@rewind.com \
  --project TEST \
  --prefix PERF \
  --count 500 \
  --size large \
  --verbose
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

| Size | Use For | Issues | Comments | Worklogs | Links |
|------|---------|--------|----------|----------|-------|
| small | Dev/Quick | 1x | 4.8x | 7.3x | 0.3x |
| medium | Staging | 1x | 4.8x | 1.5x | 0.2x |
| large | Production | 1x | 2.7x | 0.2x | 0.2x |
| xlarge | Enterprise | 1x | 0.3x | 0.06x | 0.08x |

## Troubleshooting Quick Fixes

### Rate Limited
✓ Normal! Tool will auto-retry. Be patient.

### Auth Error
```bash
# Test credentials
curl -u "you@rewind.com:$JIRA_API_TOKEN" \
  https://rewind.atlassian.net/rest/api/3/myself
```

### Project Not Found
✓ Check project key is correct (e.g., TEST, not "Test Project")
✓ Verify you have Create Issue permission

## Time Estimates

| Issues | ~Time | Items |
|--------|-------|-------|
| 25 | 2 min | ~250 |
| 50 | 3 min | ~500 |
| 100 | 6 min | ~1K |
| 500 | 25 min | ~5K |
| 1000 | 50 min | ~10K |

## Common Options

| Flag | What It Does |
|------|--------------|
| `--dry-run` | Preview only, don't create |
| `--verbose` | Show detailed progress |
| `--size small` | Use small instance multipliers |
| `--size medium` | Use medium instance multipliers |
| `--size large` | Use large instance multipliers |
| `--size xlarge` | Use xlarge instance multipliers |

## Need Help?

See the full README.md for detailed documentation!
