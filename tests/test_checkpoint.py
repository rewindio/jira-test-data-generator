"""
Unit tests for generators/checkpoint.py - CheckpointManager, CheckpointData, PhaseProgress.
"""

import json

from generators.checkpoint import CheckpointData, CheckpointManager, PhaseProgress


class TestPhaseProgress:
    """Tests for PhaseProgress dataclass."""

    def test_init_defaults(self):
        """Test PhaseProgress initializes with defaults."""
        progress = PhaseProgress()
        assert progress.status == "pending"
        assert progress.target_count == 0
        assert progress.created_count == 0
        assert progress.created_items == []

    def test_init_with_values(self):
        """Test PhaseProgress with explicit values."""
        progress = PhaseProgress(
            status="in_progress", target_count=100, created_count=50, created_items=["item1", "item2"]
        )
        assert progress.status == "in_progress"
        assert progress.target_count == 100
        assert progress.created_count == 50
        assert progress.created_items == ["item1", "item2"]

    def test_to_dict(self):
        """Test PhaseProgress serialization."""
        progress = PhaseProgress(status="complete", target_count=10, created_count=10)
        result = progress.to_dict()
        assert result["status"] == "complete"
        assert result["target_count"] == 10
        assert result["created_count"] == 10
        assert "created_items" in result

    def test_from_dict(self):
        """Test PhaseProgress deserialization."""
        data = {"status": "in_progress", "target_count": 50, "created_count": 25, "created_items": ["a", "b"]}
        progress = PhaseProgress.from_dict(data)
        assert progress.status == "in_progress"
        assert progress.target_count == 50
        assert progress.created_count == 25
        assert progress.created_items == ["a", "b"]


class TestCheckpointData:
    """Tests for CheckpointData dataclass."""

    def test_init_required_fields(self):
        """Test CheckpointData with required fields."""
        data = CheckpointData(
            run_id="TEST-123",
            prefix="TEST",
            size="small",
            target_issue_count=100,
            started_at="2024-01-01T00:00:00",
            last_updated="2024-01-01T00:00:00",
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
        )
        assert data.run_id == "TEST-123"
        assert data.prefix == "TEST"
        assert data.phases == {}
        assert data.project_keys == []
        assert data.issue_keys == []

    def test_to_dict(self):
        """Test CheckpointData serialization."""
        data = CheckpointData(
            run_id="TEST-123",
            prefix="TEST",
            size="small",
            target_issue_count=100,
            started_at="2024-01-01T00:00:00",
            last_updated="2024-01-01T00:00:00",
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            phases={"issues": PhaseProgress(status="in_progress", target_count=100)},
        )
        result = data.to_dict()
        assert result["run_id"] == "TEST-123"
        assert result["prefix"] == "TEST"
        assert "phases" in result
        assert result["phases"]["issues"]["status"] == "in_progress"

    def test_from_dict(self, sample_checkpoint_data):
        """Test CheckpointData deserialization."""
        data = CheckpointData.from_dict(sample_checkpoint_data.copy())
        assert data.run_id == "TEST-20241208-120000"
        assert data.prefix == "TEST"
        assert "projects" in data.phases
        assert data.phases["projects"].status == "complete"


class TestCheckpointManager:
    """Tests for CheckpointManager class."""

    def test_init(self, temp_checkpoint_dir):
        """Test CheckpointManager initialization."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        assert manager.prefix == "TEST"
        assert manager.checkpoint_dir == temp_checkpoint_dir
        assert manager._checkpoint is None

    def test_get_checkpoint_path_no_run_id(self, temp_checkpoint_dir):
        """Test get_checkpoint_path without run_id."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        path = manager.get_checkpoint_path()
        assert path == temp_checkpoint_dir / "TEST-checkpoint.json"

    def test_get_checkpoint_path_with_run_id(self, temp_checkpoint_dir):
        """Test get_checkpoint_path with run_id."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        path = manager.get_checkpoint_path(run_id="TEST-20241208-120000")
        assert path == temp_checkpoint_dir / "TEST-20241208-120000-checkpoint.json"

    def test_find_existing_checkpoint_none(self, temp_checkpoint_dir):
        """Test find_existing_checkpoint when none exists."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        assert manager.find_existing_checkpoint() is None

    def test_find_existing_checkpoint_prefix(self, temp_checkpoint_dir):
        """Test find_existing_checkpoint finds prefix checkpoint."""
        checkpoint_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        checkpoint_path.write_text("{}")

        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        found = manager.find_existing_checkpoint()
        assert found == checkpoint_path

    def test_find_existing_checkpoint_run_specific(self, temp_checkpoint_dir):
        """Test find_existing_checkpoint finds run-specific checkpoint."""
        checkpoint_path = temp_checkpoint_dir / "TEST-20241208-120000-checkpoint.json"
        checkpoint_path.write_text("{}")

        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        found = manager.find_existing_checkpoint()
        assert found == checkpoint_path

    def test_initialize(self, temp_checkpoint_dir):
        """Test initialize creates checkpoint."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        counts = {"comment": 480, "issue_worklog": 100}

        result = manager.initialize(
            run_id="TEST-20241208-120000",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts=counts,
        )

        assert result is not None
        assert result.run_id == "TEST-20241208-120000"
        assert "issues" in result.phases
        assert result.phases["issues"].target_count == 100
        assert result.phases["comments"].target_count == 480

        # Check file was created
        checkpoint_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        assert checkpoint_path.exists()

    def test_load_success(self, temp_checkpoint_dir, sample_checkpoint_data):
        """Test load reads checkpoint file."""
        checkpoint_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        checkpoint_path.write_text(json.dumps(sample_checkpoint_data))

        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        result = manager.load(checkpoint_path)

        assert result is not None
        assert result.run_id == "TEST-20241208-120000"
        assert len(result.project_keys) == 2

    def test_load_auto_detect(self, temp_checkpoint_dir, sample_checkpoint_data):
        """Test load auto-detects checkpoint file."""
        checkpoint_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        checkpoint_path.write_text(json.dumps(sample_checkpoint_data))

        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        result = manager.load()

        assert result is not None
        assert result.run_id == "TEST-20241208-120000"

    def test_load_not_found(self, temp_checkpoint_dir):
        """Test load returns None when file not found."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        result = manager.load()
        assert result is None

    def test_load_invalid_json(self, temp_checkpoint_dir):
        """Test load handles invalid JSON."""
        checkpoint_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        checkpoint_path.write_text("not valid json")

        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        result = manager.load(checkpoint_path)
        assert result is None

    def test_save_no_checkpoint(self, temp_checkpoint_dir):
        """Test save returns False with no checkpoint."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        assert manager.save() is False

    def test_save_success(self, temp_checkpoint_dir):
        """Test save writes checkpoint file."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Modify and save
        manager._checkpoint.project_keys = ["TEST1"]
        result = manager.save()
        assert result is True

        # Verify file contents
        checkpoint_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        data = json.loads(checkpoint_path.read_text())
        assert data["project_keys"] == ["TEST1"]

    def test_checkpoint_property(self, temp_checkpoint_dir):
        """Test checkpoint property returns checkpoint."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        assert manager.checkpoint is None

        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )
        assert manager.checkpoint is not None
        assert manager.checkpoint.run_id == "TEST-123"

    # ========== Phase Management Tests ==========

    def test_start_phase(self, temp_checkpoint_dir):
        """Test start_phase marks phase as in_progress."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.start_phase("issues")
        assert manager._checkpoint.phases["issues"].status == "in_progress"

    def test_complete_phase(self, temp_checkpoint_dir):
        """Test complete_phase marks phase as complete."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.start_phase("issues")
        manager.complete_phase("issues")
        assert manager._checkpoint.phases["issues"].status == "complete"

    def test_is_phase_complete(self, temp_checkpoint_dir):
        """Test is_phase_complete returns correct status."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        assert not manager.is_phase_complete("issues")
        manager.complete_phase("issues")
        assert manager.is_phase_complete("issues")

    def test_is_phase_complete_no_checkpoint(self, temp_checkpoint_dir):
        """Test is_phase_complete returns False with no checkpoint."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        assert not manager.is_phase_complete("issues")

    def test_get_phase_progress(self, temp_checkpoint_dir):
        """Test get_phase_progress returns phase."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={"comment": 480},
        )

        progress = manager.get_phase_progress("comments")
        assert progress is not None
        assert progress.target_count == 480

    def test_get_phase_progress_not_found(self, temp_checkpoint_dir):
        """Test get_phase_progress returns None for unknown phase."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )
        assert manager.get_phase_progress("unknown") is None

    def test_get_remaining_count(self, temp_checkpoint_dir):
        """Test get_remaining_count calculation."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={"comment": 480},
        )

        # Initially all remaining
        assert manager.get_remaining_count("comments") == 480

        # After some created
        manager._checkpoint.phases["comments"].created_count = 200
        assert manager.get_remaining_count("comments") == 280

    # ========== Progress Updates Tests ==========

    def test_update_phase_count(self, temp_checkpoint_dir):
        """Test update_phase_count sets count."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={"comment": 480},
        )

        manager.update_phase_count("comments", 100)
        assert manager._checkpoint.phases["comments"].created_count == 100

    def test_increment_phase_count(self, temp_checkpoint_dir):
        """Test increment_phase_count adds to count."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={"comment": 480},
        )

        manager.increment_phase_count("comments", 10)
        assert manager._checkpoint.phases["comments"].created_count == 10
        manager.increment_phase_count("comments", 5)
        assert manager._checkpoint.phases["comments"].created_count == 15

    def test_add_phase_items(self, temp_checkpoint_dir):
        """Test add_phase_items adds items and updates count."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_phase_items("projects", ["TEST1", "TEST2"])
        assert manager._checkpoint.phases["projects"].created_items == ["TEST1", "TEST2"]
        assert manager._checkpoint.phases["projects"].created_count == 2

    # ========== Critical Data Updates Tests ==========

    def test_set_projects(self, temp_checkpoint_dir):
        """Test set_projects stores project data."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        projects = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        manager.set_projects(projects)

        assert manager._checkpoint.project_keys == ["TEST1", "TEST2"]
        assert manager._checkpoint.project_ids == {"TEST1": "10001", "TEST2": "10002"}

    def test_add_project(self, temp_checkpoint_dir):
        """Test add_project adds single project."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_project("TEST1", "10001")
        assert "TEST1" in manager._checkpoint.project_keys
        assert manager._checkpoint.project_ids["TEST1"] == "10001"

        # Adding same project again shouldn't duplicate
        manager.add_project("TEST1", "10001")
        assert manager._checkpoint.project_keys.count("TEST1") == 1

    def test_set_categories(self, temp_checkpoint_dir):
        """Test set_categories stores category IDs."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.set_categories(["10001", "10002"])
        assert manager._checkpoint.category_ids == ["10001", "10002"]

    def test_add_issue_keys(self, temp_checkpoint_dir):
        """Test add_issue_keys stores issue data."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_issue_keys(["TEST1-1", "TEST1-2"], "TEST1")

        assert "TEST1-1" in manager._checkpoint.issue_keys
        assert manager._checkpoint.issues_per_project["TEST1"] == 2
        assert manager._checkpoint.phases["issues"].created_count == 2

    def test_add_issue_keys_large_count(self, temp_checkpoint_dir):
        """Test add_issue_keys stops storing keys after 100k."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=200000,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Add 100k keys
        keys = [f"TEST1-{i}" for i in range(1, 100001)]
        manager.add_issue_keys(keys, "TEST1")
        assert len(manager._checkpoint.issue_keys) == 100000

        # Try to add more - count should update but keys list should not grow
        more_keys = [f"TEST1-{i}" for i in range(100001, 100011)]
        manager.add_issue_keys(more_keys, "TEST1")
        assert len(manager._checkpoint.issue_keys) == 100000  # Still capped
        assert manager._checkpoint.issues_per_project["TEST1"] == 100010  # Count updated

    def test_get_total_issues_created(self, temp_checkpoint_dir):
        """Test get_total_issues_created sums all projects."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_issue_keys(["TEST1-1", "TEST1-2"], "TEST1")
        manager.add_issue_keys(["TEST2-1", "TEST2-2", "TEST2-3"], "TEST2")

        assert manager.get_total_issues_created() == 5

    def test_get_total_issues_created_no_checkpoint(self, temp_checkpoint_dir):
        """Test get_total_issues_created returns 0 with no checkpoint."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        assert manager.get_total_issues_created() == 0

    # ========== Resume Helpers Tests ==========

    def test_get_issues_needed_per_project_no_checkpoint(self, temp_checkpoint_dir):
        """Test get_issues_needed_per_project without checkpoint."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        projects = [{"key": "TEST1"}, {"key": "TEST2"}]

        result = manager.get_issues_needed_per_project(projects, 100)
        assert result["TEST1"] == 50
        assert result["TEST2"] == 50

    def test_get_issues_needed_per_project_with_checkpoint(self, temp_checkpoint_dir):
        """Test get_issues_needed_per_project with partial progress."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Add some existing issues
        manager.add_issue_keys(["TEST1-1"] * 30, "TEST1")

        projects = [{"key": "TEST1"}, {"key": "TEST2"}]
        result = manager.get_issues_needed_per_project(projects, 100)

        assert result["TEST1"] == 20  # 50 - 30 = 20
        assert result["TEST2"] == 50  # None created yet

    def test_get_issues_needed_per_project_uneven_distribution(self, temp_checkpoint_dir):
        """Test get_issues_needed_per_project with uneven count."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        projects = [{"key": "TEST1"}, {"key": "TEST2"}, {"key": "TEST3"}]

        result = manager.get_issues_needed_per_project(projects, 100)
        # 100 / 3 = 33 with 1 remainder
        total = sum(result.values())
        assert total == 100

    def test_get_resume_summary_no_checkpoint(self, temp_checkpoint_dir):
        """Test get_resume_summary without checkpoint."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        assert "No checkpoint loaded" in manager.get_resume_summary()

    def test_get_resume_summary(self, temp_checkpoint_dir):
        """Test get_resume_summary with checkpoint."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={"comment": 480},
        )

        manager._checkpoint.project_keys = ["TEST1", "TEST2"]

        # Set target and create count for projects to show in summary
        manager._checkpoint.phases["projects"].target_count = 2
        manager._checkpoint.phases["projects"].created_count = 2
        manager.complete_phase("projects")

        manager.start_phase("issues")
        manager._checkpoint.phases["issues"].target_count = 100
        manager._checkpoint.phases["issues"].created_count = 50

        summary = manager.get_resume_summary()
        assert "Resuming run" in summary
        assert "TEST-123" in summary
        assert "[OK]" in summary  # projects complete
        assert "[>>]" in summary  # issues in progress

    def test_finalize(self, temp_checkpoint_dir):
        """Test finalize completes phases and renames file."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-20241208-120000",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Set all counts to match targets
        manager._checkpoint.phases["issues"].created_count = 100
        manager._checkpoint.phases["issues"].target_count = 100

        manager.finalize()

        # Check file was renamed
        final_path = temp_checkpoint_dir / "TEST-20241208-120000-checkpoint.json"
        assert final_path.exists()

        # Original path should not exist
        original_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        assert not original_path.exists()

    def test_delete(self, temp_checkpoint_dir):
        """Test delete removes checkpoint file."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        checkpoint_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        assert checkpoint_path.exists()

        result = manager.delete()
        assert result is True
        assert not checkpoint_path.exists()

    def test_delete_no_file(self, temp_checkpoint_dir):
        """Test delete returns False when no file."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        assert manager.delete() is False

    def test_phase_order(self):
        """Test PHASE_ORDER contains expected phases."""
        assert "projects" in CheckpointManager.PHASE_ORDER
        assert "issues" in CheckpointManager.PHASE_ORDER
        assert "comments" in CheckpointManager.PHASE_ORDER
        assert "watchers" in CheckpointManager.PHASE_ORDER
        assert "attachments" in CheckpointManager.PHASE_ORDER

    def test_atomic_save(self, temp_checkpoint_dir):
        """Test save uses atomic write (temp file + rename)."""
        manager = CheckpointManager("TEST", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TEST-123",
            size="small",
            target_issue_count=100,
            jira_url="https://test.atlassian.net",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # The temp file shouldn't exist after save completes
        temp_path = temp_checkpoint_dir / "TEST-checkpoint.tmp"
        manager.save()
        assert not temp_path.exists()

        # But the actual checkpoint should exist
        checkpoint_path = temp_checkpoint_dir / "TEST-checkpoint.json"
        assert checkpoint_path.exists()
