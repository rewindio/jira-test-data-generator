"""
Benchmark tracking for data generation performance analysis.

Tracks timing per phase and calculates rates for extrapolation to larger datasets.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PhaseMetrics:
    """Metrics for a single generation phase."""

    name: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    items_created: int = 0
    items_target: int = 0
    rate_limited: int = 0  # Number of 429 responses during this phase
    errors: int = 0  # Number of errors during this phase

    @property
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def items_per_second(self) -> float:
        """Calculate items created per second."""
        duration = self.duration_seconds
        if duration <= 0 or self.items_created <= 0:
            return 0.0
        return self.items_created / duration

    @property
    def seconds_per_item(self) -> float:
        """Calculate seconds per item."""
        if self.items_created <= 0:
            return 0.0
        return self.duration_seconds / self.items_created

    @property
    def is_complete(self) -> bool:
        """Check if phase is complete."""
        return self.end_time is not None

    def format_duration(self) -> str:
        """Format duration as human-readable string."""
        seconds = self.duration_seconds
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.2f}h"

    def format_rate(self) -> str:
        """Format rate as human-readable string."""
        rate = self.items_per_second
        if rate >= 1:
            return f"{rate:.1f}/s"
        elif rate > 0:
            return f"{1 / rate:.1f}s/item"
        return "N/A"


class BenchmarkTracker:
    """Tracks performance metrics across all generation phases."""

    def __init__(self):
        self.phases: dict[str, PhaseMetrics] = {}
        self.overall_start: Optional[float] = None
        self.overall_end: Optional[float] = None
        self.logger = logging.getLogger(__name__)

        # Request statistics (global)
        self.total_requests: int = 0
        self.rate_limited_requests: int = 0
        self.error_count: int = 0

        # Current active phase for per-phase tracking
        self._current_phase: Optional[str] = None

        # Phase display names for reporting
        self.phase_display_names = {
            "project_categories": "Project Categories",
            "projects": "Projects",
            "project_properties": "Project Properties",
            "issues": "Issues",
            "components": "Components",
            "versions": "Versions",
            "comments": "Comments",
            "worklogs": "Worklogs",
            "issue_links": "Issue Links",
            "watchers": "Watchers",
            "attachments": "Attachments",
            "votes": "Votes",
            "issue_properties": "Issue Properties",
            "remote_links": "Remote Links",
            "boards": "Boards",
            "sprints": "Sprints",
            "filters": "Filters",
            "dashboards": "Dashboards",
        }

    def start_overall(self) -> None:
        """Mark the start of the overall generation process."""
        self.overall_start = time.time()

    def end_overall(self) -> None:
        """Mark the end of the overall generation process."""
        self.overall_end = time.time()

    def record_request(self) -> None:
        """Record a completed API request."""
        self.total_requests += 1

    def record_rate_limit(self) -> None:
        """Record a rate-limited request (429 response)."""
        self.rate_limited_requests += 1
        # Also track per-phase
        if self._current_phase and self._current_phase in self.phases:
            self.phases[self._current_phase].rate_limited += 1

    def record_error(self) -> None:
        """Record an error (non-429 failure)."""
        self.error_count += 1
        # Also track per-phase
        if self._current_phase and self._current_phase in self.phases:
            self.phases[self._current_phase].errors += 1

    @property
    def rate_limit_percentage(self) -> float:
        """Calculate percentage of requests that were rate limited."""
        if self.total_requests <= 0:
            return 0.0
        return (self.rate_limited_requests / self.total_requests) * 100

    @property
    def error_percentage(self) -> float:
        """Calculate percentage of requests that failed."""
        if self.total_requests <= 0:
            return 0.0
        return (self.error_count / self.total_requests) * 100

    def start_phase(self, phase_name: str, target_count: int = 0) -> None:
        """Start timing a phase.

        Args:
            phase_name: Name of the phase
            target_count: Target number of items to create
        """
        self._current_phase = phase_name
        self.phases[phase_name] = PhaseMetrics(name=phase_name, start_time=time.time(), items_target=target_count)

    def end_phase(self, phase_name: str, items_created: int) -> None:
        """End timing a phase.

        Args:
            phase_name: Name of the phase
            items_created: Actual number of items created
        """
        if phase_name in self.phases:
            self.phases[phase_name].end_time = time.time()
            self.phases[phase_name].items_created = items_created

            # Log phase completion with rate
            phase = self.phases[phase_name]
            display_name = self.phase_display_names.get(phase_name, phase_name)
            self.logger.info(
                f"  {display_name}: {items_created} items in {phase.format_duration()} ({phase.format_rate()})"
            )

        # Clear current phase
        if self._current_phase == phase_name:
            self._current_phase = None

    def get_phase(self, phase_name: str) -> Optional[PhaseMetrics]:
        """Get metrics for a specific phase."""
        return self.phases.get(phase_name)

    @property
    def total_duration_seconds(self) -> float:
        """Get total duration in seconds."""
        if self.overall_start is None:
            return 0.0
        end = self.overall_end or time.time()
        return end - self.overall_start

    @property
    def total_items_created(self) -> int:
        """Get total items created across all phases."""
        return sum(p.items_created for p in self.phases.values())

    def extrapolate_time(self, target_issues: int, current_issues: int) -> dict[str, any]:
        """Extrapolate time for a larger dataset based on current rates.

        Args:
            target_issues: Target number of issues
            current_issues: Number of issues in current run

        Returns:
            Dict with extrapolation results
        """
        if current_issues <= 0:
            return {"error": "No issues created to extrapolate from"}

        scale_factor = target_issues / current_issues

        # Calculate extrapolated times per phase
        phase_estimates = {}
        total_estimated_seconds = 0

        for phase_name, metrics in self.phases.items():
            if metrics.items_created > 0 and metrics.duration_seconds > 0:
                # Scale the time based on items ratio
                if phase_name == "issues":
                    # Issues scale linearly
                    estimated_items = target_issues
                else:
                    # Other items scale with the same multiplier ratio
                    estimated_items = int(metrics.items_created * scale_factor)

                estimated_seconds = metrics.seconds_per_item * estimated_items
                phase_estimates[phase_name] = {
                    "estimated_items": estimated_items,
                    "estimated_seconds": estimated_seconds,
                    "rate_per_second": metrics.items_per_second,
                }
                total_estimated_seconds += estimated_seconds

        return {
            "target_issues": target_issues,
            "current_issues": current_issues,
            "scale_factor": scale_factor,
            "total_estimated_seconds": total_estimated_seconds,
            "total_estimated_hours": total_estimated_seconds / 3600,
            "total_estimated_days": total_estimated_seconds / 86400,
            "phase_estimates": phase_estimates,
        }

    def format_extrapolation(self, target_issues: int, current_issues: int) -> str:
        """Format extrapolation as a human-readable report.

        Args:
            target_issues: Target number of issues
            current_issues: Number of issues in current run

        Returns:
            Formatted string report
        """
        data = self.extrapolate_time(target_issues, current_issues)

        if "error" in data:
            return f"Cannot extrapolate: {data['error']}"

        lines = [
            "",
            "=" * 60,
            f"TIME EXTRAPOLATION FOR {target_issues:,} ISSUES",
            "=" * 60,
            f"Based on current run: {current_issues:,} issues",
            f"Scale factor: {data['scale_factor']:.1f}x",
            "",
            "Estimated time per phase:",
        ]

        for phase_name, estimate in data["phase_estimates"].items():
            display_name = self.phase_display_names.get(phase_name, phase_name)
            est_seconds = estimate["estimated_seconds"]
            est_items = estimate["estimated_items"]
            rate = estimate["rate_per_second"]

            if est_seconds < 60:
                time_str = f"{est_seconds:.0f}s"
            elif est_seconds < 3600:
                time_str = f"{est_seconds / 60:.1f}m"
            elif est_seconds < 86400:
                time_str = f"{est_seconds / 3600:.1f}h"
            else:
                time_str = f"{est_seconds / 86400:.1f}d"

            lines.append(f"  {display_name}: {est_items:,} items @ {rate:.1f}/s = {time_str}")

        # Total time formatting
        total_seconds = data["total_estimated_seconds"]
        if total_seconds < 3600:
            total_str = f"{total_seconds / 60:.1f} minutes"
        elif total_seconds < 86400:
            total_str = f"{total_seconds / 3600:.1f} hours"
        else:
            days = total_seconds / 86400
            hours = (total_seconds % 86400) / 3600
            total_str = f"{days:.0f} days, {hours:.0f} hours"

        lines.extend(
            [
                "",
                "-" * 60,
                f"TOTAL ESTIMATED TIME: {total_str}",
                "-" * 60,
                "",
                "Note: Actual time may vary based on:",
                "  - Rate limiting (may add 20-50% overhead)",
                "  - Network latency",
                "  - Jira instance performance",
                "  - Concurrency settings",
            ]
        )

        return "\n".join(lines)

    def get_summary_report(self) -> str:
        """Generate a summary report of all phase timings.

        Returns:
            Formatted string report
        """
        lines = [
            "",
            "=" * 60,
            "BENCHMARK SUMMARY",
            "=" * 60,
        ]

        # Calculate total duration
        total_duration = self.total_duration_seconds
        if total_duration < 60:
            duration_str = f"{total_duration:.1f} seconds"
        elif total_duration < 3600:
            duration_str = f"{total_duration / 60:.1f} minutes"
        else:
            duration_str = f"{total_duration / 3600:.2f} hours"

        lines.append(f"Total duration: {duration_str}")
        lines.append(f"Total items created: {self.total_items_created:,}")
        lines.append("")
        lines.append("Phase breakdown:")
        lines.append("-" * 90)
        lines.append(f"{'Phase':<25} {'Items':>10} {'Duration':>10} {'Rate':>12} {'429s':>12} {'Errs':>8}")
        lines.append("-" * 90)

        for phase_name, metrics in self.phases.items():
            if metrics.items_created > 0:
                display_name = self.phase_display_names.get(phase_name, phase_name)
                # Calculate 429 percentage based on items (approximation: ~1 request per item)
                if metrics.rate_limited > 0 and metrics.items_created > 0:
                    rate_pct = (metrics.rate_limited / metrics.items_created) * 100
                    rate_limited_str = f"{metrics.rate_limited} ({rate_pct:.1f}%)"
                else:
                    rate_limited_str = "-"
                errors_str = str(metrics.errors) if metrics.errors > 0 else "-"
                lines.append(
                    f"{display_name:<25} {metrics.items_created:>10,} "
                    f"{metrics.format_duration():>10} {metrics.format_rate():>12} "
                    f"{rate_limited_str:>12} {errors_str:>8}"
                )

        lines.append("-" * 90)

        # Add key rates for reference
        issue_phase = self.phases.get("issues")
        comment_phase = self.phases.get("comments")

        lines.append("")
        lines.append("Key rates for extrapolation:")
        if issue_phase and issue_phase.items_per_second > 0:
            lines.append(
                f"  Issues: {issue_phase.items_per_second:.2f}/sec ({issue_phase.seconds_per_item:.2f}s per issue)"
            )
        if comment_phase and comment_phase.items_per_second > 0:
            lines.append(f"  Comments: {comment_phase.items_per_second:.2f}/sec")

        # Add request statistics
        lines.append("")
        lines.append("Request statistics:")
        if self.total_requests > 0:
            lines.append(f"  Total requests: {self.total_requests:,}")
            lines.append(f"  Rate limited (429): {self.rate_limited_requests:,} ({self.rate_limit_percentage:.1f}%)")
            lines.append(f"  Errors: {self.error_count:,} ({self.error_percentage:.1f}%)")
        else:
            lines.append("  (No requests recorded - dry-run mode)")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Export benchmark data as dictionary (for JSON serialization)."""
        return {
            "overall_start": datetime.fromtimestamp(self.overall_start).isoformat() if self.overall_start else None,
            "overall_end": datetime.fromtimestamp(self.overall_end).isoformat() if self.overall_end else None,
            "total_duration_seconds": self.total_duration_seconds,
            "total_items_created": self.total_items_created,
            "request_stats": {
                "total_requests": self.total_requests,
                "rate_limited": self.rate_limited_requests,
                "rate_limit_percentage": self.rate_limit_percentage,
                "errors": self.error_count,
                "error_percentage": self.error_percentage,
            },
            "phases": {
                name: {
                    "items_created": m.items_created,
                    "items_target": m.items_target,
                    "duration_seconds": m.duration_seconds,
                    "items_per_second": m.items_per_second,
                    "rate_limited": m.rate_limited,
                    "errors": m.errors,
                }
                for name, m in self.phases.items()
            },
        }
