"""
Filters and dashboards module.

Handles creation of saved filters and dashboards.
"""

import asyncio
import random
import time
from datetime import datetime
from typing import Optional

from .base import JiraAPIClient


class FilterGenerator(JiraAPIClient):
    """Generates filters and dashboards for Jira."""

    def __init__(
        self,
        jira_url: str,
        email: str,
        api_token: str,
        prefix: str,
        dry_run: bool = False,
        concurrency: int = 5,
        benchmark=None,
        request_delay: float = 0.0,
    ):
        super().__init__(jira_url, email, api_token, dry_run, concurrency, benchmark, request_delay)
        self.prefix = prefix
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Track created items
        self.created_filters: list[dict] = []
        self.created_dashboards: list[dict] = []

    def set_run_id(self, run_id: str):
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    # ========== FILTERS ==========

    def create_filter(
        self, name: str, jql: str, description: Optional[str] = None, favourite: bool = False
    ) -> Optional[dict]:
        """Create a saved filter.

        Args:
            name: Filter name
            jql: JQL query string
            description: Filter description
            favourite: Whether to mark as favourite

        Returns:
            Filter dict with 'id', 'name', 'jql' or None on failure
        """
        filter_data = {"name": name, "jql": jql, "favourite": favourite}

        if description:
            filter_data["description"] = description

        if self.dry_run:
            filter_obj = {"id": str(random.randint(10000, 99999)), "name": name, "jql": jql}
            self.created_filters.append(filter_obj)
            return filter_obj

        response = self._api_call("POST", "filter", data=filter_data)
        if response:
            filter_obj = response.json()
            self.created_filters.append(filter_obj)
            return filter_obj
        return None

    def create_filters(self, project_keys: list[str], count: int) -> list[dict]:
        """Create multiple filters with varying JQL queries.

        Args:
            project_keys: List of project keys to use in JQL
            count: Number of filters to create

        Returns:
            List of created filter dicts
        """
        self.logger.info(f"Creating {count} filters...")

        filters = []

        # JQL query templates
        jql_templates = [
            "project = {project} ORDER BY created DESC",
            "project = {project} AND status = 'To Do'",
            "project = {project} AND status = 'In Progress'",
            "project = {project} AND status = 'Done'",
            "project = {project} AND priority = High",
            "project = {project} AND created >= -7d",
            "project = {project} AND updated >= -1d",
            "project = {project} AND assignee = currentUser()",
            "project = {project} AND reporter = currentUser()",
            "project = {project} AND labels = '{prefix}'",
            "project IN ({projects}) AND type = Task",
            "project IN ({projects}) AND resolution = Unresolved",
            "labels = '{run_id}'",
        ]

        for i in range(count):
            project = random.choice(project_keys)
            template = jql_templates[i % len(jql_templates)]

            # Fill in template
            jql = template.format(
                project=project, projects=", ".join(project_keys), prefix=self.prefix, run_id=self.run_id
            )

            name = f"{self.prefix} Filter {i + 1}"
            description = f"Test filter - {self.generate_random_text(5, 10)}"

            filter_obj = self.create_filter(
                name=name, jql=jql, description=description, favourite=random.choice([True, False])
            )

            if filter_obj:
                filters.append(filter_obj)
                self.logger.info(f"Created filter {i + 1}/{count}: {name}")

            time.sleep(0.2)

        return filters

    # ========== DASHBOARDS ==========

    def create_dashboard(
        self, name: str, description: Optional[str] = None, share_permissions: Optional[list[dict]] = None
    ) -> Optional[dict]:
        """Create a dashboard.

        Args:
            name: Dashboard name
            description: Dashboard description
            share_permissions: List of share permission objects

        Returns:
            Dashboard dict with 'id', 'name' or None on failure
        """
        dashboard_data = {"name": name}

        if description:
            dashboard_data["description"] = description

        if share_permissions:
            dashboard_data["sharePermissions"] = share_permissions
        else:
            # Default to private
            dashboard_data["sharePermissions"] = []

        if self.dry_run:
            dashboard = {"id": str(random.randint(10000, 99999)), "name": name}
            self.created_dashboards.append(dashboard)
            return dashboard

        response = self._api_call("POST", "dashboard", data=dashboard_data)
        if response:
            dashboard = response.json()
            self.created_dashboards.append(dashboard)
            return dashboard
        return None

    def create_dashboards(self, count: int) -> list[dict]:
        """Create multiple dashboards.

        Args:
            count: Number of dashboards to create

        Returns:
            List of created dashboard dicts
        """
        self.logger.info(f"Creating {count} dashboards...")

        dashboards = []

        dashboard_types = [
            "Overview",
            "Sprint Progress",
            "Team Metrics",
            "Bug Tracker",
            "Release Status",
            "Performance",
            "Quality",
            "Velocity",
        ]

        for i in range(count):
            dashboard_type = dashboard_types[i % len(dashboard_types)]
            name = f"{self.prefix} {dashboard_type} Dashboard {i + 1}"
            description = f"Test dashboard for {dashboard_type.lower()} - {self.generate_random_text(5, 10)}"

            # Vary share permissions (private or authenticated only - global/public is disabled on most instances)
            if i % 2 == 0:
                share_permissions = []
            else:
                share_permissions = [{"type": "authenticated"}]

            dashboard = self.create_dashboard(name=name, description=description, share_permissions=share_permissions)

            if dashboard:
                dashboards.append(dashboard)
                self.logger.info(f"Created dashboard {i + 1}/{count}: {name}")

            time.sleep(0.2)

        return dashboards

    def add_gadget_to_dashboard(
        self, dashboard_id: str, gadget_uri: str, position: Optional[dict] = None, title: Optional[str] = None
    ) -> Optional[dict]:
        """Add a gadget to a dashboard.

        Note: This requires knowing the gadget URIs available in the instance.

        Args:
            dashboard_id: Dashboard ID
            gadget_uri: URI of the gadget to add
            position: Position dict with 'column' and 'row'
            title: Custom title for the gadget

        Returns:
            Gadget dict or None on failure
        """
        gadget_data = {"moduleKey": gadget_uri}

        if position:
            gadget_data["position"] = position
        if title:
            gadget_data["title"] = title

        if self.dry_run:
            return {"id": str(random.randint(10000, 99999)), "moduleKey": gadget_uri}

        response = self._api_call("POST", f"dashboard/{dashboard_id}/gadget", data=gadget_data)
        if response:
            return response.json()
        return None

    # ========== ASYNC METHODS ==========

    async def create_filters_async(self, project_keys: list[str], count: int) -> list[dict]:
        """Create multiple filters with varying JQL queries concurrently.

        Args:
            project_keys: List of project keys to use in JQL
            count: Number of filters to create

        Returns:
            List of created filter dicts
        """
        self.logger.info(f"Creating {count} filters (concurrency: {self.concurrency})...")

        jql_templates = [
            "project = {project} ORDER BY created DESC",
            "project = {project} AND status = 'To Do'",
            "project = {project} AND status = 'In Progress'",
            "project = {project} AND status = 'Done'",
            "project = {project} AND priority = High",
            "project = {project} AND created >= -7d",
            "project = {project} AND updated >= -1d",
            "project = {project} AND assignee = currentUser()",
            "project = {project} AND reporter = currentUser()",
            "project = {project} AND labels = '{prefix}'",
            "project IN ({projects}) AND type = Task",
            "project IN ({projects}) AND resolution = Unresolved",
            "labels = '{run_id}'",
        ]

        # Pre-generate all filter data
        tasks = []
        for i in range(count):
            project = random.choice(project_keys)
            template = jql_templates[i % len(jql_templates)]

            jql = template.format(
                project=project, projects=", ".join(project_keys), prefix=self.prefix, run_id=self.run_id
            )

            filter_data = {
                "name": f"{self.prefix} Filter {i + 1}",
                "jql": jql,
                "description": f"Test filter - {self.generate_random_text(5, 10)}",
                "favourite": random.choice([True, False]),
            }
            tasks.append(self._api_call_async("POST", "filter", data=filter_data))

        # Execute with progress tracking
        filters = []
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i : i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0] and result[1]:
                    filter_obj = result[1]
                    filters.append(filter_obj)
                    self.created_filters.append(filter_obj)
                elif self.dry_run:
                    filter_obj = {
                        "id": str(random.randint(10000, 99999)),
                        "name": f"{self.prefix} Filter {len(filters) + 1}",
                        "jql": "project = TEST",
                    }
                    filters.append(filter_obj)
                    self.created_filters.append(filter_obj)
            self.logger.info(f"Created {len(filters)}/{count} filters")

        return filters

    async def create_dashboards_async(self, count: int) -> list[dict]:
        """Create multiple dashboards concurrently.

        Args:
            count: Number of dashboards to create

        Returns:
            List of created dashboard dicts
        """
        self.logger.info(f"Creating {count} dashboards (concurrency: {self.concurrency})...")

        dashboard_types = [
            "Overview",
            "Sprint Progress",
            "Team Metrics",
            "Bug Tracker",
            "Release Status",
            "Performance",
            "Quality",
            "Velocity",
        ]

        # Pre-generate all dashboard data
        tasks = []
        for i in range(count):
            dashboard_type = dashboard_types[i % len(dashboard_types)]
            name = f"{self.prefix} {dashboard_type} Dashboard {i + 1}"
            description = f"Test dashboard for {dashboard_type.lower()} - {self.generate_random_text(5, 10)}"

            # Vary share permissions (private or authenticated only - global/public is disabled on most instances)
            if i % 2 == 0:
                share_permissions = []
            else:
                share_permissions = [{"type": "authenticated"}]

            dashboard_data = {"name": name, "description": description, "sharePermissions": share_permissions}
            tasks.append(self._api_call_async("POST", "dashboard", data=dashboard_data))

        # Execute with progress tracking
        dashboards = []
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i : i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0] and result[1]:
                    dashboard = result[1]
                    dashboards.append(dashboard)
                    self.created_dashboards.append(dashboard)
                elif self.dry_run:
                    dashboard = {
                        "id": str(random.randint(10000, 99999)),
                        "name": f"{self.prefix} Dashboard {len(dashboards) + 1}",
                    }
                    dashboards.append(dashboard)
                    self.created_dashboards.append(dashboard)
            self.logger.info(f"Created {len(dashboards)}/{count} dashboards")

        return dashboards
