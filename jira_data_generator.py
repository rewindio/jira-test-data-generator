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
        concurrency: int = 5
    ):
        self.jira_url = jira_url.rstrip('/')
        self.email = email
        self.api_token = api_token
        self.prefix = prefix
        self.size_bucket = size_bucket.lower()
        self.dry_run = dry_run
        self.concurrency = concurrency

        self.logger = logging.getLogger(__name__)

        # Generate unique label for this run
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Validate size bucket
        if self.size_bucket not in MULTIPLIERS:
            raise ValueError(f"Invalid size bucket. Must be one of: {', '.join(MULTIPLIERS.keys())}")

        # Initialize modular generators
        self._init_generators()

    def _init_generators(self):
        """Initialize all generator modules."""
        common_args = {
            'jira_url': self.jira_url,
            'email': self.email,
            'api_token': self.api_token,
            'dry_run': self.dry_run,
            'concurrency': self.concurrency
        }

        self.project_gen = ProjectGenerator(prefix=self.prefix, **common_args)
        self.issue_gen = IssueGenerator(prefix=self.prefix, **common_args)
        self.issue_items_gen = IssueItemsGenerator(prefix=self.prefix, **common_args)
        self.agile_gen = AgileGenerator(prefix=self.prefix, **common_args)
        self.filter_gen = FilterGenerator(prefix=self.prefix, **common_args)

        # Set consistent run_id across generators
        self.issue_gen.run_id = self.run_id
        self.issue_items_gen.set_run_id(self.run_id)
        self.filter_gen.set_run_id(self.run_id)
        self.project_gen.set_run_id(self.run_id)

    def calculate_counts(self, num_issues: int) -> Dict[str, int]:
        """Calculate item counts based on multipliers and target issue count."""
        multipliers = MULTIPLIERS[self.size_bucket]
        counts = {}

        for item_type, multiplier in multipliers.items():
            raw_count = num_issues * multiplier
            counts[item_type] = max(1, math.ceil(raw_count))

        return counts

    def generate_all(self, num_issues: int):
        """Generate all test data based on multipliers (synchronous mode)."""
        self._log_header(num_issues, async_mode=False)
        counts = self.calculate_counts(num_issues)
        self._log_planned_counts(num_issues, counts)

        # Create project categories first (projects can be assigned to them)
        categories = []
        if counts.get('project_category', 0) > 0:
            categories = self.project_gen.create_categories(counts['project_category'])

        # Create projects
        num_projects = counts.get('project', 1)
        projects = self.project_gen.create_projects(num_projects)

        if not projects:
            self.logger.error("Failed to create projects. Aborting.")
            return

        project_keys = [p['key'] for p in projects]

        # Assign projects to categories if we have both
        if categories and projects:
            self._assign_projects_to_categories(project_keys, categories)

        # Create project properties
        if counts.get('project_property', 0) > 0:
            self.project_gen.create_project_properties(project_keys, counts['project_property'])

        # Create issues distributed across projects
        all_issue_keys = self._create_issues_across_projects(projects, num_issues, counts)

        if not all_issue_keys:
            self.logger.error("Failed to create any issues. Aborting.")
            return

        # Create issue-dependent items
        self._create_issue_items_sync(all_issue_keys, project_keys, counts)

        # Create agile items (boards, sprints)
        self._create_agile_items_sync(project_keys, all_issue_keys, counts)

        # Create filters and dashboards
        self._create_filters_sync(project_keys, counts)

        self._log_footer(projects, all_issue_keys)

    async def generate_all_async(self, num_issues: int):
        """Generate all test data using async for high-volume items."""
        self._log_header(num_issues, async_mode=True)
        counts = self.calculate_counts(num_issues)
        self._log_planned_counts(num_issues, counts)

        # Create project categories first (projects can be assigned to them)
        categories = []
        if counts.get('project_category', 0) > 0:
            categories = self.project_gen.create_categories(counts['project_category'])

        # Create projects (sequential - usually few)
        num_projects = counts.get('project', 1)
        projects = self.project_gen.create_projects(num_projects)

        if not projects:
            self.logger.error("Failed to create projects. Aborting.")
            return

        project_keys = [p['key'] for p in projects]

        # Assign projects to categories if we have both
        if categories and projects:
            self._assign_projects_to_categories(project_keys, categories)

        # Create project properties
        if counts.get('project_property', 0) > 0:
            self.project_gen.create_project_properties(project_keys, counts['project_property'])

        # Create issues (bulk API - already optimized)
        all_issue_keys = self._create_issues_across_projects(projects, num_issues, counts)

        if not all_issue_keys:
            self.logger.error("Failed to create any issues. Aborting.")
            return

        # Create issue-dependent items using async
        try:
            await self._create_issue_items_async(all_issue_keys, project_keys, counts)

            # Create agile items (sequential for boards, sprints)
            self._create_agile_items_sync(project_keys, all_issue_keys, counts)

            # Create filters and dashboards (sequential - low volume)
            self._create_filters_sync(project_keys, counts)

        finally:
            # Clean up async sessions
            await self.issue_gen._close_async_session()
            await self.issue_items_gen._close_async_session()

        self._log_footer(projects, all_issue_keys)

    def _create_issues_across_projects(
        self,
        projects: List[Dict],
        num_issues: int,
        counts: Dict[str, int]
    ) -> List[str]:
        """Create issues distributed across projects."""
        issues_per_project = max(1, num_issues // len(projects))
        remainder = num_issues % len(projects)

        all_issue_keys = []

        for idx, project in enumerate(projects):
            # Set project context
            self.issue_gen.set_project_context(project['key'], project['id'])

            # Distribute remainder to first projects
            project_issue_count = issues_per_project + (1 if idx < remainder else 0)

            self.logger.info(f"\nCreating {project_issue_count} issues in project {project['key']}...")
            issue_keys = self.issue_gen.create_issues_bulk(project_issue_count)

            if issue_keys:
                all_issue_keys.extend(issue_keys)

                # Create components and versions for this project
                if counts.get('project_component', 0) > 0:
                    components_per_project = max(1, counts['project_component'] // len(projects))
                    self.project_gen.create_components(project['key'], components_per_project)

                if counts.get('project_version', 0) > 0:
                    versions_per_project = max(1, counts['project_version'] // len(projects))
                    self.project_gen.create_versions(project['key'], versions_per_project)

        return all_issue_keys

    def _create_issue_items_sync(
        self,
        issue_keys: List[str],
        project_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create issue-dependent items synchronously."""
        if counts.get('comment', 0) > 0:
            self.issue_items_gen.create_comments(issue_keys, counts['comment'])

        if counts.get('issue_worklog', 0) > 0:
            self.issue_items_gen.create_worklogs(issue_keys, counts['issue_worklog'])

        if counts.get('issue_link', 0) > 0:
            self.issue_items_gen.create_issue_links(issue_keys, counts['issue_link'])

        if counts.get('issue_watcher', 0) > 0:
            user_ids = self.project_gen.get_all_users(max_users=100)
            if user_ids:
                for project_key in project_keys:
                    self.project_gen.add_users_to_project(project_key, user_ids)
                self.issue_items_gen.add_watchers(issue_keys, counts['issue_watcher'], user_ids)

        if counts.get('issue_attachment', 0) > 0:
            self.issue_gen.create_attachments(issue_keys, counts['issue_attachment'])

        if counts.get('issue_vote', 0) > 0:
            self.issue_items_gen.add_votes(issue_keys, counts['issue_vote'])

        if counts.get('issue_properties', 0) > 0:
            self.issue_items_gen.create_issue_properties(issue_keys, counts['issue_properties'])

        if counts.get('issue_remote_link', 0) > 0:
            self.issue_items_gen.create_remote_links(issue_keys, counts['issue_remote_link'])

    async def _create_issue_items_async(
        self,
        issue_keys: List[str],
        project_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create issue-dependent items using async for high-volume items."""
        if counts.get('comment', 0) > 0:
            await self.issue_items_gen.create_comments_async(issue_keys, counts['comment'])

        if counts.get('issue_worklog', 0) > 0:
            await self.issue_items_gen.create_worklogs_async(issue_keys, counts['issue_worklog'])

        if counts.get('issue_link', 0) > 0:
            await self.issue_items_gen.create_issue_links_async(issue_keys, counts['issue_link'])

        if counts.get('issue_watcher', 0) > 0:
            user_ids = self.project_gen.get_all_users(max_users=100)
            if user_ids:
                for project_key in project_keys:
                    self.project_gen.add_users_to_project(project_key, user_ids)
                await self.issue_items_gen.add_watchers_async(issue_keys, counts['issue_watcher'], user_ids)

        if counts.get('issue_attachment', 0) > 0:
            await self.issue_gen.create_attachments_async(issue_keys, counts['issue_attachment'])

        if counts.get('issue_vote', 0) > 0:
            await self.issue_items_gen.add_votes_async(issue_keys, counts['issue_vote'])

        if counts.get('issue_properties', 0) > 0:
            await self.issue_items_gen.create_issue_properties_async(issue_keys, counts['issue_properties'])

        if counts.get('issue_remote_link', 0) > 0:
            await self.issue_items_gen.create_remote_links_async(issue_keys, counts['issue_remote_link'])

    def _create_agile_items_sync(
        self,
        project_keys: List[str],
        issue_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create agile items (boards, sprints)."""
        board_ids = []

        if counts.get('board', 0) > 0:
            boards = self.agile_gen.create_boards(project_keys, counts['board'])
            board_ids = [b['id'] for b in boards]

        if counts.get('sprint', 0) > 0 and board_ids:
            sprints = self.agile_gen.create_sprints(board_ids, counts['sprint'])
            sprint_ids = [s['id'] for s in sprints]

            # Assign some issues to sprints
            if sprint_ids and issue_keys:
                self.agile_gen.assign_issues_to_sprints(sprint_ids, issue_keys)

    def _create_filters_sync(
        self,
        project_keys: List[str],
        counts: Dict[str, int]
    ):
        """Create filters and dashboards."""
        if counts.get('filter', 0) > 0:
            self.filter_gen.create_filters(project_keys, counts['filter'])

        if counts.get('dashboard', 0) > 0:
            self.filter_gen.create_dashboards(counts['dashboard'])

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
        if async_mode:
            self.logger.info(f"Concurrency: {self.concurrency}")
        self.logger.info(f"Run ID (for JQL): labels = {self.run_id}")
        self.logger.info(f"Dry run: {self.dry_run}")
        self.logger.info("=" * 60)

    def _log_planned_counts(self, num_issues: int, counts: Dict[str, int]):
        """Log planned creation counts."""
        self.logger.info("\nPlanned creation counts:")
        self.logger.info(f"  Issues: {num_issues}")

        # Group by category for readability
        project_items = ['project', 'project_category', 'project_component', 'project_version', 'project_property']
        issue_items = ['comment', 'issue_worklog', 'issue_link', 'issue_watcher',
                       'issue_attachment', 'issue_vote', 'issue_properties', 'issue_remote_link']
        agile_items = ['board', 'sprint']
        other_items = ['filter', 'dashboard']

        for category, items in [
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

    def _log_footer(self, projects: List[Dict], issue_keys: List[str]):
        """Log generation footer."""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("Data generation complete!")
        self.logger.info("=" * 60)
        self.logger.info("\nTo find all generated data in JQL:")
        self.logger.info(f"  labels = {self.run_id}")
        self.logger.info("  OR")
        self.logger.info(f"  labels = {self.prefix}")
        self.logger.info(f"\nCreated {len(projects)} projects")
        self.logger.info(f"Created {len(issue_keys)} issues")


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
