"""
Shared pytest fixtures for jira-test-data-generator tests.
"""

import sys
from pathlib import Path

import pytest
import responses
from aioresponses import aioresponses

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ========== Constants ==========

JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"
TEST_PREFIX = "TEST"


# ========== Fixture: Reset class-level state ==========

@pytest.fixture(autouse=True)
def reset_text_pool():
    """Reset the text pool before each test to ensure isolation."""
    from generators.base import JiraAPIClient
    JiraAPIClient._text_pool = None
    JiraAPIClient._text_pool_lock = None
    yield


# ========== Fixture: Mock HTTP responses ==========

@pytest.fixture
def mock_responses():
    """Fixture for mocking synchronous HTTP requests."""
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def mock_aioresponses():
    """Fixture for mocking async HTTP requests."""
    with aioresponses() as m:
        yield m


# ========== Fixture: Temporary directories ==========

@pytest.fixture
def temp_checkpoint_dir(tmp_path):
    """Provide a temporary directory for checkpoint files."""
    return tmp_path


# ========== Fixture: Sample data ==========

@pytest.fixture
def sample_project():
    """Sample project data."""
    return {
        "key": "TEST1",
        "id": "10001",
        "name": "Test Project 1"
    }


@pytest.fixture
def sample_projects():
    """Sample list of projects."""
    return [
        {"key": "TEST1", "id": "10001", "name": "Test Project 1"},
        {"key": "TEST2", "id": "10002", "name": "Test Project 2"},
    ]


@pytest.fixture
def sample_issue_keys():
    """Sample list of issue keys."""
    return [f"TEST1-{i}" for i in range(1, 11)]


@pytest.fixture
def sample_user_ids():
    """Sample list of user account IDs."""
    return [f"user-{i}" for i in range(1, 6)]


@pytest.fixture
def sample_board():
    """Sample board data."""
    return {
        "id": 1,
        "name": "TEST Scrum Board 1",
        "type": "scrum"
    }


@pytest.fixture
def sample_boards():
    """Sample list of boards."""
    return [
        {"id": 1, "name": "TEST Scrum Board 1", "type": "scrum"},
        {"id": 2, "name": "TEST Kanban Board 1", "type": "kanban"},
    ]


@pytest.fixture
def sample_sprint():
    """Sample sprint data."""
    return {
        "id": 1,
        "name": "TEST Sprint 1",
        "state": "future",
        "originBoardId": 1
    }


@pytest.fixture
def sample_filter():
    """Sample filter data."""
    return {
        "id": "10001",
        "name": "TEST Filter 1",
        "jql": "project = TEST1"
    }


@pytest.fixture
def sample_dashboard():
    """Sample dashboard data."""
    return {
        "id": "10001",
        "name": "TEST Dashboard 1"
    }


@pytest.fixture
def sample_custom_field():
    """Sample custom field data."""
    return {
        "id": "customfield_10001",
        "name": "TEST Text Field 1",
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:textfield"
    }


@pytest.fixture
def sample_category():
    """Sample project category data."""
    return {
        "id": "10001",
        "name": "TEST Development 1"
    }


@pytest.fixture
def sample_version():
    """Sample version data."""
    return {
        "id": "10001",
        "name": "TEST v1.0"
    }


@pytest.fixture
def sample_component():
    """Sample component data."""
    return {
        "id": "10001",
        "name": "TEST-Component-1"
    }


# ========== Fixture: Multipliers ==========

@pytest.fixture
def sample_multipliers():
    """Sample multipliers data (small bucket)."""
    return {
        "small": {
            "project": 0.00249,
            "comment": 4.80,
            "issue_worklog": 7.27,
            "issue_link": 0.23,
            "issue_watcher": 2.24,
            "issue_attachment": 1.52,
            "issue_vote": 0.0003,
            "issue_properties": 0.74,
            "issue_remote_link": 0.33,
            "project_version": 1.44,
            "project_component": 0.21,
            "project_category": 0.02,
            "project_property": 0.09,
            "board": 0.0085,
            "sprint": 0.05,
            "filter": 0.056,
            "dashboard": 0.0087,
            "issue_field": 0.12
        }
    }


# ========== Fixture: CSV content ==========

@pytest.fixture
def sample_csv_content():
    """Sample multipliers CSV content."""
    return """Item Type,Small,Medium,Large,XLarge
project,0.00249,0.00066,0.00032,0.00001
comment,4.80,4.75,2.69,0.26
issue_worklog,7.27,1.49,0.24,0.06
issue_link,0.23,0.23,0.12,0.01
issue_watcher,2.24,2.19,1.02,0.09
issue_attachment,1.52,1.57,0.98,0.12
issue_vote,0.0003,0.0003,0.0001,0.00001
issue_properties,0.74,0.67,0.31,0.03
issue_remote_link,0.33,0.32,0.15,0.01
project_version,1.44,1.21,0.59,0.05
project_component,0.21,0.20,0.11,0.01
project_category,0.02,0.02,0.01,0.001
project_property,0.09,0.08,0.04,0.004
board,0.0085,0.0072,0.0040,0.0003
sprint,0.05,0.05,0.02,0.002
filter,0.056,0.050,0.024,0.002
dashboard,0.0087,0.0075,0.0040,0.0003
issue_field,0.12,0.11,0.05,0.005
"""


# ========== Fixture: Checkpoint data ==========

@pytest.fixture
def sample_checkpoint_data():
    """Sample checkpoint data structure."""
    return {
        "run_id": "TEST-20241208-120000",
        "prefix": "TEST",
        "size": "small",
        "target_issue_count": 100,
        "started_at": "2024-12-08T12:00:00",
        "last_updated": "2024-12-08T12:30:00",
        "jira_url": JIRA_URL,
        "async_mode": True,
        "concurrency": 5,
        "project_keys": ["TEST1", "TEST2"],
        "project_ids": {"TEST1": "10001", "TEST2": "10002"},
        "issue_keys": [f"TEST1-{i}" for i in range(1, 51)],
        "category_ids": ["10001"],
        "issues_per_project": {"TEST1": 50, "TEST2": 0},
        "phases": {
            "project_categories": {"status": "complete", "target_count": 1, "created_count": 1, "created_items": []},
            "projects": {"status": "complete", "target_count": 2, "created_count": 2, "created_items": []},
            "issues": {"status": "in_progress", "target_count": 100, "created_count": 50, "created_items": []},
            "comments": {"status": "pending", "target_count": 480, "created_count": 0, "created_items": []},
        }
    }


# ========== Fixture: Mock Jira API responses ==========

@pytest.fixture
def jira_api_responses():
    """Common Jira API response builders."""
    class JiraAPIResponses:
        @staticmethod
        def myself_response():
            return {"accountId": "test-account-id", "emailAddress": TEST_EMAIL}

        @staticmethod
        def users_response(count=5):
            return [
                {"accountId": f"user-{i}", "active": True, "accountType": "atlassian"}
                for i in range(1, count + 1)
            ]

        @staticmethod
        def project_response(key="TEST1", project_id="10001"):
            return {"key": key, "id": project_id, "name": f"Test Project {key}"}

        @staticmethod
        def project_roles_response():
            return {
                "Administrators": f"{JIRA_URL}/rest/api/3/project/TEST1/role/10002",
                "Developers": f"{JIRA_URL}/rest/api/3/project/TEST1/role/10003"
            }

        @staticmethod
        def bulk_issues_response(keys):
            return {"issues": [{"key": key} for key in keys]}

        @staticmethod
        def issue_link_types_response():
            return {"issueLinkTypes": [{"name": "Blocks"}, {"name": "Relates"}]}

        @staticmethod
        def filter_response(filter_id="10001", name="Test Filter"):
            return {"id": filter_id, "name": name, "jql": "project = TEST1"}

        @staticmethod
        def dashboard_response(dashboard_id="10001", name="Test Dashboard"):
            return {"id": dashboard_id, "name": name}

        @staticmethod
        def board_response(board_id=1, name="Test Board", board_type="scrum"):
            return {"id": board_id, "name": name, "type": board_type}

        @staticmethod
        def sprint_response(sprint_id=1, name="Test Sprint"):
            return {"id": sprint_id, "name": name, "state": "future"}

        @staticmethod
        def custom_field_response(field_id="customfield_10001"):
            return {"id": field_id, "name": "Test Field"}

        @staticmethod
        def field_contexts_response():
            return {"values": [{"id": "10001", "name": "Default Context"}]}

        @staticmethod
        def category_response(category_id="10001", name="Test Category"):
            return {"id": category_id, "name": name}

        @staticmethod
        def version_response(version_id="10001"):
            return {"id": version_id, "name": "v1.0"}

        @staticmethod
        def component_response(component_id="10001"):
            return {"id": component_id, "name": "Component-1"}

    return JiraAPIResponses()


# ========== Fixture: Base client setup ==========

@pytest.fixture
def base_client_kwargs():
    """Common kwargs for creating test clients."""
    return {
        "jira_url": JIRA_URL,
        "email": TEST_EMAIL,
        "api_token": TEST_TOKEN,
        "dry_run": False,
        "concurrency": 5,
        "benchmark": None,
        "request_delay": 0.0
    }


@pytest.fixture
def dry_run_client_kwargs(base_client_kwargs):
    """Kwargs for creating dry-run test clients."""
    return {**base_client_kwargs, "dry_run": True}
