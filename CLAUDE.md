# agents.md - Jira Test Data Generator

## Project Overview

**Purpose**: Generate realistic test data for Jira Cloud instances using production-based multipliers to simulate real-world usage patterns.

**Key Features**:
- Bulk API operations (50 issues per call)
- Intelligent rate limit handling with exponential backoff
- Production-based multipliers from Confluence data
- Unique run ID labeling for easy JQL searching
- Support for 4 instance size buckets (small/medium/large/xlarge)

**Target User**: DevOps/Engineering teams at Rewind (rewind.com) who need to test Jira backup/restore scenarios with realistic data.

---

## File Structure

```
.
├── jira_data_generator.py    # Main application (24KB)
├── requirements.txt           # Python dependencies
├── README.md                  # User-facing documentation
├── QUICKREF.md               # Quick reference for common commands
├── example_usage.sh          # Example usage scenarios
└── agents.md                 # This file - for AI agents
```

---

## Architecture & Design Patterns

### Core Classes

#### `RateLimitState` (dataclass)
- **Purpose**: Track rate limiting state across API calls
- **Fields**:
  - `retry_after`: Seconds to wait (from Retry-After header)
  - `consecutive_429s`: Count of consecutive rate limit hits
  - `current_delay`: Current exponential backoff delay
  - `max_delay`: Maximum delay cap (60s)

#### `JiraDataGenerator` (main class)
- **Purpose**: Orchestrates all Jira API operations
- **Key Properties**:
  - `BULK_CREATE_LIMIT = 50`: Jira's bulk API limit
  - `run_id`: Unique label format `PREFIX-YYYYMMDD-HHMMSS`
  - `created_issues[]`: Tracks created issue keys for linking
  - `session`: Requests session with retry strategy

### Rate Limiting Strategy

**Priority Order**:
1. **Primary**: Use `Retry-After` header from Jira response
2. **Fallback**: Exponential backoff starting at 1s, doubling on each 429
3. **Reset**: Return to 1s delay on successful request
4. **Max**: Cap at 60s delay

**Implementation**: `_handle_rate_limit()` method

### API Call Pattern

All API calls go through `_api_call()` which:
1. Handles dry-run mode
2. Implements retry logic (max 5 attempts)
3. Processes rate limit responses
4. Provides timeout protection (30s)
5. Returns None on failure (caller must check)

---

## Data Model

### Multipliers (MULTIPLIERS dict)

**Source**: Confluence page 4143612121 (Average Item Type Counts by Jira Instance Size)

**Structure**:
```python
MULTIPLIERS = {
    'small': {'comment': 4.80, 'issue_attachment': 2.10, ...},
    'medium': {...},
    'large': {...},
    'xlarge': {...}
}
```

**Size Buckets**:
- **small**: 1-1K issues (high activity per issue)
- **medium**: 1K-10K issues (balanced)
- **large**: 10K-100K issues (moderate activity)
- **xlarge**: 100K+ issues (low activity per issue)

### Created Item Types

**Project-level**:
- Versions (project_version)
- Components (project_component)

**Issue-level**:
- Issues (bulk created in batches of 50)
- Comments (comment)
- Worklogs (issue_worklog)
- Watchers (issue_watcher)
- Issue Links (issue_link)

**Not Currently Implemented**:
- Attachments (issue_attachment) - requires file handling
- Remote Links (issue_remote_link)
- Properties (issue_properties)
- Votes (issue_vote)
- Sprints (sprint) - requires Jira Software/Scrum boards

---

## Key Conventions

### Naming

- **Prefixes**: User-specified, appears in all created items (e.g., `PERF`, `LOAD`)
- **Run IDs**: `{PREFIX}-YYYYMMDD-HHMMSS` format
- **Issue Summaries**: `{PREFIX} Test Issue {N}`
- **Versions**: `{PREFIX} v{N}.0`
- **Components**: `{PREFIX}-Component-{N}`

### Logging

- **INFO**: Progress updates, batch completions
- **WARNING**: Rate limits, recoverable errors
- **ERROR**: Fatal errors, API failures
- **DEBUG**: Verbose mode only (--verbose flag)

### Error Handling

- **Fail Fast**: If issue creation fails, abort (everything depends on issues)
- **Continue on Error**: For comments/worklogs/watchers (log and continue)
- **Retry Logic**: 5 attempts for transient errors
- **Graceful Degradation**: Missing features (like attachments) are skipped with warnings

---

## Extending the Project

### Adding New Item Types

**Template for adding a new item type**:

```python
def create_new_items(self, issue_keys: List[str], count: int):
    """Create new item type"""
    self.logger.info(f"Creating {count} new items...")
    
    created = 0
    for i in range(count):
        # Pick random issue
        issue_key = random.choice(issue_keys)
        
        # Build payload
        item_data = {
            "field1": "value1",
            "field2": self.generate_random_text()
        }
        
        # Make API call
        response = self._api_call('POST', f'issue/{issue_key}/newitem', data=item_data)
        if response:
            created += 1
        
        # Strategic delay every 10 items
        if created % 10 == 0:
            self.logger.info(f"Created {created}/{count} new items")
            time.sleep(0.2)
```

**Then add to `generate_all()` method**:
```python
if counts.get('new_item_type', 0) > 0:
    self.create_new_items(issue_keys, counts['new_item_type'])
```

### Updating Multipliers

1. Update Confluence page (source of truth)
2. Update `MULTIPLIERS` dict in lines 27-80
3. Test with `--dry-run` to verify calculations
4. Document changes in README.md

### Adding Bulk Operations

**Pattern for bulk operations**:
```python
def create_items_bulk(self, items_data: List[Dict]) -> List[str]:
    """Create items in bulk"""
    created_ids = []
    
    # Split into chunks (API limit)
    for i in range(0, len(items_data), self.BULK_CREATE_LIMIT):
        batch = items_data[i:i + self.BULK_CREATE_LIMIT]
        
        response = self._api_call('POST', 'bulk/endpoint', data={"items": batch})
        if response:
            result = response.json()
            created_ids.extend([item['id'] for item in result.get('items', [])])
        
        # Delay between batches
        if i + self.BULK_CREATE_LIMIT < len(items_data):
            time.sleep(0.5)
    
    return created_ids
```

---

## Common Modifications

### Change Bulk API Limit

```python
# Line 95
BULK_CREATE_LIMIT = 50  # Change to Jira's limit for specific endpoint
```

### Adjust Rate Limit Behavior

```python
# Line 89 - Change max delay
max_delay: float = 60.0  # Increase for more conservative rate limiting

# Line 169 - Change backoff multiplier
self.rate_limit.current_delay * 2  # Change to * 1.5 for slower backoff
```

### Add Custom Issue Fields

```python
# In create_issues_bulk(), line 271-290
issue_data = {
    "fields": {
        "project": {"key": self.project_key},
        "summary": summary,
        "description": description,
        "issuetype": {"name": issue_type},
        "labels": [self.prefix, self.run_id],
        # Add custom fields here
        "customfield_10001": "custom value",
        "priority": {"name": "Medium"}
    }
}
```

---

## Testing Guidelines

### Dry Run Testing

```bash
# Always test with --dry-run first
python jira_data_generator.py \
  --url https://rewind.atlassian.net \
  --email test@rewind.com \
  --project TEST \
  --prefix DRYRUN \
  --count 100 \
  --size small \
  --dry-run
```

### Small Scale Testing

```bash
# Start with 10-25 issues
python jira_data_generator.py ... --count 10 --size small
```

### Verify in Jira

```jql
labels = PREFIX-20241204-143022
```

### Cleanup Test Data

```jql
# Find test data
labels = TESTPREFIX

# Bulk delete in Jira UI
# Or use Jira bulk operations
```

---

## Performance Characteristics

### Timing Estimates (with rate limits)

| Issues | Total Items | Estimated Time |
|--------|-------------|----------------|
| 25     | ~250        | 1-2 min        |
| 50     | ~500        | 2-3 min        |
| 100    | ~1,000      | 5-7 min        |
| 500    | ~5,000      | 20-30 min      |
| 1,000  | ~10,000     | 45-60 min      |

### Bottlenecks

1. **Issue Links**: Individual API calls (no bulk API)
2. **Watchers**: Individual API calls per issue
3. **Rate Limits**: Can slow down by 2-3x if hit frequently
4. **Worklogs**: Individual API calls (no bulk API)

### Optimization Opportunities

1. **Parallel Requests**: Use async/await for independent items
2. **Connection Pooling**: Already implemented via `requests.Session`
3. **Batch Processing**: Already implemented for issues (50 per call)
4. **Request Compression**: Not implemented (minor gains)

---

## Known Limitations

### Not Implemented

- **Attachments**: Requires file upload handling
- **Remote Links**: Less common, low priority
- **Properties**: Complex JSON structure
- **Votes**: Negligible multiplier values
- **Sprints**: Requires Jira Software with Scrum boards

### API Limitations

- **Bulk Issue Limit**: 50 issues per call (Jira Cloud limit)
- **No Bulk Links**: Issue links require individual API calls
- **No Bulk Watchers**: Watchers require individual API calls
- **Rate Limits**: Vary by Jira Cloud plan (typically 1000 req/min)

### Authentication

- **API Token Only**: Does not support OAuth 2.0
- **Cloud Only**: Not tested with Jira Server/Data Center
- **Single User**: All items created by one user

---

## Dependencies

### Required

- `requests>=2.31.0`: HTTP library with retry support
- `urllib3>=2.0.0`: Connection pooling and retries
- `python-dotenv>=1.0.0`: Load environment variables from .env file

### Python Version

- **Minimum**: Python 3.7+ (dataclasses, type hints)
- **Recommended**: Python 3.9+ (improved type hints)
- **Tested**: Python 3.11

---

## Environment Variables

### Supported

The tool uses `python-dotenv` to load environment variables from a `.env` file.

**Priority order**:
1. `--token` command line argument (highest priority)
2. `JIRA_API_TOKEN` in `.env` file
3. `JIRA_API_TOKEN` environment variable (lowest priority)

**Setup**:
```bash
cp .env.example .env
# Edit .env and add your token
```

**Example .env file**:
```bash
JIRA_API_TOKEN=your_actual_token_here
```

### Future Considerations

```bash
export JIRA_URL='https://rewind.atlassian.net'  # Make --url optional
export JIRA_EMAIL='user@rewind.com'  # Make --email optional
```

---

## Troubleshooting Guide for Agents

### Issue: "Rate limit hit" warnings

**Solution**: This is expected. The code handles it automatically. If persistent:
- Increase delays in strategic sleep statements
- Reduce batch sizes
- Add delays between operations

### Issue: "Failed to create issues. Aborting."

**Check**:
1. API token is valid
2. User has permission in project
3. Project key is correct
4. Jira URL is correct (https://company.atlassian.net)

### Issue: "Could not get current user"

**Check**:
- API token permissions
- Network connectivity
- Jira URL format

### Issue: Slow performance

**Expected**: Large datasets take time due to rate limits
**Unexpected**: Check network latency, Jira instance health

---

## Future Enhancements

### Priority 1 (High Value)

- [ ] Add attachment support with sample files
- [ ] Implement sprint creation for Scrum projects
- [ ] Add issue history tracking (status transitions)
- [ ] Support custom field configuration from JSON

### Priority 2 (Medium Value)

- [ ] Parallel processing with asyncio
- [ ] Progress bar with ETA
- [ ] Resume capability (save state)
- [ ] Delete/cleanup command

### Priority 3 (Nice to Have)

- [ ] Config file support (YAML/JSON)
- [ ] Multiple users (distribute created items)
- [ ] Realistic date distributions (not all "now")
- [ ] Export statistics/report

---

## Code Style & Patterns

### Type Hints

Use throughout for clarity:
```python
def method_name(self, param: str, count: int) -> List[str]:
```

### Docstrings

Use triple-quoted strings with brief description:
```python
def method_name(self, param: str):
    """Brief description of what this does"""
```

### Error Handling

Prefer explicit checks over exceptions:
```python
response = self._api_call(...)
if not response:
    self.logger.warning("Could not create item")
    return

# Continue with response.json()
```

### Logging

Use appropriate levels:
```python
self.logger.info("Progress update")      # User-visible progress
self.logger.warning("Recoverable error") # Something wrong but continuing
self.logger.error("Fatal error")         # Cannot continue
self.logger.debug("Detailed info")       # Verbose mode only
```

---

## Integration Points

### Confluence

**Source**: https://rewind.atlassian.net/wiki/spaces/DEV/pages/4143612121
**Used For**: Multiplier values (MULTIPLIERS dict)
**Update Frequency**: When production patterns change

### Jira Cloud REST API v3

**Endpoints Used**:
- POST `/rest/api/3/issue/bulk` - Bulk issue creation
- POST `/rest/api/3/issue/{issueKey}/comment` - Add comments
- POST `/rest/api/3/issue/{issueKey}/worklog` - Add worklogs
- POST `/rest/api/3/issue/{issueKey}/watchers` - Add watchers
- POST `/rest/api/3/issueLink` - Create issue links
- POST `/rest/api/3/version` - Create versions
- POST `/rest/api/3/component` - Create components
- GET `/rest/api/3/myself` - Get current user

**Documentation**: https://developer.atlassian.com/cloud/jira/platform/rest/v3/

---

## Security Considerations

### API Token Handling

- Never log API tokens
- Store in `.env` file (included in .gitignore)
- Support environment variable (JIRA_API_TOKEN)
- Clear from memory after use (future enhancement)
- `.env` file is git-ignored by default

### Data Privacy

- All data is test data (lorem ipsum)
- No real user data in generated content
- Use prefix to identify test data clearly

### Rate Limiting

- Respects Jira's rate limits
- Implements exponential backoff
- Prevents abuse scenarios

---

## Contact & Support

**Project Owner**: VP Cloud Operations & Security, Rewind
**Repository**: TBD
**Documentation**: README.md (user-facing), agents.md (AI-facing)
**Questions**: Check Rewind's internal documentation or Confluence page

---

## Version History

- **v1.0** (2024-12-04): Initial release
  - Bulk issue creation
  - Rate limit handling
  - 4 size buckets
  - Comments, worklogs, watchers, links
  - Versions and components

---

## Quick Reference for Common Agent Tasks

### "Add support for [feature]"

1. Check if endpoint exists in Jira API v3 docs
2. Add method following pattern in "Extending the Project"
3. Add to `generate_all()` method
4. Update MULTIPLIERS if needed
5. Test with --dry-run
6. Update README.md

### "Fix rate limiting issue"

1. Check `_handle_rate_limit()` method
2. Verify exponential backoff logic
3. Check if Retry-After header is being used
4. Adjust max_delay or backoff multiplier
5. Add logging if needed

### "Change output format"

1. Modify logging statements in relevant methods
2. Keep structure: "Created X/Y items"
3. Update README.md examples

### "Add new size bucket"

1. Add to MULTIPLIERS dict with appropriate values
2. Add to argparse choices (line 592)
3. Document in README.md
4. Update QUICKREF.md comparison table

---

**Last Updated**: 2024-12-04
**AI Agent Note**: This file is specifically for you. The user-facing docs are in README.md.
