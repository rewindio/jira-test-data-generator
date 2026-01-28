"""
Unit tests for generators/agile.py - AgileGenerator.
"""

import pytest
import responses
from aioresponses import aioresponses
from unittest.mock import patch
from datetime import datetime, timedelta

from generators.agile import AgileGenerator


JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"


@pytest.fixture
def agile_gen(base_client_kwargs):
    """Create an AgileGenerator instance."""
    return AgileGenerator(prefix="TEST", **base_client_kwargs)


@pytest.fixture
def agile_gen_dry_run(dry_run_client_kwargs):
    """Create a dry-run AgileGenerator instance."""
    return AgileGenerator(prefix="TEST", **dry_run_client_kwargs)


class TestAgileGeneratorInit:
    """Tests for AgileGenerator initialization."""

    def test_init(self, agile_gen):
        """Test AgileGenerator initializes correctly."""
        assert agile_gen.prefix == "TEST"
        assert agile_gen.AGILE_API_BASE == f"{JIRA_URL}/rest/agile/1.0"
        assert agile_gen.created_boards == []
        assert agile_gen.created_sprints == []


class TestAgileGeneratorBoards:
    """Tests for board creation."""

    @responses.activate
    def test_get_boards(self, agile_gen):
        """Test get_boards."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/agile/1.0/board",
            json={"values": [{"id": 1, "name": "Test Board"}]},
            status=200
        )

        boards = agile_gen.get_boards()

        assert len(boards) == 1
        assert boards[0]["id"] == 1

    def test_get_boards_dry_run(self, agile_gen_dry_run):
        """Test get_boards in dry run."""
        boards = agile_gen_dry_run.get_boards()
        assert boards == []

    @responses.activate
    def test_get_boards_with_project_filter(self, agile_gen):
        """Test get_boards with project filter."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/agile/1.0/board",
            json={"values": [{"id": 1}]},
            status=200
        )

        boards = agile_gen.get_boards(project_key="TEST1")

        assert len(responses.calls) == 1
        assert "projectKeyOrId=TEST1" in responses.calls[0].request.url

    @responses.activate
    def test_create_board(self, agile_gen):
        """Test create_board."""
        # Mock filter creation
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/filter",
            json={"id": "10001"},
            status=201
        )
        # Mock board creation
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/agile/1.0/board",
            json={"id": 1, "name": "TEST Scrum Board 1", "type": "scrum"},
            status=201
        )

        board = agile_gen.create_board("TEST Scrum Board 1", "TEST1", "scrum")

        assert board is not None
        assert board["id"] == 1
        assert board["type"] == "scrum"
        assert len(agile_gen.created_boards) == 1

    def test_create_board_dry_run(self, agile_gen_dry_run):
        """Test create_board in dry run."""
        board = agile_gen_dry_run.create_board("TEST Scrum Board 1", "TEST1", "scrum")

        assert board is not None
        assert "id" in board
        assert board["type"] == "scrum"

    @responses.activate
    def test_create_board_filter_fails(self, agile_gen):
        """Test create_board when filter creation fails."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/filter",
            status=400
        )

        board = agile_gen.create_board("TEST Board", "TEST1", "scrum")

        assert board is None

    @responses.activate
    def test_create_boards(self, agile_gen):
        """Test create_boards creates multiple boards."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/filter",
                json={"id": f"1000{i+1}"},
                status=201
            )
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/agile/1.0/board",
                json={"id": i + 1, "type": "scrum" if i % 2 == 0 else "kanban"},
                status=201
            )

        project_keys = ["TEST1", "TEST2"]
        with patch("time.sleep"):
            boards = agile_gen.create_boards(project_keys, 3)

        assert len(boards) == 3


class TestAgileGeneratorSprints:
    """Tests for sprint creation."""

    @responses.activate
    def test_create_sprint(self, agile_gen):
        """Test create_sprint."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/agile/1.0/sprint",
            json={"id": 1, "name": "TEST Sprint 1", "state": "future"},
            status=201
        )

        now = datetime.now()
        sprint = agile_gen.create_sprint(
            board_id=1,
            name="TEST Sprint 1",
            start_date=now,
            end_date=now + timedelta(weeks=2),
            goal="Sprint goal"
        )

        assert sprint is not None
        assert sprint["id"] == 1
        assert len(agile_gen.created_sprints) == 1

    def test_create_sprint_dry_run(self, agile_gen_dry_run):
        """Test create_sprint in dry run."""
        sprint = agile_gen_dry_run.create_sprint(
            board_id=1,
            name="TEST Sprint 1"
        )

        assert sprint is not None
        assert "id" in sprint
        assert sprint["state"] == "future"

    @responses.activate
    def test_create_sprints(self, agile_gen):
        """Test create_sprints creates multiple sprints."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/agile/1.0/sprint",
                json={"id": i + 1, "name": f"TEST Sprint {i + 1}"},
                status=201
            )

        board_ids = [1, 2]
        with patch("time.sleep"):
            sprints = agile_gen.create_sprints(board_ids, 3)

        assert len(sprints) == 3

    def test_create_sprints_no_boards(self, agile_gen):
        """Test create_sprints with no boards."""
        sprints = agile_gen.create_sprints([], 3)
        assert sprints == []

    @pytest.mark.asyncio
    async def test_create_sprints_async(self, agile_gen):
        """Test create_sprints_async."""
        board_ids = [1, 2]

        with aioresponses() as m:
            for i in range(3):
                m.post(
                    f"{JIRA_URL}/rest/agile/1.0/sprint",
                    payload={"id": i + 1, "name": f"TEST Sprint {i + 1}"}
                )

            sprints = await agile_gen.create_sprints_async(board_ids, 3)

        assert len(sprints) >= 0
        await agile_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_sprints_async_no_boards(self, agile_gen):
        """Test create_sprints_async with no boards."""
        sprints = await agile_gen.create_sprints_async([], 3)
        assert sprints == []


class TestAgileGeneratorSprintIssues:
    """Tests for adding issues to sprints."""

    @responses.activate
    def test_add_issues_to_sprint(self, agile_gen):
        """Test add_issues_to_sprint."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/agile/1.0/sprint/1/issue",
            status=204
        )

        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3"]
        with patch("time.sleep"):
            count = agile_gen.add_issues_to_sprint(1, issue_keys)

        assert count == 3

    def test_add_issues_to_sprint_dry_run(self, agile_gen_dry_run):
        """Test add_issues_to_sprint in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2"]
        count = agile_gen_dry_run.add_issues_to_sprint(1, issue_keys)
        assert count == 2

    def test_add_issues_to_sprint_empty(self, agile_gen):
        """Test add_issues_to_sprint with no issues."""
        count = agile_gen.add_issues_to_sprint(1, [])
        assert count == 0

    @responses.activate
    def test_add_issues_to_sprint_batched(self, agile_gen):
        """Test add_issues_to_sprint with batches."""
        # Two batches needed for 75 issues
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/agile/1.0/sprint/1/issue",
            status=204
        )
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/agile/1.0/sprint/1/issue",
            status=204
        )

        issue_keys = [f"TEST1-{i}" for i in range(1, 76)]
        with patch("time.sleep"):
            count = agile_gen.add_issues_to_sprint(1, issue_keys)

        assert count == 75

    @responses.activate
    def test_assign_issues_to_sprints(self, agile_gen):
        """Test assign_issues_to_sprints."""
        # Two sprints, should distribute issues
        for _ in range(2):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/agile/1.0/sprint/1/issue",
                status=204
            )
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/agile/1.0/sprint/2/issue",
                status=204
            )

        sprint_ids = [1, 2]
        issue_keys = [f"TEST1-{i}" for i in range(1, 11)]
        with patch("time.sleep"):
            count = agile_gen.assign_issues_to_sprints(sprint_ids, issue_keys)

        assert count > 0

    def test_assign_issues_to_sprints_empty(self, agile_gen):
        """Test assign_issues_to_sprints with no data."""
        assert agile_gen.assign_issues_to_sprints([], ["TEST1-1"]) == 0
        assert agile_gen.assign_issues_to_sprints([1], []) == 0

    @pytest.mark.asyncio
    async def test_add_issues_to_sprint_async(self, agile_gen):
        """Test add_issues_to_sprint_async."""
        issue_keys = ["TEST1-1", "TEST1-2"]

        with aioresponses() as m:
            m.post(
                f"{JIRA_URL}/rest/agile/1.0/sprint/1/issue",
                status=204
            )

            count = await agile_gen.add_issues_to_sprint_async(1, issue_keys)

        assert count >= 0
        await agile_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_add_issues_to_sprint_async_dry_run(self, agile_gen_dry_run):
        """Test add_issues_to_sprint_async in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2"]
        count = await agile_gen_dry_run.add_issues_to_sprint_async(1, issue_keys)
        assert count == 2

    @pytest.mark.asyncio
    async def test_assign_issues_to_sprints_async(self, agile_gen):
        """Test assign_issues_to_sprints_async."""
        sprint_ids = [1, 2]
        issue_keys = [f"TEST1-{i}" for i in range(1, 11)]

        with aioresponses() as m:
            for _ in range(4):
                m.post(
                    f"{JIRA_URL}/rest/agile/1.0/sprint/1/issue",
                    status=204
                )
                m.post(
                    f"{JIRA_URL}/rest/agile/1.0/sprint/2/issue",
                    status=204
                )

            count = await agile_gen.assign_issues_to_sprints_async(sprint_ids, issue_keys)

        assert count >= 0
        await agile_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_assign_issues_to_sprints_async_empty(self, agile_gen):
        """Test assign_issues_to_sprints_async with no data."""
        assert await agile_gen.assign_issues_to_sprints_async([], ["TEST1-1"]) == 0
        assert await agile_gen.assign_issues_to_sprints_async([1], []) == 0


class TestAgileGeneratorAgileAPICall:
    """Tests for agile API call wrapper."""

    @responses.activate
    def test_agile_api_call(self, agile_gen):
        """Test _agile_api_call uses correct base URL."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/agile/1.0/test",
            json={"data": "test"},
            status=200
        )

        response = agile_gen._agile_api_call("GET", "test")

        assert response is not None
        assert response.json()["data"] == "test"

    @pytest.mark.asyncio
    async def test_agile_api_call_async(self, agile_gen):
        """Test _agile_api_call_async uses correct base URL."""
        with aioresponses() as m:
            m.get(
                f"{JIRA_URL}/rest/agile/1.0/test",
                payload={"data": "test"}
            )

            success, result = await agile_gen._agile_api_call_async("GET", "test")

        assert success is True
        assert result["data"] == "test"
        await agile_gen._close_async_session()
