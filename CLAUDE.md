# CLAUDE.md - Jira Test Data Generator

## Project Overview

**Purpose**: Generate realistic test data for Jira Cloud instances using production-based multipliers to simulate real-world usage patterns.

**Key Features**:
- Bulk API operations (50 issues per call)
- **Parallel issue creation across projects** for significant speedup
- Async concurrency for high-volume items (comments, worklogs, watchers, votes, properties, remote links)
- **Optimized attachments** with pre-generated pool of small files (1-5KB) and session reuse
- **Pre-generated random text pool** for reduced CPU overhead at scale
- **Optimized connection pooling** for both sync and async HTTP sessions
- **Memory-efficient task batching** to avoid creating millions of task objects upfront
- Intelligent rate limit handling with exponential backoff
- Production-based multipliers loaded from CSV file
- Dynamic project creation based on multipliers
- Auto-assigns Project Administrator role for watcher permissions
- Unique run ID labeling for easy JQL searching
- Support for 4 instance size buckets (small/medium/large/xlarge)
- Modular architecture for maintainability
- **Checkpointing for resumable large-scale runs** (18M+ issues)
- **Benchmarking with time extrapolation and request statistics** for planning large runs

**Target User**: DevOps/Engineering teams at Rewind (rewind.com) who need to test Jira backup/restore scenarios with realistic data.

---

## File Structure

```
.
├── jira_data_generator.py       # Main orchestrator (~800 lines)
├── jira_user_generator.py       # User/group creation helper (~480 lines)
├── generators/                   # Modular generators package
│   ├── __init__.py              # Package exports
│   ├── base.py                  # JiraAPIClient, RateLimitState (~300 lines)
│   ├── projects.py              # ProjectGenerator (~400 lines) - projects, categories, versions, components, properties
│   ├── issues.py                # IssueGenerator (~250 lines)
│   ├── issue_items.py           # IssueItemsGenerator (~450 lines)
│   ├── agile.py                 # AgileGenerator (~250 lines)
│   ├── filters.py               # FilterGenerator (~200 lines)
│   ├── custom_fields.py         # CustomFieldGenerator (~500 lines) - custom fields, contexts, options
│   ├── checkpoint.py            # CheckpointManager (~450 lines) - resumable runs
│   └── benchmark.py             # BenchmarkTracker (~400 lines) - timing, request stats, extrapolation
├── item_type_multipliers.csv    # Multiplier configuration
├── requirements.txt             # Python dependencies
├── .env.example                 # API token template
├── .gitignore                   # Python venv and credentials
├── README.md                    # User-facing documentation
├── QUICKREF.md                  # Quick reference for common commands
├── example_usage.sh             # Example usage scenarios
└── CLAUDE.md                    # This file - for AI agents
```

---

## Architecture & Design Patterns

### Module Overview

The codebase uses a modular architecture with specialized generators:

| Module | Class | Responsibility |
|--------|-------|----------------|
| `base.py` | `JiraAPIClient` | HTTP sessions, rate limiting, base API calls, text pool, connection pooling |
| `projects.py` | `ProjectGenerator` | Projects, categories, versions, components, properties, role management |
| `issues.py` | `IssueGenerator` | Bulk issue creation (parallel across projects), attachments (pooled) |
| `issue_items.py` | `IssueItemsGenerator` | Comments, worklogs, links, watchers, votes, properties, remote links |
| `agile.py` | `AgileGenerator` | Boards, sprints, sprint issue assignment |
| `filters.py` | `FilterGenerator` | Saved filters, dashboards |
| `custom_fields.py` | `CustomFieldGenerator` | Custom fields (20 types), contexts, options |
| `checkpoint.py` | `CheckpointManager` | Progress tracking, resume support for large runs |
| `benchmark.py` | `BenchmarkTracker` | Per-phase timing, rates calculation, request statistics, time extrapolation |

### Core Classes

#### `RateLimitState` (dataclass) - `generators/base.py`
- **Purpose**: Track rate limiting state across API calls (thread-safe for async)
- **Fields**:
  - `retry_after`: Seconds to wait (from Retry-After header)
  - `consecutive_429s`: Count of consecutive rate limit hits
  - `current_delay`: Current exponential backoff delay
  - `max_delay`: Maximum delay cap (60s)
  - `_lock`: asyncio.Lock for thread-safe updates in async context

#### `JiraAPIClient` (base class) - `generators/base.py`
- **Purpose**: Base class for all generators with shared API functionality
- **Key Methods**:
  - `_api_call()`: Synchronous API call with rate limiting and request tracking
  - `_api_call_async()`: Async API call with rate limiting and request tracking
  - `_create_session()`: Create requests session with optimized connection pooling
  - `_get_async_session()`: Get/create aiohttp session with optimized connection pooling
  - `_init_text_pool()`: Initialize pre-generated random text pool (class method)
  - `generate_random_text()`: Get random text from pre-generated pool (class method)
  - `_record_request()`: Record API request in benchmark stats
  - `_record_rate_limit()`: Record rate limit hit in benchmark stats
  - `_record_error()`: Record error in benchmark stats
  - `get_current_user_account_id()`: Fetch authenticated user
  - `get_all_users()`: Fetch users for watchers
- **Class-Level Attributes**:
  - `_TEXT_POOL_SIZE`: Number of pre-generated text strings per category (1000)
  - `_text_pool`: Dict with 'short', 'medium', 'long' text pools
  - `_LOREM_WORDS`: Word list for text generation (60 words)
- **Constructor Parameters**:
  - `benchmark`: Optional BenchmarkTracker for request statistics tracking

#### `JiraDataGenerator` (orchestrator) - `jira_data_generator.py`
- **Purpose**: Orchestrates all generator modules
- **Key Properties**:
  - `project_gen`, `issue_gen`, `issue_items_gen`, `agile_gen`, `filter_gen`: Generator instances
  - `run_id`: Unique label format `PREFIX-YYYYMMDD-HHMMSS`
  - `checkpoint`: Optional CheckpointManager for resumable runs
  - `benchmark`: BenchmarkTracker for timing and request statistics (passed to all generators)

#### `CheckpointManager` - `generators/checkpoint.py`
- **Purpose**: Track progress and enable resumable data generation for large runs
- **Key Features**:
  - JSON-based checkpoint file (`{PREFIX}-checkpoint.json`)
  - Phase-level progress tracking (pending/in_progress/complete)
  - Count-based tracking for high-volume items
  - Atomic file writes (temp file + rename)
  - Auto-archive on completion to `{run_id}-checkpoint.json`
- **Key Methods**:
  - `initialize()`: Create new checkpoint for fresh run
  - `load()`: Load existing checkpoint for resume
  - `save()`: Persist current state to file
  - `is_phase_complete()`: Check if phase can be skipped
  - `get_remaining_count()`: Calculate items still needed
  - `finalize()`: Mark run complete, archive checkpoint

#### `BenchmarkTracker` - `generators/benchmark.py`
- **Purpose**: Track performance metrics and provide time extrapolations for large runs
- **Key Features**:
  - Per-phase timing with items/second rate calculation
  - Request statistics tracking (total, rate limited, errors)
  - Time extrapolation to 18M issues based on observed rates
  - JSON export for programmatic analysis
- **Key Properties**:
  - `total_requests`: Count of API requests made
  - `rate_limited_requests`: Count of 429 responses
  - `error_count`: Count of failed requests (non-429)
  - `rate_limit_percentage`: Percentage of requests that were rate limited
  - `error_percentage`: Percentage of requests that failed
- **Key Methods**:
  - `start_phase(name, target_count)`: Begin timing a phase
  - `end_phase(name, items_created)`: End timing, log rate
  - `record_request()`: Increment request counter
  - `record_rate_limit()`: Increment rate limit counter
  - `record_error()`: Increment error counter
  - `get_summary_report()`: Generate human-readable summary
  - `format_extrapolation(target, current)`: Generate time estimate for target
  - `to_dict()`: Export all data as JSON-serializable dict

### Async vs Sync Operations

The tool uses a hybrid approach optimized for 18M+ issue scale:

| Operation | Mode | Volume at 18M | Reason |
|-----------|------|---------------|--------|
| Custom Fields | **Async** | 22K | Configuration items, created first |
| Project Categories | Sequential | 360 | Low volume, created before projects |
| Projects | Sequential | 5,760 | Low volume, dependencies |
| Project Properties | **Async** | 1.6M | High volume at scale |
| Issues (bulk) | **Parallel** | 18M | Async across projects (50/call per project) |
| Components | **Async** | 3.8M | High volume at scale |
| Versions | **Async** | 25.9M | Very high volume at scale |
| Boards | Sequential | 15K | Filter dependency required |
| Sprints | **Async** | 900K | Scrum boards only (kanban doesn't support sprints) |
| Filters | **Async** | 100K | Medium-high volume at scale |
| Dashboards | **Async** | 16K | Private or authenticated sharing (global disabled) |
| Comments | **Async** | 48.4M | Very high volume |
| Worklogs | **Async** | 4.3M | High volume |
| Issue Links | **Async** | 4.1M | High volume |
| Watchers | **Async** | 40.3M | Very high volume |
| Attachments | **Async** | 27.4M | Pooled 1-5KB files for fast uploads |
| Votes | **Async** | 5.4K | Low volume (but async for consistency) |
| Issue Properties | **Async** | 13.3M | High volume |
| Remote Links | **Async** | 5.9M | Medium-high volume |

### Rate Limiting Strategy

**Priority Order**:
1. **Primary**: Use `Retry-After` header from Jira response
2. **Fallback**: Exponential backoff starting at 1s, doubling on each 429
3. **Reset**: Return to 1s delay on successful request
4. **Max**: Cap at 60s delay
5. **Thread-safe**: Uses asyncio.Lock for shared state in async context

**Sync Implementation**: `JiraAPIClient._handle_rate_limit()` method
**Async Implementation**: `JiraAPIClient._handle_rate_limit_async()` method

### API Call Patterns

#### Synchronous (`_api_call`)
Used for low-volume operations (projects, issues bulk, components, versions):
1. Handles dry-run mode
2. Implements retry logic (max 5 attempts)
3. Processes rate limit responses
4. Provides timeout protection (30s)
5. Supports custom base_url for agile API
6. Returns Response object or None on failure

#### Asynchronous (`_api_call_async`)
Used for high-volume operations (comments, worklogs, links, watchers, etc.):
1. Uses aiohttp ClientSession with connection pooling
2. Semaphore-controlled concurrency
3. Shared rate limit tracking via asyncio.Lock
4. Supports custom base_url for agile API
5. Returns tuple: `(success: bool, response_json: Optional[Dict])`

---

## Data Model

### Multipliers (loaded from CSV)

**Source**: `item_type_multipliers.csv`

**Loading**:
```python
def load_multipliers_from_csv(csv_path: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """Load multipliers from CSV file."""
```

**CSV Structure**:
```csv
Item Type,Small,Medium,Large,XLarge
comment,4.80,4.75,2.69,0.26
issue_worklog,7.27,1.49,0.24,0.06
project,0.00249,0.00066,0.00032,0.00001
...
```

**Size Buckets**:
- **small**: 1-1K issues (high activity per issue)
- **medium**: 1K-10K issues (balanced)
- **large**: 10K-100K issues (moderate activity)
- **xlarge**: 100K+ issues (low activity per issue)

### Created Item Types

**Project-level** (created sequentially via `ProjectGenerator`):
- Project Categories (project_category) - created before projects
- Projects (dynamically created based on multiplier)
- Project Properties (project_property) - custom key-value metadata
- Versions (project_version)
- Components (project_component)

**Issue-level** (via `IssueGenerator` and `IssueItemsGenerator`):
- Issues (bulk created in batches of 50)
- Comments (comment) - **async**
- Worklogs (issue_worklog) - **async**
- Watchers (issue_watcher) - **async**
- Issue Links (issue_link) - **async**
- Attachments (issue_attachment) - **async**
- Votes (issue_vote) - **async**
- Properties (issue_properties) - **async**
- Remote Links (issue_remote_link) - **async**

**Agile items** (via `AgileGenerator`):
- Boards (board) - scrum and kanban
- Sprints (sprint) - with issue assignment

**Other items** (via `FilterGenerator`):
- Filters (filter) - saved JQL queries
- Dashboards (dashboard) - with share permissions

**Configuration items** (via `CustomFieldGenerator`):
- Custom Fields (issue_field) - 20 types with contexts and options

**Not Implemented** (system/configuration items):
- Workflows, screens, permission schemes
- Issue types, priorities, resolutions
- These are configuration items that should already exist

---

## Key Conventions

### Naming

- **Prefixes**: User-specified, appears in all created items (e.g., `PERF`, `LOAD`)
- **Project Keys**: `{PREFIX[:6]}{N}` (e.g., `PERF1`, `PERF2`)
- **Run IDs**: `{PREFIX}-YYYYMMDD-HHMMSS` format
- **Issue Summaries**: `{PROJECT_KEY} Test Issue {N}`
- **Versions**: `{PREFIX} v{N}.0`
- **Components**: `{PREFIX}-Component-{N}`
- **Categories**: `{PREFIX} {Type} {N}` (e.g., `PERF Development 1`)
- **Project Properties**: `{prefix}_property_{N}`
- **Boards**: `{PREFIX} {Type} Board {N}`
- **Sprints**: `{PREFIX} Sprint {N}`
- **Filters**: `{PREFIX} Filter {N}`
- **Dashboards**: `{PREFIX} {Type} Dashboard {N}`

### Logging

- **INFO**: Progress updates, batch completions
- **WARNING**: Rate limits, recoverable errors
- **ERROR**: Fatal errors, API failures
- **DEBUG**: Verbose mode only (--verbose flag)

### Error Handling

- **Fail Fast**: If project/issue creation fails, abort (everything depends on these)
- **Continue on Error**: For comments/worklogs/watchers/etc. (log and continue)
- **Retry Logic**: 5 attempts for transient errors
- **Graceful Degradation**: Missing features are skipped with warnings

---

## Extending the Project

### Adding New Generator Module

1. Create new file in `generators/` directory
2. Inherit from `JiraAPIClient`
3. Implement sync and async methods following existing patterns
4. Add to `generators/__init__.py` exports
5. Initialize in `JiraDataGenerator._init_generators()`
6. Call from `generate_all()` and `generate_all_async()`

### Adding New Async Item Type

**Template for adding a new async item type** (in `IssueItemsGenerator` or new module):

```python
async def create_new_items_async(self, issue_keys: List[str], count: int) -> int:
    """Create new item type concurrently"""
    self.logger.info(f"Creating {count} new items (concurrency: {self.concurrency})...")

    # Pre-generate all tasks
    tasks = []
    for i in range(count):
        issue_key = random.choice(issue_keys)
        item_data = {
            "field1": "value1",
            "field2": self.generate_random_text()
        }
        tasks.append(self._api_call_async('POST', f'issue/{issue_key}/newitem', data=item_data))

    # Execute with progress tracking
    created = 0
    for i in range(0, len(tasks), self.concurrency * 2):
        batch = tasks[i:i + self.concurrency * 2]
        results = await asyncio.gather(*batch, return_exceptions=True)
        for result in results:
            if isinstance(result, tuple) and result[0]:
                created += 1
        self.logger.info(f"Created {created}/{count} new items")

    return created
```

### Adding New Sync Item Type

**Template for sync item type**:

```python
def create_new_items(self, issue_keys: List[str], count: int) -> int:
    """Create new item type"""
    self.logger.info(f"Creating {count} new items...")

    created = 0
    for i in range(count):
        issue_key = random.choice(issue_keys)
        item_data = {
            "field1": "value1",
            "field2": self.generate_random_text()
        }

        response = self._api_call('POST', f'issue/{issue_key}/newitem', data=item_data)
        if response:
            created += 1

        if created % 10 == 0:
            self.logger.info(f"Created {created}/{count} new items")
            time.sleep(0.2)

    return created
```

### Updating Multipliers

1. Edit `item_type_multipliers.csv` file
2. Test with `--dry-run` to verify calculations
3. Document changes in README.md

---

## API Endpoints Used

### Jira Cloud REST API v3

**Base URL**: `{jira_url}/rest/api/3/`

| Endpoint | Method | Generator | Purpose |
|----------|--------|-----------|---------|
| `projectCategory` | POST | ProjectGenerator | Create project category |
| `project` | POST | ProjectGenerator | Create project |
| `project/{key}` | GET/PUT | ProjectGenerator | Get/update project details |
| `project/{key}/role` | GET | ProjectGenerator | Get project roles |
| `project/{key}/role/{id}` | POST | ProjectGenerator | Add user to role |
| `project/{key}/properties/{key}` | PUT | ProjectGenerator | Set project properties |
| `issue/bulk` | POST | IssueGenerator | Bulk issue creation |
| `issue/{key}/attachments` | POST | IssueGenerator | Upload attachments |
| `issue/{key}/comment` | POST | IssueItemsGenerator | Add comments |
| `issue/{key}/worklog` | POST | IssueItemsGenerator | Add worklogs |
| `issue/{key}/watchers` | POST | IssueItemsGenerator | Add watchers |
| `issue/{key}/votes` | POST | IssueItemsGenerator | Add votes |
| `issue/{key}/properties/{key}` | PUT | IssueItemsGenerator | Set issue properties |
| `issue/{key}/remotelink` | POST | IssueItemsGenerator | Add remote links |
| `issueLink` | POST | IssueItemsGenerator | Create issue links |
| `issueLinkType` | GET | IssueItemsGenerator | Get link types |
| `version` | POST | ProjectGenerator | Create versions |
| `component` | POST | ProjectGenerator | Create components |
| `filter` | POST | FilterGenerator | Create filters |
| `dashboard` | POST | FilterGenerator | Create dashboards |
| `field` | POST | CustomFieldGenerator | Create custom fields |
| `field/{id}/context` | GET/POST | CustomFieldGenerator | Get/create field contexts |
| `field/{id}/context/{id}/option` | POST | CustomFieldGenerator | Create field options |
| `myself` | GET | JiraAPIClient | Get current user |
| `users/search` | GET | JiraAPIClient | Search users |

### Jira Software Cloud REST API (Agile)

**Base URL**: `{jira_url}/rest/agile/1.0/`

| Endpoint | Method | Generator | Purpose |
|----------|--------|-----------|---------|
| `board` | GET/POST | AgileGenerator | Get/create boards |
| `sprint` | POST | AgileGenerator | Create sprints |
| `sprint/{id}/issue` | POST | AgileGenerator | Add issues to sprint |

**Documentation**: https://developer.atlassian.com/cloud/jira/platform/rest/v3/

---

## Performance Optimizations

The tool includes several optimizations designed for 18M+ issue scale:

### 1. Pre-Generated Random Text Pool

**Location**: `generators/base.py` (class-level in `JiraAPIClient`)

```python
# Class attributes
_TEXT_POOL_SIZE = 1000  # Strings per category
_text_pool = {'short': [...], 'medium': [...], 'long': [...]}
_LOREM_WORDS = [...]  # 60 words
```

**How it works**:
- 3,000 pre-generated text strings (1,000 per size category)
- Categories: short (3-10 words), medium (5-15 words), long (10-30 words)
- `generate_random_text()` selects from pool based on requested word range
- Thread-safe initialization with double-checked locking

**Impact**: ~38x faster text generation (3.8M/sec vs ~100K/sec)

### 2. Connection Pool Tuning

**Sync Session** (`_create_session()`):
```python
HTTPAdapter(
    pool_connections=20,  # Cache 20 host pools
    pool_maxsize=50,      # 50 connections per host
    pool_block=False      # Don't block on pool exhaustion
)
```

**Async Session** (`_get_async_session()`):
```python
TCPConnector(
    limit=100,            # Total connections
    limit_per_host=50,    # Per-host limit
    ttl_dns_cache=300,    # 5-minute DNS cache
    enable_cleanup_closed=True
)
```

**Impact**: Reduces TCP handshake overhead by reusing connections

### 3. Memory-Efficient Task Batching

**Before** (creates all tasks upfront):
```python
tasks = []
for _ in range(count):  # 48M iterations for comments
    tasks.append(...)   # 48M task objects in memory
```

**After** (generates per-batch):
```python
for batch_start in range(0, count, batch_size):
    tasks = []  # Only batch_size tasks in memory
    for _ in range(current_batch_size):
        tasks.append(...)
    results = await asyncio.gather(*tasks)
```

**Impact**: Reduces peak memory from GBs to MBs at scale

### 4. Attachment Session Reuse

**Location**: `generators/issues.py`

```python
async def _get_attachment_session(self) -> aiohttp.ClientSession:
    """Reusable session for all attachment uploads"""
    if self._attachment_session is None:
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=20)
        self._attachment_session = aiohttp.ClientSession(...)
    return self._attachment_session
```

**Impact**: Eliminates ~27M session creation/teardown cycles at 18M scale

### 5. Attachment File Pooling

**Location**: `generators/issues.py`

- Pool of 20 pre-generated files (1-5KB each)
- Files reused across all attachment uploads
- Eliminates per-upload content generation

**Impact**: ~100x smaller files, no per-upload generation overhead

### API Limitations

**No Bulk Watcher API**: Jira Cloud REST API does not support adding multiple watchers in a single call. Each watcher requires an individual POST to `/rest/api/3/issue/{issueIdOrKey}/watchers`. This is a Jira API limitation, not something we can optimize around.

---

## Common Modifications

### Change Concurrency Default

```python
# In JiraDataGenerator.__init__()
concurrency: int = 5  # Change default value
```

### Change Bulk API Limit

```python
# In IssueGenerator class
BULK_CREATE_LIMIT = 50  # Change to Jira's limit
```

### Adjust Rate Limit Behavior

```python
# In RateLimitState dataclass
max_delay: float = 60.0  # Increase for more conservative rate limiting

# In JiraAPIClient._handle_rate_limit_async()
self.rate_limit.current_delay * 2  # Change multiplier for backoff
```

### Add Custom Issue Fields

```python
# In IssueGenerator.create_issues_bulk(), inside the issue_data dict
issue_data = {
    "fields": {
        "project": {"id": project_id},
        "summary": summary,
        "description": description,
        "issuetype": {"name": "Task"},
        "labels": [self.run_id, self.prefix],
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
  --url https://mycompany.atlassian.net \
  --email test@company.com \
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

### Test Different Concurrency Levels

```bash
# Low concurrency (safer)
python jira_data_generator.py ... --concurrency 3

# High concurrency (faster)
python jira_data_generator.py ... --concurrency 15

# Sequential (debugging)
python jira_data_generator.py ... --no-async
```

### Verify in Jira

```jql
labels = PREFIX-20241204-143022
```

---

## Performance Characteristics

### Timing Estimates

| Issues | Total Items | Sequential | Async (c=5) | Async (c=10) |
|--------|-------------|------------|-------------|--------------|
| 25     | ~250        | 1-2 min    | 30-60s      | 20-40s       |
| 100    | ~1,000      | 5-7 min    | 2-3 min     | 1-2 min      |
| 500    | ~5,000      | 20-30 min  | 8-12 min    | 5-8 min      |
| 1,000  | ~10,000     | 45-60 min  | 15-25 min   | 10-15 min    |

*Times vary based on rate limits and network latency*

### Bottlenecks

1. **Rate Limits**: Primary bottleneck - higher concurrency hits limits faster
2. **Network Latency**: Each API call has ~100-300ms latency
3. **No Bulk API**: Issue links, watchers, votes require individual calls

### Optimization Features

1. **Async I/O**: Concurrent requests for high-volume items
2. **Semaphore Control**: Prevents overwhelming the API
3. **Connection Pooling**: Reuses HTTP connections (both sync and async)
4. **Batch Processing**: Issues created 50 at a time via bulk API
5. **Shared Rate Limit State**: All async tasks respect the same limits

---

## Dependencies

### Required

- `requests>=2.31.0`: HTTP library with retry support (sync)
- `aiohttp>=3.9.0`: Async HTTP library (async)
- `urllib3>=2.0.0`: Connection pooling and retries
- `python-dotenv>=1.0.0`: Load environment variables from .env file

### Python Version

- **Minimum**: Python 3.7+ (dataclasses, type hints, asyncio)
- **Recommended**: Python 3.9+ (improved type hints)
- **Tested**: Python 3.11, 3.14

---

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
| `--resume` | No | Resume from existing checkpoint | `false` |
| `--no-checkpoint` | No | Disable checkpointing entirely | `false` |

\* Token can also be set via `JIRA_API_TOKEN` environment variable or `.env` file

---

## Checkpointing System

### Overview

The checkpointing system enables resumable data generation for large-scale runs (designed for 18M+ issues). Progress is automatically saved to a JSON file and can be resumed after interruptions.

### Checkpoint File Format

```json
{
  "run_id": "PERF-20241208-143022",
  "prefix": "PERF",
  "size": "small",
  "target_issue_count": 1000000,
  "started_at": "2024-12-08T14:30:22",
  "last_updated": "2024-12-08T16:45:00",
  "jira_url": "https://company.atlassian.net",
  "async_mode": true,
  "concurrency": 10,
  "project_keys": ["PERF1", "PERF2"],
  "project_ids": {"PERF1": "10001", "PERF2": "10002"},
  "issue_keys": ["PERF1-1", "PERF1-2", ...],
  "issues_per_project": {"PERF1": 500000, "PERF2": 450000},
  "phases": {
    "projects": {"status": "complete", "target_count": 2, "created_count": 2},
    "issues": {"status": "in_progress", "target_count": 1000000, "created_count": 950000},
    "comments": {"status": "pending", "target_count": 4800000, "created_count": 0},
    ...
  }
}
```

### Phase Tracking

All phases are tracked with status (pending/in_progress/complete) and counts:

| Phase | Tracks |
|-------|--------|
| `project_categories` | Category creation |
| `projects` | Project keys and IDs |
| `project_properties` | Property count |
| `issues` | Issue keys, per-project counts |
| `components` | Component count |
| `versions` | Version count |
| `comments` | Comment count |
| `worklogs` | Worklog count |
| `issue_links` | Link count |
| `watchers` | Watcher count |
| `attachments` | Attachment count |
| `votes` | Vote count |
| `issue_properties` | Property count |
| `remote_links` | Remote link count |
| `boards` | Board count |
| `sprints` | Sprint count |
| `filters` | Filter count |
| `dashboards` | Dashboard count |

### Usage Examples

```bash
# Start a new large run (checkpoint auto-created)
python jira_data_generator.py \
  --url https://company.atlassian.net \
  --email user@company.com \
  --prefix BIGRUN \
  --count 1000000 \
  --size large \
  --concurrency 10

# Resume after interruption
python jira_data_generator.py \
  --url https://company.atlassian.net \
  --email user@company.com \
  --prefix BIGRUN \
  --count 1000000 \
  --size large \
  --resume

# Disable checkpointing for small runs
python jira_data_generator.py ... --no-checkpoint
```

### Resume Behavior

When `--resume` is specified:
1. Looks for `{PREFIX}-checkpoint.json` in current directory
2. Validates URL matches (warns if different)
3. Restores run_id to maintain JQL label consistency
4. Skips completed phases entirely
5. For partial phases, calculates remaining items needed
6. Fetches existing issue keys from Jira if needed

### Checkpoint Lifecycle

1. **Start**: Creates `{PREFIX}-checkpoint.json`
2. **During run**: Updates after each phase/batch completion
3. **On interrupt**: Last save preserved for resume
4. **On completion**: Renames to `{run_id}-checkpoint.json` for archival

### Design Decisions

- **Count-based tracking**: For 18M issues, storing all keys would be ~500MB. Instead, we track counts per project and can reconstruct keys via JQL query on resume.
- **Phase granularity**: Complete phases are skipped entirely; partial phases continue from last count.
- **Atomic writes**: Uses temp file + rename to prevent corruption on interrupt.
- **No item-level tracking for high-volume items**: Comments, worklogs, etc. track only total count (some items may be duplicated on resume, which is acceptable).

---

## Troubleshooting Guide for Agents

### Issue: "Rate limit hit" warnings

**Solution**: This is expected. The code handles it automatically. If persistent:
- Reduce `--concurrency` value
- The tool will auto-adjust with exponential backoff

### Issue: "Failed to create projects. Aborting."

**Check**:
1. API token has project creation permissions
2. Prefix creates valid project keys (uppercase, max 10 chars)
3. No existing projects conflict with generated keys

### Issue: "Failed to create issues. Aborting."

**Check**:
1. API token is valid
2. User has permission in project
3. Project was created successfully
4. Jira URL is correct (https://company.atlassian.net)

### Issue: Async-related errors

**Solution**: Try `--no-async` flag to use sequential mode
```bash
python jira_data_generator.py ... --no-async
```

### Issue: Slow performance

**Expected**: Large datasets take time due to rate limits
**Try**: Increase `--concurrency` (but may hit rate limits faster)

### Issue: Board creation fails

**Check**:
1. Jira Software is enabled (not just Jira Core)
2. Project type is 'software'
3. Filter creation succeeds (boards require filters)

---

## Quick Reference for Common Agent Tasks

### "Add support for [feature]"

1. Check if endpoint exists in Jira API v3 docs
2. Decide which generator module to use (or create new one)
3. Decide sync vs async (based on volume)
4. Add method following patterns above
5. Add to `JiraDataGenerator.generate_all()` and `generate_all_async()`
6. Add multiplier to CSV if needed
7. Test with --dry-run
8. Update README.md

### "Fix rate limiting issue"

1. Check `JiraAPIClient._handle_rate_limit_async()` method for async
2. Check `JiraAPIClient._handle_rate_limit()` method for sync
3. Verify asyncio.Lock is used for shared state
4. Adjust max_delay or backoff multiplier
5. Consider reducing default concurrency

### "Change output format"

1. Modify logging statements in relevant generator methods
2. Keep structure: "Created X/Y items"
3. For async: log progress in batch loop
4. Update README.md examples

### "Add new size bucket"

1. Add column to `item_type_multipliers.csv`
2. Update `size_map` in `load_multipliers_from_csv()`
3. Add to argparse choices
4. Document in README.md

---

## User Generator Script

### Overview

`jira_user_generator.py` is a helper script for creating sandbox test users and groups.

### Key Classes

#### `JiraUserGenerator`
- **Purpose**: Invite users and create groups in Jira Cloud
- **Key Properties**:
  - `VALID_PRODUCTS`: List of valid Jira product names
  - `products`: List of products to grant access (default: `['jira-software']`)
  - `created_users[]`: Track invited users
  - `existing_users[]`: Track users that already exist
  - `created_groups[]`: Track created groups
  - `existing_groups[]`: Track groups that already exist

### Command Line Options

| Option | Required | Description | Default |
|--------|----------|-------------|---------|
| `--url` | Yes | Jira instance URL | - |
| `--email` | Yes | Your Jira admin email | - |
| `--token` | No* | API token | From env |
| `--base-email` | Yes | Base email for sandbox users | - |
| `--users` | Yes | Number of users to create | - |
| `--groups` | No | Group names to create | None |
| `--products` | No | Products to grant access | `jira-software` |
| `--user-prefix` | No | Display name prefix | `Sandbox` |
| `--dry-run` | No | Preview only | `false` |
| `--verbose` | No | Debug logging | `false` |

---

## Version History

- **v3.7** (2024-12-10): Fix dashboard sharing and sprint board filtering
  - Fixed dashboard creation error: Removed `{"type": "global"}` share permission which is disabled on most Jira Cloud instances
  - Dashboards now alternate between private and authenticated user sharing
  - Fixed sprint creation error: Sprints are now only created on scrum boards (kanban boards don't support sprints)
  - Added `scrum_board_ids` filtering in both sync and async agile item creation

- **v3.6** (2024-12-09): Performance optimizations for 18M+ scale
  - **Session reuse for attachments**: Dedicated `aiohttp.ClientSession` reused across all attachment uploads (eliminates ~27M session creation/teardown cycles at 18M scale)
  - **Pre-generated random text pool**: 3,000 pre-generated text strings in 3 size categories (short/medium/long), ~38x faster than generating on-the-fly
  - **Memory-efficient task batching**: All async methods now generate tasks per-batch instead of upfront (reduces peak memory from GBs to MBs at scale)
  - **Optimized connection pooling**:
    - Sync (requests): `HTTPAdapter(pool_connections=20, pool_maxsize=50)`
    - Async (aiohttp): `TCPConnector(limit=100, limit_per_host=50, ttl_dns_cache=300)`
  - Updated all async methods in `issue_items.py`, `projects.py`, and `issues.py`

- **v3.5** (2024-12-09): Parallel issue creation and attachment optimization
  - Added `create_issues_bulk_async()` method for parallel issue creation across projects
  - Issues now created concurrently across multiple projects (up to 5 parallel)
  - Added attachment pooling system with pre-generated 1-5KB files
  - Reduced attachment size from 1-500KB to 1-5KB (~100x smaller)
  - Pool of 20 reusable attachments eliminates per-upload content generation
  - Expected 10-20x speedup for attachment phase
  - Updated all documentation (README, QUICKREF, CLAUDE.md)

- **v3.4** (2024-12-08): Custom fields support
  - Added `CustomFieldGenerator` module for creating custom fields
  - Supports 20 field types: textfield, textarea, float, date, datetime, select, multiselect, radiobuttons, checkboxes, userpicker, grouppicker, labels, url, project, version, etc.
  - Automatically creates options for select-type fields
  - Both sync and async methods available
  - Created early as configuration items (before projects)
  - At 18M issues: ~22K custom fields

- **v3.3** (2024-12-08): Expanded async support for 18M+ issue scale
  - Added async methods for versions, components, project properties
  - Added async methods for sprints, filters, dashboards
  - Updated main generator to use async for all high-volume operations
  - Boards remain sequential (filter dependency required)
  - Volume analysis: versions (25.9M), components (3.8M), sprints (900K) at 18M scale

- **v3.2** (2024-12-08): Request statistics tracking
  - Added request statistics to benchmark summary (total requests, rate limited %, errors %)
  - Added `record_request()`, `record_rate_limit()`, `record_error()` methods to BenchmarkTracker
  - Integrated request tracking into `JiraAPIClient._api_call()` and `_api_call_async()`
  - Added `benchmark` parameter to all generator classes
  - Shows "(No requests recorded - dry-run mode)" in dry-run mode
  - Updated README, QUICKREF, and CLAUDE.md documentation

- **v3.1** (2024-12-08): Benchmarking and time extrapolation
  - Added `BenchmarkTracker` class for performance tracking
  - Per-phase timing with items/second rates
  - Automatic time extrapolation for 18M issues
  - Summary report with phase breakdown
  - Updated README and QUICKREF with benchmarking docs

- **v3.0** (2024-12-08): Checkpointing for resumable large runs
  - Added `CheckpointManager` for progress tracking
  - New `--resume` flag to continue interrupted runs
  - New `--no-checkpoint` flag to disable checkpointing
  - Phase-level and count-based progress tracking
  - Atomic checkpoint file writes
  - Support for 18M+ issue runs with interruption recovery

- **v2.1** (2024-12-08): Project categories and properties
  - Added project categories (organize projects)
  - Added project properties (custom key-value metadata)
  - Projects automatically assigned to categories
  - Updated all documentation

- **v2.0** (2024-12-08): Modular architecture refactor
  - Split monolithic file into `generators/` package
  - Added votes, properties, remote links support
  - Added boards and sprints (agile API)
  - Added filters and dashboards
  - Improved code organization and maintainability
  - Updated CLAUDE.md with new architecture

- **v1.2** (2024-12-05): User generator script
  - New `jira_user_generator.py` helper script
  - Invite sandbox users with plus-addressing
  - Create groups
  - Grant Jira product access

- **v1.1** (2024-12-05): Async concurrency support
  - Added aiohttp for async HTTP requests
  - Concurrent creation for comments, worklogs, watchers, links
  - `--concurrency` flag to control parallel requests
  - `--no-async` flag for sequential mode

- **v1.0** (2024-12-04): Initial release
  - Bulk issue creation
  - Rate limit handling
  - 4 size buckets
  - Comments, worklogs, watchers, links
  - Versions and components

---

**Last Updated**: 2024-12-10 (v3.7 - Fix Dashboard Sharing and Sprint Board Filtering)
**AI Agent Note**: This file is specifically for you. The user-facing docs are in README.md.
