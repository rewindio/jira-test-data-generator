"""
Issue items generation module.

Handles creation of issue-related items: comments, worklogs, links,
watchers, votes, properties, and remote links.
"""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .base import JiraAPIClient


class IssueItemsGenerator(JiraAPIClient):
    """Generates issue-related items for Jira."""

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
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def set_run_id(self, run_id: str):
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    # ========== COMMENTS ==========

    def create_comments(self, issue_keys: List[str], count: int) -> int:
        """Create comments on issues"""
        self.logger.info(f"Creating {count} comments...")

        created = 0
        for _ in range(count):
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

            response = self._api_call('POST', f'issue/{issue_key}/comment', data=comment_data)
            if response:
                created += 1

            if created % 10 == 0:
                self.logger.info(f"Created {created}/{count} comments")
                time.sleep(0.2)

        return created

    async def create_comments_async(self, issue_keys: List[str], count: int) -> int:
        """Create comments on issues concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Creating {count} comments (concurrency: {self.concurrency})...")

        created = 0
        batch_size = self.concurrency * 2

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
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

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1

            self.logger.info(f"Created {created}/{count} comments")

        return created

    # ========== WORKLOGS ==========

    def create_worklogs(self, issue_keys: List[str], count: int) -> int:
        """Create worklogs on issues"""
        self.logger.info(f"Creating {count} worklogs...")

        created = 0
        for _ in range(count):
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

            response = self._api_call('POST', f'issue/{issue_key}/worklog', data=worklog_data)
            if response:
                created += 1

            if created % 10 == 0:
                self.logger.info(f"Created {created}/{count} worklogs")
                time.sleep(0.2)

        return created

    async def create_worklogs_async(self, issue_keys: List[str], count: int) -> int:
        """Create worklogs on issues concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Creating {count} worklogs (concurrency: {self.concurrency})...")

        created = 0
        batch_size = self.concurrency * 2

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
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

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1

            self.logger.info(f"Created {created}/{count} worklogs")

        return created

    # ========== ISSUE LINKS ==========

    def get_link_types(self) -> List[Dict]:
        """Get available issue link types"""
        if self.dry_run:
            return [{'name': 'Blocks'}, {'name': 'Relates'}]

        response = self._api_call('GET', 'issueLinkType')
        if response:
            return response.json().get('issueLinkTypes', [])
        return []

    def create_issue_links(self, issue_keys: List[str], count: int) -> int:
        """Create issue links"""
        self.logger.info(f"Creating {count} issue links...")

        if len(issue_keys) < 2:
            self.logger.warning("Need at least 2 issues to create links")
            return 0

        link_types = self.get_link_types()
        if not link_types:
            self.logger.warning("No link types available")
            return 0

        created = 0
        for _ in range(count):
            inward_issue = random.choice(issue_keys)
            outward_issue = random.choice([k for k in issue_keys if k != inward_issue])
            link_type = random.choice(link_types)

            link_data = {
                "type": {"name": link_type['name']},
                "inwardIssue": {"key": inward_issue},
                "outwardIssue": {"key": outward_issue}
            }

            response = self._api_call('POST', 'issueLink', data=link_data)
            if response is not None or self.dry_run:
                created += 1

            if created % 10 == 0:
                self.logger.info(f"Created {created}/{count} issue links")
                time.sleep(0.2)

        return created

    async def create_issue_links_async(self, issue_keys: List[str], count: int) -> int:
        """Create issue links concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Creating {count} issue links (concurrency: {self.concurrency})...")

        if len(issue_keys) < 2:
            self.logger.warning("Need at least 2 issues to create links")
            return 0

        link_types = self.get_link_types()
        if not link_types:
            self.logger.warning("No link types available")
            return 0

        created = 0
        batch_size = self.concurrency * 2

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
                inward_issue = random.choice(issue_keys)
                outward_issue = random.choice([k for k in issue_keys if k != inward_issue])
                link_type = random.choice(link_types)

                link_data = {
                    "type": {"name": link_type['name']},
                    "inwardIssue": {"key": inward_issue},
                    "outwardIssue": {"key": outward_issue}
                }
                tasks.append(self._api_call_async('POST', 'issueLink', data=link_data))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1

            self.logger.info(f"Created {created}/{count} issue links")

        return created

    # ========== WATCHERS ==========

    def add_watchers(self, issue_keys: List[str], count: int, user_ids: List[str]) -> int:
        """Add watchers to issues"""
        self.logger.info(f"Adding {count} watchers...")

        if not user_ids:
            self.logger.warning("No users available for watchers")
            return 0

        created = 0
        failed = 0
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            watcher_id = random.choice(user_ids)

            response = self._api_call('POST', f'issue/{issue_key}/watchers', data=watcher_id)
            if response is not None or self.dry_run:
                created += 1
            else:
                failed += 1

            if (created + failed) % 10 == 0:
                self.logger.info(f"Added {created}/{count} watchers ({failed} failed)")
                time.sleep(0.2)

        self.logger.info(f"Watchers complete: {created} added, {failed} failed")
        return created

    async def add_watchers_async(self, issue_keys: List[str], count: int, user_ids: List[str]) -> int:
        """Add watchers to issues concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Adding {count} watchers (concurrency: {self.concurrency})...")

        if not user_ids:
            self.logger.warning("No users available for watchers")
            return 0

        created = 0
        failed = 0
        batch_size = self.concurrency * 2

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
                issue_key = random.choice(issue_keys)
                watcher_id = random.choice(user_ids)
                tasks.append(self._api_call_async('POST', f'issue/{issue_key}/watchers', data=watcher_id))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
                else:
                    failed += 1

            self.logger.info(f"Added {created}/{count} watchers ({failed} failed)")

        self.logger.info(f"Watchers complete: {created} added, {failed} failed")
        return created

    # ========== VOTES ==========

    def add_votes(self, issue_keys: List[str], count: int) -> int:
        """Add votes to issues.

        Note: Each user can only vote once per issue. This adds votes from the
        current authenticated user to random issues.
        """
        self.logger.info(f"Adding {count} votes...")

        # Votes are per-user, so we can only add one vote per issue from this user
        # Shuffle issue keys to randomize which issues get votes
        issues_to_vote = random.sample(issue_keys, min(count, len(issue_keys)))

        created = 0
        failed = 0
        for issue_key in issues_to_vote:
            response = self._api_call('POST', f'issue/{issue_key}/votes')
            if response is not None or self.dry_run:
                created += 1
            else:
                failed += 1

            if (created + failed) % 10 == 0:
                self.logger.info(f"Added {created}/{count} votes ({failed} failed)")
                time.sleep(0.2)

        self.logger.info(f"Votes complete: {created} added, {failed} failed")
        return created

    async def add_votes_async(self, issue_keys: List[str], count: int) -> int:
        """Add votes to issues concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Adding {count} votes (concurrency: {self.concurrency})...")

        issues_to_vote = random.sample(issue_keys, min(count, len(issue_keys)))
        total_votes = len(issues_to_vote)

        created = 0
        failed = 0
        batch_size = self.concurrency * 2

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, total_votes, batch_size):
            batch_end = min(batch_start + batch_size, total_votes)
            batch_issues = issues_to_vote[batch_start:batch_end]

            # Generate tasks for this batch only
            tasks = []
            for issue_key in batch_issues:
                tasks.append(self._api_call_async('POST', f'issue/{issue_key}/votes'))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
                else:
                    failed += 1

            self.logger.info(f"Added {created}/{total_votes} votes ({failed} failed)")

        self.logger.info(f"Votes complete: {created} added, {failed} failed")
        return created

    # ========== ISSUE PROPERTIES ==========

    def create_issue_properties(self, issue_keys: List[str], count: int) -> int:
        """Create custom properties on issues.

        Issue properties are key-value pairs that can store arbitrary JSON data.
        """
        self.logger.info(f"Creating {count} issue properties...")

        created = 0
        failed = 0
        for i in range(count):
            issue_key = random.choice(issue_keys)
            property_key = f"{self.prefix.lower()}_property_{i + 1}"

            # Generate random property data
            property_data = {
                "generatedBy": "jira-test-data-generator",
                "runId": self.run_id,
                "timestamp": datetime.now().isoformat(),
                "randomValue": random.randint(1, 10000),
                "category": random.choice(["alpha", "beta", "gamma", "delta"]),
                "metadata": {
                    "index": i + 1,
                    "description": self.generate_random_text(5, 15)
                }
            }

            # Note: Properties use PUT, not POST
            response = self._api_call('PUT', f'issue/{issue_key}/properties/{property_key}', data=property_data)
            if response is not None or self.dry_run:
                created += 1
            else:
                failed += 1

            if (created + failed) % 10 == 0:
                self.logger.info(f"Created {created}/{count} properties ({failed} failed)")
                time.sleep(0.2)

        self.logger.info(f"Properties complete: {created} created, {failed} failed")
        return created

    async def create_issue_properties_async(self, issue_keys: List[str], count: int) -> int:
        """Create custom properties on issues concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Creating {count} issue properties (concurrency: {self.concurrency})...")

        created = 0
        failed = 0
        batch_size = self.concurrency * 2
        property_index = 0

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
                property_index += 1
                issue_key = random.choice(issue_keys)
                property_key = f"{self.prefix.lower()}_property_{property_index}"

                property_data = {
                    "generatedBy": "jira-test-data-generator",
                    "runId": self.run_id,
                    "timestamp": datetime.now().isoformat(),
                    "randomValue": random.randint(1, 10000),
                    "category": random.choice(["alpha", "beta", "gamma", "delta"]),
                    "metadata": {
                        "index": property_index,
                        "description": self.generate_random_text(5, 15)
                    }
                }
                tasks.append(self._api_call_async('PUT', f'issue/{issue_key}/properties/{property_key}', data=property_data))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
                else:
                    failed += 1

            self.logger.info(f"Created {created}/{count} properties ({failed} failed)")

        self.logger.info(f"Properties complete: {created} created, {failed} failed")
        return created

    # ========== REMOTE LINKS ==========

    def create_remote_links(self, issue_keys: List[str], count: int) -> int:
        """Create remote links on issues.

        Remote links connect Jira issues to external URLs/resources.
        """
        self.logger.info(f"Creating {count} remote links...")

        # Sample external URLs to link to
        external_urls = [
            "https://confluence.example.com/display/DOC/Page",
            "https://github.com/org/repo/pull/123",
            "https://github.com/org/repo/issues/456",
            "https://docs.example.com/api/v1/",
            "https://monitoring.example.com/dashboard/1",
            "https://ci.example.com/job/build/789",
            "https://wiki.example.com/knowledge-base/article-1",
        ]

        created = 0
        failed = 0
        for i in range(count):
            issue_key = random.choice(issue_keys)
            url = random.choice(external_urls)

            remote_link_data = {
                "globalId": f"{self.run_id}-remote-link-{i + 1}",
                "application": {
                    "type": "com.test.data.generator",
                    "name": "Test Data Generator"
                },
                "relationship": random.choice(["relates to", "is documented by", "is tested by"]),
                "object": {
                    "url": url,
                    "title": f"{self.prefix} Remote Link {i + 1}",
                    "summary": self.generate_random_text(5, 15),
                    "icon": {
                        "url16x16": "https://example.com/icon.png",
                        "title": "External Resource"
                    }
                }
            }

            response = self._api_call('POST', f'issue/{issue_key}/remotelink', data=remote_link_data)
            if response is not None or self.dry_run:
                created += 1
            else:
                failed += 1

            if (created + failed) % 10 == 0:
                self.logger.info(f"Created {created}/{count} remote links ({failed} failed)")
                time.sleep(0.2)

        self.logger.info(f"Remote links complete: {created} created, {failed} failed")
        return created

    async def create_remote_links_async(self, issue_keys: List[str], count: int) -> int:
        """Create remote links on issues concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Creating {count} remote links (concurrency: {self.concurrency})...")

        external_urls = [
            "https://confluence.example.com/display/DOC/Page",
            "https://github.com/org/repo/pull/123",
            "https://github.com/org/repo/issues/456",
            "https://docs.example.com/api/v1/",
            "https://monitoring.example.com/dashboard/1",
            "https://ci.example.com/job/build/789",
            "https://wiki.example.com/knowledge-base/article-1",
        ]

        created = 0
        failed = 0
        batch_size = self.concurrency * 2
        link_index = 0

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
                link_index += 1
                issue_key = random.choice(issue_keys)
                url = random.choice(external_urls)

                remote_link_data = {
                    "globalId": f"{self.run_id}-remote-link-{link_index}",
                    "application": {
                        "type": "com.test.data.generator",
                        "name": "Test Data Generator"
                    },
                    "relationship": random.choice(["relates to", "is documented by", "is tested by"]),
                    "object": {
                        "url": url,
                        "title": f"{self.prefix} Remote Link {link_index}",
                        "summary": self.generate_random_text(5, 15),
                        "icon": {
                            "url16x16": "https://example.com/icon.png",
                            "title": "External Resource"
                        }
                    }
                }
                tasks.append(self._api_call_async('POST', f'issue/{issue_key}/remotelink', data=remote_link_data))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
                else:
                    failed += 1

            self.logger.info(f"Created {created}/{count} remote links ({failed} failed)")

        self.logger.info(f"Remote links complete: {created} created, {failed} failed")
        return created
