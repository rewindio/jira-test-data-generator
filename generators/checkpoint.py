"""
Checkpoint management for resumable data generation.

Provides checkpoint saving and loading for long-running data generation tasks,
allowing resumption after failures or interruptions.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class PhaseProgress:
    """Tracks progress for a single generation phase."""
    status: str = "pending"  # pending, in_progress, complete
    target_count: int = 0
    created_count: int = 0
    # For phases that create named items (projects, boards, etc.)
    created_items: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhaseProgress":
        return cls(**data)


@dataclass
class CheckpointData:
    """Complete checkpoint state for a generation run."""
    # Run identification
    run_id: str
    prefix: str
    size: str
    target_issue_count: int

    # Timestamps
    started_at: str
    last_updated: str

    # Configuration
    jira_url: str
    async_mode: bool
    concurrency: int

    # Phase progress
    phases: Dict[str, PhaseProgress] = field(default_factory=dict)

    # Critical data needed for resume
    project_keys: List[str] = field(default_factory=list)
    project_ids: Dict[str, str] = field(default_factory=dict)  # key -> id mapping
    issue_keys: List[str] = field(default_factory=list)
    category_ids: List[str] = field(default_factory=list)

    # For large issue counts, track per-project to avoid huge lists
    issues_per_project: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "run_id": self.run_id,
            "prefix": self.prefix,
            "size": self.size,
            "target_issue_count": self.target_issue_count,
            "started_at": self.started_at,
            "last_updated": self.last_updated,
            "jira_url": self.jira_url,
            "async_mode": self.async_mode,
            "concurrency": self.concurrency,
            "project_keys": self.project_keys,
            "project_ids": self.project_ids,
            "issue_keys": self.issue_keys,
            "category_ids": self.category_ids,
            "issues_per_project": self.issues_per_project,
            "phases": {k: v.to_dict() for k, v in self.phases.items()}
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointData":
        phases = {k: PhaseProgress.from_dict(v) for k, v in data.pop("phases", {}).items()}
        return cls(phases=phases, **data)


class CheckpointManager:
    """Manages checkpoint file operations for resumable generation."""

    # All phases in execution order
    PHASE_ORDER = [
        "project_categories",
        "projects",
        "project_properties",
        "issues",
        "components",
        "versions",
        "comments",
        "worklogs",
        "issue_links",
        "watchers",
        "attachments",
        "votes",
        "issue_properties",
        "remote_links",
        "boards",
        "sprints",
        "filters",
        "dashboards",
    ]

    def __init__(self, prefix: str, checkpoint_dir: Optional[Path] = None):
        """Initialize checkpoint manager.

        Args:
            prefix: The run prefix (used for checkpoint filename)
            checkpoint_dir: Directory to store checkpoints (default: current directory)
        """
        self.prefix = prefix
        self.checkpoint_dir = checkpoint_dir or Path.cwd()
        self.logger = logging.getLogger(__name__)
        self._checkpoint: Optional[CheckpointData] = None
        self._checkpoint_path: Optional[Path] = None

    def get_checkpoint_path(self, run_id: Optional[str] = None) -> Path:
        """Get the checkpoint file path."""
        if run_id:
            return self.checkpoint_dir / f"{run_id}-checkpoint.json"
        return self.checkpoint_dir / f"{self.prefix}-checkpoint.json"

    def find_existing_checkpoint(self) -> Optional[Path]:
        """Find an existing checkpoint file for this prefix."""
        # First check for prefix-only checkpoint (active/latest)
        prefix_checkpoint = self.get_checkpoint_path()
        if prefix_checkpoint.exists():
            return prefix_checkpoint

        # Look for any run-specific checkpoints
        pattern = f"{self.prefix}-*-checkpoint.json"
        checkpoints = sorted(self.checkpoint_dir.glob(pattern), reverse=True)
        if checkpoints:
            return checkpoints[0]

        return None

    def initialize(
        self,
        run_id: str,
        size: str,
        target_issue_count: int,
        jira_url: str,
        async_mode: bool,
        concurrency: int,
        counts: Dict[str, int]
    ) -> CheckpointData:
        """Initialize a new checkpoint for a fresh run.

        Args:
            run_id: Unique run identifier
            size: Size bucket (small, medium, large, xlarge)
            target_issue_count: Total issues to create
            jira_url: Jira instance URL
            async_mode: Whether async mode is enabled
            concurrency: Concurrency level
            counts: Calculated counts for each item type

        Returns:
            Initialized CheckpointData
        """
        now = datetime.now().isoformat()

        # Initialize all phases from counts
        phases = {}
        phase_mapping = {
            "project_categories": "project_category",
            "projects": "project",
            "project_properties": "project_property",
            "issues": None,  # Special case - use target_issue_count
            "components": "project_component",
            "versions": "project_version",
            "comments": "comment",
            "worklogs": "issue_worklog",
            "issue_links": "issue_link",
            "watchers": "issue_watcher",
            "attachments": "issue_attachment",
            "votes": "issue_vote",
            "issue_properties": "issue_properties",
            "remote_links": "issue_remote_link",
            "boards": "board",
            "sprints": "sprint",
            "filters": "filter",
            "dashboards": "dashboard",
        }

        for phase_name in self.PHASE_ORDER:
            count_key = phase_mapping.get(phase_name)
            if phase_name == "issues":
                target = target_issue_count
            elif count_key and count_key in counts:
                target = counts[count_key]
            else:
                target = 0

            phases[phase_name] = PhaseProgress(
                status="pending",
                target_count=target,
                created_count=0,
                created_items=[]
            )

        self._checkpoint = CheckpointData(
            run_id=run_id,
            prefix=self.prefix,
            size=size,
            target_issue_count=target_issue_count,
            started_at=now,
            last_updated=now,
            jira_url=jira_url,
            async_mode=async_mode,
            concurrency=concurrency,
            phases=phases,
            project_keys=[],
            project_ids={},
            issue_keys=[],
            category_ids=[],
            issues_per_project={}
        )

        # Use prefix-only path for active checkpoint
        self._checkpoint_path = self.get_checkpoint_path()
        self.save()

        self.logger.info(f"Initialized checkpoint: {self._checkpoint_path}")
        return self._checkpoint

    def load(self, checkpoint_path: Optional[Path] = None) -> Optional[CheckpointData]:
        """Load checkpoint from file.

        Args:
            checkpoint_path: Path to checkpoint file (auto-detect if None)

        Returns:
            Loaded CheckpointData or None if not found
        """
        if checkpoint_path is None:
            checkpoint_path = self.find_existing_checkpoint()

        if checkpoint_path is None or not checkpoint_path.exists():
            self.logger.debug(f"No checkpoint found for prefix: {self.prefix}")
            return None

        try:
            with open(checkpoint_path, 'r') as f:
                data = json.load(f)

            self._checkpoint = CheckpointData.from_dict(data)
            self._checkpoint_path = checkpoint_path
            self.logger.info(f"Loaded checkpoint from: {checkpoint_path}")
            self.logger.info(f"  Run ID: {self._checkpoint.run_id}")
            self.logger.info(f"  Started: {self._checkpoint.started_at}")
            self.logger.info(f"  Last updated: {self._checkpoint.last_updated}")

            return self._checkpoint

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self.logger.error(f"Failed to load checkpoint from {checkpoint_path}: {e}")
            return None

    def save(self) -> bool:
        """Save current checkpoint to file.

        Returns:
            True if successful, False otherwise
        """
        if self._checkpoint is None:
            self.logger.warning("No checkpoint data to save")
            return False

        if self._checkpoint_path is None:
            self._checkpoint_path = self.get_checkpoint_path()

        self._checkpoint.last_updated = datetime.now().isoformat()

        try:
            # Write to temp file first, then rename for atomicity
            temp_path = self._checkpoint_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(self._checkpoint.to_dict(), f, indent=2)

            temp_path.replace(self._checkpoint_path)
            return True

        except (IOError, OSError) as e:
            self.logger.error(f"Failed to save checkpoint: {e}")
            return False

    @property
    def checkpoint(self) -> Optional[CheckpointData]:
        """Get current checkpoint data."""
        return self._checkpoint

    # ========== Phase Management ==========

    def start_phase(self, phase_name: str) -> None:
        """Mark a phase as in progress."""
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].status = "in_progress"
            self.save()

    def complete_phase(self, phase_name: str) -> None:
        """Mark a phase as complete."""
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].status = "complete"
            self.save()

    def is_phase_complete(self, phase_name: str) -> bool:
        """Check if a phase is complete."""
        if self._checkpoint and phase_name in self._checkpoint.phases:
            return self._checkpoint.phases[phase_name].status == "complete"
        return False

    def get_phase_progress(self, phase_name: str) -> Optional[PhaseProgress]:
        """Get progress for a specific phase."""
        if self._checkpoint and phase_name in self._checkpoint.phases:
            return self._checkpoint.phases[phase_name]
        return None

    def get_remaining_count(self, phase_name: str) -> int:
        """Get remaining items to create for a phase."""
        progress = self.get_phase_progress(phase_name)
        if progress:
            return max(0, progress.target_count - progress.created_count)
        return 0

    # ========== Progress Updates ==========

    def update_phase_count(self, phase_name: str, created_count: int) -> None:
        """Update the created count for a phase.

        Args:
            phase_name: Phase to update
            created_count: Total items created so far (not increment)
        """
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].created_count = created_count
            self.save()

    def increment_phase_count(self, phase_name: str, increment: int = 1) -> None:
        """Increment the created count for a phase.

        Args:
            phase_name: Phase to update
            increment: Number of items to add to count
        """
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].created_count += increment
            # Save periodically (every 50 items) to avoid excessive I/O
            if self._checkpoint.phases[phase_name].created_count % 50 == 0:
                self.save()

    def add_phase_items(self, phase_name: str, items: List[str]) -> None:
        """Add created items to a phase (for items that need to be tracked).

        Args:
            phase_name: Phase to update
            items: List of item identifiers (keys, IDs, etc.)
        """
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].created_items.extend(items)
            self._checkpoint.phases[phase_name].created_count = len(
                self._checkpoint.phases[phase_name].created_items
            )
            self.save()

    # ========== Critical Data Updates ==========

    def set_projects(self, projects: List[Dict[str, str]]) -> None:
        """Store created projects.

        Args:
            projects: List of project dicts with 'key' and 'id'
        """
        if self._checkpoint:
            self._checkpoint.project_keys = [p['key'] for p in projects]
            self._checkpoint.project_ids = {p['key']: p['id'] for p in projects}
            self.save()

    def add_project(self, project_key: str, project_id: str) -> None:
        """Add a single project to checkpoint."""
        if self._checkpoint:
            if project_key not in self._checkpoint.project_keys:
                self._checkpoint.project_keys.append(project_key)
            self._checkpoint.project_ids[project_key] = project_id
            self.save()

    def set_categories(self, category_ids: List[str]) -> None:
        """Store created category IDs."""
        if self._checkpoint:
            self._checkpoint.category_ids = category_ids
            self.save()

    def add_issue_keys(self, issue_keys: List[str], project_key: str) -> None:
        """Add issue keys to checkpoint.

        Args:
            issue_keys: List of issue keys created
            project_key: Project the issues belong to
        """
        if self._checkpoint:
            # For very large runs, we only track count per project
            if len(self._checkpoint.issue_keys) < 100000:
                self._checkpoint.issue_keys.extend(issue_keys)

            # Always track per-project counts
            current = self._checkpoint.issues_per_project.get(project_key, 0)
            self._checkpoint.issues_per_project[project_key] = current + len(issue_keys)

            # Update phase progress
            total_issues = sum(self._checkpoint.issues_per_project.values())
            self._checkpoint.phases["issues"].created_count = total_issues

            # Save periodically (every 500 issues) to balance safety vs performance
            # At 50 issues/batch, this saves every 10 batches
            # Max data loss on crash: ~500 issues instead of ~50
            if total_issues % 500 == 0:
                self.save()

    def get_total_issues_created(self) -> int:
        """Get total number of issues created across all projects."""
        if self._checkpoint:
            return sum(self._checkpoint.issues_per_project.values())
        return 0

    # ========== Resume Helpers ==========

    def get_issues_needed_per_project(self, projects: List[Dict], total_issues: int) -> Dict[str, int]:
        """Calculate how many issues still need to be created per project.

        Args:
            projects: List of project dicts with 'key'
            total_issues: Total target issue count

        Returns:
            Dict mapping project_key -> issues_to_create
        """
        if not self._checkpoint:
            # No checkpoint - create all issues evenly distributed
            per_project = total_issues // len(projects)
            remainder = total_issues % len(projects)
            return {
                p['key']: per_project + (1 if i < remainder else 0)
                for i, p in enumerate(projects)
            }

        # Calculate remaining per project
        existing = self._checkpoint.issues_per_project
        per_project = total_issues // len(projects)
        remainder = total_issues % len(projects)

        result = {}
        for i, project in enumerate(projects):
            key = project['key']
            target = per_project + (1 if i < remainder else 0)
            created = existing.get(key, 0)
            result[key] = max(0, target - created)

        return result

    def get_resume_summary(self) -> str:
        """Get a human-readable summary of checkpoint state for resume."""
        if not self._checkpoint:
            return "No checkpoint loaded"

        lines = [
            f"Resuming run: {self._checkpoint.run_id}",
            f"Started: {self._checkpoint.started_at}",
            f"Last updated: {self._checkpoint.last_updated}",
            "",
            "Phase Progress:",
        ]

        for phase_name in self.PHASE_ORDER:
            progress = self._checkpoint.phases.get(phase_name)
            if progress and progress.target_count > 0:
                status_icon = {
                    "complete": "[OK]",
                    "in_progress": "[>>]",
                    "pending": "[  ]"
                }.get(progress.status, "[??]")

                lines.append(
                    f"  {status_icon} {phase_name}: {progress.created_count}/{progress.target_count}"
                )

        lines.append("")
        lines.append(f"Projects: {len(self._checkpoint.project_keys)}")
        lines.append(f"Total issues: {self.get_total_issues_created()}/{self._checkpoint.target_issue_count}")

        return "\n".join(lines)

    def finalize(self) -> None:
        """Mark all phases as complete and rename checkpoint to include run_id."""
        if not self._checkpoint:
            return

        # Mark all phases complete
        for phase in self._checkpoint.phases.values():
            if phase.status != "complete" and phase.created_count >= phase.target_count:
                phase.status = "complete"

        self.save()

        # Rename to run_id-specific file for archival
        if self._checkpoint_path:
            final_path = self.get_checkpoint_path(self._checkpoint.run_id)
            if self._checkpoint_path != final_path:
                try:
                    self._checkpoint_path.rename(final_path)
                    self.logger.info(f"Archived checkpoint to: {final_path}")
                except OSError as e:
                    self.logger.warning(f"Could not archive checkpoint: {e}")

    def delete(self) -> bool:
        """Delete the checkpoint file."""
        if self._checkpoint_path and self._checkpoint_path.exists():
            try:
                self._checkpoint_path.unlink()
                self.logger.info(f"Deleted checkpoint: {self._checkpoint_path}")
                return True
            except OSError as e:
                self.logger.error(f"Failed to delete checkpoint: {e}")
                return False
        return False
