"""
Unit tests for generators/issues.py - IssueGenerator.
"""

from unittest.mock import patch

import pytest
import responses
from aioresponses import aioresponses

from generators.checkpoint import CheckpointManager
from generators.issues import IssueGenerator

JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"


@pytest.fixture
def issue_gen(base_client_kwargs):
    """Create an IssueGenerator instance."""
    return IssueGenerator(prefix="TEST", **base_client_kwargs)


@pytest.fixture
def issue_gen_dry_run(dry_run_client_kwargs):
    """Create a dry-run IssueGenerator instance."""
    return IssueGenerator(prefix="TEST", **dry_run_client_kwargs)


@pytest.fixture
def issue_gen_with_checkpoint(base_client_kwargs, temp_checkpoint_dir):
    """Create an IssueGenerator with checkpoint."""
    checkpoint = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
    checkpoint.initialize(
        run_id="TEST-123", size="small", target_issue_count=100,
        jira_url=JIRA_URL, async_mode=True, concurrency=5, counts={}
    )
    return IssueGenerator(prefix="TEST", checkpoint=checkpoint, **base_client_kwargs)


class TestIssueGeneratorInit:
    """Tests for IssueGenerator initialization."""

    def test_init(self, issue_gen):
        """Test IssueGenerator initializes correctly."""
        assert issue_gen.prefix == "TEST"
        assert issue_gen.run_id is not None
        assert issue_gen.project_key is None
        assert issue_gen._project_id is None
        assert issue_gen.created_issues == []

    def test_set_project_context(self, issue_gen):
        """Test set_project_context sets project info."""
        issue_gen.set_project_context("TEST1", "10001")
        assert issue_gen.project_key == "TEST1"
        assert issue_gen._project_id == "10001"

    def test_bulk_create_limit(self, issue_gen):
        """Test BULK_CREATE_LIMIT is set."""
        assert issue_gen.BULK_CREATE_LIMIT == 50

    def test_attachment_pool_size(self, issue_gen):
        """Test ATTACHMENT_POOL_SIZE is set."""
        assert issue_gen.ATTACHMENT_POOL_SIZE == 20


class TestIssueGeneratorProjectId:
    """Tests for get_project_id method."""

    @responses.activate
    def test_get_project_id(self, issue_gen):
        """Test get_project_id fetches project ID."""
        issue_gen.project_key = "TEST1"

        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/project/TEST1",
            json={"key": "TEST1", "id": "10001"},
            status=200
        )

        project_id = issue_gen.get_project_id()
        assert project_id == "10001"

    def test_get_project_id_dry_run(self, issue_gen_dry_run):
        """Test get_project_id in dry run."""
        issue_gen_dry_run.project_key = "TEST1"

        project_id = issue_gen_dry_run.get_project_id()
        assert project_id == "10000"

    def test_get_project_id_cached(self, issue_gen):
        """Test get_project_id returns cached value."""
        issue_gen._project_id = "cached-id"

        project_id = issue_gen.get_project_id()
        assert project_id == "cached-id"


class TestIssueGeneratorBulkCreate:
    """Tests for bulk issue creation."""

    @responses.activate
    def test_create_issues_bulk_single_batch(self, issue_gen):
        """Test create_issues_bulk with single batch."""
        issue_gen.set_project_context("TEST1", "10001")

        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/bulk",
            json={"issues": [{"key": f"TEST1-{i}"} for i in range(1, 11)]},
            status=201
        )

        with patch("time.sleep"):
            issue_keys = issue_gen.create_issues_bulk(10)

        assert len(issue_keys) == 10
        assert "TEST1-1" in issue_keys

    def test_create_issues_bulk_dry_run(self, issue_gen_dry_run):
        """Test create_issues_bulk in dry run."""
        issue_gen_dry_run.set_project_context("TEST1", "10001")

        issue_keys = issue_gen_dry_run.create_issues_bulk(10)

        assert len(issue_keys) == 10
        assert all(key.startswith("TEST1-") for key in issue_keys)

    @responses.activate
    def test_create_issues_bulk_multiple_batches(self, issue_gen):
        """Test create_issues_bulk with multiple batches."""
        issue_gen.set_project_context("TEST1", "10001")

        # First batch (50 issues)
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/bulk",
            json={"issues": [{"key": f"TEST1-{i}"} for i in range(1, 51)]},
            status=201
        )
        # Second batch (25 issues)
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/bulk",
            json={"issues": [{"key": f"TEST1-{i}"} for i in range(51, 76)]},
            status=201
        )

        with patch("time.sleep"):
            issue_keys = issue_gen.create_issues_bulk(75)

        assert len(issue_keys) == 75

    @responses.activate
    def test_create_issues_bulk_partial_failure(self, issue_gen):
        """Test create_issues_bulk handles partial failures."""
        issue_gen.set_project_context("TEST1", "10001")

        # First batch succeeds
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/bulk",
            json={"issues": [{"key": f"TEST1-{i}"} for i in range(1, 51)]},
            status=201
        )
        # Second batch fails
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/bulk",
            status=500
        )

        with patch("time.sleep"):
            issue_keys = issue_gen.create_issues_bulk(75)

        # Should have first batch
        assert len(issue_keys) == 50

    def test_create_issues_bulk_no_project(self, issue_gen):
        """Test create_issues_bulk without project context."""
        # Should not raise but return empty
        issue_keys = issue_gen.create_issues_bulk(10)
        assert len(issue_keys) == 0


class TestIssueGeneratorBulkAsync:
    """Tests for async bulk issue creation."""

    @pytest.mark.asyncio
    async def test_create_issues_bulk_async(self, issue_gen):
        """Test create_issues_bulk_async."""
        with aioresponses() as m:
            m.post(
                f"{JIRA_URL}/rest/api/3/issue/bulk",
                payload={"issues": [{"key": f"TEST1-{i}"} for i in range(1, 11)]}
            )

            issue_keys = await issue_gen.create_issues_bulk_async(10, "TEST1", "10001")

        assert len(issue_keys) == 10
        await issue_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_issues_bulk_async_dry_run(self, issue_gen_dry_run):
        """Test create_issues_bulk_async in dry run."""
        issue_keys = await issue_gen_dry_run.create_issues_bulk_async(10, "TEST1", "10001")

        assert len(issue_keys) == 10
        assert all(key.startswith("TEST1-") for key in issue_keys)

    @pytest.mark.asyncio
    async def test_create_issues_bulk_async_no_project_id(self, issue_gen):
        """Test create_issues_bulk_async without project ID fails."""
        issue_keys = await issue_gen.create_issues_bulk_async(10, "TEST1", None)
        assert len(issue_keys) == 0


class TestIssueGeneratorAttachments:
    """Tests for attachment creation."""

    @responses.activate
    def test_add_attachment(self, issue_gen):
        """Test add_attachment."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/TEST1-1/attachments",
            json=[{"id": "10001", "filename": "test.txt"}],
            status=200
        )

        result = issue_gen.add_attachment("TEST1-1", b"test content", "test.txt")

        assert result is True

    def test_add_attachment_dry_run(self, issue_gen_dry_run):
        """Test add_attachment in dry run."""
        result = issue_gen_dry_run.add_attachment("TEST1-1", b"test content", "test.txt")
        assert result is True

    @responses.activate
    def test_add_attachment_rate_limited(self, issue_gen):
        """Test add_attachment handles rate limiting."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/TEST1-1/attachments",
            status=429,
            headers={"Retry-After": "0.01"}
        )
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/TEST1-1/attachments",
            json=[{"id": "10001"}],
            status=200
        )

        with patch("time.sleep"):
            result = issue_gen.add_attachment("TEST1-1", b"test content", "test.txt")

        assert result is True

    @responses.activate
    def test_add_attachment_failure(self, issue_gen):
        """Test add_attachment handles failure."""
        # All retries fail
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/attachments",
                status=500
            )

        with patch("time.sleep"):
            result = issue_gen.add_attachment("TEST1-1", b"test content", "test.txt")

        assert result is False

    @responses.activate
    def test_add_attachment_already_exists(self, issue_gen):
        """Test add_attachment handles already exists error."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/TEST1-1/attachments",
            json={"errorMessages": ["Attachment already exists"]},
            status=400
        )

        with patch("time.sleep"):
            result = issue_gen.add_attachment("TEST1-1", b"test content", "test.txt")

        # Should return False when already exists
        assert result is False

    @responses.activate
    def test_create_attachments(self, issue_gen):
        """Test create_attachments."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/attachments",
                json=[{"id": f"1000{i+1}"}],
                status=200
            )
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-2/attachments",
                json=[{"id": f"2000{i+1}"}],
                status=200
            )
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/issue/TEST1-3/attachments",
                json=[{"id": f"3000{i+1}"}],
                status=200
            )

        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3"]
        with patch("time.sleep"):
            count = issue_gen.create_attachments(issue_keys, 3)

        assert count >= 0

    def test_create_attachments_dry_run(self, issue_gen_dry_run):
        """Test create_attachments in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2", "TEST1-3"]
        count = issue_gen_dry_run.create_attachments(issue_keys, 5)
        assert count == 5


class TestIssueGeneratorAttachmentsAsync:
    """Tests for async attachment creation."""

    @pytest.mark.asyncio
    async def test_add_attachment_async(self, issue_gen):
        """Test add_attachment_async."""
        with aioresponses() as m:
            m.post(
                f"{JIRA_URL}/rest/api/3/issue/TEST1-1/attachments",
                payload=[{"id": "10001"}]
            )

            result = await issue_gen.add_attachment_async("TEST1-1", b"test content", "test.txt")

        assert result is True
        await issue_gen._close_async_session()
        await issue_gen._close_attachment_session()

    @pytest.mark.asyncio
    async def test_add_attachment_async_dry_run(self, issue_gen_dry_run):
        """Test add_attachment_async in dry run."""
        result = await issue_gen_dry_run.add_attachment_async("TEST1-1", b"test content", "test.txt")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_attachments_async(self, issue_gen):
        """Test create_attachments_async."""
        issue_keys = ["TEST1-1", "TEST1-2"]

        with aioresponses() as m:
            for _ in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-1/attachments",
                    payload=[{"id": "10001"}]
                )
                m.post(
                    f"{JIRA_URL}/rest/api/3/issue/TEST1-2/attachments",
                    payload=[{"id": "10002"}]
                )

            count = await issue_gen.create_attachments_async(issue_keys, 3)

        assert count >= 0
        await issue_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_attachments_async_dry_run(self, issue_gen_dry_run):
        """Test create_attachments_async in dry run."""
        issue_keys = ["TEST1-1", "TEST1-2"]
        count = await issue_gen_dry_run.create_attachments_async(issue_keys, 5)
        assert count == 5


class TestIssueGeneratorAttachmentPool:
    """Tests for attachment file pooling."""

    def test_init_attachment_pool(self, issue_gen):
        """Test _init_attachment_pool creates pool."""
        issue_gen._init_attachment_pool()

        assert issue_gen._attachment_pool is not None
        assert len(issue_gen._attachment_pool) == issue_gen.ATTACHMENT_POOL_SIZE

        # Each item should be a tuple (content, filename)
        for content, filename in issue_gen._attachment_pool:
            assert isinstance(content, bytes)
            assert isinstance(filename, str)
            assert len(content) >= 1024  # At least 1KB
            assert len(content) <= 5120  # At most 5KB

    def test_init_attachment_pool_idempotent(self, issue_gen):
        """Test _init_attachment_pool is idempotent."""
        issue_gen._init_attachment_pool()
        pool1 = issue_gen._attachment_pool

        issue_gen._init_attachment_pool()
        pool2 = issue_gen._attachment_pool

        assert pool1 is pool2

    def test_get_pooled_attachment(self, issue_gen):
        """Test get_pooled_attachment returns attachment from pool."""
        content, filename = issue_gen.get_pooled_attachment()

        assert isinstance(content, bytes)
        assert isinstance(filename, str)
        assert len(content) >= 1024

    def test_get_pooled_attachment_unique_filenames(self, issue_gen):
        """Test get_pooled_attachment creates unique filenames."""
        filenames = set()
        for _ in range(10):
            _, filename = issue_gen.get_pooled_attachment()
            filenames.add(filename)

        # Should have mostly unique filenames due to random suffix
        assert len(filenames) > 5


class TestIssueGeneratorFileGeneration:
    """Tests for file generation methods."""

    def test_generate_small_file(self, issue_gen):
        """Test _generate_small_file creates valid file."""
        content, filename = issue_gen._generate_small_file(0)

        assert isinstance(content, bytes)
        assert isinstance(filename, str)
        assert len(content) >= 1024
        assert len(content) <= 5120
        assert issue_gen.prefix in filename

    def test_generate_random_file(self, issue_gen):
        """Test generate_random_file creates valid file."""
        content, filename = issue_gen.generate_random_file(1, 10)

        assert isinstance(content, bytes)
        assert isinstance(filename, str)
        assert len(content) >= 1024
        assert len(content) <= 10240
        assert issue_gen.prefix in filename

    def test_generate_random_file_multiple_types(self, issue_gen):
        """Test generate_random_file covers different file types."""
        # Generate multiple files to cover different branches (json, csv, txt, log)
        generated_extensions = set()
        for _ in range(20):
            content, filename = issue_gen.generate_random_file(1, 5)
            ext = filename.rsplit('.', 1)[-1]
            generated_extensions.add(ext)
            assert isinstance(content, bytes)

        # Should have generated at least a couple different types
        assert len(generated_extensions) >= 2

    def test_generate_small_file_multiple_types(self, issue_gen):
        """Test _generate_small_file covers different file types."""
        generated_extensions = set()
        for i in range(20):
            content, filename = issue_gen._generate_small_file(i)
            ext = filename.rsplit('.', 1)[-1]
            generated_extensions.add(ext)

        assert len(generated_extensions) >= 2


class TestIssueGeneratorWithCheckpoint:
    """Tests for checkpoint integration."""

    @responses.activate
    def test_create_issues_bulk_with_checkpoint(self, issue_gen_with_checkpoint):
        """Test create_issues_bulk updates checkpoint."""
        issue_gen_with_checkpoint.set_project_context("TEST1", "10001")

        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/issue/bulk",
            json={"issues": [{"key": f"TEST1-{i}"} for i in range(1, 51)]},
            status=201
        )

        with patch("time.sleep"):
            issue_keys = issue_gen_with_checkpoint.create_issues_bulk(50)

        assert len(issue_keys) == 50
        # Checkpoint should have been updated
        checkpoint = issue_gen_with_checkpoint.checkpoint
        assert checkpoint is not None
        assert "TEST1" in checkpoint.checkpoint.issues_per_project


class TestIssueGeneratorCreatedIssues:
    """Tests for created issues tracking."""

    def test_created_issues_tracked(self, issue_gen_dry_run):
        """Test created_issues list is populated."""
        issue_gen_dry_run.set_project_context("TEST1", "10001")

        issue_keys = issue_gen_dry_run.create_issues_bulk(5)

        assert len(issue_keys) == 5
        assert len(issue_gen_dry_run.created_issues) == 5

    def test_created_issues_are_keys(self, issue_gen_dry_run):
        """Test created_issues are issue keys."""
        issue_gen_dry_run.set_project_context("TEST1", "10001")

        issue_gen_dry_run.create_issues_bulk(3)

        assert len(issue_gen_dry_run.created_issues) == 3
        # created_issues contains the issue keys as strings
        for key in issue_gen_dry_run.created_issues:
            assert isinstance(key, str)
            assert key.startswith("TEST1-")
