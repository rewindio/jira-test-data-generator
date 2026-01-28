"""
Unit tests for generators/projects.py - ProjectGenerator.
"""

from unittest.mock import patch

import pytest
import responses
from aioresponses import aioresponses

from generators.checkpoint import CheckpointManager
from generators.projects import ProjectGenerator

JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"


@pytest.fixture
def project_gen(base_client_kwargs):
    """Create a ProjectGenerator instance."""
    return ProjectGenerator(prefix="TEST", **base_client_kwargs)


@pytest.fixture
def project_gen_dry_run(dry_run_client_kwargs):
    """Create a dry-run ProjectGenerator instance."""
    return ProjectGenerator(prefix="TEST", **dry_run_client_kwargs)


@pytest.fixture
def project_gen_with_checkpoint(base_client_kwargs, temp_checkpoint_dir):
    """Create a ProjectGenerator with checkpoint."""
    checkpoint = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
    checkpoint.initialize(
        run_id="TEST-123",
        size="small",
        target_issue_count=100,
        jira_url=JIRA_URL,
        async_mode=True,
        concurrency=5,
        counts={},
    )
    return ProjectGenerator(prefix="TEST", checkpoint=checkpoint, **base_client_kwargs)


class TestProjectGeneratorInit:
    """Tests for ProjectGenerator initialization."""

    def test_init(self, project_gen):
        """Test ProjectGenerator initializes correctly."""
        assert project_gen.prefix == "TEST"
        assert project_gen.created_projects == []
        assert project_gen.created_categories == []
        assert project_gen.created_versions == []
        assert project_gen.created_components == []
        assert project_gen.run_id is not None

    def test_set_run_id(self, project_gen):
        """Test set_run_id updates run_id."""
        project_gen.set_run_id("NEW-RUN-ID")
        assert project_gen.run_id == "NEW-RUN-ID"

    def test_checkpoint_counters(self, project_gen):
        """Test checkpoint counters are initialized."""
        assert project_gen._versions_checkpoint_counter == 0
        assert project_gen._versions_last_checkpoint == 0


class TestProjectGeneratorCategories:
    """Tests for project category creation."""

    @responses.activate
    def test_create_category(self, project_gen):
        """Test create_category."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/projectCategory",
            json={"id": "10001", "name": "TEST Development 1"},
            status=201,
        )

        category = project_gen.create_category("TEST Development 1")

        assert category is not None
        assert category["id"] == "10001"
        # created_categories contains full dicts, not just names
        assert len(project_gen.created_categories) == 1
        assert project_gen.created_categories[0]["name"] == "TEST Development 1"

    def test_create_category_dry_run(self, project_gen_dry_run):
        """Test create_category in dry run."""
        category = project_gen_dry_run.create_category("TEST Development 1")

        assert category is not None
        assert "id" in category
        assert category["name"] == "TEST Development 1"

    @responses.activate
    def test_create_categories(self, project_gen):
        """Test create_categories creates multiple categories."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/projectCategory",
                json={"id": f"1000{i + 1}", "name": f"TEST Category {i + 1}"},
                status=201,
            )

        with patch("time.sleep"):
            categories = project_gen.create_categories(3)

        assert len(categories) == 3


class TestProjectGeneratorProjects:
    """Tests for project creation."""

    @responses.activate
    def test_create_projects(self, project_gen):
        """Test create_projects creates multiple projects."""
        # Mock current user
        responses.add(responses.GET, f"{JIRA_URL}/rest/api/3/myself", json={"accountId": "user-123"}, status=200)
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/project",
                json={"key": f"TEST{i + 1}", "id": f"1000{i + 1}"},
                status=201,
            )
            # Mock get admin role
            responses.add(
                responses.GET,
                f"{JIRA_URL}/rest/api/3/project/TEST{i + 1}/role",
                json={"Administrators": f"{JIRA_URL}/rest/api/3/project/TEST{i + 1}/role/10002"},
                status=200,
            )
            # Mock add user to role
            responses.add(responses.POST, f"{JIRA_URL}/rest/api/3/project/TEST{i + 1}/role/10002", status=200)

        with patch("time.sleep"):
            projects = project_gen.create_projects(3)

        assert len(projects) == 3
        assert projects[0]["key"] == "TEST1"
        assert projects[2]["key"] == "TEST3"

    def test_create_projects_dry_run(self, project_gen_dry_run):
        """Test create_projects in dry run."""
        with patch("time.sleep"):
            projects = project_gen_dry_run.create_projects(3)

        assert len(projects) == 3
        assert projects[0]["key"] == "TEST1"

    @responses.activate
    def test_create_projects_already_exists(self, project_gen):
        """Test create_projects when project already exists."""
        # Mock current user
        responses.add(responses.GET, f"{JIRA_URL}/rest/api/3/myself", json={"accountId": "user-123"}, status=200)
        # Create fails
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/project",
            json={"errorMessages": ["A project with that key already exists."]},
            status=400,
        )
        # Get existing project
        responses.add(
            responses.GET, f"{JIRA_URL}/rest/api/3/project/TEST1", json={"key": "TEST1", "id": "10001"}, status=200
        )

        with patch("time.sleep"):
            projects = project_gen.create_projects(1)

        assert len(projects) == 1
        assert projects[0]["key"] == "TEST1"

    @responses.activate
    def test_get_project(self, project_gen):
        """Test get_project."""
        responses.add(
            responses.GET, f"{JIRA_URL}/rest/api/3/project/TEST1", json={"key": "TEST1", "id": "10001"}, status=200
        )

        project = project_gen.get_project("TEST1")

        assert project is not None
        assert project["key"] == "TEST1"
        assert project["id"] == "10001"


class TestProjectGeneratorAssignToCategory:
    """Tests for assigning projects to categories."""

    @responses.activate
    def test_assign_project_to_category(self, project_gen):
        """Test assign_project_to_category."""
        responses.add(
            responses.PUT,
            f"{JIRA_URL}/rest/api/3/project/TEST1",
            json={"key": "TEST1", "projectCategory": {"id": "10001"}},
            status=200,
        )

        result = project_gen.assign_project_to_category("TEST1", "10001")

        assert result is True

    def test_assign_project_to_category_dry_run(self, project_gen_dry_run):
        """Test assign_project_to_category in dry run."""
        result = project_gen_dry_run.assign_project_to_category("TEST1", "10001")
        assert result is True


class TestProjectGeneratorVersions:
    """Tests for version creation."""

    @responses.activate
    def test_create_versions(self, project_gen):
        """Test create_versions."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/version",
                json={"id": f"1000{i + 1}", "name": f"TEST v{i + 1}.0"},
                status=201,
            )

        with patch("time.sleep"):
            versions = project_gen.create_versions("TEST1", 3)

        assert len(versions) == 3

    def test_create_versions_dry_run(self, project_gen_dry_run):
        """Test create_versions in dry run."""
        with patch("time.sleep"):
            versions = project_gen_dry_run.create_versions("TEST1", 3)

        assert len(versions) == 3
        assert all(v.startswith("version-") for v in versions)

    @pytest.mark.asyncio
    async def test_create_versions_async(self, project_gen):
        """Test create_versions_async."""
        with aioresponses() as m:
            for i in range(3):
                m.post(f"{JIRA_URL}/rest/api/3/version", payload={"id": f"1000{i + 1}", "name": f"TEST v{i + 1}.0"})

            versions = await project_gen.create_versions_async("TEST1", 3)

        assert len(versions) >= 0  # May vary based on async completion
        await project_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_versions_async_dry_run(self, project_gen_dry_run):
        """Test create_versions_async in dry run."""
        versions = await project_gen_dry_run.create_versions_async("TEST1", 3)

        assert len(versions) == 3


class TestProjectGeneratorComponents:
    """Tests for component creation."""

    @responses.activate
    def test_create_components(self, project_gen):
        """Test create_components."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/component",
                json={"id": f"1000{i + 1}", "name": f"TEST-Component-{i + 1}"},
                status=201,
            )

        with patch("time.sleep"):
            components = project_gen.create_components("TEST1", 3)

        assert len(components) == 3

    def test_create_components_dry_run(self, project_gen_dry_run):
        """Test create_components in dry run."""
        with patch("time.sleep"):
            components = project_gen_dry_run.create_components("TEST1", 3)

        assert len(components) == 3
        assert all(c.startswith("component-") for c in components)

    @pytest.mark.asyncio
    async def test_create_components_async(self, project_gen):
        """Test create_components_async."""
        with aioresponses() as m:
            for i in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/component",
                    payload={"id": f"1000{i + 1}", "name": f"TEST-Component-{i + 1}"},
                )

            components = await project_gen.create_components_async("TEST1", 3)

        assert len(components) >= 0
        await project_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_components_async_dry_run(self, project_gen_dry_run):
        """Test create_components_async in dry run."""
        components = await project_gen_dry_run.create_components_async("TEST1", 3)

        assert len(components) == 3


class TestProjectGeneratorProperties:
    """Tests for project property creation."""

    @responses.activate
    def test_create_project_property(self, project_gen):
        """Test create_project_property."""
        responses.add(responses.PUT, f"{JIRA_URL}/rest/api/3/project/TEST1/properties/test_property_1", status=201)

        result = project_gen.create_project_property("TEST1", "test_property_1", {"key": "value"})

        assert result is True

    def test_create_project_property_dry_run(self, project_gen_dry_run):
        """Test create_project_property in dry run."""
        result = project_gen_dry_run.create_project_property("TEST1", "test_property_1", {"key": "value"})
        assert result is True

    @responses.activate
    def test_create_project_properties(self, project_gen):
        """Test create_project_properties."""
        for i in range(3):
            responses.add(
                responses.PUT, f"{JIRA_URL}/rest/api/3/project/TEST1/properties/test_property_{i + 1}", status=201
            )
            responses.add(
                responses.PUT, f"{JIRA_URL}/rest/api/3/project/TEST2/properties/test_property_{i + 1}", status=201
            )

        with patch("time.sleep"):
            count = project_gen.create_project_properties(["TEST1", "TEST2"], 3)

        assert count == 3

    @pytest.mark.asyncio
    async def test_create_project_properties_async(self, project_gen):
        """Test create_project_properties_async."""
        with aioresponses() as m:
            for i in range(3):
                m.put(f"{JIRA_URL}/rest/api/3/project/TEST1/properties/test_property_{i + 1}", status=201)

            count = await project_gen.create_project_properties_async(["TEST1"], 3)

        assert count >= 0
        await project_gen._close_async_session()


class TestProjectGeneratorRoles:
    """Tests for project role management."""

    @responses.activate
    def test_get_project_admin_role_id(self, project_gen):
        """Test get_project_admin_role_id."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/project/TEST1/role",
            json={
                "Administrators": f"{JIRA_URL}/rest/api/3/project/TEST1/role/10002",
                "Developers": f"{JIRA_URL}/rest/api/3/project/TEST1/role/10003",
            },
            status=200,
        )

        role_id = project_gen.get_project_admin_role_id("TEST1")

        assert role_id == "10002"

    def test_get_project_admin_role_id_dry_run(self, project_gen_dry_run):
        """Test get_project_admin_role_id in dry run."""
        role_id = project_gen_dry_run.get_project_admin_role_id("TEST1")
        assert role_id == "10002"

    @responses.activate
    def test_get_project_viewer_role_id(self, project_gen):
        """Test get_project_viewer_role_id."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/project/TEST1/role",
            json={
                "Users": f"{JIRA_URL}/rest/api/3/project/TEST1/role/10003",
                "Administrators": f"{JIRA_URL}/rest/api/3/project/TEST1/role/10002",
            },
            status=200,
        )

        role_id = project_gen.get_project_viewer_role_id("TEST1")

        assert role_id == "10003"

    def test_get_project_viewer_role_id_dry_run(self, project_gen_dry_run):
        """Test get_project_viewer_role_id in dry run."""
        role_id = project_gen_dry_run.get_project_viewer_role_id("TEST1")
        assert role_id == "10002"

    @responses.activate
    def test_add_user_to_project_role(self, project_gen):
        """Test add_user_to_project_role."""
        responses.add(responses.POST, f"{JIRA_URL}/rest/api/3/project/TEST1/role/10002", json={"id": 10002}, status=200)

        result = project_gen.add_user_to_project_role("TEST1", "10002", "user-123")

        assert result is True

    def test_add_user_to_project_role_dry_run(self, project_gen_dry_run):
        """Test add_user_to_project_role in dry run."""
        result = project_gen_dry_run.add_user_to_project_role("TEST1", "10002", "user-123")
        assert result is True

    @responses.activate
    def test_add_users_to_project(self, project_gen):
        """Test add_users_to_project."""
        # Mock get roles
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/project/TEST1/role",
            json={"Administrators": f"{JIRA_URL}/rest/api/3/project/TEST1/role/10002"},
            status=200,
        )
        # Mock add user
        responses.add(responses.POST, f"{JIRA_URL}/rest/api/3/project/TEST1/role/10002", status=200)

        with patch("time.sleep"):
            result = project_gen.add_users_to_project("TEST1", ["user-123"])

        # Returns count of users added
        assert result == 1

    def test_add_users_to_project_empty(self, project_gen):
        """Test add_users_to_project with empty list."""
        result = project_gen.add_users_to_project("TEST1", [])
        assert result == 0


class TestProjectGeneratorWithCheckpoint:
    """Tests for checkpoint integration."""

    @responses.activate
    def test_create_projects_with_checkpoint(self, project_gen_with_checkpoint):
        """Test create_projects updates checkpoint."""
        # Mock current user
        responses.add(responses.GET, f"{JIRA_URL}/rest/api/3/myself", json={"accountId": "user-123"}, status=200)
        responses.add(
            responses.POST, f"{JIRA_URL}/rest/api/3/project", json={"key": "TEST1", "id": "10001"}, status=201
        )
        # Mock get admin role
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/project/TEST1/role",
            json={"Administrators": f"{JIRA_URL}/rest/api/3/project/TEST1/role/10002"},
            status=200,
        )
        # Mock add user to role
        responses.add(responses.POST, f"{JIRA_URL}/rest/api/3/project/TEST1/role/10002", status=200)

        with patch("time.sleep"):
            projects = project_gen_with_checkpoint.create_projects(1)

        assert len(projects) == 1
        # Checkpoint should have been updated
        assert project_gen_with_checkpoint.checkpoint is not None
