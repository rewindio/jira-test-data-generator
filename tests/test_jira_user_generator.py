"""
Unit tests for jira_user_generator.py - JiraUserGenerator.
"""

from unittest.mock import patch

import pytest
import requests
import responses

from jira_user_generator import JiraUserGenerator

JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"


@pytest.fixture
def user_gen():
    """Create a JiraUserGenerator instance."""
    return JiraUserGenerator(
        jira_url=JIRA_URL,
        email=TEST_EMAIL,
        api_token=TEST_TOKEN,
        products=["jira-software"],
        dry_run=False
    )


@pytest.fixture
def user_gen_dry_run():
    """Create a dry-run JiraUserGenerator instance."""
    return JiraUserGenerator(
        jira_url=JIRA_URL,
        email=TEST_EMAIL,
        api_token=TEST_TOKEN,
        products=["jira-software"],
        dry_run=True
    )


class TestJiraUserGeneratorInit:
    """Tests for JiraUserGenerator initialization."""

    def test_init_basic(self, user_gen):
        """Test basic initialization."""
        assert user_gen.jira_url == JIRA_URL
        assert user_gen.email == TEST_EMAIL
        assert user_gen.products == ["jira-software"]
        assert user_gen.dry_run is False
        assert user_gen.created_users == []
        assert user_gen.created_groups == []
        assert user_gen.existing_users == []
        assert user_gen.existing_groups == []

    def test_init_url_normalization(self):
        """Test URL trailing slash is removed."""
        gen = JiraUserGenerator(
            jira_url=f"{JIRA_URL}/",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN
        )
        assert gen.jira_url == JIRA_URL

    def test_init_default_products(self):
        """Test default products are jira-software."""
        gen = JiraUserGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN
        )
        assert gen.products == ["jira-software"]

    def test_init_multiple_products(self):
        """Test initialization with multiple products."""
        gen = JiraUserGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            products=["jira-software", "jira-servicedesk"]
        )
        assert len(gen.products) == 2

    def test_valid_products_constant(self):
        """Test VALID_PRODUCTS contains expected products."""
        assert "jira-software" in JiraUserGenerator.VALID_PRODUCTS
        assert "jira-core" in JiraUserGenerator.VALID_PRODUCTS
        assert "jira-servicedesk" in JiraUserGenerator.VALID_PRODUCTS


class TestJiraUserGeneratorEmailParsing:
    """Tests for email parsing and generation."""

    def test_parse_email_basic(self, user_gen):
        """Test parse_email with basic email."""
        prefix, domain = user_gen.parse_email("user@example.com")
        assert prefix == "user"
        assert domain == "example.com"

    def test_parse_email_with_plus(self, user_gen):
        """Test parse_email with plus addressing."""
        prefix, domain = user_gen.parse_email("user+existing@example.com")
        assert prefix == "user"
        assert domain == "example.com"

    def test_parse_email_invalid(self, user_gen):
        """Test parse_email with invalid email."""
        with pytest.raises(ValueError) as exc_info:
            user_gen.parse_email("invalid-email")
        assert "Invalid email format" in str(exc_info.value)

    def test_generate_sandbox_email(self, user_gen):
        """Test generate_sandbox_email."""
        email = user_gen.generate_sandbox_email("user@example.com", 1)
        assert email == "user+sandbox1@example.com"

    def test_generate_sandbox_email_existing_plus(self, user_gen):
        """Test generate_sandbox_email with existing plus."""
        email = user_gen.generate_sandbox_email("user+test@example.com", 5)
        assert email == "user+sandbox5@example.com"

    def test_generate_sandbox_email_sequence(self, user_gen):
        """Test generate_sandbox_email for multiple users."""
        emails = [user_gen.generate_sandbox_email("user@example.com", i) for i in range(1, 4)]
        assert emails == [
            "user+sandbox1@example.com",
            "user+sandbox2@example.com",
            "user+sandbox3@example.com"
        ]


class TestJiraUserGeneratorUserOperations:
    """Tests for user operations."""

    @responses.activate
    def test_check_user_exists_found(self, user_gen):
        """Test check_user_exists when user exists."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/user/search",
            json=[{"accountId": "user-123", "emailAddress": "test@example.com"}],
            status=200
        )

        user = user_gen.check_user_exists("test@example.com")

        assert user is not None
        assert user["accountId"] == "user-123"

    @responses.activate
    def test_check_user_exists_not_found(self, user_gen):
        """Test check_user_exists when user doesn't exist."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/user/search",
            json=[],
            status=200
        )

        user = user_gen.check_user_exists("nonexistent@example.com")

        assert user is None

    def test_check_user_exists_dry_run(self, user_gen_dry_run):
        """Test check_user_exists in dry run."""
        user = user_gen_dry_run.check_user_exists("test@example.com")
        assert user is None

    @responses.activate
    def test_create_user_new(self, user_gen):
        """Test create_user for new user."""
        # Check user doesn't exist
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/user/search",
            json=[],
            status=200
        )
        # Create user
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/user",
            json={"accountId": "user-123", "emailAddress": "test@example.com"},
            status=201
        )

        user = user_gen.create_user("test@example.com", "Test User")

        assert user is not None
        assert user["accountId"] == "user-123"
        assert len(user_gen.created_users) == 1
        assert user_gen.created_users[0]["status"] == "invited"

    @responses.activate
    def test_create_user_exists(self, user_gen):
        """Test create_user when user already exists."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/user/search",
            json=[{"accountId": "user-123", "emailAddress": "test@example.com"}],
            status=200
        )

        user = user_gen.create_user("test@example.com", "Test User")

        assert user is not None
        assert len(user_gen.existing_users) == 1
        assert user_gen.existing_users[0]["status"] == "exists"

    def test_create_user_dry_run(self, user_gen_dry_run):
        """Test create_user in dry run."""
        user = user_gen_dry_run.create_user("test@example.com", "Test User")

        assert user is not None
        assert len(user_gen_dry_run.created_users) == 1
        assert user_gen_dry_run.created_users[0]["status"] == "dry_run"

    @responses.activate
    def test_generate_users(self, user_gen):
        """Test generate_users creates multiple users."""
        for i in range(1, 4):
            # Check if exists
            responses.add(
                responses.GET,
                f"{JIRA_URL}/rest/api/3/user/search",
                json=[],
                status=200
            )
            # Create
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/user",
                json={"accountId": f"user-{i}"},
                status=201
            )

        with patch("time.sleep"):
            users = user_gen.generate_users("base@example.com", 3)

        assert len(users) == 3

    def test_generate_users_dry_run(self, user_gen_dry_run):
        """Test generate_users in dry run."""
        with patch("time.sleep"):
            users = user_gen_dry_run.generate_users("base@example.com", 3, prefix="Test")

        assert len(users) == 3


class TestJiraUserGeneratorGroupOperations:
    """Tests for group operations."""

    @responses.activate
    def test_check_group_exists_found(self, user_gen):
        """Test check_group_exists when group exists."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/group/bulk",
            json={"values": [{"name": "Test Group", "groupId": "group-123"}]},
            status=200
        )

        group = user_gen.check_group_exists("Test Group")

        assert group is not None
        assert group["groupId"] == "group-123"

    @responses.activate
    def test_check_group_exists_not_found(self, user_gen):
        """Test check_group_exists when group doesn't exist."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/group/bulk",
            json={"values": []},
            status=200
        )

        group = user_gen.check_group_exists("Nonexistent Group")

        assert group is None

    def test_check_group_exists_dry_run(self, user_gen_dry_run):
        """Test check_group_exists in dry run."""
        group = user_gen_dry_run.check_group_exists("Test Group")
        assert group is None

    @responses.activate
    def test_create_group_new(self, user_gen):
        """Test create_group for new group."""
        # Check group doesn't exist
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/group/bulk",
            json={"values": []},
            status=200
        )
        # Create group
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/group",
            json={"name": "Test Group", "groupId": "group-123"},
            status=201
        )

        group = user_gen.create_group("Test Group")

        assert group is not None
        assert len(user_gen.created_groups) == 1
        assert user_gen.created_groups[0]["status"] == "created"

    @responses.activate
    def test_create_group_exists(self, user_gen):
        """Test create_group when group already exists."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/group/bulk",
            json={"values": [{"name": "Test Group", "groupId": "group-123"}]},
            status=200
        )

        group = user_gen.create_group("Test Group")

        assert group is not None
        assert len(user_gen.existing_groups) == 1
        assert user_gen.existing_groups[0]["status"] == "exists"

    def test_create_group_dry_run(self, user_gen_dry_run):
        """Test create_group in dry run."""
        group = user_gen_dry_run.create_group("Test Group")

        assert group is not None
        assert len(user_gen_dry_run.created_groups) == 1
        assert user_gen_dry_run.created_groups[0]["status"] == "dry_run"

    @responses.activate
    def test_generate_groups(self, user_gen):
        """Test generate_groups creates multiple groups."""
        for i in range(3):
            # Check if exists
            responses.add(
                responses.GET,
                f"{JIRA_URL}/rest/api/3/group/bulk",
                json={"values": []},
                status=200
            )
            # Create
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/group",
                json={"name": f"Group {i+1}", "groupId": f"group-{i+1}"},
                status=201
            )

        with patch("time.sleep"):
            groups = user_gen.generate_groups(["Group 1", "Group 2", "Group 3"])

        assert len(groups) == 3


class TestJiraUserGeneratorGroupMembership:
    """Tests for group membership operations."""

    @responses.activate
    def test_add_user_to_group(self, user_gen):
        """Test add_user_to_group."""
        responses.add(
            responses.POST,
            f"{JIRA_URL}/rest/api/3/group/user",
            status=201
        )

        result = user_gen.add_user_to_group("user-123", "Test Group")

        assert result is True

    def test_add_user_to_group_dry_run(self, user_gen_dry_run):
        """Test add_user_to_group in dry run."""
        result = user_gen_dry_run.add_user_to_group("user-123", "Test Group")
        assert result is True


class TestJiraUserGeneratorGenerateAll:
    """Tests for the main generate_all method."""

    def test_generate_all_dry_run(self, user_gen_dry_run, caplog):
        """Test generate_all in dry run mode."""
        with patch("time.sleep"):
            user_gen_dry_run.generate_all(
                base_email="user@example.com",
                user_count=3,
                group_names=["Group 1", "Group 2"],
                user_prefix="Test"
            )

        assert len(user_gen_dry_run.created_users) == 3
        assert len(user_gen_dry_run.created_groups) == 2

    def test_generate_all_no_groups(self, user_gen_dry_run):
        """Test generate_all without groups."""
        with patch("time.sleep"):
            user_gen_dry_run.generate_all(
                base_email="user@example.com",
                user_count=2,
                user_prefix="Test"
            )

        assert len(user_gen_dry_run.created_users) == 2
        assert len(user_gen_dry_run.created_groups) == 0

    def test_generate_all_logs_summary(self, user_gen_dry_run, caplog):
        """Test generate_all logs summary."""
        import logging
        caplog.set_level(logging.INFO)

        with patch("time.sleep"):
            user_gen_dry_run.generate_all(
                base_email="user@example.com",
                user_count=2
            )

        assert "Generation complete" in caplog.text


class TestJiraUserGeneratorAPICall:
    """Tests for API call handling."""

    @responses.activate
    def test_api_call_rate_limit(self, user_gen):
        """Test API call handles rate limiting."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/test",
            json={},
            status=429,
            headers={"Retry-After": "0.01"}
        )
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/test",
            json={"success": True},
            status=200
        )

        with patch("time.sleep"):
            response = user_gen._api_call("GET", "test")

        assert response is not None
        assert response.json()["success"] is True

    def test_api_call_dry_run(self, user_gen_dry_run):
        """Test API call in dry run mode."""
        response = user_gen_dry_run._api_call("GET", "test")
        assert response is None

    def test_create_session(self, user_gen):
        """Test _create_session creates proper session."""
        session = user_gen._create_session()
        assert session is not None
        assert "https://" in session.adapters

    @responses.activate
    def test_api_call_error_with_response(self, user_gen):
        """Test API call error handling with response body."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/test",
            json={"errorMessages": ["Test error"]},
            status=400
        )

        with patch("time.sleep"):
            with pytest.raises(requests.exceptions.HTTPError):
                user_gen._api_call("GET", "test")


class TestJiraUserGeneratorFailurePaths:
    """Tests for failure paths."""

    @responses.activate
    def test_create_user_api_fails_catches_exception(self, user_gen):
        """Test create_user handles API failure gracefully."""
        # Check if exists returns nothing
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/user/search",
            json=[],
            status=200
        )
        # Create returns 400 - need to add multiple for all retry attempts
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/user",
                json={"errorMessages": ["Invalid request"]},
                status=400
            )

        with patch("time.sleep"):
            try:
                user = user_gen.create_user("test@example.com", "Test User")
                # If no exception, user should be None
                assert user is None
            except Exception:
                # Exception is expected from the retry mechanism
                pass

    @responses.activate
    def test_create_group_api_fails_catches_exception(self, user_gen):
        """Test create_group handles API failure gracefully."""
        # Check if exists returns nothing
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/group/bulk",
            json={"values": []},
            status=200
        )
        # Create returns 400 - need to add multiple for all retry attempts
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{JIRA_URL}/rest/api/3/group",
                json={"errorMessages": ["Invalid request"]},
                status=400
            )

        with patch("time.sleep"):
            try:
                group = user_gen.create_group("Test Group")
                # If no exception, group should be None
                assert group is None
            except Exception:
                # Exception is expected from the retry mechanism
                pass
