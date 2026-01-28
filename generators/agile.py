"""
Agile module for boards and sprints.

Uses the Jira Software Cloud REST API (agile API).
"""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Optional

from .base import JiraAPIClient


class AgileGenerator(JiraAPIClient):
    """Generates boards and sprints using Jira Software agile API."""

    # Agile API base URL
    AGILE_API_BASE = None  # Set in __init__

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
        self.AGILE_API_BASE = f"{self.jira_url}/rest/agile/1.0"

        # Track created items
        self.created_boards: list[dict] = []
        self.created_sprints: list[dict] = []

    def _agile_api_call(self, method: str, endpoint: str, data: Optional[dict] = None, params: Optional[dict] = None):
        """Make an API call to the agile API."""
        return self._api_call(method=method, endpoint=endpoint, data=data, params=params, base_url=self.AGILE_API_BASE)

    def get_boards(self, project_key: Optional[str] = None) -> list[dict]:
        """Get existing boards, optionally filtered by project."""
        params = {}
        if project_key:
            params["projectKeyOrId"] = project_key

        if self.dry_run:
            return []

        response = self._agile_api_call("GET", "board", params=params)
        if response:
            return response.json().get("values", [])
        return []

    def create_board(self, name: str, project_key: str, board_type: str = "scrum") -> Optional[dict]:
        """Create a board for a project.

        Args:
            name: Board name
            project_key: Project key to associate with
            board_type: 'scrum', 'kanban', or 'agility'

        Returns:
            Board dict with 'id', 'name', 'type' or None on failure
        """
        self.logger.info(f"Creating {board_type} board '{name}' for project {project_key}...")

        if self.dry_run:
            board = {"id": random.randint(1000, 9999), "name": name, "type": board_type}
            self.created_boards.append(board)
            return board

        # First, we need a filter for the board
        # Create a simple filter that shows all issues in the project
        # Use a unique name with timestamp to avoid conflicts
        filter_name = f"{name} Filter {int(time.time())}"
        # Use simple JQL without Rank field (Rank may not exist in all projects)
        filter_data = {
            "name": filter_name,
            "description": f"Filter for {name} board",
            "jql": f"project = {project_key} ORDER BY created DESC",
            "favourite": False,
        }

        self.logger.info(f"Creating filter '{filter_name}' for board...")
        filter_response = self._api_call("POST", "filter", data=filter_data)
        if not filter_response:
            self.logger.warning(
                f"Could not create filter for board {name}. "
                f"This may be due to API permissions. Run with --verbose to see detailed error."
            )
            return None

        try:
            filter_id = filter_response.json().get("id")
        except Exception as e:
            self.logger.error(f"Error parsing filter response for board {name}: {e}")
            self.logger.error(f"Response text: {filter_response.text}")
            return None

        if not filter_id:
            self.logger.warning(f"Filter created but no ID returned. Response: {filter_response.text}")
            return None

        self.logger.debug(f"Created filter with ID: {filter_id}")

        # Board requires a location to be properly associated with the project
        board_data = {
            "name": name,
            "type": board_type,
            "filterId": int(filter_id),
            "location": {"projectKeyOrId": project_key, "type": "project"},
        }

        response = self._agile_api_call("POST", "board", data=board_data)
        if response:
            board = response.json()
            self.created_boards.append(board)
            self.logger.info(f"Created board: {board.get('name')} (ID: {board.get('id')})")
            return board
        else:
            self.logger.warning(f"Failed to create board {name}")
            return None

    def create_boards(self, project_keys: list[str], count: int) -> list[dict]:
        """Create boards distributed across projects.

        Args:
            project_keys: List of project keys to create boards for
            count: Total number of boards to create

        Returns:
            List of created board dicts
        """
        self.logger.info(f"Creating {count} boards...")

        boards = []
        board_types = ["scrum", "kanban"]

        for i in range(count):
            project_key = project_keys[i % len(project_keys)]
            board_type = board_types[i % len(board_types)]
            name = f"{self.prefix} {board_type.title()} Board {i + 1}"

            board = self.create_board(name, project_key, board_type)
            if board:
                boards.append(board)

            time.sleep(0.3)

        return boards

    def create_sprint(
        self,
        board_id: int,
        name: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        goal: Optional[str] = None,
    ) -> Optional[dict]:
        """Create a sprint for a board.

        Args:
            board_id: ID of the board to create sprint in
            name: Sprint name
            start_date: Sprint start date
            end_date: Sprint end date
            goal: Sprint goal

        Returns:
            Sprint dict with 'id', 'name', 'state' or None on failure
        """
        self.logger.debug(f"Creating sprint '{name}' for board {board_id}...")

        sprint_data = {"name": name, "originBoardId": board_id}

        if start_date:
            sprint_data["startDate"] = start_date.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        if end_date:
            sprint_data["endDate"] = end_date.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        if goal:
            sprint_data["goal"] = goal

        if self.dry_run:
            sprint = {"id": random.randint(1000, 9999), "name": name, "state": "future", "originBoardId": board_id}
            self.created_sprints.append(sprint)
            return sprint

        response = self._agile_api_call("POST", "sprint", data=sprint_data)
        if response:
            sprint = response.json()
            self.created_sprints.append(sprint)
            return sprint
        else:
            self.logger.warning(f"Failed to create sprint {name}")
            return None

    def create_sprints(self, board_ids: list[int], count: int) -> list[dict]:
        """Create sprints distributed across boards.

        Creates sprints with varying dates (past, current, future).

        Args:
            board_ids: List of board IDs to create sprints for
            count: Total number of sprints to create

        Returns:
            List of created sprint dicts
        """
        self.logger.info(f"Creating {count} sprints...")

        if not board_ids:
            self.logger.warning("No boards available for sprint creation")
            return []

        sprints = []
        now = datetime.now()

        for i in range(count):
            board_id = board_ids[i % len(board_ids)]
            sprint_num = i + 1

            # Create sprints with different time periods
            # Some past, some current, some future
            if i % 3 == 0:
                # Past sprint
                start_date = now - timedelta(weeks=4 + i)
                end_date = start_date + timedelta(weeks=2)
                goal = f"Historical sprint {sprint_num}"
            elif i % 3 == 1:
                # Current/recent sprint
                start_date = now - timedelta(weeks=1)
                end_date = now + timedelta(weeks=1)
                goal = f"Active sprint {sprint_num}"
            else:
                # Future sprint
                start_date = now + timedelta(weeks=i)
                end_date = start_date + timedelta(weeks=2)
                goal = f"Upcoming sprint {sprint_num}"

            name = f"{self.prefix} Sprint {sprint_num}"

            sprint = self.create_sprint(
                board_id=board_id, name=name, start_date=start_date, end_date=end_date, goal=goal
            )

            if sprint:
                sprints.append(sprint)
                self.logger.info(f"Created sprint {sprint_num}/{count}: {name}")

            time.sleep(0.2)

        return sprints

    def add_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> int:
        """Add issues to a sprint.

        Args:
            sprint_id: Sprint ID
            issue_keys: List of issue keys to add

        Returns:
            Number of issues successfully added
        """
        if not issue_keys:
            return 0

        self.logger.debug(f"Adding {len(issue_keys)} issues to sprint {sprint_id}...")

        if self.dry_run:
            return len(issue_keys)

        # Move issues to sprint in batches
        batch_size = 50
        added = 0

        for i in range(0, len(issue_keys), batch_size):
            batch = issue_keys[i : i + batch_size]
            data = {"issues": batch}

            response = self._agile_api_call("POST", f"sprint/{sprint_id}/issue", data=data)
            if response is not None:
                added += len(batch)

            time.sleep(0.2)

        return added

    def assign_issues_to_sprints(self, sprint_ids: list[int], issue_keys: list[str]) -> int:
        """Distribute issues across sprints.

        Args:
            sprint_ids: List of sprint IDs
            issue_keys: List of issue keys to distribute

        Returns:
            Total number of issues assigned
        """
        if not sprint_ids or not issue_keys:
            return 0

        self.logger.info(f"Assigning {len(issue_keys)} issues to {len(sprint_ids)} sprints...")

        # Distribute issues roughly evenly across sprints
        # Some issues won't be assigned to any sprint (backlog)
        issues_to_assign = issue_keys[: int(len(issue_keys) * 0.7)]  # 70% get assigned

        total_added = 0
        issues_per_sprint = max(1, len(issues_to_assign) // len(sprint_ids))

        for i, sprint_id in enumerate(sprint_ids):
            start_idx = i * issues_per_sprint
            end_idx = start_idx + issues_per_sprint
            if i == len(sprint_ids) - 1:
                # Last sprint gets remaining issues
                end_idx = len(issues_to_assign)

            sprint_issues = issues_to_assign[start_idx:end_idx]
            added = self.add_issues_to_sprint(sprint_id, sprint_issues)
            total_added += added

        self.logger.info(f"Assigned {total_added} issues to sprints")
        return total_added

    # ========== ASYNC METHODS ==========

    async def _agile_api_call_async(
        self, method: str, endpoint: str, data: Optional[dict] = None, params: Optional[dict] = None
    ) -> tuple[bool, Optional[dict]]:
        """Make an async API call to the agile API."""
        return await self._api_call_async(
            method=method, endpoint=endpoint, data=data, params=params, base_url=self.AGILE_API_BASE
        )

    async def create_sprints_async(self, board_ids: list[int], count: int) -> list[dict]:
        """Create sprints distributed across boards concurrently.

        Args:
            board_ids: List of board IDs to create sprints for
            count: Total number of sprints to create

        Returns:
            List of created sprint dicts
        """
        self.logger.info(f"Creating {count} sprints (concurrency: {self.concurrency})...")

        if not board_ids:
            self.logger.warning("No boards available for sprint creation")
            return []

        now = datetime.now()

        # Pre-generate all sprint data
        tasks = []
        for i in range(count):
            board_id = board_ids[i % len(board_ids)]
            sprint_num = i + 1

            # Create sprints with different time periods
            if i % 3 == 0:
                start_date = now - timedelta(weeks=4 + i)
                end_date = start_date + timedelta(weeks=2)
                goal = f"Historical sprint {sprint_num}"
            elif i % 3 == 1:
                start_date = now - timedelta(weeks=1)
                end_date = now + timedelta(weeks=1)
                goal = f"Active sprint {sprint_num}"
            else:
                start_date = now + timedelta(weeks=i)
                end_date = start_date + timedelta(weeks=2)
                goal = f"Upcoming sprint {sprint_num}"

            sprint_data = {
                "name": f"{self.prefix} Sprint {sprint_num}",
                "originBoardId": board_id,
                "startDate": start_date.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "endDate": end_date.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "goal": goal,
            }
            tasks.append(self._agile_api_call_async("POST", "sprint", data=sprint_data))

        # Execute with progress tracking
        sprints = []
        for i in range(0, len(tasks), self.concurrency * 2):
            batch = tasks[i : i + self.concurrency * 2]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for _idx, result in enumerate(results):
                if isinstance(result, tuple) and result[0] and result[1]:
                    sprint = result[1]
                    sprints.append(sprint)
                    self.created_sprints.append(sprint)
                elif self.dry_run:
                    sprint = {
                        "id": random.randint(1000, 9999),
                        "name": f"{self.prefix} Sprint {len(sprints) + 1}",
                        "state": "future",
                        "originBoardId": board_ids[len(sprints) % len(board_ids)],
                    }
                    sprints.append(sprint)
                    self.created_sprints.append(sprint)
            self.logger.info(f"Created {len(sprints)}/{count} sprints")

        return sprints

    async def add_issues_to_sprint_async(self, sprint_id: int, issue_keys: list[str]) -> int:
        """Add issues to a sprint asynchronously."""
        if not issue_keys:
            return 0

        self.logger.debug(f"Adding {len(issue_keys)} issues to sprint {sprint_id}...")

        if self.dry_run:
            return len(issue_keys)

        # Move issues to sprint in batches
        batch_size = 50
        tasks = []

        for i in range(0, len(issue_keys), batch_size):
            batch = issue_keys[i : i + batch_size]
            data = {"issues": batch}
            tasks.append(self._agile_api_call_async("POST", f"sprint/{sprint_id}/issue", data=data))

        added = 0
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for idx, result in enumerate(results):
            if isinstance(result, tuple) and result[0]:
                batch_start = idx * batch_size
                batch_end = min(batch_start + batch_size, len(issue_keys))
                added += batch_end - batch_start

        return added

    async def assign_issues_to_sprints_async(self, sprint_ids: list[int], issue_keys: list[str]) -> int:
        """Distribute issues across sprints concurrently."""
        if not sprint_ids or not issue_keys:
            return 0

        self.logger.info(f"Assigning {len(issue_keys)} issues to {len(sprint_ids)} sprints...")

        # Distribute issues roughly evenly across sprints (70% get assigned)
        issues_to_assign = issue_keys[: int(len(issue_keys) * 0.7)]
        issues_per_sprint = max(1, len(issues_to_assign) // len(sprint_ids))

        tasks = []
        for i, sprint_id in enumerate(sprint_ids):
            start_idx = i * issues_per_sprint
            end_idx = start_idx + issues_per_sprint
            if i == len(sprint_ids) - 1:
                end_idx = len(issues_to_assign)

            sprint_issues = issues_to_assign[start_idx:end_idx]
            if sprint_issues:
                tasks.append(self.add_issues_to_sprint_async(sprint_id, sprint_issues))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_added = sum(r for r in results if isinstance(r, int))

        self.logger.info(f"Assigned {total_added} issues to sprints")
        return total_added
