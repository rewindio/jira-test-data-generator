#!/usr/bin/env python3
"""
Jira Test Data Generator

Generates realistic test data for Jira instances based on multipliers from production data.
Handles rate limiting intelligently and uses bulk APIs for best performance.
Supports concurrent API calls via asyncio for improved performance.
"""

import argparse
import asyncio
import csv
import json
import logging
import math
import os
import random
import string
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta

import aiohttp
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv


def load_multipliers_from_csv(csv_path: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """Load multipliers from CSV file.

    Returns dict keyed by size bucket (small, medium, large, xlarge),
    with each value being a dict of item_type -> multiplier.
    """
    if csv_path is None:
        # Default to item_type_multipliers.csv in same directory as script
        csv_path = Path(__file__).parent / 'item_type_multipliers.csv'

    multipliers = {
        'small': {},
        'medium': {},
        'large': {},
        'xlarge': {}
    }

    size_map = {
        'Small': 'small',
        'Medium': 'medium',
        'Large': 'large',
        'XLarge': 'xlarge'
    }

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            item_type = row['Item Type']
            for csv_col, size_key in size_map.items():
                value = row.get(csv_col, '').strip()
                if value:
                    try:
                        multipliers[size_key][item_type] = float(value)
                    except ValueError:
                        pass  # Skip invalid values

    return multipliers


# Load multipliers from CSV file
MULTIPLIERS = load_multipliers_from_csv()


@dataclass
class RateLimitState:
    """Tracks rate limiting state (shared across async tasks)"""
    retry_after: Optional[float] = None
    consecutive_429s: int = 0
    current_delay: float = 1.0
    max_delay: float = 60.0
    # Lock for thread-safe updates in async context
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class JiraDataGenerator:
    """Generates test data for Jira with intelligent rate limiting"""
    
    BULK_CREATE_LIMIT = 50  # Jira's bulk create limit
    
    def __init__(
        self,
        jira_url: str,
        email: str,
        api_token: str,
        prefix: str,
        size_bucket: str = 'small',
        dry_run: bool = False,
        concurrency: int = 5
    ):
        self.jira_url = jira_url.rstrip('/')
        self.email = email
        self.api_token = api_token
        self.prefix = prefix
        self.size_bucket = size_bucket.lower()
        self.dry_run = dry_run
        self.concurrency = concurrency

        # Project context (set dynamically when creating projects)
        self.project_key = None

        self.rate_limit = RateLimitState()
        self.session = self._create_session()
        self.logger = logging.getLogger(__name__)

        # Async session (created lazily)
        self._async_session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

        # Track created items for linking
        self.created_issues = []
        self.created_users = []
        self.created_versions = []
        self.created_components = []
        self.created_sprints = []

        # Project ID (fetched lazily)
        self._project_id = None

        # Generate unique label for this run
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Validate size bucket
        if self.size_bucket not in MULTIPLIERS:
            raise ValueError(f"Invalid size bucket. Must be one of: {', '.join(MULTIPLIERS.keys())}")
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic"""
        session = requests.Session()
        
        # Don't retry on 429 - we'll handle that ourselves
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _handle_rate_limit(self, response: requests.Response):
        """Handle rate limit responses intelligently"""
        if response.status_code == 429:
            self.rate_limit.consecutive_429s += 1
            
            # Check for Retry-After header
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                try:
                    self.rate_limit.retry_after = float(retry_after)
                except ValueError:
                    # Might be a date string, default to 60s
                    self.rate_limit.retry_after = 60
            else:
                # Use exponential backoff
                self.rate_limit.current_delay = min(
                    self.rate_limit.current_delay * 2,
                    self.rate_limit.max_delay
                )
                self.rate_limit.retry_after = self.rate_limit.current_delay
            
            self.logger.warning(
                f"Rate limit hit ({self.rate_limit.consecutive_429s} consecutive). "
                f"Waiting {self.rate_limit.retry_after:.1f}s"
            )
            time.sleep(self.rate_limit.retry_after)
            
        elif response.status_code < 300:
            # Success - reset backoff
            self.rate_limit.consecutive_429s = 0
            self.rate_limit.current_delay = 1.0
    
    def _api_call(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        max_retries: int = 5
    ) -> Optional[requests.Response]:
        """Make an API call with rate limit handling"""
        url = f"{self.jira_url}/rest/api/3/{endpoint}"
        
        if self.dry_run:
            self.logger.info(f"DRY RUN: {method} {endpoint}")
            return None
        
        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    auth=(self.email, self.api_token),
                    headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
                    timeout=30
                )
                
                self._handle_rate_limit(response)
                
                if response.status_code == 429:
                    continue  # Retry after waiting
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                # Check if this is an "already exists" error (expected when re-running)
                is_already_exists = False
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_text = e.response.text.lower()
                        is_already_exists = 'already exists' in error_text or 'already a member' in error_text
                    except Exception:
                        pass

                if is_already_exists:
                    # Log at debug level - this is expected behavior when re-running
                    self.logger.debug(f"Item already exists: {endpoint}")
                else:
                    self.logger.error(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    # Log response body for errors to help debug
                    if hasattr(e, 'response') and e.response is not None:
                        try:
                            error_detail = e.response.text
                            self.logger.error(f"Response body: {error_detail}")
                        except Exception:
                            pass

                # Don't retry on client errors (4xx) - they won't succeed
                if hasattr(e, 'response') and e.response is not None and e.response.status_code < 500:
                    return None
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return None  # Return None instead of raising
        
        return None

    async def _get_async_session(self) -> aiohttp.ClientSession:
        """Get or create async HTTP session"""
        if self._async_session is None or self._async_session.closed:
            auth = aiohttp.BasicAuth(self.email, self.api_token)
            timeout = aiohttp.ClientTimeout(total=30)
            self._async_session = aiohttp.ClientSession(
                auth=auth,
                timeout=timeout,
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                }
            )
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)
        return self._async_session

    async def _close_async_session(self):
        """Close async HTTP session"""
        if self._async_session and not self._async_session.closed:
            await self._async_session.close()

    async def _handle_rate_limit_async(self, status: int, headers: dict) -> float:
        """Handle rate limit responses in async context. Returns delay if rate limited."""
        if status == 429:
            async with self.rate_limit._lock:
                self.rate_limit.consecutive_429s += 1

                retry_after = headers.get('Retry-After')
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = 60
                else:
                    self.rate_limit.current_delay = min(
                        self.rate_limit.current_delay * 2,
                        self.rate_limit.max_delay
                    )
                    delay = self.rate_limit.current_delay

                self.logger.warning(
                    f"Rate limit hit ({self.rate_limit.consecutive_429s} consecutive). "
                    f"Waiting {delay:.1f}s"
                )
                return delay
        elif status < 300:
            async with self.rate_limit._lock:
                self.rate_limit.consecutive_429s = 0
                self.rate_limit.current_delay = 1.0
        return 0

    async def _api_call_async(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        max_retries: int = 5
    ) -> Tuple[bool, Optional[Dict]]:
        """Make an async API call with rate limit handling.

        Returns (success: bool, response_json: Optional[Dict])
        """
        url = f"{self.jira_url}/rest/api/3/{endpoint}"

        if self.dry_run:
            self.logger.debug(f"DRY RUN: {method} {endpoint}")
            return (True, None)

        session = await self._get_async_session()

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    async with session.request(method, url, json=data, params=params) as response:
                        delay = await self._handle_rate_limit_async(response.status, dict(response.headers))

                        if response.status == 429:
                            await asyncio.sleep(delay)
                            continue

                        if response.status >= 400:
                            error_text = await response.text()
                            # Check if this is an "already exists" error (expected when re-running)
                            is_already_exists = 'already exists' in error_text.lower() or 'already a member' in error_text.lower()
                            if is_already_exists:
                                self.logger.debug(f"Item already exists: {endpoint}")
                            else:
                                self.logger.error(f"API call failed ({response.status}): {endpoint}")
                                self.logger.error(f"Response: {error_text}")
                            # Don't retry on client errors (4xx) except 429 (rate limit)
                            if response.status < 500:
                                return (False, None)
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)
                                continue
                            return (False, None)

                        if response.status == 204:
                            return (True, None)

                        result = await response.json()
                        return (True, result)

                except aiohttp.ClientError as e:
                    self.logger.error(f"Async API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        return (False, None)

        return (False, None)

    def get_project_id(self) -> Optional[str]:
        """Fetch and cache the project ID from the project key"""
        if self._project_id:
            return self._project_id

        if self.dry_run:
            self._project_id = "10000"  # Fake ID for dry run
            return self._project_id

        response = self._api_call('GET', f'project/{self.project_key}')
        if response:
            project_data = response.json()
            self._project_id = project_data.get('id')
            self.logger.debug(f"Fetched project ID: {self._project_id} for key: {self.project_key}")
            return self._project_id
        else:
            self.logger.error(f"Could not fetch project ID for key: {self.project_key}")
            return None

    def generate_random_text(self, min_words: int = 5, max_words: int = 20) -> str:
        """Generate random lorem ipsum style text"""
        words = [
            'lorem', 'ipsum', 'dolor', 'sit', 'amet', 'consectetur', 'adipiscing', 'elit',
            'sed', 'do', 'eiusmod', 'tempor', 'incididunt', 'ut', 'labore', 'et', 'dolore',
            'magna', 'aliqua', 'enim', 'ad', 'minim', 'veniam', 'quis', 'nostrud',
            'exercitation', 'ullamco', 'laboris', 'nisi', 'aliquip', 'ex', 'ea', 'commodo'
        ]
        num_words = random.randint(min_words, max_words)
        return ' '.join(random.choices(words, k=num_words)).capitalize()
    
    def create_issues_bulk(self, count: int) -> List[str]:
        """Create issues in bulk batches."""
        self.logger.info(f"Creating {count} issues in batches of {self.BULK_CREATE_LIMIT}...")

        # Fetch project ID - bulk API requires ID, not key
        project_id = self.get_project_id()
        if not project_id and not self.dry_run:
            self.logger.error("Cannot create issues without valid project ID")
            return []

        issue_keys = []

        for batch_start in range(0, count, self.BULK_CREATE_LIMIT):
            batch_size = min(self.BULK_CREATE_LIMIT, count - batch_start)

            # Prepare bulk create payload
            issues_data = {
                "issueUpdates": []
            }

            for i in range(batch_size):
                issue_num = batch_start + i + 1
                issue_data = {
                    "fields": {
                        "project": {"id": project_id},
                        "summary": f"{self.prefix} Test Issue {issue_num}",
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": f"Test issue created by data generator. {self.generate_random_text(10, 30)}"
                                        }
                                    ]
                                }
                            ]
                        },
                        "issuetype": {"name": "Task"},
                        "labels": [self.run_id, self.prefix]
                    }
                }
                issues_data["issueUpdates"].append(issue_data)

            if self.dry_run:
                self.logger.info(f"DRY RUN: Would create batch of {batch_size} issues")
                # Generate fake keys for dry run
                for i in range(batch_size):
                    issue_keys.append(f"{self.project_key}-{batch_start + i + 1}")
            else:
                self.logger.debug(f"Bulk create payload: {issues_data}")
                response = self._api_call('POST', 'issue/bulk', data=issues_data)

                if response:
                    result = response.json()
                    created = result.get('issues', [])
                    for issue in created:
                        key = issue.get('key')
                        if key:
                            issue_keys.append(key)
                            self.logger.info(f"Created issue: {key}")

            # Small delay between batches to be nice
            if batch_start + batch_size < count:
                time.sleep(0.5)

        self.created_issues = issue_keys
        return issue_keys
    
    def generate_random_file(self, min_size_kb: int = 1, max_size_kb: int = 100) -> Tuple[bytes, str]:
        """Generate random file content with a random size.

        Returns (content_bytes, filename)
        """
        # Random size between min and max KB
        size_bytes = random.randint(min_size_kb * 1024, max_size_kb * 1024)

        # Choose a random file type
        file_types = [
            ('txt', 'text/plain'),
            ('json', 'application/json'),
            ('csv', 'text/csv'),
            ('log', 'text/plain'),
        ]
        ext, _ = random.choice(file_types)

        # Generate random content
        if ext == 'json':
            # Generate fake JSON
            data = {
                'id': random.randint(1, 10000),
                'name': self.generate_random_text(2, 5),
                'description': self.generate_random_text(10, 30),
                'values': [random.randint(1, 100) for _ in range(10)],
                'metadata': {
                    'created': datetime.now().isoformat(),
                    'prefix': self.prefix
                }
            }
            content = json.dumps(data, indent=2).encode('utf-8')
            # Pad to desired size
            if len(content) < size_bytes:
                padding = ''.join(random.choices(string.ascii_letters + string.digits, k=size_bytes - len(content)))
                content = content[:-1] + f', "padding": "{padding}"}}'.encode('utf-8')
        elif ext == 'csv':
            # Generate fake CSV
            lines = ['id,name,value,timestamp']
            while len('\n'.join(lines).encode('utf-8')) < size_bytes:
                lines.append(f'{random.randint(1,10000)},{self.generate_random_text(1,3)},{random.randint(1,1000)},{datetime.now().isoformat()}')
            content = '\n'.join(lines).encode('utf-8')
        else:
            # Plain text - just random words
            words = []
            while len(' '.join(words).encode('utf-8')) < size_bytes:
                words.append(self.generate_random_text(5, 20))
            content = ' '.join(words).encode('utf-8')

        # Trim to exact size
        content = content[:size_bytes]

        filename = f"{self.prefix}_attachment_{random.randint(1000, 9999)}.{ext}"
        return content, filename

    def add_attachment(self, issue_key: str, content: bytes, filename: str) -> bool:
        """Add an attachment to an issue.

        The attachment API requires multipart form data, not JSON.
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would attach {filename} ({len(content)} bytes) to {issue_key}")
            return True

        url = f"{self.jira_url}/rest/api/3/issue/{issue_key}/attachments"

        try:
            response = self.session.post(
                url,
                files={'file': (filename, content)},
                headers={'X-Atlassian-Token': 'no-check'},  # Required for attachment API
                auth=(self.email, self.api_token),
                timeout=60
            )

            if response.status_code == 429:
                retry_after = float(response.headers.get('Retry-After', 30))
                self.logger.warning(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                return self.add_attachment(issue_key, content, filename)

            response.raise_for_status()
            return True

        except requests.exceptions.RequestException as e:
            # Check for "already exists" type errors
            is_expected = False
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_text = e.response.text.lower()
                    is_expected = 'already exists' in error_text
                except Exception:
                    pass

            if is_expected:
                self.logger.debug(f"Attachment already exists: {filename}")
            else:
                self.logger.error(f"Failed to attach {filename} to {issue_key}: {e}")
            return False

    def create_attachments(self, issue_keys: List[str], count: int):
        """Create attachments on issues"""
        self.logger.info(f"Creating {count} attachments...")

        created = 0
        failed = 0
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            content, filename = self.generate_random_file(min_size_kb=1, max_size_kb=500)

            if self.add_attachment(issue_key, content, filename):
                created += 1
            else:
                failed += 1

            if (created + failed) % 10 == 0:
                self.logger.info(f"Created {created}/{count} attachments ({failed} failed)")
                time.sleep(0.2)

        self.logger.info(f"Attachments complete: {created} added, {failed} failed")
        return created

    async def add_attachment_async(self, issue_key: str, content: bytes, filename: str) -> bool:
        """Add an attachment to an issue asynchronously."""
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would attach {filename} ({len(content)} bytes) to {issue_key}")
            return True

        url = f"{self.jira_url}/rest/api/3/issue/{issue_key}/attachments"

        # Need a separate session for attachments - the main session has JSON content-type
        auth = aiohttp.BasicAuth(self.email, self.api_token)

        async with self._semaphore:
            try:
                # Create multipart form data
                data = aiohttp.FormData()
                data.add_field('file', content, filename=filename, content_type='application/octet-stream')

                async with aiohttp.ClientSession(auth=auth) as attachment_session:
                    async with attachment_session.post(
                        url,
                        data=data,
                        headers={'X-Atlassian-Token': 'no-check'},
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        if response.status == 429:
                            retry_after = float(response.headers.get('Retry-After', 30))
                            self.logger.warning(f"Rate limited. Waiting {retry_after}s...")
                            await asyncio.sleep(retry_after)
                            return await self.add_attachment_async(issue_key, content, filename)

                        if response.status >= 400:
                            error_text = await response.text()
                            if 'already exists' not in error_text.lower():
                                self.logger.error(f"Failed to attach {filename} to {issue_key}: {response.status}")
                            return False

                        return True

            except aiohttp.ClientError as e:
                self.logger.error(f"Failed to attach {filename} to {issue_key}: {e}")
                return False

    async def create_attachments_async(self, issue_keys: List[str], count: int) -> int:
        """Create attachments on issues concurrently"""
        self.logger.info(f"Creating {count} attachments (concurrency: {self.concurrency})...")

        # Pre-generate all attachment data and tasks
        tasks = []
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            content, filename = self.generate_random_file(min_size_kb=1, max_size_kb=500)
            tasks.append(self.add_attachment_async(issue_key, content, filename))

        # Execute with progress tracking
        created = 0
        failed = 0
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i:i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1
                else:
                    failed += 1
            self.logger.info(f"Created {created}/{count} attachments ({failed} failed)")

        self.logger.info(f"Attachments complete: {created} added, {failed} failed")
        return created

    def create_comments(self, issue_keys: List[str], count: int):
        """Create comments on issues"""
        self.logger.info(f"Creating {count} comments...")
        
        comments_per_issue = {}
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            comments_per_issue[issue_key] = comments_per_issue.get(issue_key, 0) + 1
        
        created = 0
        for issue_key, num_comments in comments_per_issue.items():
            for _ in range(num_comments):
                comment_data = {
                    "body": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"{self.prefix} comment: {self.generate_random_text(5, 15)}"
                                    }
                                ]
                            }
                        ]
                    }
                }
                
                self._api_call('POST', f'issue/{issue_key}/comment', data=comment_data)
                created += 1
                
                if created % 10 == 0:
                    self.logger.info(f"Created {created}/{count} comments")
                    time.sleep(0.2)  # Small delay every 10 comments

    async def create_comments_async(self, issue_keys: List[str], count: int) -> int:
        """Create comments on issues concurrently"""
        self.logger.info(f"Creating {count} comments (concurrency: {self.concurrency})...")

        # Pre-generate all comment tasks
        tasks = []
        for i in range(count):
            issue_key = random.choice(issue_keys)
            comment_data = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"{self.prefix} comment: {self.generate_random_text(5, 15)}"
                                }
                            ]
                        }
                    ]
                }
            }
            tasks.append(self._api_call_async('POST', f'issue/{issue_key}/comment', data=comment_data))

        # Execute with progress tracking
        created = 0
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i:i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
            self.logger.info(f"Created {created}/{count} comments")

        return created

    def create_worklogs(self, issue_keys: List[str], count: int):
        """Create worklogs on issues"""
        self.logger.info(f"Creating {count} worklogs...")
        
        worklogs_per_issue = {}
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            worklogs_per_issue[issue_key] = worklogs_per_issue.get(issue_key, 0) + 1
        
        created = 0
        for issue_key, num_worklogs in worklogs_per_issue.items():
            for _ in range(num_worklogs):
                # Random time spent between 30 minutes and 8 hours
                time_spent_seconds = random.randint(1800, 28800)
                
                worklog_data = {
                    "timeSpentSeconds": time_spent_seconds,
                    "comment": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"{self.prefix} work: {self.generate_random_text(3, 10)}"
                                    }
                                ]
                            }
                        ]
                    },
                    "started": (datetime.now() - timedelta(days=random.randint(0, 30))).strftime('%Y-%m-%dT%H:%M:%S.000+0000')
                }
                
                self._api_call('POST', f'issue/{issue_key}/worklog', data=worklog_data)
                created += 1
                
                if created % 10 == 0:
                    self.logger.info(f"Created {created}/{count} worklogs")
                    time.sleep(0.2)

    async def create_worklogs_async(self, issue_keys: List[str], count: int) -> int:
        """Create worklogs on issues concurrently"""
        self.logger.info(f"Creating {count} worklogs (concurrency: {self.concurrency})...")

        # Pre-generate all worklog tasks
        tasks = []
        for i in range(count):
            issue_key = random.choice(issue_keys)
            time_spent_seconds = random.randint(1800, 28800)

            worklog_data = {
                "timeSpentSeconds": time_spent_seconds,
                "comment": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"{self.prefix} work: {self.generate_random_text(3, 10)}"
                                }
                            ]
                        }
                    ]
                },
                "started": (datetime.now() - timedelta(days=random.randint(0, 30))).strftime('%Y-%m-%dT%H:%M:%S.000+0000')
            }
            tasks.append(self._api_call_async('POST', f'issue/{issue_key}/worklog', data=worklog_data))

        # Execute with progress tracking
        created = 0
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i:i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
            self.logger.info(f"Created {created}/{count} worklogs")

        return created

    def create_issue_links(self, issue_keys: List[str], count: int):
        """Create issue links"""
        self.logger.info(f"Creating {count} issue links...")

        if len(issue_keys) < 2:
            self.logger.warning("Need at least 2 issues to create links")
            return

        # Get available link types
        if self.dry_run:
            link_types = [{'name': 'Blocks'}, {'name': 'Relates'}]
        else:
            response = self._api_call('GET', 'issueLinkType')
            if not response:
                self.logger.warning("Could not fetch link types")
                return

            link_types = response.json().get('issueLinkTypes', [])
            if not link_types:
                self.logger.warning("No link types available")
                return

        created = 0
        for _ in range(count):
            # Pick two different random issues
            inward_issue = random.choice(issue_keys)
            outward_issue = random.choice([k for k in issue_keys if k != inward_issue])
            link_type = random.choice(link_types)

            link_data = {
                "type": {"name": link_type['name']},
                "inwardIssue": {"key": inward_issue},
                "outwardIssue": {"key": outward_issue}
            }

            self._api_call('POST', 'issueLink', data=link_data)
            created += 1

            if created % 10 == 0:
                self.logger.info(f"Created {created}/{count} issue links")
                time.sleep(0.2)

    async def create_issue_links_async(self, issue_keys: List[str], count: int) -> int:
        """Create issue links concurrently"""
        self.logger.info(f"Creating {count} issue links (concurrency: {self.concurrency})...")

        if len(issue_keys) < 2:
            self.logger.warning("Need at least 2 issues to create links")
            return 0

        # Get available link types
        if self.dry_run:
            link_types = [{'name': 'Blocks'}, {'name': 'Relates'}]
        else:
            response = self._api_call('GET', 'issueLinkType')
            if not response:
                self.logger.warning("Could not fetch link types")
                return 0
            link_types = response.json().get('issueLinkTypes', [])
            if not link_types:
                self.logger.warning("No link types available")
                return 0

        # Pre-generate all link tasks
        tasks = []
        for _ in range(count):
            inward_issue = random.choice(issue_keys)
            outward_issue = random.choice([k for k in issue_keys if k != inward_issue])
            link_type = random.choice(link_types)

            link_data = {
                "type": {"name": link_type['name']},
                "inwardIssue": {"key": inward_issue},
                "outwardIssue": {"key": outward_issue}
            }
            tasks.append(self._api_call_async('POST', 'issueLink', data=link_data))

        # Execute with progress tracking
        created = 0
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i:i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
            self.logger.info(f"Created {created}/{count} issue links")

        return created

    def add_watchers(self, issue_keys: List[str], count: int, project_keys: List[str]):
        """Add watchers to issues using users from the Jira instance"""
        self.logger.info(f"Adding {count} watchers...")

        # Fetch users from Jira to use as watchers
        watcher_ids = self.get_all_users(max_users=100)

        if not watcher_ids:
            self.logger.warning("No users found in Jira instance, skipping watchers")
            return

        # Warn if requested watchers exceeds available users
        if count > len(watcher_ids):
            self.logger.warning(
                f"Requested {count} watchers but only {len(watcher_ids)} users available in Jira. "
                f"Some users will be added as watchers to multiple issues."
            )

        # Add users to all projects so they can view issues
        for project_key in project_keys:
            self.add_users_to_project(project_key, watcher_ids)

        created = 0
        failed = 0
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            watcher_id = random.choice(watcher_ids)

            response = self._api_call('POST', f'issue/{issue_key}/watchers', data=watcher_id)
            if response is not None:
                created += 1
            else:
                failed += 1

            if (created + failed) % 10 == 0:
                self.logger.info(f"Added {created}/{count} watchers ({failed} failed)")
                time.sleep(0.2)

        self.logger.info(f"Watchers complete: {created} added, {failed} failed")

    async def add_watchers_async(self, issue_keys: List[str], count: int, project_keys: List[str]) -> int:
        """Add watchers to issues concurrently using users from the Jira instance"""
        self.logger.info(f"Adding {count} watchers (concurrency: {self.concurrency})...")

        # Fetch users from Jira to use as watchers
        watcher_ids = self.get_all_users(max_users=100)

        if not watcher_ids:
            self.logger.warning("No users found in Jira instance, skipping watchers")
            return 0

        # Warn if requested watchers exceeds available users
        if count > len(watcher_ids):
            self.logger.warning(
                f"Requested {count} watchers but only {len(watcher_ids)} users available in Jira. "
                f"Some users will be added as watchers to multiple issues."
            )

        # Add users to all projects so they can view issues
        for project_key in project_keys:
            self.add_users_to_project(project_key, watcher_ids)

        # Pre-generate all watcher tasks - randomly assign watchers to issues
        tasks = []
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            watcher_id = random.choice(watcher_ids)
            tasks.append(self._api_call_async('POST', f'issue/{issue_key}/watchers', data=watcher_id))

        # Execute with progress tracking
        created = 0
        failed = 0
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i:i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
                else:
                    failed += 1
            self.logger.info(f"Added {created}/{count} watchers ({failed} failed)")

        self.logger.info(f"Watchers complete: {created} added, {failed} failed")
        return created

    def create_versions(self, count: int):
        """Create project versions"""
        self.logger.info(f"Creating {count} versions...")
        
        for i in range(count):
            version_data = {
                "name": f"{self.prefix} v{i + 1}.0",
                "description": f"Test version {i + 1} - {self.generate_random_text(5, 10)}",
                "project": self.project_key,
                "released": random.choice([True, False])
            }
            
            response = self._api_call('POST', 'version', data=version_data)
            if response:
                version_id = response.json().get('id')
                self.created_versions.append(version_id)
                self.logger.info(f"Created version {i + 1}/{count}")
            
            time.sleep(0.2)
    
    def create_components(self, count: int):
        """Create project components"""
        self.logger.info(f"Creating {count} components...")
        
        for i in range(count):
            component_data = {
                "name": f"{self.prefix}-Component-{i + 1}",
                "description": f"Test component - {self.generate_random_text(5, 10)}",
                "project": self.project_key
            }
            
            response = self._api_call('POST', 'component', data=component_data)
            if response:
                component_id = response.json().get('id')
                self.created_components.append(component_id)
                self.logger.info(f"Created component {i + 1}/{count}")
            
            time.sleep(0.2)

    def get_project_admin_role_id(self, project_key: str) -> Optional[str]:
        """Get the Administrator role ID for a project"""
        if self.dry_run:
            return "10002"  # Common default for Administrator role

        response = self._api_call('GET', f'project/{project_key}/role')
        if response:
            roles = response.json()
            # Look for Administrator role in the response
            for role_name, role_url in roles.items():
                if 'administrator' in role_name.lower():
                    # Extract role ID from URL (e.g., .../role/10002)
                    role_id = role_url.rstrip('/').split('/')[-1]
                    return role_id
        return None

    def add_user_to_project_role(self, project_key: str, role_id: str, account_id: str) -> bool:
        """Add a user to a project role"""
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would add user to role in {project_key}")
            return True

        data = {
            "user": [account_id]
        }

        response = self._api_call('POST', f'project/{project_key}/role/{role_id}', data=data)
        if response:
            self.logger.debug(f"Added user to role in {project_key}")
            return True
        else:
            self.logger.debug(f"Failed to add user to role in {project_key} (may already exist)")
            return False

    def get_project_viewer_role_id(self, project_key: str) -> Optional[str]:
        """Get a role ID that grants view permission. Falls back to Administrators if no other role exists."""
        if self.dry_run:
            return "10002"  # Common default for Administrators role

        response = self._api_call('GET', f'project/{project_key}/role')
        if response:
            roles = response.json()

            # System roles that cannot be modified
            system_roles = ['atlassian-addons', 'system', 'service']

            def is_system_role(name):
                return any(sr in name.lower() for sr in system_roles)

            # Look for a role that grants view access - try common names first
            for role_name in ['Users', 'Viewers', 'Developers', 'Member', 'Team']:
                for name, role_url in roles.items():
                    if role_name.lower() in name.lower() and not is_system_role(name):
                        role_id = role_url.rstrip('/').split('/')[-1]
                        self.logger.debug(f"Found viewer role: {name} (ID: {role_id})")
                        return role_id

            # Fall back to Administrators role if no other suitable role found
            for name, role_url in roles.items():
                if 'admin' in name.lower() and not is_system_role(name):
                    role_id = role_url.rstrip('/').split('/')[-1]
                    self.logger.debug(f"Using Administrators role for viewers: {name} (ID: {role_id})")
                    return role_id

            self.logger.warning(f"No suitable role found in project {project_key}. Available roles: {list(roles.keys())}")
        return None

    def add_users_to_project(self, project_key: str, user_account_ids: List[str]) -> int:
        """Add multiple users to a project so they can view issues"""
        if not user_account_ids:
            return 0

        role_id = self.get_project_viewer_role_id(project_key)
        if not role_id:
            self.logger.warning(f"Could not find viewer role for project {project_key}")
            return 0

        self.logger.info(f"Adding {len(user_account_ids)} users to project {project_key}...")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would add {len(user_account_ids)} users to project")
            return len(user_account_ids)

        added = 0
        for account_id in user_account_ids:
            if self.add_user_to_project_role(project_key, role_id, account_id):
                added += 1

        self.logger.info(f"Added {added}/{len(user_account_ids)} users to project {project_key}")
        return added

    def get_project(self, project_key: str) -> Optional[Dict[str, str]]:
        """Fetch a project's info by key"""
        response = self._api_call('GET', f'project/{project_key}')
        if response:
            result = response.json()
            return {
                "key": result.get('key'),
                "id": result.get('id')
            }
        return None

    def create_projects(self, count: int) -> List[Dict[str, str]]:
        """Create projects and return list of project info dicts with 'key' and 'id'.

        If a project already exists with our prefix, reuse it instead of failing.
        """
        self.logger.info(f"Creating {count} projects...")

        created_projects = []
        current_user_id = self.get_current_user_account_id()

        for i in range(count):
            # Generate a unique project key (max 10 chars, uppercase)
            project_key = f"{self.prefix[:6].upper()}{i + 1}"

            if self.dry_run:
                self.logger.info(f"DRY RUN: Would create project {project_key}")
                created_projects.append({
                    "key": project_key,
                    "id": f"1000{i}"
                })
                # Also simulate adding admin role
                self.get_project_admin_role_id(project_key)
                self.add_user_to_project_role(project_key, "10002", current_user_id)
                time.sleep(0.3)
                continue

            # Try to create project
            project_data = {
                "key": project_key,
                "name": f"{self.prefix} Test Project {i + 1}",
                "description": f"Test project created by data generator. {self.generate_random_text(5, 15)}",
                "projectTypeKey": "software",
                "leadAccountId": current_user_id
            }

            response = self._api_call('POST', 'project', data=project_data)
            if response:
                result = response.json()
                created_projects.append({
                    "key": result.get('key'),
                    "id": result.get('id')
                })
                self.logger.info(f"Created project {i + 1}/{count}: {result.get('key')}")

                # Add current user to Administrator role for watchers permission
                admin_role_id = self.get_project_admin_role_id(result.get('key'))
                if admin_role_id and current_user_id:
                    self.add_user_to_project_role(result.get('key'), admin_role_id, current_user_id)
            else:
                # Creation failed - try to fetch existing project (may already exist)
                existing_project = self.get_project(project_key)
                if existing_project:
                    self.logger.info(f"Project {project_key} already exists, reusing it")
                    created_projects.append(existing_project)
                else:
                    self.logger.warning(f"Failed to create project {project_key}")

            time.sleep(0.3)

        return created_projects

    def get_current_user_account_id(self) -> Optional[str]:
        """Get the current user's account ID for project lead"""
        if self.dry_run:
            return "dry-run-account-id"

        response = self._api_call('GET', 'myself')
        if response:
            return response.json().get('accountId')
        return None

    def get_all_users(self, max_users: int = 100) -> List[str]:
        """Fetch users from the Jira instance to use as watchers.

        Returns a list of account IDs.
        """
        if self.dry_run:
            return [f"dry-run-user-{i}" for i in range(1, 6)]

        self.logger.info("Fetching users from Jira instance...")

        users = []
        start_at = 0

        while len(users) < max_users:
            # Use users/search endpoint which returns assignable users
            response = self._api_call(
                'GET',
                'users/search',
                params={
                    'startAt': start_at,
                    'maxResults': 50
                }
            )

            if not response:
                break

            batch = response.json()
            if not batch:
                break

            for user in batch:
                account_id = user.get('accountId')
                # Filter out inactive users and app users
                if account_id and user.get('active', True) and user.get('accountType') == 'atlassian':
                    users.append(account_id)

            if len(batch) < 50:
                break

            start_at += 50

        self.logger.info(f"Found {len(users)} users to use as watchers")
        return users[:max_users]

    def generate_all(self, num_issues: int):
        """Generate all test data based on multipliers"""
        multipliers = MULTIPLIERS[self.size_bucket]

        self.logger.info(f"=" * 60)
        self.logger.info(f"Starting Jira data generation")
        self.logger.info(f"Size bucket: {self.size_bucket}")
        self.logger.info(f"Target issues: {num_issues}")
        self.logger.info(f"Prefix: {self.prefix}")
        self.logger.info(f"Run ID (for JQL): labels = {self.run_id}")
        self.logger.info(f"Dry run: {self.dry_run}")
        self.logger.info(f"=" * 60)

        # Calculate counts - use math.ceil to round up, minimum of 1
        counts = {}
        for item_type, multiplier in multipliers.items():
            raw_count = num_issues * multiplier
            counts[item_type] = max(1, math.ceil(raw_count))

        self.logger.info(f"\nPlanned creation counts:")
        self.logger.info(f"  Issues: {num_issues}")
        for item_type, count in sorted(counts.items()):
            self.logger.info(f"  {item_type}: {count}")

        # Create projects first (everything else depends on these)
        num_projects = counts.get('project', 1)
        projects = self.create_projects(num_projects)

        if not projects:
            self.logger.error("Failed to create projects. Aborting.")
            return

        # Distribute issues across projects
        issues_per_project = max(1, num_issues // len(projects))
        remainder = num_issues % len(projects)

        all_issue_keys = []
        for idx, project in enumerate(projects):
            # Update current project context
            self.project_key = project['key']
            self._project_id = project['id']

            # Give extra issues to first projects if there's a remainder
            project_issue_count = issues_per_project + (1 if idx < remainder else 0)

            self.logger.info(f"\nCreating {project_issue_count} issues in project {project['key']}...")
            issue_keys = self.create_issues_bulk(project_issue_count)

            if issue_keys:
                all_issue_keys.extend(issue_keys)

                # Create components and versions for this project
                if counts.get('project_component', 0) > 0:
                    components_per_project = max(1, counts['project_component'] // len(projects))
                    self.create_components(components_per_project)

                if counts.get('project_version', 0) > 0:
                    versions_per_project = max(1, counts['project_version'] // len(projects))
                    self.create_versions(versions_per_project)

        if not all_issue_keys:
            self.logger.error("Failed to create any issues. Aborting.")
            return

        # Create issue-dependent items across all issues
        if counts.get('comment', 0) > 0:
            self.create_comments(all_issue_keys, counts['comment'])

        if counts.get('issue_worklog', 0) > 0:
            self.create_worklogs(all_issue_keys, counts['issue_worklog'])

        if counts.get('issue_link', 0) > 0:
            self.create_issue_links(all_issue_keys, counts['issue_link'])

        if counts.get('issue_watcher', 0) > 0:
            project_keys = [p['key'] for p in projects]
            self.add_watchers(all_issue_keys, counts['issue_watcher'], project_keys)

        if counts.get('issue_attachment', 0) > 0:
            self.create_attachments(all_issue_keys, counts['issue_attachment'])

        self.logger.info(f"\n" + "=" * 60)
        self.logger.info(f"Data generation complete!")
        self.logger.info(f"=" * 60)
        self.logger.info(f"\nTo find all generated data in JQL:")
        self.logger.info(f"  labels = {self.run_id}")
        self.logger.info(f"  OR")
        self.logger.info(f"  labels = {self.prefix}")
        self.logger.info(f"\nCreated {len(projects)} projects")
        self.logger.info(f"Created {len(all_issue_keys)} issues")

    async def generate_all_async(self, num_issues: int):
        """Generate all test data based on multipliers using async for high-volume items"""
        multipliers = MULTIPLIERS[self.size_bucket]

        self.logger.info(f"=" * 60)
        self.logger.info(f"Starting Jira data generation (async mode)")
        self.logger.info(f"Size bucket: {self.size_bucket}")
        self.logger.info(f"Target issues: {num_issues}")
        self.logger.info(f"Prefix: {self.prefix}")
        self.logger.info(f"Concurrency: {self.concurrency}")
        self.logger.info(f"Run ID (for JQL): labels = {self.run_id}")
        self.logger.info(f"Dry run: {self.dry_run}")
        self.logger.info(f"=" * 60)

        # Calculate counts - use math.ceil to round up, minimum of 1
        counts = {}
        for item_type, multiplier in multipliers.items():
            raw_count = num_issues * multiplier
            counts[item_type] = max(1, math.ceil(raw_count))

        self.logger.info(f"\nPlanned creation counts:")
        self.logger.info(f"  Issues: {num_issues}")
        for item_type, count in sorted(counts.items()):
            self.logger.info(f"  {item_type}: {count}")

        # Create projects first (everything else depends on these)
        # Projects are created sequentially (usually few of them)
        num_projects = counts.get('project', 1)
        projects = self.create_projects(num_projects)

        if not projects:
            self.logger.error("Failed to create projects. Aborting.")
            return

        # Distribute issues across projects
        issues_per_project = max(1, num_issues // len(projects))
        remainder = num_issues % len(projects)

        all_issue_keys = []
        for idx, project in enumerate(projects):
            # Update current project context
            self.project_key = project['key']
            self._project_id = project['id']

            # Give extra issues to first projects if there's a remainder
            project_issue_count = issues_per_project + (1 if idx < remainder else 0)

            self.logger.info(f"\nCreating {project_issue_count} issues in project {project['key']}...")
            # Issues use bulk API - keep synchronous as it's already optimized
            issue_keys = self.create_issues_bulk(project_issue_count)

            if issue_keys:
                all_issue_keys.extend(issue_keys)

                # Create components and versions for this project (low volume, keep sync)
                if counts.get('project_component', 0) > 0:
                    components_per_project = max(1, counts['project_component'] // len(projects))
                    self.create_components(components_per_project)

                if counts.get('project_version', 0) > 0:
                    versions_per_project = max(1, counts['project_version'] // len(projects))
                    self.create_versions(versions_per_project)

        if not all_issue_keys:
            self.logger.error("Failed to create any issues. Aborting.")
            await self._close_async_session()
            return

        # Create issue-dependent items using async for high volume items
        try:
            if counts.get('comment', 0) > 0:
                await self.create_comments_async(all_issue_keys, counts['comment'])

            if counts.get('issue_worklog', 0) > 0:
                await self.create_worklogs_async(all_issue_keys, counts['issue_worklog'])

            if counts.get('issue_link', 0) > 0:
                await self.create_issue_links_async(all_issue_keys, counts['issue_link'])

            if counts.get('issue_watcher', 0) > 0:
                project_keys = [p['key'] for p in projects]
                await self.add_watchers_async(all_issue_keys, counts['issue_watcher'], project_keys)

            if counts.get('issue_attachment', 0) > 0:
                await self.create_attachments_async(all_issue_keys, counts['issue_attachment'])

        finally:
            await self._close_async_session()

        self.logger.info(f"\n" + "=" * 60)
        self.logger.info(f"Data generation complete!")
        self.logger.info(f"=" * 60)
        self.logger.info(f"\nTo find all generated data in JQL:")
        self.logger.info(f"  labels = {self.run_id}")
        self.logger.info(f"  OR")
        self.logger.info(f"  labels = {self.prefix}")
        self.logger.info(f"\nCreated {len(projects)} projects")
        self.logger.info(f"Created {len(all_issue_keys)} issues")


def main():
    parser = argparse.ArgumentParser(
        description='Generate test data for Jira based on production multipliers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 100 issues for a small instance (creates projects automatically)
  %(prog)s --url https://mycompany.atlassian.net \\
           --email user@example.com \\
           --token YOUR_API_TOKEN \\
           --prefix PERF \\
           --count 100 \\
           --size small

  # Faster generation with higher concurrency
  %(prog)s --url https://mycompany.atlassian.net \\
           --email user@example.com \\
           --prefix LOAD \\
           --count 500 \\
           --size medium \\
           --concurrency 10

  # Dry run to see what would be created
  %(prog)s --url https://mycompany.atlassian.net \\
           --email user@example.com \\
           --token YOUR_API_TOKEN \\
           --prefix LOAD \\
           --count 500 \\
           --size medium \\
           --dry-run

JQL Search:
  After generation, search for your data using:
    labels = PREFIX-YYYYMMDD-HHMMSS
  Or more broadly:
    labels = PREFIX
        """
    )

    parser.add_argument('--url', required=True, help='Jira URL (e.g., https://mycompany.atlassian.net)')
    parser.add_argument('--email', required=True, help='Your Jira email')
    parser.add_argument('--token', help='Jira API token (or set JIRA_API_TOKEN in .env file or env var)')
    parser.add_argument('--prefix', required=True, help='Prefix for all created items and project keys (e.g., PERF)')
    parser.add_argument('--count', type=int, required=True, help='Number of issues to create')
    parser.add_argument(
        '--size',
        choices=['small', 'medium', 'large', 'xlarge'],
        default='small',
        help='Instance size bucket (affects multipliers)'
    )
    parser.add_argument(
        '--concurrency',
        type=int,
        default=5,
        help='Number of concurrent API requests (default: 5, increase for faster generation)'
    )
    parser.add_argument('--no-async', action='store_true', help='Disable async mode (use sequential requests)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be created without creating it')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    args = parser.parse_args()

    # Generate log filename based on prefix and timestamp
    log_filename = f"jira_generator_{args.prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Setup logging - output to both console and file
    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # Create root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    logger.addHandler(file_handler)

    logging.info(f"Logging to file: {log_filename}")

    # Load environment variables from .env file
    load_dotenv()

    # Get API token from: command line arg > .env file > environment variable
    api_token = args.token or os.environ.get('JIRA_API_TOKEN')
    if not api_token:
        print("Error: Jira API token required. Use --token, set JIRA_API_TOKEN in .env file, or set as environment variable", file=sys.stderr)
        sys.exit(1)

    try:
        generator = JiraDataGenerator(
            jira_url=args.url,
            email=args.email,
            api_token=api_token,
            prefix=args.prefix,
            size_bucket=args.size,
            dry_run=args.dry_run,
            concurrency=args.concurrency
        )

        if args.no_async:
            generator.generate_all(args.count)
        else:
            asyncio.run(generator.generate_all_async(args.count))

    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
