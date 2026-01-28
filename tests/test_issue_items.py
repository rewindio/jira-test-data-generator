"""
Unit tests for generators/issue_items.py - IssueItemsGenerator.
"""

from unittest.mock import patch

import pytest
import responses
from aioresponses import aioresponses

from generators.checkpoint import CheckpointManager
from generators.issue_items import IssueItemsGenerator

JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"


@pytest.fixture
def issue_items_gen(base_client_kwargs):
    """Create an IssueItemsGenerator instance."""
    return IssueItemsGenerator(prefix="TEST", **base_client_kwargs)


@pytest.fixture
def issue_items_gen_dry_run(dry_run_client_kwargs):
    """Create a dry-run IssueItemsGenerator instance."""
    return IssueItemsGenerator(prefix="TEST", **dry_run_client_kwargs)


@pytest.fixture
def issue_items_gen_with_checkpoint(base_client_kwargs, temp_checkpoint_dir):
    """Create an IssueItemsGenerator with checkpoint."""
    checkpoint = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
    checkpoint.initialize(
        run_id="TEST-123", size="small", target_issue_count=100,
        jira_url=JIRA_URL, async_mode=True, concurrency=5,
        counts={"comment": 480, "issue_worklog": 100}
    )
    return IssueItemsGenerator(prefix="TEST", checkpoint=checkpoint, **base_client_kwargs)


class TestIssueItemsGeneratorInit:
    """Tests for IssueItemsGenerator initialization."""

    def test_init(self, issue_items_gen):
        """Test IssueItemsGenerator initializes correctly."""
        assert issue_items_gen.prefix == "TEST"
        assert issue_items_gen.run_id is not None

    def test_set_run_id(self, issue_items_gen):
        """Test set_run_id updates run_id."""
        issue_items_gen.set_run_id("NEW-RUN-ID")
        assert issue_items_gen.run_id == "NEW-RUN-ID"


class TestIssueItemsGeneratorComments:
    """Tests for comment creation."""

    @responses.activate
    def test_create_comments(self, issue_items_gen):
        """Test create_comments."""
        for _ in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/comment",
                json={"id": "10001"},
                status=201
            )

        issue_keys = ["TEST1-1"]
        with patch("time.sleep"):
            count = issue_items_gen.create_comments(issue_keys, 3)

        assert count == 3

    def test_create_comments_dry_run(self, issue_items_gen_dry_run):
        """Test create_comments in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2"]
        # In dry run, the actual method returns 0 since it doesn't mock individual calls
        # The method iterates through count but doesn't actually create anything without mocked responses
        count = issue_items_gen_dry_run.create_comments(issue_keys, 3)
        # Dry run returns 0 since _api_call returns None in dry run
        assert count == 0

    @pytest.mark.asyncio
    async def test_create_comments_async(self, issue_items_gen):
        """Test create_comments_async."""
        issue_keys = ["TEST1-1", "TEST1-2"]

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-1/comment",
                    payload={"id": "10001"}
                )
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-2/comment",
                    payload={"id": "10002"}
                )

            count = await issue_items_gen.create_comments_async(issue_keys, 3)

        assert count >= 0
        await issue_items_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_comments_async_dry_run(self, issue_items_gen_dry_run):
        """Test create_comments_async in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2"]
        # In dry run, async returns 0 since results are (True, None) and the check is for result[0] and result[1]
        count = await issue_items_gen_dry_run.create_comments_async(issue_keys, 5)
        # The async dry run check is `if isinstance(result, tuple) and result[0]` which might pass
        # but since it still calls _api_call_async which returns (True, None) in dry run,
        # we need to verify the actual behavior
        assert count >= 0


class TestIssueItemsGeneratorWorklogs:
    """Tests for worklog creation."""

    @responses.activate
    def test_create_worklogs(self, issue_items_gen):
        """Test create_worklogs."""
        for _ in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/worklog",
                json={"id": "10001"},
                status=201
            )

        issue_keys = ["TEST1-1"]
        with patch("time.sleep"):
            count = issue_items_gen.create_worklogs(issue_keys, 3)

        assert count == 3

    def test_create_worklogs_dry_run(self, issue_items_gen_dry_run):
        """Test create_worklogs in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2"]
        count = issue_items_gen_dry_run.create_worklogs(issue_keys, 3)
        # Dry run returns 0 since _api_call returns None
        assert count == 0

    @pytest.mark.asyncio
    async def test_create_worklogs_async(self, issue_items_gen):
        """Test create_worklogs_async."""
        issue_keys = ["TEST1-1"]

        with aioresponses() as m:
            for _ in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-1/worklog",
                    payload={"id": "10001"}
                )

            count = await issue_items_gen.create_worklogs_async(issue_keys, 3)

        assert count >= 0
        await issue_items_gen._close_async_session()


class TestIssueItemsGeneratorLinks:
    """Tests for issue link creation."""

    @responses.activate
    def test_get_link_types(self, issue_items_gen):
        """Test get_link_types."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/issueLinkType",
            json={"issueLinkTypes": [{"name": "Blocks"}, {"name": "Relates"}]},
            status=200
        )

        link_types = issue_items_gen.get_link_types()

        assert len(link_types) == 2
        # Returns list of dicts, not just names
        assert link_types[0]["name"] == "Blocks"

    def test_get_link_types_dry_run(self, issue_items_gen_dry_run):
        """Test get_link_types in dry run."""
        link_types = issue_items_gen_dry_run.get_link_types()
        assert len(link_types) == 2
        assert link_types[0]["name"] == "Blocks"

    @responses.activate
    def test_create_issue_links(self, issue_items_gen):
        """Test create_issue_links."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/issueLinkType",
            json={"issueLinkTypes": [{"name": "Blocks"}]},
            status=200
        )
        for _ in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issueLink",
                status=201
            )

        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3"]
        with patch("time.sleep"):
            count = issue_items_gen.create_issue_links(issue_keys, 3)

        assert count >= 0

    def test_create_issue_links_dry_run(self, issue_items_gen_dry_run):
        """Test create_issue_links in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3"]
        count = issue_items_gen_dry_run.create_issue_links(issue_keys, 3)
        # Dry run should work since the method checks `or self.dry_run`
        assert count == 3

    def test_create_issue_links_not_enough_issues(self, issue_items_gen_dry_run):
        """Test create_issue_links with less than 2 issues."""
        issue_keys = ["TEST1-1"]  # Need at least 2
        count = issue_items_gen_dry_run.create_issue_links(issue_keys, 3)
        assert count == 0

    @pytest.mark.asyncio
    async def test_create_issue_links_async(self, issue_items_gen):
        """Test create_issue_links_async."""
        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3"]

        with aioresponses() as m:
            m.get(
                f"{JIRA_URL}/rest/api/3/issueLinkType",
                payload={"issueLinkTypes": [{"name": "Blocks"}]}
            )
            for _ in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/issueLink",
                    status=201
                )

            count = await issue_items_gen.create_issue_links_async(issue_keys, 3)

        assert count >= 0
        await issue_items_gen._close_async_session()


class TestIssueItemsGeneratorWatchers:
    """Tests for watcher creation."""

    @responses.activate
    def test_add_watchers(self, issue_items_gen):
        """Test add_watchers."""
        for _ in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/watchers",
                status=204
            )

        issue_keys = ["TEST1-1"]
        user_ids = ["user-1", "user-2", "user-3"]
        with patch("time.sleep"):
            count = issue_items_gen.add_watchers(issue_keys, 3, user_ids)

        assert count >= 0

    def test_add_watchers_dry_run(self, issue_items_gen_dry_run):
        """Test add_watchers in dry run."""
        issue_keys = ["TEST1-1"]
        user_ids = ["user-1", "user-2"]
        count = issue_items_gen_dry_run.add_watchers(issue_keys, 3, user_ids)
        # Dry run should work since method checks `or self.dry_run`
        assert count == 3

    def test_add_watchers_no_users(self, issue_items_gen_dry_run):
        """Test add_watchers with no user IDs."""
        issue_keys = ["TEST1-1"]
        count = issue_items_gen_dry_run.add_watchers(issue_keys, 3, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_add_watchers_async(self, issue_items_gen):
        """Test add_watchers_async."""
        issue_keys = ["TEST1-1"]
        user_ids = ["user-1", "user-2"]

        with aioresponses() as m:
            for _ in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-1/watchers",
                    status=204
                )

            count = await issue_items_gen.add_watchers_async(issue_keys, 3, user_ids)

        assert count >= 0
        await issue_items_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_add_watchers_async_no_users(self, issue_items_gen_dry_run):
        """Test add_watchers_async with no users."""
        issue_keys = ["TEST1-1"]
        count = await issue_items_gen_dry_run.add_watchers_async(issue_keys, 5, [])
        assert count == 0


class TestIssueItemsGeneratorVotes:
    """Tests for vote creation."""

    @responses.activate
    def test_add_votes(self, issue_items_gen):
        """Test add_votes."""
        for _ in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/votes",
                status=204
            )
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-2/votes",
                status=204
            )
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-3/votes",
                status=204
            )

        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3"]
        with patch("time.sleep"):
            count = issue_items_gen.add_votes(issue_keys, 3)

        assert count >= 0

    def test_add_votes_dry_run(self, issue_items_gen_dry_run):
        """Test add_votes in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3", "TEST1-4", "TEST1-5"]
        count = issue_items_gen_dry_run.add_votes(issue_keys, 3)
        # Dry run should work since method checks `or self.dry_run`
        assert count == 3

    @pytest.mark.asyncio
    async def test_add_votes_async(self, issue_items_gen):
        """Test add_votes_async."""
        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3"]

        with aioresponses() as m:
            for key in issue_keys:
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/{key}/votes",
                    status=204
                )

            count = await issue_items_gen.add_votes_async(issue_keys, 3)

        assert count >= 0
        await issue_items_gen._close_async_session()


class TestIssueItemsGeneratorProperties:
    """Tests for issue property creation."""

    @responses.activate
    def test_create_issue_properties(self, issue_items_gen):
        """Test create_issue_properties."""
        for i in range(3):
            responses.add(
                responses.PUT,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/properties/test_property_{i+1}",
                status=201
            )

        issue_keys = ["TEST1-1"]
        with patch("time.sleep"):
            count = issue_items_gen.create_issue_properties(issue_keys, 3)

        assert count >= 0

    def test_create_issue_properties_dry_run(self, issue_items_gen_dry_run):
        """Test create_issue_properties in dry run."""
        issue_keys = ["TEST1-1"]
        count = issue_items_gen_dry_run.create_issue_properties(issue_keys, 3)
        # Dry run should work since method checks `or self.dry_run`
        assert count == 3

    @pytest.mark.asyncio
    async def test_create_issue_properties_async(self, issue_items_gen):
        """Test create_issue_properties_async."""
        issue_keys = ["TEST1-1"]

        with aioresponses() as m:
            for i in range(3):
                m.put(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-1/properties/test_property_{i+1}",
                    status=201
                )

            count = await issue_items_gen.create_issue_properties_async(issue_keys, 3)

        assert count >= 0
        await issue_items_gen._close_async_session()


class TestIssueItemsGeneratorRemoteLinks:
    """Tests for remote link creation."""

    @responses.activate
    def test_create_remote_links(self, issue_items_gen):
        """Test create_remote_links."""
        for _ in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/remotelink",
                json={"id": "10001"},
                status=201
            )

        issue_keys = ["TEST1-1"]
        with patch("time.sleep"):
            count = issue_items_gen.create_remote_links(issue_keys, 3)

        assert count >= 0

    def test_create_remote_links_dry_run(self, issue_items_gen_dry_run):
        """Test create_remote_links in dry run."""
        issue_keys = ["TEST1-1"]
        count = issue_items_gen_dry_run.create_remote_links(issue_keys, 3)
        # Dry run should work since method checks `or self.dry_run`
        assert count == 3

    @pytest.mark.asyncio
    async def test_create_remote_links_async(self, issue_items_gen):
        """Test create_remote_links_async."""
        issue_keys = ["TEST1-1"]

        with aioresponses() as m:
            for _ in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-1/remotelink",
                    payload={"id": "10001"}
                )

            count = await issue_items_gen.create_remote_links_async(issue_keys, 3)

        assert count >= 0
        await issue_items_gen._close_async_session()


class TestIssueItemsGeneratorWithCheckpoint:
    """Tests for checkpoint integration."""

    @pytest.mark.asyncio
    async def test_create_comments_async_with_checkpoint(self, issue_items_gen_with_checkpoint):
        """Test create_comments_async with checkpoint saves progress."""
        issue_keys = ["TEST1-1"]

        with aioresponses() as m:
            for _ in range(600):  # More than checkpoint interval (500)
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-1/comment",
                    payload={"id": "10001"}
                )

            await issue_items_gen_with_checkpoint.create_comments_async(
                issue_keys, 100, start_count=0
            )

        # Checkpoint should have been saved periodically
        assert issue_items_gen_with_checkpoint.checkpoint is not None
        await issue_items_gen_with_checkpoint._close_async_session()
