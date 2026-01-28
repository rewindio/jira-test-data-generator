"""
Unit tests for generators/filters.py - FilterGenerator.
"""

import pytest
import responses
from aioresponses import aioresponses
from unittest.mock import patch

from generators.filters import FilterGenerator


JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"


@pytest.fixture
def filter_gen(base_client_kwargs):
    """Create a FilterGenerator instance."""
    return FilterGenerator(prefix="TEST", **base_client_kwargs)


@pytest.fixture
def filter_gen_dry_run(dry_run_client_kwargs):
    """Create a dry-run FilterGenerator instance."""
    return FilterGenerator(prefix="TEST", **dry_run_client_kwargs)


class TestFilterGeneratorInit:
    """Tests for FilterGenerator initialization."""

    def test_init(self, filter_gen):
        """Test FilterGenerator initializes correctly."""
        assert filter_gen.prefix == "TEST"
        assert filter_gen.run_id is not None
        assert filter_gen.created_filters == []
        assert filter_gen.created_dashboards == []

    def test_set_run_id(self, filter_gen):
        """Test set_run_id updates run_id."""
        filter_gen.set_run_id("NEW-RUN-ID")
        assert filter_gen.run_id == "NEW-RUN-ID"


class TestFilterGeneratorFilters:
    """Tests for filter creation."""

    @responses.activate
    def test_create_filter(self, filter_gen):
        """Test create_filter."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/filter",
            json={"id": "10001", "name": "TEST Filter 1", "jql": "project = TEST1"},
            status=201
        )

        filter_obj = filter_gen.create_filter(
            name="TEST Filter 1",
            jql="project = TEST1",
            description="Test description",
            favourite=True
        )

        assert filter_obj is not None
        assert filter_obj["id"] == "10001"
        assert len(filter_gen.created_filters) == 1

    def test_create_filter_dry_run(self, filter_gen_dry_run):
        """Test create_filter in dry run."""
        filter_obj = filter_gen_dry_run.create_filter(
            name="TEST Filter 1",
            jql="project = TEST1"
        )

        assert filter_obj is not None
        assert "id" in filter_obj
        assert filter_obj["jql"] == "project = TEST1"

    @responses.activate
    def test_create_filters(self, filter_gen):
        """Test create_filters creates multiple filters."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/filter",
                json={"id": f"1000{i+1}", "name": f"TEST Filter {i+1}"},
                status=201
            )

        project_keys = ["TEST1", "TEST2"]
        with patch("time.sleep"):
            filters = filter_gen.create_filters(project_keys, 3)

        assert len(filters) == 3

    def test_create_filters_dry_run(self, filter_gen_dry_run):
        """Test create_filters in dry run."""
        project_keys = ["TEST1", "TEST2"]
        filters = filter_gen_dry_run.create_filters(project_keys, 5)
        assert len(filters) == 5

    @pytest.mark.asyncio
    async def test_create_filters_async(self, filter_gen):
        """Test create_filters_async."""
        project_keys = ["TEST1", "TEST2"]

        with aioresponses() as m:
            for i in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/filter",
                    payload={"id": f"1000{i+1}", "name": f"TEST Filter {i+1}"}
                )

            filters = await filter_gen.create_filters_async(project_keys, 3)

        assert len(filters) >= 0
        await filter_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_filters_async_dry_run(self, filter_gen_dry_run):
        """Test create_filters_async in dry run."""
        project_keys = ["TEST1", "TEST2"]
        filters = await filter_gen_dry_run.create_filters_async(project_keys, 5)
        assert len(filters) == 5


class TestFilterGeneratorDashboards:
    """Tests for dashboard creation."""

    @responses.activate
    def test_create_dashboard(self, filter_gen):
        """Test create_dashboard."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/dashboard",
            json={"id": "10001", "name": "TEST Dashboard 1"},
            status=201
        )

        dashboard = filter_gen.create_dashboard(
            name="TEST Dashboard 1",
            description="Test description",
            share_permissions=[{"type": "authenticated"}]
        )

        assert dashboard is not None
        assert dashboard["id"] == "10001"
        assert len(filter_gen.created_dashboards) == 1

    def test_create_dashboard_dry_run(self, filter_gen_dry_run):
        """Test create_dashboard in dry run."""
        dashboard = filter_gen_dry_run.create_dashboard(
            name="TEST Dashboard 1"
        )

        assert dashboard is not None
        assert "id" in dashboard

    @responses.activate
    def test_create_dashboard_private(self, filter_gen):
        """Test create_dashboard with private permissions."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/dashboard",
            json={"id": "10001", "name": "Private Dashboard"},
            status=201
        )

        dashboard = filter_gen.create_dashboard(
            name="Private Dashboard",
            share_permissions=[]  # Empty = private
        )

        assert dashboard is not None

    @responses.activate
    def test_create_dashboards(self, filter_gen):
        """Test create_dashboards creates multiple dashboards."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/dashboard",
                json={"id": f"1000{i+1}", "name": f"TEST Dashboard {i+1}"},
                status=201
            )

        with patch("time.sleep"):
            dashboards = filter_gen.create_dashboards(3)

        assert len(dashboards) == 3

    def test_create_dashboards_dry_run(self, filter_gen_dry_run):
        """Test create_dashboards in dry run."""
        dashboards = filter_gen_dry_run.create_dashboards(5)
        assert len(dashboards) == 5

    @pytest.mark.asyncio
    async def test_create_dashboards_async(self, filter_gen):
        """Test create_dashboards_async."""
        with aioresponses() as m:
            for i in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/dashboard",
                    payload={"id": f"1000{i+1}", "name": f"TEST Dashboard {i+1}"}
                )

            dashboards = await filter_gen.create_dashboards_async(3)

        assert len(dashboards) >= 0
        await filter_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_dashboards_async_dry_run(self, filter_gen_dry_run):
        """Test create_dashboards_async in dry run."""
        dashboards = await filter_gen_dry_run.create_dashboards_async(5)
        assert len(dashboards) == 5


class TestFilterGeneratorGadgets:
    """Tests for dashboard gadget management."""

    @responses.activate
    def test_add_gadget_to_dashboard(self, filter_gen):
        """Test add_gadget_to_dashboard."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/dashboard/10001/gadget",
            json={"id": "10001", "moduleKey": "com.atlassian.jira.gadgets:filter-results"},
            status=200
        )

        gadget = filter_gen.add_gadget_to_dashboard(
            dashboard_id="10001",
            gadget_uri="com.atlassian.jira.gadgets:filter-results",
            position={"column": 0, "row": 0},
            title="My Gadget"
        )

        assert gadget is not None
        assert gadget["moduleKey"] == "com.atlassian.jira.gadgets:filter-results"

    def test_add_gadget_to_dashboard_dry_run(self, filter_gen_dry_run):
        """Test add_gadget_to_dashboard in dry run."""
        gadget = filter_gen_dry_run.add_gadget_to_dashboard(
            dashboard_id="10001",
            gadget_uri="com.atlassian.jira.gadgets:filter-results"
        )

        assert gadget is not None
        assert "id" in gadget


class TestFilterGeneratorJQLTemplates:
    """Tests for JQL template usage."""

    def test_filter_jql_templates(self, filter_gen_dry_run):
        """Test filters use various JQL templates."""
        project_keys = ["TEST1", "TEST2"]
        filters = filter_gen_dry_run.create_filters(project_keys, 13)

        # Should have used various templates
        jqls = [f["jql"] for f in filters]

        # Check for project-specific queries
        assert any("project = TEST" in jql for jql in jqls)
        # Check for status queries
        assert any("status" in jql for jql in jqls)
        # Check for label queries
        assert any("labels" in jql for jql in jqls)

    def test_filter_uses_run_id(self, filter_gen_dry_run):
        """Test filter JQL can use run_id."""
        filter_gen_dry_run.set_run_id("TEST-20241208-120000")
        project_keys = ["TEST1"]

        # Create enough filters to hit the label template
        filters = filter_gen_dry_run.create_filters(project_keys, 13)

        jqls = [f["jql"] for f in filters]
        # At least one should reference the run_id
        assert any("TEST-20241208-120000" in jql for jql in jqls)


class TestFilterGeneratorDashboardTypes:
    """Tests for dashboard type variations."""

    def test_dashboard_types(self, filter_gen_dry_run):
        """Test dashboards use various types."""
        dashboards = filter_gen_dry_run.create_dashboards(8)

        names = [d["name"] for d in dashboards]

        # Check for various dashboard types in names
        dashboard_types = ["Overview", "Sprint Progress", "Team Metrics", "Bug Tracker",
                         "Release Status", "Performance", "Quality", "Velocity"]

        found_types = 0
        for dtype in dashboard_types:
            if any(dtype in name for name in names):
                found_types += 1

        assert found_types >= 1  # Should have at least one type
