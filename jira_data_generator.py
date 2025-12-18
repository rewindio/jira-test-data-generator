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
import logging
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from generators.base import JiraAPIClient, RateLimitState
from generators.projects import ProjectGenerator
from generators.issues import IssueGenerator
from generators.issue_items import IssueItemsGenerator
from generators.agile import AgileGenerator
from generators.filters import FilterGenerator
from generators.custom_fields import CustomFieldGenerator
from generators.checkpoint import CheckpointManager
from generators.benchmark import BenchmarkTracker


def load_multipliers_from_csv(csv_path: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """Load multipliers from CSV file.

    Returns dict keyed by size bucket (small, medium, large, xlarge),
    with each value being a dict of item_type -> multiplier.
    """
    if csv_path is None:
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
                        pass

    return multipliers


# Load multipliers from CSV file
MULTIPLIERS = load_multipliers_from_csv()


class JiraDataGenerator:
    """Orchestrates all Jira test data generation using modular generators."""

    def __init__(
        self,
        jira_url: str,
        email: str,
        api_token: str,
        prefix: str,
        size_bucket: str = 'small',
        dry_run: bool = False,
        concurrency: int = 5,
        checkpoint_manager: Optional[CheckpointManager] = None,
        request_delay: float = 0.0,
        issues_only: bool = False,
        project_override: Optional[int] = None
    ):
        self.jira_url = jira_url.rstrip('/')
        self.email = email
        self.api_token = api_token
        self.prefix = prefix
        self.size_bucket = size_bucket.lower()
        self.dry_run = dry_run
        self.concurrency = concurrency
        self.checkpoint = checkpoint_manager
        self.request_delay = request_delay
        self.issues_only = issues_only
        self.project_override = project_override

        self.logger = logging.getLogger(__name__)

        # Generate unique label for this run (may be overridden by checkpoint)
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Validate size bucket
        if self.size_bucket not in MULTIPLIERS:
            raise ValueError(f"Invalid size bucket. Must be one of: {', '.join(MULTIPLIERS.keys())}")

        # Initialize benchmark tracker
        self.benchmark = BenchmarkTracker()

        # Initialize modular generators
        self._init_generators()

    def _init_generators(self):
        """Initialize all generator modules."""
        common_args = {
            'jira_url': self.jira_url,
            'email': self.email,
            'api_token': self.api_token,
            'dry_run': self.dry_run,
            'concurrency': self.concurrency,
            'benchmark': self.benchmark,
            'request_delay': self.request_delay
        }

        self.project_gen = ProjectGenerator(prefix=self.prefix, checkpoint=self.checkpoint, **common_args)
        self.issue_gen = IssueGenerator(prefix=self.prefix, checkpoint=self.checkpoint, **common_args)
        self.issue_items_gen = IssueItemsGenerator(prefix=self.prefix, checkpoint=self.checkpoint, **common_args)
        self.agile_gen = AgileGenerator(prefix=self.prefix, **common_args)
        self.filter_gen = FilterGenerator(prefix=self.prefix, **common_args)
        self.custom_field_gen = CustomFieldGenerator(prefix=self.prefix, **common_args)

        # Set consistent run_id across generators
        self.issue_gen.run_id = self.run_id
        self.issue_items_gen.set_run_id(self.run_id)
        self.filter_gen.set_run_id(self.run_id)
        self.project_gen.set_run_id(self.run_id)
        self.custom_field_gen.set_run_id(self.run_id)

    def calculate_counts(self, num_issues: int) -> Dict[str, int]:
        """Calculate item counts based on multipliers and target issue count.

        If issues_only is True, only project and issue counts are calculated;
        all associated data (comments, worklogs, etc.) is set to 0.

        If project_override is set, uses that instead of the calculated project count.
        """
        multipliers = MULTIPLIERS[self.size_bucket]
        counts = {}

        # Items to include when issues_only is True
        # These are the minimum required to create issues
        issues_only_items = {'project', 'issue'}

        for item_type, multiplier in multipliers.items():
            if self.issues_only and item_type not in issues_only_items:
                counts[item_type] = 0
            else:
                raw_count = num_issues * multiplier
                counts[item_type] = max(1, math.ceil(raw_count))

        # Apply project override if specified
        if self.project_override is not None:
            counts['project'] = max(1, self.project_override)

        return counts

    # ========== Checkpoint Helper Methods ==========

    def _init_or_resume_checkpoint(
        self,
        num_issues: int,
        counts: Dict[str, int],
        async_mode: bool
    ) -> bool:
        """Initialize checkpoint for new run or prepare for resume.

        Returns True if resuming from existing checkpoint.
        """
        if not self.checkpoint:
            return False

        # Check if we're resuming (checkpoint was pre-loaded)
        if self.checkpoint.checkpoint is not None:
            # Use run_id from checkpoint
            self.run_id = self.checkpoint.checkpoint.run_id
            # Update generators with the restored run_id
            self.issue_gen.run_id = self.run_id
            self.issue_items_gen.set_run_id(self.run_id)
            self.filter_gen.set_run_id(self.run_id)
            self.project_gen.set_run_id(self.run_id)

            self.logger.info("\n" + "=" * 60)
            self.logger.info("RESUMING FROM CHECKPOINT")
            self.logger.info("=" * 60)
            self.logger.info(self.checkpoint.get_resume_summary())
            self.logger.info("=" * 60 + "\n")
            return True

        # Initialize new checkpoint
        self.checkpoint.initialize(
            run_id=self.run_id,
            size=self.size_bucket,
            target_issue_count=num_issues,
            jira_url=self.jira_url,
            async_mode=async_mode,
            concurrency=self.concurrency,
            counts=counts
        )
        return False

    def _is_phase_complete(self, phase_name: str) -> bool:
        """Check if a phase is complete in checkpoint."""
        if not self.checkpoint:
            return False
        return self.checkpoint.is_phase_complete(phase_name)

    def _start_phase(self, phase_name: str) -> None:
        """Mark a phase as started in checkpoint."""
        if self.checkpoint:
            self.checkpoint.start_phase(phase_name)

    def _complete_phase(self, phase_name: str) -> None:
        """Mark a phase as complete in checkpoint."""
        if self.checkpoint:
            self.checkpoint.complete_phase(phase_name)

    def _get_remaining_count(self, phase_name: str, default: int) -> int:
        """Get remaining count for a phase, or default if no checkpoint."""
        if not self.checkpoint:
            return default
        remaining = self.checkpoint.get_remaining_count(phase_name)
        return remaining if remaining > 0 else default

    def _create_or_resume_projects(
        self,
        counts: Dict[str, int],
        resuming: bool
    ) -> List[Dict]:
        """Create projects or restore from checkpoint."""
        if resuming and self.checkpoint and self.checkpoint.checkpoint:
            # Restore projects from checkpoint
            cp = self.checkpoint.checkpoint
            if cp.project_keys:
                self.logger.info(f"Restored {len(cp.project_keys)} projects from checkpoint")
                return [{'key': k, 'id': cp.project_ids.get(k, '')} for k in cp.project_keys]

        # Create new projects
        if not self._is_phase_complete("projects"):
            self._start_phase("projects")
            num_projects = counts.get('project', 1)
            projects = self.project_gen.create_projects(num_projects)

            if projects and self.checkpoint:
                self.checkpoint.set_projects(projects)

            self._complete_phase("projects")
            return projects

        # Projects phase complete but no keys in checkpoint - shouldn't happen
        self.logger.warning("Projects phase marked complete but no project keys found")
        return []

    def generate_all(self, num_issues: int):
        """Generate all test data based on multipliers (synchronous mode)."""
        self._log_header(num_issues, async_mode=False)
        counts = self.calculate_counts(num_issues)
        self._log_planned_counts(num_issues, counts)

        # Start overall benchmark
        self.benchmark.start_overall()

        # Initialize or resume from checkpoint
        resuming = self._init_or_resume_checkpoint(num_issues, counts, async_mode=False)

        # Create custom fields first (configuration items)
        if not self._is_phase_complete("custom_fields"):
            if counts.get('issue_field', 0) > 0:
                self._start_phase("custom_fields")
                self.benchmark.start_phase("custom_fields", counts['issue_field'])
                custom_fields = self.custom_field_gen.create_custom_fields(counts['issue_field'])
                self.benchmark.end_phase("custom_fields", len(custom_fields))
                if self.checkpoint:
                    self.checkpoint.update_phase_count("custom_fields", len(custom_fields))
                self._complete_phase("custom_fields")

        # Create project categories (projects can be assigned to them)
        categories = []
        if not self._is_phase_complete("project_categories"):
            if counts.get('project_category', 0) > 0:
                self._start_phase("project_categories")
                self.benchmark.start_phase("project_categories", counts['project_category'])
                categories = self.project_gen.create_categories(counts['project_category'])
                self.benchmark.end_phase("project_categories", len(categories))
                if self.checkpoint:
                    self.checkpoint.set_categories([c['id'] for c in categories])
                self._complete_phase("project_categories")
        elif self.checkpoint and self.checkpoint.checkpoint:
            # Load existing categories from checkpoint
            category_ids = self.checkpoint.checkpoint.category_ids
            categories = [{'id': cid} for cid in category_ids]

        # Create projects
        self.benchmark.start_phase("projects", counts.get('project', 1))
        projects = self._create_or_resume_projects(counts, resuming)
        self.benchmark.end_phase("projects", len(projects) if projects else 0)
        if not projects:
            self.logger.error("Failed to create projects. Aborting.")
            return

        project_keys = [p['key'] for p in projects]

        # Assign projects to categories if we have both
        if categories and projects and not resuming:
            self._assign_projects_to_categories(project_keys, categories)

        # Create project properties
        if not self._is_phase_complete("project_properties"):
            if counts.get('project_property', 0) > 0:
                self._start_phase("project_properties")
                self.benchmark.start_phase("project_properties", counts['project_property'])
                remaining = self._get_remaining_count("project_properties", counts.get('project_property', 0))
                created = 0
                if remaining > 0:
                    created = self.project_gen.create_project_properties(project_keys, remaining)
                self.benchmark.end_phase("project_properties", created if created else remaining)
                self._complete_phase("project_properties")

        # Create issues distributed across projects
        self.benchmark.start_phase("issues", num_issues)
        all_issue_keys = self._create_issues_across_projects(projects, num_issues, counts)
        self.benchmark.end_phase("issues", len(all_issue_keys))

        if not all_issue_keys:
            self.logger.error("Failed to create any issues. Aborting.")
            return

        # Create issue-dependent items
        self._create_issue_items_sync(all_issue_keys, project_keys, counts)

        # Create agile items (boards, sprints)
        self._create_agile_items_sync(project_keys, all_issue_keys, counts)

        # Create filters and dashboards
        self._create_filters_sync(project_keys, counts)

        # End overall benchmark
        self.benchmark.end_overall()

        # Finalize checkpoint
        if self.checkpoint:
            self.checkpoint.finalize()

        self._log_footer(projects, all_issue_keys, num_issues)

    async def generate_all_async(self, num_issues: int):
        """Generate all test data using async for high-volume items."""
        self._log_header(num_issues, async_mode=True)
        counts = self.calculate_counts(num_issues)
        self._log_planned_counts(num_issues, counts)

        # Start overall benchmark
        self.benchmark.start_overall()

        # Initialize or resume from checkpoint
        resuming = self._init_or_resume_checkpoint(num_issues, counts, async_mode=True)

        # Create custom fields first (configuration items, async for high volume)
        if not self._is_phase_complete("custom_fields"):
            if counts.get('issue_field', 0) > 0:
                self._start_phase("custom_fields")
                self.benchmark.start_phase("custom_fields", counts['issue_field'])
                custom_fields = await self.custom_field_gen.create_custom_fields_async(counts['issue_field'])
                self.benchmark.end_phase("custom_fields", len(custom_fields))
                if self.checkpoint:
                    self.checkpoint.update_phase_count("custom_fields", len(custom_fields))
                self._complete_phase("custom_fields")

        # Create project categories (projects can be assigned to them)
        categories = []
        if not self._is_phase_complete("project_categories"):
            if counts.get('project_category', 0) > 0:
                self._start_phase("project_categories")
                self.benchmark.start_phase("project_categories", counts['project_category'])
                categories = self.project_gen.create_categories(counts['project_category'])
                self.benchmark.end_phase("project_categories", len(categories))
                if self.checkpoint:
                    self.checkpoint.set_categories([c['id'] for c in categories])
                self._complete_phase("project_categories")
        elif self.checkpoint and self.checkpoint.checkpoint:
            # Load existing categories from checkpoint
            category_ids = self.checkpoint.checkpoint.category_ids
            categories = [{'id': cid} for cid in category_ids]

        # Create projects (sequential - usually few)
        self.benchmark.start_phase("projects", counts.get('project', 1))
        projects = self._create_or_resume_projects(counts, resuming)
        self.benchmark.end_phase("projects", len(projects) if projects else 0)
        if not projects:
            self.logger.error("Failed to create projects. Aborting.")
            return

        project_keys = [p['key'] for p in projects]

        # Assign projects to categories if we have both
        if categories and projects and not resuming:
            self._assign_projects_to_categories(project_keys, categories)

        # Create project properties (async for high volume at 18M scale)
        if not self._is_phase_complete("project_properties"):
            if counts.get('project_property', 0) > 0:
                self._start_phase("project_properties")
                self.benchmark.start_phase("project_properties", counts['project_property'])
                remaining = self._get_remaining_count("project_properties", counts.get('project_property', 0))
                created = 0
                if remaining > 0:
                    created = await self.project_gen.create_project_properties_async(project_keys, remaining)
                self.benchmark.end_phase("project_properties", created if created else remaining)
                self._complete_phase("project_properties")

        # Create issues (bulk API - already optimized)
        self.benchmark.start_phase("issues", num_issues)
        all_issue_keys = await self._create_issues_across_projects_async(projects, num_issues, counts)
        self.benchmark.end_phase("issues", len(all_issue_keys))

        if not all_issue_keys:
            self.logger.error("Failed to create any issues. Aborting.")
            return

        # Create issue-dependent items using async
        try:
            await self._create_issue_items_async(all_issue_keys, project_keys, counts)

            # Create agile items (boards sequential due to filter dependency, sprints async)
            await self._create_agile_items_async(project_keys, all_issue_keys, counts)

            # Create filters and dashboards (async for high volume at 18M scale)
            await self._create_filters_async(project_keys, counts)

        finally:
            # Clean up async sessions
            await self.issue_gen._close_async_session()
            await self.issue_items_gen._close_async_session()
            await self.project_gen._close_async_session()
            await self.agile_gen._close_async_session()
            await self.filter_gen._close_async_session()
            await self.custom_field_gen._close_async_session()

        # End overall benchmark
        self.benchmark.end_overall()

        # Finalize checkpoint
        if self.checkpoint:
            self.checkpoint.finalize()

        self._log_footer(projects, all_issue_keys, num_issues)

    def _create_issues_across_projects(
        self,
        projects: List[Dict],
        num_issues: int,
        counts: Dict[str, int]
    ) -> List[str]:
        """Create issues distributed across projects."""
        # Check if issues phase is complete
        if self._is_phase_complete("issues"):
            # Restore issue keys from checkpoint or reconstruct them
            if self.checkpoint and self.checkpoint.checkpoint:
                issue_keys = self.checkpoint.checkpoint.issue_keys
                if issue_keys:
                    self.logger.info(f"Restored {len(issue_keys)} issue keys from checkpoint")
                    return issue_keys
                # If we don't have keys but have counts, we need to query Jira
                # For now, reconstruct based on known counts (assumes sequential keys)
                total = self.checkpoint.get_total_issues_created()
                self.logger.info(f"Issues phase complete ({total} created). Reconstructing keys from Jira...")
                return self._fetch_issue_keys_from_jira()

        self._start_phase("issues")

        # Calculate how many issues each project needs
        if self.checkpoint:
            issues_needed = self.checkpoint.get_issues_needed_per_project(projects, num_issues)
        else:
            issues_per_project = max(1, num_issues // len(projects))
            remainder = num_issues % len(projects)
            issues_needed = {
                p['key']: issues_per_project + (1 if i < remainder else 0)
                for i, p in enumerate(projects)
            }

        all_issue_keys = []

        # Restore existing issue keys from checkpoint
        if self.checkpoint and self.checkpoint.checkpoint:
            all_issue_keys = list(self.checkpoint.checkpoint.issue_keys)

        for idx, project in enumerate(projects):
            project_key = project['key']
            project_issue_count = issues_needed.get(project_key, 0)

            if project_issue_count <= 0:
                self.logger.info(f"Skipping project {project_key} - no issues needed")
                continue

            # Set project context
            self.issue_gen.set_project_context(project_key, project['id'])

            self.logger.info(f"\nCreating {project_issue_count} issues in project {project_key}...")
            issue_keys = self.issue_gen.create_issues_bulk(project_issue_count)

            if issue_keys:
                all_issue_keys.extend(issue_keys)
                # Note: Checkpointing is now handled per-batch (50 issues) inside IssueGenerator

                # Create components and versions for this project (only on first run per project)
                if not self._is_phase_complete("components"):
                    if counts.get('project_component', 0) > 0:
                        components_per_project = max(1, counts['project_component'] // len(projects))
                        self.project_gen.create_components(project_key, components_per_project)

                if not self._is_phase_complete("versions"):
                    if counts.get('project_version', 0) > 0:
                        versions_per_project = max(1, counts['project_version'] // len(projects))
                        self.project_gen.create_versions(project_key, versions_per_project)

        # Mark components and versions complete
        self._complete_phase("components")
        self._complete_phase("versions")
        self._complete_phase("issues")

        return all_issue_keys

    async def _create_issues_across_projects_async(
        self,
        projects: List[Dict],
        num_issues: int,
        counts: Dict[str, int]
    ) -> List[str]:
        """Create issues distributed across projects with parallel execution.

        Issues are now created in parallel across all projects for significantly
        improved throughput. At 18M scale with many projects, this can provide
        substantial speedup.
        """
        # Check if issues phase is complete
        if self._is_phase_complete("issues"):
            # Restore issue keys from checkpoint or reconstruct them
            if self.checkpoint and self.checkpoint.checkpoint:
                issue_keys = self.checkpoint.checkpoint.issue_keys
                if issue_keys:
                    self.logger.info(f"Restored {len(issue_keys)} issue keys from checkpoint")
                    return issue_keys
                total = self.checkpoint.get_total_issues_created()
                self.logger.info(f"Issues phase complete ({total} created). Reconstructing keys from Jira...")
                return self._fetch_issue_keys_from_jira()

        self._start_phase("issues")

        # Calculate how many issues each project needs
        if self.checkpoint:
            issues_needed = self.checkpoint.get_issues_needed_per_project(projects, num_issues)
        else:
            issues_per_project = max(1, num_issues // len(projects))
            remainder = num_issues % len(projects)
            issues_needed = {
                p['key']: issues_per_project + (1 if i < remainder else 0)
                for i, p in enumerate(projects)
            }

        all_issue_keys = []

        # Restore existing issue keys from checkpoint
        if self.checkpoint and self.checkpoint.checkpoint:
            all_issue_keys = list(self.checkpoint.checkpoint.issue_keys)

        # Filter to projects that still need issues
        projects_to_process = [
            p for p in projects
            if issues_needed.get(p['key'], 0) > 0
        ]

        if not projects_to_process:
            self.logger.info("No projects need issue creation")
            return all_issue_keys

        # Determine parallelism level for projects
        # Use min of: number of projects, concurrency setting, or 5 (reasonable default)
        max_parallel_projects = min(len(projects_to_process), self.concurrency, 5)

        self.logger.info(f"\nCreating issues in parallel across {len(projects_to_process)} projects "
                        f"(parallelism: {max_parallel_projects})...")

        # Process projects in parallel batches
        for batch_start in range(0, len(projects_to_process), max_parallel_projects):
            batch_projects = projects_to_process[batch_start:batch_start + max_parallel_projects]

            # Create tasks for parallel execution
            tasks = []
            for project in batch_projects:
                project_key = project['key']
                project_id = project['id']
                project_issue_count = issues_needed.get(project_key, 0)

                task = self.issue_gen.create_issues_bulk_async(
                    count=project_issue_count,
                    project_key=project_key,
                    project_id=project_id
                )
                tasks.append((project_key, task))

            # Execute in parallel
            results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

            # Process results
            # Note: Checkpointing is now handled per-batch (50 issues) inside IssueGenerator
            for (project_key, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    self.logger.error(f"Failed to create issues in {project_key}: {result}")
                    continue

                issue_keys = result
                if issue_keys:
                    all_issue_keys.extend(issue_keys)

            self.logger.info(f"Batch complete: {len(all_issue_keys)} total issues created so far")

        # Create components and versions for all projects (async for high volume)
        # These are created after all issues to avoid interleaving with issue creation
        if not self._is_phase_complete("components"):
            if counts.get('project_component', 0) > 0:
                components_per_project = max(1, counts['project_component'] // len(projects))
                total_components = components_per_project * len(projects)
                self.benchmark.start_phase("components", total_components)

                component_tasks = []
                for project in projects:
                    component_tasks.append(
                        self.project_gen.create_components_async(project['key'], components_per_project)
                    )
                await asyncio.gather(*component_tasks, return_exceptions=True)
                self.benchmark.end_phase("components", total_components)

        if not self._is_phase_complete("versions"):
            if counts.get('project_version', 0) > 0:
                versions_per_project = max(1, counts['project_version'] // len(projects))
                total_versions = versions_per_project * len(projects)
                self.benchmark.start_phase("versions", total_versions)

                version_tasks = []
                for project in projects:
                    version_tasks.append(
                        self.project_gen.create_versions_async(project['key'], versions_per_project)
                    )
                await asyncio.gather(*version_tasks, return_exceptions=True)
                self.benchmark.end_phase("versions", total_versions)

        # Mark components and versions complete
        self._complete_phase("components")
        self._complete_phase("versions")
        self._complete_phase("issues")

        return all_issue_keys

    def _fetch_issue_keys_from_jira(self) -> List[str]:
        """Fetch issue keys from Jira using run_id label.

        Used when resuming and we need to get the issue keys for items creation.
        """
        issue_keys = []

        if self.dry_run:
            return [f"DRYRUN-{i}" for i in range(1, 101)]

        self.logger.info(f"Fetching issues with label: {self.run_id}")

        start_at = 0
        max_results = 100

        while True:
            response = self.project_gen._api_call(
                'GET',
                'search',
                params={
                    'jql': f'labels = "{self.run_id}"',
                    'fields': 'key',
                    'startAt': start_at,
                    'maxResults': max_results
                }
            )

            if not response:
                break

            data = response.json()
            issues = data.get('issues', [])

            for issue in issues:
                issue_keys.append(issue['key'])

            if len(issues) < max_results:
                break

            start_at += max_results

        self.logger.info(f"Found {len(issue_keys)} existing issues")
        return issue_keys

    def _create_issue_items_sync(
        self,
        issue_keys: List[str],
        project_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create issue-dependent items synchronously."""
        if not self._is_phase_complete("comments"):
            if counts.get('comment', 0) > 0:
                self._start_phase("comments")
                self.benchmark.start_phase("comments", counts['comment'])
                remaining = self._get_remaining_count("comments", counts['comment'])
                created = 0
                if remaining > 0:
                    created = self.issue_items_gen.create_comments(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("comments", counts['comment'] - remaining + created)
                self.benchmark.end_phase("comments", created)
                self._complete_phase("comments")

        if not self._is_phase_complete("worklogs"):
            if counts.get('issue_worklog', 0) > 0:
                self._start_phase("worklogs")
                self.benchmark.start_phase("worklogs", counts['issue_worklog'])
                remaining = self._get_remaining_count("worklogs", counts['issue_worklog'])
                created = 0
                if remaining > 0:
                    created = self.issue_items_gen.create_worklogs(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("worklogs", counts['issue_worklog'] - remaining + created)
                self.benchmark.end_phase("worklogs", created)
                self._complete_phase("worklogs")

        if not self._is_phase_complete("issue_links"):
            if counts.get('issue_link', 0) > 0:
                self._start_phase("issue_links")
                self.benchmark.start_phase("issue_links", counts['issue_link'])
                remaining = self._get_remaining_count("issue_links", counts['issue_link'])
                created = 0
                if remaining > 0:
                    created = self.issue_items_gen.create_issue_links(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("issue_links", counts['issue_link'] - remaining + created)
                self.benchmark.end_phase("issue_links", created)
                self._complete_phase("issue_links")

        if not self._is_phase_complete("watchers"):
            if counts.get('issue_watcher', 0) > 0:
                self._start_phase("watchers")
                self.benchmark.start_phase("watchers", counts['issue_watcher'])
                user_ids = self.project_gen.get_all_users(max_users=100)
                created = 0
                if user_ids:
                    for project_key in project_keys:
                        self.project_gen.add_users_to_project(project_key, user_ids)
                    remaining = self._get_remaining_count("watchers", counts['issue_watcher'])
                    if remaining > 0:
                        created = self.issue_items_gen.add_watchers(issue_keys, remaining, user_ids)
                        if self.checkpoint:
                            self.checkpoint.update_phase_count("watchers", counts['issue_watcher'] - remaining + created)
                self.benchmark.end_phase("watchers", created)
                self._complete_phase("watchers")

        if not self._is_phase_complete("attachments"):
            if counts.get('issue_attachment', 0) > 0:
                self._start_phase("attachments")
                self.benchmark.start_phase("attachments", counts['issue_attachment'])
                remaining = self._get_remaining_count("attachments", counts['issue_attachment'])
                created = 0
                if remaining > 0:
                    created = self.issue_gen.create_attachments(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("attachments", counts['issue_attachment'] - remaining + created)
                self.benchmark.end_phase("attachments", created)
                self._complete_phase("attachments")

        if not self._is_phase_complete("votes"):
            if counts.get('issue_vote', 0) > 0:
                self._start_phase("votes")
                self.benchmark.start_phase("votes", counts['issue_vote'])
                remaining = self._get_remaining_count("votes", counts['issue_vote'])
                created = 0
                if remaining > 0:
                    created = self.issue_items_gen.add_votes(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("votes", counts['issue_vote'] - remaining + created)
                self.benchmark.end_phase("votes", created)
                self._complete_phase("votes")

        if not self._is_phase_complete("issue_properties"):
            if counts.get('issue_properties', 0) > 0:
                self._start_phase("issue_properties")
                self.benchmark.start_phase("issue_properties", counts['issue_properties'])
                remaining = self._get_remaining_count("issue_properties", counts['issue_properties'])
                created = 0
                if remaining > 0:
                    created = self.issue_items_gen.create_issue_properties(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("issue_properties", counts['issue_properties'] - remaining + created)
                self.benchmark.end_phase("issue_properties", created)
                self._complete_phase("issue_properties")

        if not self._is_phase_complete("remote_links"):
            if counts.get('issue_remote_link', 0) > 0:
                self._start_phase("remote_links")
                self.benchmark.start_phase("remote_links", counts['issue_remote_link'])
                remaining = self._get_remaining_count("remote_links", counts['issue_remote_link'])
                created = 0
                if remaining > 0:
                    created = self.issue_items_gen.create_remote_links(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("remote_links", counts['issue_remote_link'] - remaining + created)
                self.benchmark.end_phase("remote_links", created)
                self._complete_phase("remote_links")

    async def _create_issue_items_async(
        self,
        issue_keys: List[str],
        project_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create issue-dependent items using async for high-volume items."""
        if not self._is_phase_complete("comments"):
            if counts.get('comment', 0) > 0:
                self._start_phase("comments")
                self.benchmark.start_phase("comments", counts['comment'])
                remaining = self._get_remaining_count("comments", counts['comment'])
                start_count = counts['comment'] - remaining  # How many already created
                created = 0
                if remaining > 0:
                    created = await self.issue_items_gen.create_comments_async(issue_keys, remaining, start_count)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("comments", start_count + created)
                self.benchmark.end_phase("comments", created)
                self._complete_phase("comments")

        if not self._is_phase_complete("worklogs"):
            if counts.get('issue_worklog', 0) > 0:
                self._start_phase("worklogs")
                self.benchmark.start_phase("worklogs", counts['issue_worklog'])
                remaining = self._get_remaining_count("worklogs", counts['issue_worklog'])
                created = 0
                if remaining > 0:
                    created = await self.issue_items_gen.create_worklogs_async(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("worklogs", counts['issue_worklog'] - remaining + created)
                self.benchmark.end_phase("worklogs", created)
                self._complete_phase("worklogs")

        if not self._is_phase_complete("issue_links"):
            if counts.get('issue_link', 0) > 0:
                self._start_phase("issue_links")
                self.benchmark.start_phase("issue_links", counts['issue_link'])
                remaining = self._get_remaining_count("issue_links", counts['issue_link'])
                created = 0
                if remaining > 0:
                    created = await self.issue_items_gen.create_issue_links_async(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("issue_links", counts['issue_link'] - remaining + created)
                self.benchmark.end_phase("issue_links", created)
                self._complete_phase("issue_links")

        if not self._is_phase_complete("watchers"):
            if counts.get('issue_watcher', 0) > 0:
                self._start_phase("watchers")
                self.benchmark.start_phase("watchers", counts['issue_watcher'])
                user_ids = self.project_gen.get_all_users(max_users=100)
                created = 0
                if user_ids:
                    for project_key in project_keys:
                        self.project_gen.add_users_to_project(project_key, user_ids)
                    remaining = self._get_remaining_count("watchers", counts['issue_watcher'])
                    start_count = counts['issue_watcher'] - remaining  # How many already created
                    if remaining > 0:
                        created = await self.issue_items_gen.add_watchers_async(issue_keys, remaining, user_ids, start_count)
                        if self.checkpoint:
                            self.checkpoint.update_phase_count("watchers", start_count + created)
                self.benchmark.end_phase("watchers", created)
                self._complete_phase("watchers")

        if not self._is_phase_complete("attachments"):
            if counts.get('issue_attachment', 0) > 0:
                self._start_phase("attachments")
                self.benchmark.start_phase("attachments", counts['issue_attachment'])
                remaining = self._get_remaining_count("attachments", counts['issue_attachment'])
                start_count = counts['issue_attachment'] - remaining  # How many already created
                created = 0
                if remaining > 0:
                    created = await self.issue_gen.create_attachments_async(issue_keys, remaining, start_count)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("attachments", start_count + created)
                self.benchmark.end_phase("attachments", created)
                self._complete_phase("attachments")

        if not self._is_phase_complete("votes"):
            if counts.get('issue_vote', 0) > 0:
                self._start_phase("votes")
                self.benchmark.start_phase("votes", counts['issue_vote'])
                remaining = self._get_remaining_count("votes", counts['issue_vote'])
                created = 0
                if remaining > 0:
                    created = await self.issue_items_gen.add_votes_async(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("votes", counts['issue_vote'] - remaining + created)
                self.benchmark.end_phase("votes", created)
                self._complete_phase("votes")

        if not self._is_phase_complete("issue_properties"):
            if counts.get('issue_properties', 0) > 0:
                self._start_phase("issue_properties")
                self.benchmark.start_phase("issue_properties", counts['issue_properties'])
                remaining = self._get_remaining_count("issue_properties", counts['issue_properties'])
                created = 0
                if remaining > 0:
                    created = await self.issue_items_gen.create_issue_properties_async(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("issue_properties", counts['issue_properties'] - remaining + created)
                self.benchmark.end_phase("issue_properties", created)
                self._complete_phase("issue_properties")

        if not self._is_phase_complete("remote_links"):
            if counts.get('issue_remote_link', 0) > 0:
                self._start_phase("remote_links")
                self.benchmark.start_phase("remote_links", counts['issue_remote_link'])
                remaining = self._get_remaining_count("remote_links", counts['issue_remote_link'])
                created = 0
                if remaining > 0:
                    created = await self.issue_items_gen.create_remote_links_async(issue_keys, remaining)
                    if self.checkpoint:
                        self.checkpoint.update_phase_count("remote_links", counts['issue_remote_link'] - remaining + created)
                self.benchmark.end_phase("remote_links", created)
                self._complete_phase("remote_links")

    def _create_agile_items_sync(
        self,
        project_keys: List[str],
        issue_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create agile items (boards, sprints)."""
        board_ids = []

        if not self._is_phase_complete("boards"):
            if counts.get('board', 0) > 0:
                self._start_phase("boards")
                self.benchmark.start_phase("boards", counts['board'])
                boards = self.agile_gen.create_boards(project_keys, counts['board'])
                board_ids = [b['id'] for b in boards]
                # Only scrum boards support sprints
                scrum_board_ids = [b['id'] for b in boards if b.get('type') == 'scrum']
                self.benchmark.end_phase("boards", len(boards))
                if self.checkpoint:
                    self.checkpoint.update_phase_count("boards", len(boards))
                self._complete_phase("boards")
        else:
            scrum_board_ids = []

        if not self._is_phase_complete("sprints"):
            if counts.get('sprint', 0) > 0 and scrum_board_ids:
                self._start_phase("sprints")
                self.benchmark.start_phase("sprints", counts['sprint'])
                sprints = self.agile_gen.create_sprints(scrum_board_ids, counts['sprint'])
                sprint_ids = [s['id'] for s in sprints]
                self.benchmark.end_phase("sprints", len(sprints))
                if self.checkpoint:
                    self.checkpoint.update_phase_count("sprints", len(sprints))

                # Assign some issues to sprints
                if sprint_ids and issue_keys:
                    self.agile_gen.assign_issues_to_sprints(sprint_ids, issue_keys)
                self._complete_phase("sprints")

    async def _create_agile_items_async(
        self,
        project_keys: List[str],
        issue_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create agile items (boards sequential, sprints async)."""
        board_ids = []

        # Boards must be sequential (they require creating a filter first)
        if not self._is_phase_complete("boards"):
            if counts.get('board', 0) > 0:
                self._start_phase("boards")
                self.benchmark.start_phase("boards", counts['board'])
                boards = self.agile_gen.create_boards(project_keys, counts['board'])
                board_ids = [b['id'] for b in boards]
                # Only scrum boards support sprints
                scrum_board_ids = [b['id'] for b in boards if b.get('type') == 'scrum']
                self.benchmark.end_phase("boards", len(boards))
                if self.checkpoint:
                    self.checkpoint.update_phase_count("boards", len(boards))
                self._complete_phase("boards")
        else:
            scrum_board_ids = []

        # Sprints can be async (high volume at 18M scale: 900K)
        if not self._is_phase_complete("sprints"):
            if counts.get('sprint', 0) > 0 and scrum_board_ids:
                self._start_phase("sprints")
                self.benchmark.start_phase("sprints", counts['sprint'])
                sprints = await self.agile_gen.create_sprints_async(scrum_board_ids, counts['sprint'])
                sprint_ids = [s['id'] for s in sprints]
                self.benchmark.end_phase("sprints", len(sprints))
                if self.checkpoint:
                    self.checkpoint.update_phase_count("sprints", len(sprints))

                # Assign some issues to sprints (async)
                if sprint_ids and issue_keys:
                    await self.agile_gen.assign_issues_to_sprints_async(sprint_ids, issue_keys)
                self._complete_phase("sprints")

    def _create_filters_sync(
        self,
        project_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create filters and dashboards."""
        if not self._is_phase_complete("filters"):
            if counts.get('filter', 0) > 0:
                self._start_phase("filters")
                self.benchmark.start_phase("filters", counts['filter'])
                created = self.filter_gen.create_filters(project_keys, counts['filter'])
                created_count = len(created) if isinstance(created, list) else created
                self.benchmark.end_phase("filters", created_count)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("filters", created_count)
                self._complete_phase("filters")

        if not self._is_phase_complete("dashboards"):
            if counts.get('dashboard', 0) > 0:
                self._start_phase("dashboards")
                self.benchmark.start_phase("dashboards", counts['dashboard'])
                created = self.filter_gen.create_dashboards(counts['dashboard'])
                created_count = len(created) if isinstance(created, list) else created
                self.benchmark.end_phase("dashboards", created_count)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("dashboards", created_count)
                self._complete_phase("dashboards")

    async def _create_filters_async(
        self,
        project_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create filters and dashboards (async for high volume at 18M scale)."""
        if not self._is_phase_complete("filters"):
            if counts.get('filter', 0) > 0:
                self._start_phase("filters")
                self.benchmark.start_phase("filters", counts['filter'])
                created = await self.filter_gen.create_filters_async(project_keys, counts['filter'])
                created_count = len(created) if isinstance(created, list) else created
                self.benchmark.end_phase("filters", created_count)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("filters", created_count)
                self._complete_phase("filters")

        if not self._is_phase_complete("dashboards"):
            if counts.get('dashboard', 0) > 0:
                self._start_phase("dashboards")
                self.benchmark.start_phase("dashboards", counts['dashboard'])
                created = await self.filter_gen.create_dashboards_async(counts['dashboard'])
                created_count = len(created) if isinstance(created, list) else created
                self.benchmark.end_phase("dashboards", created_count)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("dashboards", created_count)
                self._complete_phase("dashboards")

    def _assign_projects_to_categories(
        self,
        project_keys: List[str],
        categories: List[Dict[str, str]]
    ):
        """Assign projects to categories (round-robin distribution)."""
        if not categories:
            return

        self.logger.info(f"Assigning {len(project_keys)} projects to {len(categories)} categories...")

        for i, project_key in enumerate(project_keys):
            category = categories[i % len(categories)]
            self.project_gen.assign_project_to_category(project_key, category['id'])

    def _log_header(self, num_issues: int, async_mode: bool):
        """Log generation header."""
        mode = "async mode" if async_mode else "sync mode"
        self.logger.info("=" * 60)
        self.logger.info(f"Starting Jira data generation ({mode})")
        self.logger.info(f"Size bucket: {self.size_bucket}")
        self.logger.info(f"Target issues: {num_issues}")
        self.logger.info(f"Prefix: {self.prefix}")
        if self.issues_only:
            self.logger.info("Mode: ISSUES ONLY (skipping associated data)")
        if async_mode:
            self.logger.info(f"Concurrency: {self.concurrency}")
            if self.request_delay > 0:
                self.logger.info(f"Request delay: {self.request_delay}s (+ adaptive)")
            else:
                self.logger.info(f"Request delay: adaptive only")
        self.logger.info(f"Run ID (for JQL): labels = {self.run_id}")
        self.logger.info(f"Dry run: {self.dry_run}")
        self.logger.info("=" * 60)

    def _log_planned_counts(self, num_issues: int, counts: Dict[str, int]):
        """Log planned creation counts."""
        self.logger.info("\nPlanned creation counts:")
        self.logger.info(f"  Issues: {num_issues}")

        # Group by category for readability
        config_items = ['issue_field']
        project_items = ['project', 'project_category', 'project_component', 'project_version', 'project_property']
        issue_items = ['comment', 'issue_worklog', 'issue_link', 'issue_watcher',
                       'issue_attachment', 'issue_vote', 'issue_properties', 'issue_remote_link']
        agile_items = ['board', 'sprint']
        other_items = ['filter', 'dashboard']

        for category, items in [
            ("Configuration items", config_items),
            ("Project items", project_items),
            ("Issue items", issue_items),
            ("Agile items", agile_items),
            ("Other items", other_items)
        ]:
            category_counts = {k: counts.get(k, 0) for k in items if counts.get(k, 0) > 0}
            if category_counts:
                self.logger.info(f"\n  {category}:")
                for item, count in category_counts.items():
                    self.logger.info(f"    {item}: {count}")

    def _log_footer(self, projects: List[Dict], issue_keys: List[str], num_issues: int):
        """Log generation footer with benchmark summary."""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("Data generation complete!")
        self.logger.info("=" * 60)
        self.logger.info("\nTo find all generated data in JQL:")
        self.logger.info(f"  labels = {self.run_id}")
        self.logger.info("  OR")
        self.logger.info(f"  labels = {self.prefix}")
        self.logger.info(f"\nCreated {len(projects)} projects")
        self.logger.info(f"Created {len(issue_keys)} issues")

        # Log benchmark summary
        self.logger.info(self.benchmark.get_summary_report())

        # Log extrapolations for common large-scale targets
        if num_issues >= 10:
            # Show extrapolation for 18M issues (max Jira limit)
            self.logger.info(self.benchmark.format_extrapolation(18_000_000, num_issues))


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

  # Resume from checkpoint (after interruption)
  %(prog)s --url https://mycompany.atlassian.net \\
           --email user@example.com \\
           --prefix LOAD \\
           --count 500 \\
           --size medium \\
           --resume

JQL Search:
  After generation, search for your data using:
    labels = PREFIX-YYYYMMDD-HHMMSS
  Or more broadly:
    labels = PREFIX

Checkpointing:
  - Progress is automatically saved to {PREFIX}-checkpoint.json
  - Use --resume to continue from where you left off
  - Use --no-checkpoint to disable checkpointing entirely
        """
    )

    parser.add_argument('--url', required=True, help='Jira URL (e.g., https://mycompany.atlassian.net)')
    parser.add_argument('--email', required=True, help='Your Jira email')
    parser.add_argument('--token', help='Jira API token (or set JIRA_API_TOKEN in .env file or env var)')
    parser.add_argument('--prefix', required=True, help='Prefix for all created items and project keys (e.g., PERF)')
    parser.add_argument('--count', type=int, required=True, help='Number of issues to create')
    parser.add_argument('--projects', type=int, default=None,
                        help='Override number of projects (default: calculated from multipliers). Issues spread evenly across projects.')
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
    parser.add_argument(
        '--request-delay',
        type=float,
        default=0.0,
        help='Delay between requests in seconds (default: 0). Use 0.05-0.1 to reduce rate limiting.'
    )
    parser.add_argument('--no-async', action='store_true', help='Disable async mode (use sequential requests)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be created without creating it')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--issues-only', action='store_true',
                        help='Only create projects and issues, skip all associated data (comments, worklogs, etc.)')

    # Checkpoint options
    parser.add_argument('--resume', action='store_true',
                        help='Resume from existing checkpoint file')
    parser.add_argument('--no-checkpoint', action='store_true',
                        help='Disable checkpointing (not recommended for large runs)')

    args = parser.parse_args()

    # Generate log filename based on prefix and timestamp
    log_filename = f"jira_generator_{args.prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

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

    # Get API token
    api_token = args.token or os.environ.get('JIRA_API_TOKEN')
    if not api_token:
        print("Error: Jira API token required. Use --token, set JIRA_API_TOKEN in .env file, or set as environment variable", file=sys.stderr)
        sys.exit(1)

    # Setup checkpoint manager
    checkpoint_manager = None
    if not args.no_checkpoint:
        checkpoint_manager = CheckpointManager(args.prefix)

        if args.resume:
            # Try to load existing checkpoint
            checkpoint_path = checkpoint_manager.find_existing_checkpoint()
            if checkpoint_path:
                loaded = checkpoint_manager.load(checkpoint_path)
                if loaded:
                    logging.info(f"Found checkpoint: {checkpoint_path}")
                    # Validate checkpoint matches current parameters
                    if loaded.jira_url != args.url:
                        logging.warning(f"Checkpoint URL ({loaded.jira_url}) differs from current ({args.url})")
                    if loaded.target_issue_count != args.count:
                        logging.warning(f"Checkpoint target count ({loaded.target_issue_count}) differs from current ({args.count})")
                        logging.warning("Using checkpoint's target count for consistency")
                else:
                    logging.error("Failed to load checkpoint. Starting fresh.")
            else:
                logging.warning(f"No checkpoint found for prefix '{args.prefix}'. Starting fresh.")
        else:
            # Check if checkpoint exists but --resume wasn't specified
            existing = checkpoint_manager.find_existing_checkpoint()
            if existing:
                logging.warning(f"Found existing checkpoint: {existing}")
                logging.warning("Use --resume to continue from checkpoint, or delete the file to start fresh.")
                response = input("Continue with new run (overwrites checkpoint)? [y/N]: ").strip().lower()
                if response != 'y':
                    logging.info("Aborting. Use --resume to continue from checkpoint.")
                    sys.exit(0)

    try:
        generator = JiraDataGenerator(
            jira_url=args.url,
            email=args.email,
            api_token=api_token,
            prefix=args.prefix,
            size_bucket=args.size,
            dry_run=args.dry_run,
            concurrency=args.concurrency,
            checkpoint_manager=checkpoint_manager,
            request_delay=args.request_delay,
            issues_only=args.issues_only,
            project_override=args.projects
        )

        if args.no_async:
            generator.generate_all(args.count)
        else:
            asyncio.run(generator.generate_all_async(args.count))

    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)
        if checkpoint_manager and checkpoint_manager.checkpoint:
            logging.info("Progress saved to checkpoint. Use --resume to continue.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        if checkpoint_manager and checkpoint_manager.checkpoint:
            logging.info("Progress saved to checkpoint. Use --resume to continue.")
        sys.exit(1)


if __name__ == '__main__':
    main()
