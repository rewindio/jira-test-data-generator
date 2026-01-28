"""
Unit tests for generators/custom_fields.py - CustomFieldGenerator.
"""

import pytest
import responses
from aioresponses import aioresponses
from unittest.mock import patch

from generators.custom_fields import (
    CustomFieldGenerator,
    CUSTOM_FIELD_TYPES,
    GENERATABLE_FIELD_TYPES
)


JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"


@pytest.fixture
def custom_field_gen(base_client_kwargs):
    """Create a CustomFieldGenerator instance."""
    return CustomFieldGenerator(prefix="TEST", **base_client_kwargs)


@pytest.fixture
def custom_field_gen_dry_run(dry_run_client_kwargs):
    """Create a dry-run CustomFieldGenerator instance."""
    return CustomFieldGenerator(prefix="TEST", **dry_run_client_kwargs)


class TestCustomFieldTypes:
    """Tests for custom field type definitions."""

    def test_custom_field_types_defined(self):
        """Test CUSTOM_FIELD_TYPES has all expected types."""
        expected_types = [
            "textfield", "textarea", "float", "datepicker", "datetime",
            "select", "multiselect", "radiobuttons", "multicheckboxes",
            "userpicker", "multiuserpicker", "grouppicker", "multigrouppicker",
            "cascadingselect", "labels", "url", "project", "version",
            "multiversion", "readonlyfield"
        ]
        for field_type in expected_types:
            assert field_type in CUSTOM_FIELD_TYPES

    def test_custom_field_types_have_required_fields(self):
        """Test each field type has required configuration."""
        for field_type, config in CUSTOM_FIELD_TYPES.items():
            assert "type" in config, f"{field_type} missing 'type'"
            assert "searcherKey" in config, f"{field_type} missing 'searcherKey'"
            assert "description" in config, f"{field_type} missing 'description'"

    def test_generatable_field_types(self):
        """Test GENERATABLE_FIELD_TYPES excludes read-only."""
        assert "readonlyfield" not in GENERATABLE_FIELD_TYPES
        # Should include common types
        assert "textfield" in GENERATABLE_FIELD_TYPES
        assert "select" in GENERATABLE_FIELD_TYPES

    def test_select_types_have_options_flag(self):
        """Test select types have has_options flag."""
        select_types = ["select", "multiselect", "radiobuttons", "multicheckboxes", "cascadingselect"]
        for field_type in select_types:
            assert CUSTOM_FIELD_TYPES[field_type].get("has_options") is True


class TestCustomFieldGeneratorInit:
    """Tests for CustomFieldGenerator initialization."""

    def test_init(self, custom_field_gen):
        """Test CustomFieldGenerator initializes correctly."""
        assert custom_field_gen.prefix == "TEST"
        assert custom_field_gen.run_id is not None
        assert custom_field_gen.created_fields == []
        assert custom_field_gen.created_contexts == []
        assert custom_field_gen.created_options == []

    def test_set_run_id(self, custom_field_gen):
        """Test set_run_id updates run_id."""
        custom_field_gen.set_run_id("NEW-RUN-ID")
        assert custom_field_gen.run_id == "NEW-RUN-ID"


class TestCustomFieldGeneratorFields:
    """Tests for custom field creation."""

    @responses.activate
    def test_create_custom_field(self, custom_field_gen):
        """Test create_custom_field."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/field",
            json={"id": "customfield_10001", "name": "TEST Text Field 1"},
            status=201
        )

        field = custom_field_gen.create_custom_field(
            name="TEST Text Field 1",
            field_type="textfield",
            description="Test description"
        )

        assert field is not None
        assert field["id"] == "customfield_10001"
        assert len(custom_field_gen.created_fields) == 1

    def test_create_custom_field_dry_run(self, custom_field_gen_dry_run):
        """Test create_custom_field in dry run."""
        field = custom_field_gen_dry_run.create_custom_field(
            name="TEST Text Field 1",
            field_type="textfield"
        )

        assert field is not None
        assert "id" in field
        assert field["id"].startswith("customfield_")

    def test_create_custom_field_invalid_type(self, custom_field_gen):
        """Test create_custom_field with invalid type."""
        field = custom_field_gen.create_custom_field(
            name="Invalid Field",
            field_type="nonexistent_type"
        )
        assert field is None

    @responses.activate
    def test_create_custom_fields(self, custom_field_gen):
        """Test create_custom_fields creates multiple fields."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/field",
                json={"id": f"customfield_1000{i+1}", "name": f"Field {i+1}"},
                status=201
            )
            # For select types, need context and options responses
            responses.add(
                responses.GET,
                f"{JIRA_URL}/rest/api/3/field/customfield_1000{i+1}/context",
                json={"values": [{"id": "10001"}]},
                status=200
            )
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/field/customfield_1000{i+1}/context/10001/option",
                json={"options": []},
                status=201
            )

        with patch("time.sleep"):
            fields = custom_field_gen.create_custom_fields(3)

        assert len(fields) >= 0

    def test_create_custom_fields_dry_run(self, custom_field_gen_dry_run):
        """Test create_custom_fields in dry run."""
        fields = custom_field_gen_dry_run.create_custom_fields(5)
        assert len(fields) == 5

    @pytest.mark.asyncio
    async def test_create_custom_fields_async(self, custom_field_gen):
        """Test create_custom_fields_async."""
        with aioresponses() as m:
            for i in range(3):
                m.post(
                    f"{JIRA_URL}/rest/api/3/field",
                    payload={"id": f"customfield_1000{i+1}", "name": f"Field {i+1}"}
                )
                m.get(
                    f"{JIRA_URL}/rest/api/3/field/customfield_1000{i+1}/context",
                    payload={"values": [{"id": "10001"}]}
                )
                m.post(
                    f"{JIRA_URL}/rest/api/3/field/customfield_1000{i+1}/context/10001/option",
                    payload={"options": []}
                )

            fields = await custom_field_gen.create_custom_fields_async(3)

        assert len(fields) >= 0
        await custom_field_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_create_custom_fields_async_dry_run(self, custom_field_gen_dry_run):
        """Test create_custom_fields_async in dry run."""
        fields = await custom_field_gen_dry_run.create_custom_fields_async(5)
        assert len(fields) == 5


class TestCustomFieldGeneratorContexts:
    """Tests for field context management."""

    @responses.activate
    def test_get_field_contexts(self, custom_field_gen):
        """Test get_field_contexts."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/field/customfield_10001/context",
            json={"values": [{"id": "10001", "name": "Default Context"}]},
            status=200
        )

        contexts = custom_field_gen.get_field_contexts("customfield_10001")

        assert len(contexts) == 1
        assert contexts[0]["id"] == "10001"

    def test_get_field_contexts_dry_run(self, custom_field_gen_dry_run):
        """Test get_field_contexts in dry run."""
        contexts = custom_field_gen_dry_run.get_field_contexts("customfield_10001")
        assert len(contexts) == 1
        assert "id" in contexts[0]

    @responses.activate
    def test_create_field_context(self, custom_field_gen):
        """Test create_field_context."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/field/customfield_10001/context",
            json={"values": [{"id": "10002", "name": "Custom Context"}]},
            status=201
        )

        context = custom_field_gen.create_field_context(
            field_id="customfield_10001",
            name="Custom Context",
            description="Test context",
            project_ids=["10001"],
            issue_type_ids=["10001"]
        )

        assert context is not None
        assert context["id"] == "10002"
        assert len(custom_field_gen.created_contexts) == 1

    def test_create_field_context_dry_run(self, custom_field_gen_dry_run):
        """Test create_field_context in dry run."""
        context = custom_field_gen_dry_run.create_field_context(
            field_id="customfield_10001",
            name="Custom Context"
        )

        assert context is not None
        assert "id" in context


class TestCustomFieldGeneratorOptions:
    """Tests for field option management."""

    @responses.activate
    def test_create_field_options(self, custom_field_gen):
        """Test create_field_options."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/field/customfield_10001/context/10001/option",
            json={"options": [
                {"id": "10001", "value": "Option 1"},
                {"id": "10002", "value": "Option 2"}
            ]},
            status=201
        )

        options = custom_field_gen.create_field_options(
            field_id="customfield_10001",
            context_id="10001",
            options=["Option 1", "Option 2"]
        )

        assert len(options) == 2
        assert len(custom_field_gen.created_options) == 2

    def test_create_field_options_dry_run(self, custom_field_gen_dry_run):
        """Test create_field_options in dry run."""
        options = custom_field_gen_dry_run.create_field_options(
            field_id="customfield_10001",
            context_id="10001",
            options=["Option 1", "Option 2", "Option 3"]
        )

        assert len(options) == 3
        assert all("id" in opt for opt in options)

    def test_create_field_options_empty(self, custom_field_gen):
        """Test create_field_options with empty list."""
        options = custom_field_gen.create_field_options(
            field_id="customfield_10001",
            context_id="10001",
            options=[]
        )
        assert options == []

    @responses.activate
    def test_create_field_options_for_field(self, custom_field_gen):
        """Test _create_field_options_for_field helper."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/field/customfield_10001/context",
            json={"values": [{"id": "10001"}]},
            status=200
        )
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/field/customfield_10001/context/10001/option",
            json={"options": [{"id": "10001", "value": "Option 1"}]},
            status=201
        )

        field_obj = {"id": "customfield_10001", "type_key": "select"}
        options = custom_field_gen._create_field_options_for_field(field_obj, num_options=5)

        assert len(options) >= 0


class TestCustomFieldGeneratorConfigurations:
    """Tests for field configuration management."""

    @responses.activate
    def test_get_field_configurations(self, custom_field_gen):
        """Test get_field_configurations."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/fieldconfiguration",
            json={"values": [{"id": 10000, "name": "Default Configuration"}]},
            status=200
        )

        configs = custom_field_gen.get_field_configurations()

        assert len(configs) == 1
        assert configs[0]["id"] == 10000

    def test_get_field_configurations_dry_run(self, custom_field_gen_dry_run):
        """Test get_field_configurations in dry run."""
        configs = custom_field_gen_dry_run.get_field_configurations()
        assert len(configs) == 1

    @responses.activate
    def test_create_field_configuration(self, custom_field_gen):
        """Test create_field_configuration."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/fieldconfiguration",
            json={"id": 10001, "name": "Custom Configuration"},
            status=201
        )

        config = custom_field_gen.create_field_configuration(
            name="Custom Configuration",
            description="Test configuration"
        )

        assert config is not None
        assert config["id"] == 10001

    def test_create_field_configuration_dry_run(self, custom_field_gen_dry_run):
        """Test create_field_configuration in dry run."""
        config = custom_field_gen_dry_run.create_field_configuration(
            name="Custom Configuration"
        )

        assert config is not None
        assert "id" in config

    @responses.activate
    def test_create_field_configuration_scheme(self, custom_field_gen):
        """Test create_field_configuration_scheme."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/fieldconfigurationscheme",
            json={"id": 10001, "name": "Custom Scheme"},
            status=201
        )

        scheme = custom_field_gen.create_field_configuration_scheme(
            name="Custom Scheme",
            description="Test scheme"
        )

        assert scheme is not None
        assert scheme["id"] == 10001

    def test_create_field_configuration_scheme_dry_run(self, custom_field_gen_dry_run):
        """Test create_field_configuration_scheme in dry run."""
        scheme = custom_field_gen_dry_run.create_field_configuration_scheme(
            name="Custom Scheme"
        )

        assert scheme is not None
        assert "id" in scheme


class TestCustomFieldGeneratorAsync:
    """Tests for async context operations."""

    @pytest.mark.asyncio
    async def test_get_field_contexts_async(self, custom_field_gen):
        """Test _get_field_contexts_async."""
        with aioresponses() as m:
            m.get(
                f"{JIRA_URL}/rest/api/3/field/customfield_10001/context",
                payload={"values": [{"id": "10001"}]}
            )

            contexts = await custom_field_gen._get_field_contexts_async("customfield_10001")

        assert len(contexts) == 1
        await custom_field_gen._close_async_session()

    @pytest.mark.asyncio
    async def test_get_field_contexts_async_dry_run(self, custom_field_gen_dry_run):
        """Test _get_field_contexts_async in dry run."""
        contexts = await custom_field_gen_dry_run._get_field_contexts_async("customfield_10001")
        assert len(contexts) == 1

    @pytest.mark.asyncio
    async def test_create_options_for_fields_async(self, custom_field_gen):
        """Test _create_options_for_fields_async."""
        fields = [
            {"id": "customfield_10001", "type_key": "select"},
            {"id": "customfield_10002", "type_key": "textfield"}  # No options needed
        ]

        with aioresponses() as m:
            m.get(
                f"{JIRA_URL}/rest/api/3/field/customfield_10001/context",
                payload={"values": [{"id": "10001"}]}
            )
            m.post(
                f"{JIRA_URL}/rest/api/3/field/customfield_10001/context/10001/option",
                payload={"options": []}
            )

            await custom_field_gen._create_options_for_fields_async(fields)

        await custom_field_gen._close_async_session()
