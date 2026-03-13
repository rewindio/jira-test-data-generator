#!/usr/bin/env python3
"""
Jira User and Group Generator

Creates test users and groups in Jira Cloud instances.
Users are created with email addresses in the format: prefix+sandboxN@domain
"""

import argparse
import logging
import os
import sys
import time
from typing import Optional

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class JiraUserGenerator:
    """Generates test users and groups for Jira"""

    # Valid Jira Cloud products for user access
    VALID_PRODUCTS = ["jira-software", "jira-core", "jira-servicedesk", "jira-product-discovery"]

    def __init__(
        self, jira_url: str, email: str, api_token: str, products: Optional[list[str]] = None, dry_run: bool = False
    ):
        self.jira_url = jira_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.products = products if products is not None else ["jira-software"]
        self.dry_run = dry_run

        self.session = self._create_session()
        self.logger = logging.getLogger(__name__)

        # Track created items
        self.created_users = []
        self.created_groups = []
        self.existing_users = []
        self.existing_groups = []

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic"""
        session = requests.Session()

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _api_call(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        max_retries: int = 5,
    ) -> Optional[requests.Response]:
        """Make an API call with rate limit handling"""
        url = f"{self.jira_url}/rest/api/3/{endpoint}"

        if self.dry_run:
            self.logger.info(f"DRY RUN: {method} {endpoint}")
            if data:
                self.logger.debug(f"  Data: {data}")
            return None

        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    auth=(self.email, self.api_token),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    timeout=30,
                )

                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", 30))
                    self.logger.warning(f"Rate limited. Waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response

            except requests.exceptions.RequestException as e:
                self.logger.error(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                if hasattr(e, "response") and e.response is not None:
                    try:
                        error_detail = e.response.text
                        self.logger.error(f"Response body: {error_detail}")
                    except Exception:
                        pass
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
                else:
                    raise

        return None

    def parse_email(self, base_email: str) -> tuple:
        """Parse email into prefix and domain parts"""
        if "@" not in base_email:
            raise ValueError(f"Invalid email format: {base_email}")

        # Handle existing + in email
        local_part, domain = base_email.rsplit("@", 1)
        if "+" in local_part:
            prefix = local_part.split("+")[0]
        else:
            prefix = local_part

        return prefix, domain

    def generate_sandbox_email(self, base_email: str, index: int) -> str:
        """Generate a sandbox email address"""
        prefix, domain = self.parse_email(base_email)
        return f"{prefix}+sandbox{index}@{domain}"

    def check_user_exists(self, email: str) -> Optional[dict]:
        """Check if a user already exists in Jira"""
        if self.dry_run:
            return None

        response = self._api_call("GET", "user/search", params={"query": email})
        if response:
            users = response.json()
            for user in users:
                if user.get("emailAddress", "").lower() == email.lower():
                    return user
        return None

    def create_user(self, email: str, display_name: str) -> Optional[dict]:
        """Create/invite a single user in Jira Cloud

        Uses POST /rest/api/3/user to invite users.
        Requires site-admin or user-access-admin permissions.

        Returns the user dict if created/exists, None on failure.
        """
        self.logger.info(f"Processing user: {email} ({display_name})")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would check/invite user {email}")
            self.created_users.append({"email": email, "displayName": display_name, "status": "dry_run"})
            return {"email": email, "displayName": display_name}

        # Check if user already exists
        existing_user = self.check_user_exists(email)
        if existing_user:
            self.logger.info(f"User {email} already exists (accountId: {existing_user.get('accountId')})")
            self.existing_users.append(
                {
                    "email": email,
                    "displayName": existing_user.get("displayName", display_name),
                    "accountId": existing_user.get("accountId"),
                    "status": "exists",
                }
            )
            return existing_user

        # Invite the user via POST /rest/api/3/user
        user_data = {
            "emailAddress": email,
            "displayName": display_name,
            "products": self.products,  # Grant access to specified products
        }

        response = self._api_call("POST", "user", data=user_data)

        if response:
            user = response.json()
            self.logger.info(f"Invited user: {email} (accountId: {user.get('accountId')})")
            self.created_users.append(
                {"email": email, "displayName": display_name, "accountId": user.get("accountId"), "status": "invited"}
            )
            return user

        # If API call failed, log it
        self.logger.warning(f"Failed to invite user {email}")
        self.created_users.append({"email": email, "displayName": display_name, "status": "failed"})

        return None

    def check_group_exists(self, group_name: str) -> Optional[dict]:
        """Check if a group already exists in Jira"""
        if self.dry_run:
            return None

        response = self._api_call("GET", "group/bulk", params={"groupName": group_name})
        if response:
            groups = response.json().get("values", [])
            for group in groups:
                if group.get("name", "").lower() == group_name.lower():
                    return group
        return None

    def create_group(self, group_name: str) -> Optional[dict]:
        """Create a group in Jira"""
        self.logger.info(f"Processing group: {group_name}")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would check/create group {group_name}")
            self.created_groups.append({"name": group_name, "status": "dry_run"})
            return {"name": group_name}

        # Check if group exists
        existing_group = self.check_group_exists(group_name)
        if existing_group:
            self.logger.info(f"Group {group_name} already exists (groupId: {existing_group.get('groupId')})")
            self.existing_groups.append(
                {"name": group_name, "groupId": existing_group.get("groupId"), "status": "exists"}
            )
            return existing_group

        # Create the group
        group_data = {"name": group_name}
        response = self._api_call("POST", "group", data=group_data)

        if response:
            group = response.json()
            self.logger.info(f"Created group: {group_name}")
            self.created_groups.append({"name": group_name, "groupId": group.get("groupId"), "status": "created"})
            return group

        return None

    def add_user_to_group(self, account_id: str, group_name: str) -> bool:
        """Add a user to a group"""
        self.logger.info(f"Adding user {account_id} to group {group_name}")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would add user to group {group_name}")
            return True

        data = {"accountId": account_id}
        response = self._api_call("POST", "group/user", data=data, params={"groupname": group_name})

        if response:
            self.logger.info(f"Added user to group {group_name}")
            return True

        return False

    def generate_users(self, base_email: str, count: int, prefix: str = "Sandbox") -> list[dict]:
        """Generate multiple sandbox users"""
        self.logger.info(f"Generating {count} sandbox users from {base_email}")

        users = []
        for i in range(1, count + 1):
            email = self.generate_sandbox_email(base_email, i)
            display_name = f"{prefix} User {i}"

            user = self.create_user(email, display_name)
            if user:
                users.append(user)

            time.sleep(0.3)  # Small delay between users

        return users

    def generate_groups(self, group_names: list[str]) -> list[dict]:
        """Generate multiple groups"""
        self.logger.info(f"Generating {len(group_names)} groups")

        groups = []
        for name in group_names:
            group = self.create_group(name)
            if group:
                groups.append(group)

            time.sleep(0.3)

        return groups

    def generate_all(
        self, base_email: str, user_count: int, group_names: Optional[list[str]] = None, user_prefix: str = "Sandbox"
    ):
        """Generate users and optionally groups"""
        self.logger.info("=" * 60)
        self.logger.info("Starting Jira user/group generation")
        self.logger.info(f"Base email: {base_email}")
        self.logger.info(f"User count: {user_count}")
        self.logger.info(f"Products: {', '.join(self.products) if self.products else 'None (org only)'}")
        self.logger.info(f"Groups: {group_names or 'None'}")
        self.logger.info(f"Dry run: {self.dry_run}")
        self.logger.info("=" * 60)

        # Generate email list for reference
        self.logger.info("\nPlanned user emails:")
        for i in range(1, user_count + 1):
            email = self.generate_sandbox_email(base_email, i)
            self.logger.info(f"  {i}. {email}")

        # Create groups first
        if group_names:
            self.logger.info(f"\nCreating {len(group_names)} groups...")
            self.generate_groups(group_names)

        # Create users
        self.logger.info(f"\nCreating {user_count} users...")
        self.generate_users(base_email, user_count, user_prefix)

        # Summary
        self.logger.info("\n" + "=" * 60)
        self.logger.info("Generation complete!")
        self.logger.info("=" * 60)

        # Groups summary
        if self.existing_groups:
            self.logger.info(f"\nGroups already existing: {len(self.existing_groups)}")
            for group in self.existing_groups:
                self.logger.info(f"  - {group.get('name')} (groupId: {group.get('groupId')})")

        created_groups = [g for g in self.created_groups if g.get("status") == "created"]
        if created_groups:
            self.logger.info(f"\nGroups created: {len(created_groups)}")
            for group in created_groups:
                self.logger.info(f"  - {group.get('name')}")

        # Users summary
        if self.existing_users:
            self.logger.info(f"\nUsers already existing: {len(self.existing_users)}")
            for user in self.existing_users:
                self.logger.info(f"  - {user.get('email')} (accountId: {user.get('accountId')})")

        invited_users = [u for u in self.created_users if u.get("status") == "invited"]
        if invited_users:
            self.logger.info(f"\nUsers invited: {len(invited_users)}")
            for user in invited_users:
                self.logger.info(f"  - {user.get('email')} (accountId: {user.get('accountId')})")

        failed_users = [u for u in self.created_users if u.get("status") == "failed"]
        if failed_users:
            self.logger.info(f"\nUsers failed to invite: {len(failed_users)}")
            for user in failed_users:
                self.logger.info(f"  - {user.get('email')}")

        # Final tally
        self.logger.info("\nSummary:")
        self.logger.info(
            f"  Users:  {len(self.existing_users)} existing, {len(invited_users)} invited, {len(failed_users)} failed"
        )
        self.logger.info(f"  Groups: {len(self.existing_groups)} existing, {len(created_groups)} created")


def main():
    parser = argparse.ArgumentParser(
        description="Generate test users and groups for Jira",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 5 sandbox users
  %(prog)s --url https://mycompany.atlassian.net \\
           --email admin@mycompany.com \\
           --base-email user@example.com \\
           --users 5

  # Generate users and groups
  %(prog)s --url https://mycompany.atlassian.net \\
           --email admin@mycompany.com \\
           --base-email user@example.com \\
           --users 10 \\
           --groups "Test Group 1" "Test Group 2"

  # Dry run to see what would be created
  %(prog)s --url https://mycompany.atlassian.net \\
           --email admin@mycompany.com \\
           --base-email user@example.com \\
           --users 5 \\
           --dry-run

Generated emails will be in format:
  user+sandbox1@example.com
  user+sandbox2@example.com
  ...
        """,
    )

    parser.add_argument("--url", help="Jira URL (e.g., https://mycompany.atlassian.net) or set JIRA_URL in .env")
    parser.add_argument("--email", help="Your Jira admin email or set JIRA_EMAIL in .env")
    parser.add_argument("--token", help="Jira API token (or set JIRA_API_TOKEN env var)")
    parser.add_argument("--base-email", required=True, help="Base email for sandbox users (e.g., user@example.com)")
    parser.add_argument("--users", type=int, required=True, help="Number of sandbox users to create")
    parser.add_argument("--groups", nargs="+", help="Group names to create")
    parser.add_argument("--user-prefix", default="Sandbox", help="Display name prefix for users (default: Sandbox)")
    parser.add_argument(
        "--products",
        nargs="+",
        default=["jira-software"],
        choices=["jira-software", "jira-core", "jira-servicedesk", "jira-product-discovery"],
        help="Products to grant access to (default: jira-software). Use --products none for no product access.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without creating it")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Load environment variables from .env file
    load_dotenv()

    # Resolve URL, email, and token from args or environment
    jira_url = args.url or os.environ.get("JIRA_URL")
    if not jira_url:
        print(
            "Error: Jira URL required. Use --url or set JIRA_URL as an environment variable (or in a .env file)",
            file=sys.stderr,
        )
        sys.exit(1)

    jira_email = args.email or os.environ.get("JIRA_EMAIL")
    if not jira_email:
        print(
            "Error: Jira email required. Use --email or set JIRA_EMAIL as an environment variable (or in a .env file)",
            file=sys.stderr,
        )
        sys.exit(1)

    api_token = args.token or os.environ.get("JIRA_API_TOKEN")
    if not api_token:
        print("Error: Jira API token required. Use --token or set JIRA_API_TOKEN", file=sys.stderr)
        sys.exit(1)

    try:
        generator = JiraUserGenerator(
            jira_url=jira_url, email=jira_email, api_token=api_token, products=args.products, dry_run=args.dry_run
        )

        generator.generate_all(
            base_email=args.base_email, user_count=args.users, group_names=args.groups, user_prefix=args.user_prefix
        )

    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
