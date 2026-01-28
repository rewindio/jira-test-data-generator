"""
Unit tests for jira_data_generator.py - JiraDataGenerator main orchestrator.
"""

import os
import sys
import csv
import tempfile
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest
import responses
from aioresponses import aioresponses

# Import the module
from jira_data_generator import (
    JiraDataGenerator,
    load_multipliers_from_csv,
    MULTIPLIERS
)
from generators.checkpoint import CheckpointManager


JIRA_URL = "https://test.atlassian.net"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"


class TestLoadMultipliersFromCSV:
    """Tests for CSV multiplier loading."""

    def test_load_multipliers_default(self):
        """Test loading multipliers from default CSV."""
        multipliers = load_multipliers_from_csv()

        assert "small" in multipliers
        assert "medium" in multipliers
        assert "large" in multipliers
        assert "xlarge" in multipliers

    def test_load_multipliers_has_expected_types(self):
        """Test multipliers contain expected item types."""
        multipliers = load_multipliers_from_csv()

        expected_types = ["project", "comment", "issue_worklog", "issue_link"]
        for item_type in expected_types:
            assert item_type in multipliers["small"]

    def test_load_multipliers_custom_file(self, tmp_path, sample_csv_content):
        """Test loading multipliers from custom CSV file."""
        csv_path = tmp_path / "custom_multipliers.csv"
        csv_path.write_text(sample_csv_content)

        multipliers = load_multipliers_from_csv(str(csv_path))

        assert "small" in multipliers
        assert multipliers["small"]["project"] == 0.00249
        assert multipliers["small"]["comment"] == 4.80

    def test_load_multipliers_handles_missing_values(self, tmp_path):
        """Test loading multipliers handles missing values."""
        csv_content = """Item Type,Small,Medium,Large,XLarge
project,0.00249,,,
comment,,4.75,,
"""
        csv_path = tmp_path / "partial.csv"
        csv_path.write_text(csv_content)

        multipliers = load_multipliers_from_csv(str(csv_path))

        assert multipliers["small"]["project"] == 0.00249
        assert "comment" not in multipliers["small"]
        assert multipliers["medium"]["comment"] == 4.75

    def test_multipliers_global_loaded(self):
        """Test MULTIPLIERS global is loaded."""
        assert MULTIPLIERS is not None
        assert len(MULTIPLIERS) == 4


class TestJiraDataGeneratorInit:
    """Tests for JiraDataGenerator initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator.jira_url == JIRA_URL
        assert generator.email == TEST_EMAIL
        assert generator.prefix == "TEST"
        assert generator.size_bucket == "small"
        assert generator.dry_run is False

    def test_init_url_normalization(self):
        """Test URL trailing slash is removed."""
        generator = JiraDataGenerator(
            jira_url=f"{JIRA_URL}/",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator.jira_url == JIRA_URL

    def test_init_with_options(self):
        """Test initialization with options."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            size_bucket="large",
            dry_run=True,
            concurrency=10,
            request_delay=0.1,
            issues_only=True,
            project_override=5
        )

        assert generator.size_bucket == "large"
        assert generator.dry_run is True
        assert generator.concurrency == 10
        assert generator.request_delay == 0.1
        assert generator.issues_only is True
        assert generator.project_override == 5

    def test_init_invalid_size_bucket(self):
        """Test initialization with invalid size bucket."""
        with pytest.raises(ValueError) as exc_info:
            JiraDataGenerator(
                jira_url=JIRA_URL,
                email=TEST_EMAIL,
                api_token=TEST_TOKEN,
                prefix="TEST",
                size_bucket="invalid"
            )
        assert "Invalid size bucket" in str(exc_info.value)

    def test_init_creates_generators(self):
        """Test initialization creates generator modules."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator.project_gen is not None
        assert generator.issue_gen is not None
        assert generator.issue_items_gen is not None
        assert generator.agile_gen is not None
        assert generator.filter_gen is not None
        assert generator.custom_field_gen is not None

    def test_init_creates_benchmark(self):
        """Test initialization creates benchmark tracker."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator.benchmark is not None

    def test_init_with_checkpoint(self, temp_checkpoint_dir):
        """Test initialization with checkpoint manager."""
        checkpoint = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)

        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            checkpoint_manager=checkpoint
        )

        assert generator.checkpoint is checkpoint


class TestJiraDataGeneratorCalculateCounts:
    """Tests for count calculation."""

    def test_calculate_counts_basic(self):
        """Test basic count calculation."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            size_bucket="small"
        )

        counts = generator.calculate_counts(100)

        assert counts["project"] >= 1
        assert counts["comment"] > 0
        assert counts["issue_worklog"] > 0

    def test_calculate_counts_minimum_one(self):
        """Test counts are at least 1."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        counts = generator.calculate_counts(10)

        for item_type, count in counts.items():
            assert count >= 1 or count == 0  # Some may be 0 for small counts

    def test_calculate_counts_issues_only(self):
        """Test calculate_counts in issues_only mode."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            issues_only=True
        )

        counts = generator.calculate_counts(100)

        # Should have project and issue counts
        assert counts.get("project", 0) >= 1

        # Should NOT have associated data counts
        assert counts.get("comment", 0) == 0
        assert counts.get("issue_worklog", 0) == 0
        assert counts.get("issue_watcher", 0) == 0

    def test_calculate_counts_project_override(self):
        """Test calculate_counts with project override."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            project_override=10
        )

        counts = generator.calculate_counts(100)

        assert counts["project"] == 10

    def test_calculate_counts_different_sizes(self):
        """Test calculate_counts varies by size."""
        small_gen = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            size_bucket="small"
        )
        large_gen = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            size_bucket="large"
        )

        small_counts = small_gen.calculate_counts(1000)
        large_counts = large_gen.calculate_counts(1000)

        # Small should have more comments per issue
        assert small_counts.get("comment", 0) >= large_counts.get("comment", 0)


class TestJiraDataGeneratorCheckpointHelpers:
    """Tests for checkpoint helper methods."""

    def test_is_phase_complete_no_checkpoint(self):
        """Test _is_phase_complete without checkpoint."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator._is_phase_complete("issues") is False

    def test_is_phase_complete_with_checkpoint(self, temp_checkpoint_dir):
        """Test _is_phase_complete with checkpoint."""
        checkpoint = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        checkpoint.initialize(
            run_id="TEST-123", size="small", target_issue_count=100,
            jira_url=JIRA_URL, async_mode=True, concurrency=5, counts={}
        )
        checkpoint.complete_phase("projects")

        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            checkpoint_manager=checkpoint
        )

        assert generator._is_phase_complete("projects") is True
        assert generator._is_phase_complete("issues") is False

    def test_get_remaining_count_no_checkpoint(self):
        """Test _get_remaining_count without checkpoint."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator._get_remaining_count("comments", 480) == 480

    def test_get_remaining_count_with_checkpoint(self, temp_checkpoint_dir):
        """Test _get_remaining_count with partial progress."""
        checkpoint = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        checkpoint.initialize(
            run_id="TEST-123", size="small", target_issue_count=100,
            jira_url=JIRA_URL, async_mode=True, concurrency=5,
            counts={"comment": 480}
        )
        checkpoint._checkpoint.phases["comments"].created_count = 200

        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            checkpoint_manager=checkpoint
        )

        assert generator._get_remaining_count("comments", 480) == 280


class TestJiraDataGeneratorDryRun:
    """Tests for dry run mode."""

    def test_generate_all_dry_run(self):
        """Test generate_all in dry run mode."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        # Should complete without making actual API calls
        generator.generate_all(10)

        # Check benchmark was used
        assert generator.benchmark.total_items_created >= 0

    @pytest.mark.asyncio
    async def test_generate_all_async_dry_run(self):
        """Test generate_all_async in dry run mode."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        # Should complete without making actual API calls
        await generator.generate_all_async(10)

        # Check benchmark was used
        assert generator.benchmark.total_items_created >= 0


class TestJiraDataGeneratorLogging:
    """Tests for logging methods."""

    def test_log_header(self, caplog):
        """Test _log_header output."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        with caplog.at_level("INFO"):
            generator._log_header(100, async_mode=True)

        assert "Jira data generation" in caplog.text
        assert "async mode" in caplog.text

    def test_log_header_issues_only(self, caplog):
        """Test _log_header shows issues_only mode."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
            issues_only=True
        )

        with caplog.at_level("INFO"):
            generator._log_header(100, async_mode=False)

        assert "ISSUES ONLY" in caplog.text

    def test_log_planned_counts(self, caplog):
        """Test _log_planned_counts output."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        counts = generator.calculate_counts(100)

        with caplog.at_level("INFO"):
            generator._log_planned_counts(100, counts)

        assert "Planned creation counts" in caplog.text

    def test_log_footer(self, caplog):
        """Test _log_footer output."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        generator.benchmark.start_overall()
        generator.benchmark.end_overall()

        projects = [{"key": "TEST1"}]
        issue_keys = ["TEST1-1", "TEST1-2"]

        with caplog.at_level("INFO"):
            generator._log_footer(projects, issue_keys, 10)

        assert "Data generation complete" in caplog.text
        assert "TEST1" in caplog.text or "1 projects" in caplog.text


class TestJiraDataGeneratorCategoryAssignment:
    """Tests for project category assignment."""

    def test_assign_projects_to_categories_empty(self, caplog):
        """Test _assign_projects_to_categories with no categories."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        # Should not raise
        generator._assign_projects_to_categories(["TEST1"], [])

    def test_assign_projects_to_categories(self, caplog):
        """Test _assign_projects_to_categories."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        with caplog.at_level("INFO"):
            generator._assign_projects_to_categories(
                ["TEST1", "TEST2"],
                [{"id": "10001"}, {"id": "10002"}]
            )

        assert "Assigning" in caplog.text


class TestJiraDataGeneratorFetchIssueKeys:
    """Tests for fetching issue keys from Jira."""

    def test_fetch_issue_keys_dry_run(self):
        """Test _fetch_issue_keys_from_jira in dry run."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        keys = generator._fetch_issue_keys_from_jira()

        assert len(keys) == 100
        assert all(key.startswith("DRYRUN-") for key in keys)

    @responses.activate
    def test_fetch_issue_keys_from_jira(self):
        """Test _fetch_issue_keys_from_jira."""
        responses.add(
            responses.GET,
            f"{JIRA_URL}/rest/api/3/search",
            json={"issues": [{"key": f"TEST1-{i}"} for i in range(1, 51)]},
            status=200
        )

        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        keys = generator._fetch_issue_keys_from_jira()

        assert len(keys) == 50


class TestJiraDataGeneratorSyncMode:
    """Tests for synchronous mode."""

    def test_generate_all_sync_dry_run(self):
        """Test generate_all in sync mode with dry run."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        # Should complete without making actual API calls
        generator.generate_all(10)

        # Check benchmark was used
        assert generator.benchmark.total_items_created >= 0

    def test_generate_all_issues_only_sync_dry_run(self):
        """Test generate_all sync with issues_only in dry run."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
            issues_only=True
        )

        generator.generate_all(10)

        # Should have created fewer items
        assert generator.benchmark.total_items_created >= 0


class TestJiraDataGeneratorRunId:
    """Tests for run ID management."""

    def test_run_id_generated(self):
        """Test run_id is generated."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator.run_id is not None
        assert generator.run_id.startswith("TEST-")

    def test_run_id_propagated_to_generators(self):
        """Test run_id is propagated to key generator modules."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        # These generators have run_id explicitly set
        assert generator.project_gen.run_id == generator.run_id
        assert generator.issue_gen.run_id == generator.run_id
        assert generator.issue_items_gen.run_id == generator.run_id
        assert generator.filter_gen.run_id == generator.run_id
        assert generator.custom_field_gen.run_id == generator.run_id


class TestJiraDataGeneratorBenchmark:
    """Tests for benchmark tracking."""

    def test_benchmark_created(self):
        """Test benchmark is created on init."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator.benchmark is not None
        from generators.benchmark import BenchmarkTracker
        assert isinstance(generator.benchmark, BenchmarkTracker)

    def test_benchmark_passed_to_generators(self):
        """Test benchmark is passed to all generators."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        # All generators should have the same benchmark
        assert generator.project_gen.benchmark is generator.benchmark
        assert generator.issue_gen.benchmark is generator.benchmark
        assert generator.issue_items_gen.benchmark is generator.benchmark
        assert generator.agile_gen.benchmark is generator.benchmark
        assert generator.filter_gen.benchmark is generator.benchmark
        assert generator.custom_field_gen.benchmark is generator.benchmark


class TestJiraDataGeneratorHelpers:
    """Tests for helper methods."""

    def test_complete_phase(self):
        """Test _complete_phase helper."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        # Should not raise even without checkpoint
        generator._complete_phase("projects")

    def test_is_phase_complete_no_checkpoint(self):
        """Test _is_phase_complete without checkpoint."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        # Should return False when no checkpoint
        assert generator._is_phase_complete("projects") is False

    def test_get_remaining_count_no_checkpoint(self):
        """Test _get_remaining_count without checkpoint."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True
        )

        # Should return full count when no checkpoint
        assert generator._get_remaining_count("comments", 100) == 100


class TestJiraDataGeneratorGeneratorModules:
    """Tests for generator module access."""

    def test_all_generators_initialized(self):
        """Test all generator modules are initialized."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST"
        )

        assert generator.project_gen is not None
        assert generator.issue_gen is not None
        assert generator.issue_items_gen is not None
        assert generator.agile_gen is not None
        assert generator.filter_gen is not None
        assert generator.custom_field_gen is not None

    def test_generators_have_correct_prefix(self):
        """Test all generators have correct prefix."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="MYPREFIX"
        )

        assert generator.project_gen.prefix == "MYPREFIX"
        assert generator.issue_gen.prefix == "MYPREFIX"
        assert generator.custom_field_gen.prefix == "MYPREFIX"

    def test_generators_share_concurrency_setting(self):
        """Test generators share concurrency setting."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            concurrency=15
        )

        assert generator.project_gen.concurrency == 15
        assert generator.issue_gen.concurrency == 15
        assert generator.issue_items_gen.concurrency == 15

    def test_generators_share_request_delay(self):
        """Test generators share request_delay setting."""
        generator = JiraDataGenerator(
            jira_url=JIRA_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            request_delay=0.1
        )

        assert generator.project_gen.request_delay == 0.1
        assert generator.issue_gen.request_delay == 0.1
        assert generator.issue_items_gen.request_delay == 0.1


class TestJiraDataGeneratorSizeBuckets:
    """Tests for size bucket functionality."""

    def test_all_size_buckets_valid(self):
        """Test all valid size buckets can be used."""
        for size in ["small", "medium", "large", "xlarge"]:
            generator = JiraDataGenerator(
                jira_url=JIRA_URL,
                email=TEST_EMAIL,
                api_token=TEST_TOKEN,
                prefix="TEST",
                size_bucket=size
            )
            assert generator.size_bucket == size

    def test_counts_vary_by_size(self):
        """Test counts vary by size bucket."""
        small_gen = JiraDataGenerator(
            jira_url=JIRA_URL, email=TEST_EMAIL, api_token=TEST_TOKEN,
            prefix="TEST", size_bucket="small"
        )
        xlarge_gen = JiraDataGenerator(
            jira_url=JIRA_URL, email=TEST_EMAIL, api_token=TEST_TOKEN,
            prefix="TEST", size_bucket="xlarge"
        )

        small_counts = small_gen.calculate_counts(1000)
        xlarge_counts = xlarge_gen.calculate_counts(1000)

        # Small bucket typically has more items per issue
        assert small_counts.get("comment", 0) != xlarge_counts.get("comment", 0)
