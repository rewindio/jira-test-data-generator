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

    def generate_random_file(self, min_size_kb: int = 1, max_size_kb: int = 100) -> Tuple[bytes, str]:
        """Generate random file content with a random size.

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
        """Create attachments on issues concurrently"""
        self.logger.info(f"Creating {count} attachments (concurrency: {self.concurrency})...")

        tasks = []
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            content, filename = self.generate_random_file(min_size_kb=1, max_size_kb=500)
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
