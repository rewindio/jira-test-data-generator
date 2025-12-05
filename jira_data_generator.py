#!/usr/bin/env python3
"""
Jira Test Data Generator

Generates realistic test data for Jira instances based on multipliers from production data.
Handles rate limiting intelligently and uses bulk APIs for best performance.
"""

import argparse
import csv
import json
import logging
import math
import os
import random
import string
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

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
    """Tracks rate limiting state"""
    retry_after: Optional[float] = None
    consecutive_429s: int = 0
    current_delay: float = 1.0
    max_delay: float = 60.0


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
        dry_run: bool = False
    ):
        self.jira_url = jira_url.rstrip('/')
        self.email = email
        self.api_token = api_token
        self.prefix = prefix
        self.size_bucket = size_bucket.lower()
        self.dry_run = dry_run

        # Project context (set dynamically when creating projects)
        self.project_key = None
        
        self.rate_limit = RateLimitState()
        self.session = self._create_session()
        self.logger = logging.getLogger(__name__)
        
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
                self.logger.error(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                # Log response body for 4xx errors to help debug
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_detail = e.response.text
                        self.logger.error(f"Response body: {error_detail}")
                    except Exception:
                        pass
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise
        
        return None

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
        """Create issues in bulk batches"""
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
    
    def add_watchers(self, issue_keys: List[str], count: int):
        """Add watchers to issues"""
        self.logger.info(f"Adding {count} watchers...")

        # Get current user as the watcher
        if self.dry_run:
            current_user_account_id = "dry-run-account-id"
        else:
            response = self._api_call('GET', 'myself')
            if not response:
                self.logger.warning("Could not get current user")
                return

            current_user_account_id = response.json().get('accountId')
            if not current_user_account_id:
                self.logger.warning("Could not get account ID")
                return
        
        # Distribute watchers across issues
        watches_per_issue = {}
        for _ in range(count):
            issue_key = random.choice(issue_keys)
            watches_per_issue[issue_key] = True  # One watcher (current user) per issue
        
        created = 0
        for issue_key in watches_per_issue.keys():
            # Add current user as watcher
            self._api_call('POST', f'issue/{issue_key}/watchers', data=current_user_account_id)
            created += 1
            
            if created % 10 == 0:
                self.logger.info(f"Added {created}/{len(watches_per_issue)} watchers")
                time.sleep(0.2)
    
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

    def create_projects(self, count: int) -> List[Dict[str, str]]:
        """Create projects and return list of project info dicts with 'key' and 'id'"""
        self.logger.info(f"Creating {count} projects...")

        created_projects = []

        for i in range(count):
            # Generate a unique project key (max 10 chars, uppercase)
            project_key = f"{self.prefix[:6].upper()}{i + 1}"

            project_data = {
                "key": project_key,
                "name": f"{self.prefix} Test Project {i + 1}",
                "description": f"Test project created by data generator. {self.generate_random_text(5, 15)}",
                "projectTypeKey": "software",
                "leadAccountId": self.get_current_user_account_id()
            }

            if self.dry_run:
                self.logger.info(f"DRY RUN: Would create project {project_key}")
                created_projects.append({
                    "key": project_key,
                    "id": f"1000{i}"
                })
            else:
                response = self._api_call('POST', 'project', data=project_data)
                if response:
                    result = response.json()
                    created_projects.append({
                        "key": result.get('key'),
                        "id": result.get('id')
                    })
                    self.logger.info(f"Created project {i + 1}/{count}: {result.get('key')}")
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
            self.add_watchers(all_issue_keys, counts['issue_watcher'])

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
    parser.add_argument('--dry-run', action='store_true', help='Show what would be created without creating it')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
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
            dry_run=args.dry_run
        )
        
        generator.generate_all(args.count)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
