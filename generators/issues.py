"""
Issue generation module.

Handles bulk issue creation and attachment uploads.
"""

import asyncio
import json
import random
import string
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import aiohttp

from .base import JiraAPIClient


class IssueGenerator(JiraAPIClient):
    """Generates issues and attachments for Jira."""

    BULK_CREATE_LIMIT = 50  # Jira's bulk create limit
    ATTACHMENT_POOL_SIZE = 20  # Number of pre-generated attachments to reuse

    def __init__(
        self,
        jira_url: str,
        email: str,
        api_token: str,
        prefix: str,
        dry_run: bool = False,
        concurrency: int = 5,
        benchmark=None
    ):
        super().__init__(jira_url, email, api_token, dry_run, concurrency, benchmark)
        self.prefix = prefix

        # Track created items
        self.created_issues: List[str] = []

        # Project context (set dynamically)
        self.project_key: Optional[str] = None
        self._project_id: Optional[str] = None

        # Generate unique label for this run
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Pre-generated attachment pool (created lazily)
        self._attachment_pool: Optional[List[Tuple[bytes, str]]] = None

    def set_project_context(self, project_key: str, project_id: str):
        """Set the current project context for issue creation."""
        self.project_key = project_key
        self._project_id = project_id

    def get_project_id(self) -> Optional[str]:
        """Fetch and cache the project ID from the project key"""
        if self._project_id:
            return self._project_id

        if self.dry_run:
            self._project_id = "10000"
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

    def create_issues_bulk(self, count: int) -> List[str]:
        """Create issues in bulk batches."""
        self.logger.info(f"Creating {count} issues in batches of {self.BULK_CREATE_LIMIT}...")

        project_id = self.get_project_id()
        if not project_id and not self.dry_run:
            self.logger.error("Cannot create issues without valid project ID")
            return []

        issue_keys = []

        for batch_start in range(0, count, self.BULK_CREATE_LIMIT):
            batch_size = min(self.BULK_CREATE_LIMIT, count - batch_start)

            issues_data = {"issueUpdates": []}

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

            if batch_start + batch_size < count:
                time.sleep(0.5)

        self.created_issues = issue_keys
        return issue_keys

    async def create_issues_bulk_async(self, count: int, project_key: str, project_id: str) -> List[str]:
        """Create issues in bulk batches asynchronously.

        This method is designed for parallel execution across multiple projects.

        Args:
            count: Number of issues to create
            project_key: The project key (e.g., 'PERF1')
            project_id: The project ID

        Returns:
            List of created issue keys
        """
        self.logger.info(f"Creating {count} issues in project {project_key} (async batches of {self.BULK_CREATE_LIMIT})...")

        if not project_id and not self.dry_run:
            self.logger.error(f"Cannot create issues without valid project ID for {project_key}")
            return []

        issue_keys = []
        batches_created = 0
        total_batches = (count + self.BULK_CREATE_LIMIT - 1) // self.BULK_CREATE_LIMIT

        for batch_start in range(0, count, self.BULK_CREATE_LIMIT):
            batch_size = min(self.BULK_CREATE_LIMIT, count - batch_start)

            issues_data = {"issueUpdates": []}

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
                self.logger.debug(f"DRY RUN: Would create batch of {batch_size} issues in {project_key}")
                for i in range(batch_size):
                    issue_keys.append(f"{project_key}-{batch_start + i + 1}")
            else:
                success, result = await self._api_call_async('POST', 'issue/bulk', data=issues_data)

                if success and result:
                    created = result.get('issues', [])
                    for issue in created:
                        key = issue.get('key')
                        if key:
                            issue_keys.append(key)

            batches_created += 1
            if batches_created % 10 == 0 or batches_created == total_batches:
                self.logger.info(f"  {project_key}: {len(issue_keys)}/{count} issues created ({batches_created}/{total_batches} batches)")

        return issue_keys

    def _init_attachment_pool(self) -> None:
        """Initialize the pool of pre-generated attachments for reuse.

        Creates a pool of small (1-5 KB) attachments that are reused across
        all attachment uploads. This significantly improves performance by:
        1. Avoiding repeated random content generation
        2. Using small file sizes to minimize upload time
        """
        if self._attachment_pool is not None:
            return

        self.logger.info(f"Pre-generating {self.ATTACHMENT_POOL_SIZE} attachments (1-5 KB each)...")
        self._attachment_pool = []

        for i in range(self.ATTACHMENT_POOL_SIZE):
            content, filename = self._generate_small_file(i)
            self._attachment_pool.append((content, filename))

        total_size = sum(len(c) for c, _ in self._attachment_pool)
        self.logger.info(f"Attachment pool ready: {self.ATTACHMENT_POOL_SIZE} files, {total_size / 1024:.1f} KB total")

    def _generate_small_file(self, index: int) -> Tuple[bytes, str]:
        """Generate a small file (1-5 KB) for the attachment pool.

        Args:
            index: Index in the pool (used for unique filename)

        Returns (content_bytes, filename)
        """
        size_bytes = random.randint(1 * 1024, 5 * 1024)  # 1-5 KB

        file_types = [
            ('txt', 'text/plain'),
            ('json', 'application/json'),
            ('csv', 'text/csv'),
            ('log', 'text/plain'),
        ]
        ext, _ = random.choice(file_types)

        if ext == 'json':
            data = {
                'id': index,
                'name': self.generate_random_text(2, 5),
                'description': self.generate_random_text(10, 30),
                'values': [random.randint(1, 100) for _ in range(10)],
                'prefix': self.prefix
            }
            content = json.dumps(data, indent=2).encode('utf-8')
            if len(content) < size_bytes:
                padding = ''.join(random.choices(string.ascii_letters + string.digits, k=size_bytes - len(content)))
                content = content[:-1] + f', "padding": "{padding}"}}'.encode('utf-8')
        elif ext == 'csv':
            lines = ['id,name,value,data']
            while len('\n'.join(lines).encode('utf-8')) < size_bytes:
                lines.append(f'{random.randint(1,10000)},{self.generate_random_text(1,3)},{random.randint(1,1000)},data')
            content = '\n'.join(lines).encode('utf-8')
        else:
            words = []
            while len(' '.join(words).encode('utf-8')) < size_bytes:
                words.append(self.generate_random_text(5, 20))
            content = ' '.join(words).encode('utf-8')

        content = content[:size_bytes]
        filename = f"{self.prefix}_file_{index:04d}.{ext}"
        return content, filename

    def get_pooled_attachment(self) -> Tuple[bytes, str]:
        """Get a random attachment from the pre-generated pool.

        Initializes the pool on first call. Returns a tuple of (content, filename).
        The filename is modified with a random suffix to ensure uniqueness in Jira.
        """
        self._init_attachment_pool()

        content, base_filename = random.choice(self._attachment_pool)

        # Add random suffix to filename to make it unique per upload
        name, ext = base_filename.rsplit('.', 1)
        unique_filename = f"{name}_{random.randint(10000, 99999)}.{ext}"

        return content, unique_filename

    def generate_random_file(self, min_size_kb: int = 1, max_size_kb: int = 100) -> Tuple[bytes, str]:
        """Generate random file content with a random size.

        DEPRECATED: Use get_pooled_attachment() instead for better performance.

        Returns (content_bytes, filename)
        """
        size_bytes = random.randint(min_size_kb * 1024, max_size_kb * 1024)

        file_types = [
            ('txt', 'text/plain'),
            ('json', 'application/json'),
            ('csv', 'text/csv'),
            ('log', 'text/plain'),
        ]
        ext, _ = random.choice(file_types)

        if ext == 'json':
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
            if len(content) < size_bytes:
                padding = ''.join(random.choices(string.ascii_letters + string.digits, k=size_bytes - len(content)))
                content = content[:-1] + f', "padding": "{padding}"}}'.encode('utf-8')
        elif ext == 'csv':
            lines = ['id,name,value,timestamp']
            while len('\n'.join(lines).encode('utf-8')) < size_bytes:
                lines.append(f'{random.randint(1,10000)},{self.generate_random_text(1,3)},{random.randint(1,1000)},{datetime.now().isoformat()}')
            content = '\n'.join(lines).encode('utf-8')
        else:
            words = []
            while len(' '.join(words).encode('utf-8')) < size_bytes:
                words.append(self.generate_random_text(5, 20))
            content = ' '.join(words).encode('utf-8')

        content = content[:size_bytes]
        filename = f"{self.prefix}_attachment_{random.randint(1000, 9999)}.{ext}"
        return content, filename

    def add_attachment(self, issue_key: str, content: bytes, filename: str) -> bool:
        """Add an attachment to an issue."""
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would attach {filename} ({len(content)} bytes) to {issue_key}")
            return True

        url = f"{self.jira_url}/rest/api/3/issue/{issue_key}/attachments"
        max_retries = 5

        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    url,
                    files={'file': (filename, content)},
                    headers={'X-Atlassian-Token': 'no-check'},
                    auth=(self.email, self.api_token),
                    timeout=60
                )

                if response.status_code == 429:
                    retry_after = float(response.headers.get('Retry-After', 30))
                    self.logger.warning(f"Rate limited. Waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue  # Retry within the loop

                response.raise_for_status()
                return True

            except Exception as e:
                is_expected = False
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_text = e.response.text.lower()
                        is_expected = 'already exists' in error_text
                    except Exception:
                        pass

                if is_expected:
                    self.logger.debug(f"Attachment already exists: {filename}")
                    return False

                self.logger.error(f"Failed to attach {filename} to {issue_key}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return False

        return False

    def create_attachments(self, issue_keys: List[str], count: int) -> int:
        """Create attachments on issues using pre-generated pool."""
        # Initialize pool (logs info about pool)
        self._init_attachment_pool()

        self.logger.info(f"Creating {count} attachments (using pooled 1-5 KB files)...")

        created = 0
        failed = 0
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            content, filename = self.get_pooled_attachment()

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
        auth = aiohttp.BasicAuth(self.email, self.api_token)

        # Ensure semaphore is initialized
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)

        max_retries = 5
        async with self._semaphore:
            for attempt in range(max_retries):
                # Wait for any global cooldown before making request
                await self._wait_for_cooldown()

                try:
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
                                delay = await self._handle_rate_limit_async(response.status, dict(response.headers))
                                await asyncio.sleep(delay)
                                continue  # Retry within the loop

                            if response.status >= 400:
                                error_text = await response.text()
                                if 'already exists' not in error_text.lower():
                                    self.logger.error(f"Failed to attach {filename} to {issue_key}: {response.status} - {error_text[:200]}")
                                return False

                            return True

                except aiohttp.ClientError as e:
                    self.logger.error(f"Failed to attach {filename} to {issue_key}: ClientError - {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    return False
                except Exception as e:
                    self.logger.error(f"Failed to attach {filename} to {issue_key}: {type(e).__name__} - {e}")
                    return False

        return False

    async def create_attachments_async(self, issue_keys: List[str], count: int) -> int:
        """Create attachments on issues concurrently using pre-generated pool."""
        # Initialize pool (logs info about pool)
        self._init_attachment_pool()

        self.logger.info(f"Creating {count} attachments (concurrency: {self.concurrency}, using pooled 1-5 KB files)...")

        tasks = []
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            content, filename = self.get_pooled_attachment()
            tasks.append(self.add_attachment_async(issue_key, content, filename))

        created = 0
        failed = 0
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i:i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1
                elif isinstance(result, Exception):
                    self.logger.error(f"Attachment failed with exception: {type(result).__name__} - {result}")
                    failed += 1
                else:
                    failed += 1
            self.logger.info(f"Created {created}/{count} attachments ({failed} failed)")

        self.logger.info(f"Attachments complete: {created} added, {failed} failed")
        return created
