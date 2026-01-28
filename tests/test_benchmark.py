"""
Unit tests for generators/benchmark.py - BenchmarkTracker and PhaseMetrics.
"""

import time

from generators.benchmark import BenchmarkTracker, PhaseMetrics


class TestPhaseMetrics:
    """Tests for PhaseMetrics dataclass."""

    def test_init_defaults(self):
        """Test PhaseMetrics initializes with defaults."""
        metrics = PhaseMetrics(name="test")
        assert metrics.name == "test"
        assert metrics.start_time is None
        assert metrics.end_time is None
        assert metrics.items_created == 0
        assert metrics.items_target == 0
        assert metrics.rate_limited == 0
        assert metrics.errors == 0

    def test_duration_seconds_no_start(self):
        """Test duration is 0 when not started."""
        metrics = PhaseMetrics(name="test")
        assert metrics.duration_seconds == 0.0

    def test_duration_seconds_in_progress(self):
        """Test duration while in progress."""
        metrics = PhaseMetrics(name="test", start_time=time.time() - 5.0)
        assert 4.9 <= metrics.duration_seconds <= 5.5

    def test_duration_seconds_complete(self):
        """Test duration when complete."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 10.0, end_time=now)
        assert 9.9 <= metrics.duration_seconds <= 10.1

    def test_items_per_second_zero_duration(self):
        """Test items_per_second with zero duration."""
        metrics = PhaseMetrics(name="test")
        assert metrics.items_per_second == 0.0

    def test_items_per_second_zero_items(self):
        """Test items_per_second with zero items."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 10.0, end_time=now, items_created=0)
        assert metrics.items_per_second == 0.0

    def test_items_per_second_calculation(self):
        """Test items_per_second calculation."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 10.0, end_time=now, items_created=100)
        assert 9.9 <= metrics.items_per_second <= 10.1

    def test_seconds_per_item_zero_items(self):
        """Test seconds_per_item with zero items."""
        metrics = PhaseMetrics(name="test")
        assert metrics.seconds_per_item == 0.0

    def test_seconds_per_item_calculation(self):
        """Test seconds_per_item calculation."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 10.0, end_time=now, items_created=100)
        assert 0.099 <= metrics.seconds_per_item <= 0.101

    def test_is_complete_false(self):
        """Test is_complete returns False when not ended."""
        metrics = PhaseMetrics(name="test", start_time=time.time())
        assert not metrics.is_complete

    def test_is_complete_true(self):
        """Test is_complete returns True when ended."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 1.0, end_time=now)
        assert metrics.is_complete

    def test_format_duration_seconds(self):
        """Test format_duration for seconds."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 30.0, end_time=now)
        assert "30" in metrics.format_duration()
        assert "s" in metrics.format_duration()

    def test_format_duration_minutes(self):
        """Test format_duration for minutes."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 120.0, end_time=now)
        assert "2" in metrics.format_duration()
        assert "m" in metrics.format_duration()

    def test_format_duration_hours(self):
        """Test format_duration for hours."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 7200.0, end_time=now)
        assert "2" in metrics.format_duration()
        assert "h" in metrics.format_duration()

    def test_format_rate_fast(self):
        """Test format_rate for fast rates."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 10.0, end_time=now, items_created=100)
        assert "/s" in metrics.format_rate()

    def test_format_rate_slow(self):
        """Test format_rate for slow rates."""
        now = time.time()
        metrics = PhaseMetrics(name="test", start_time=now - 100.0, end_time=now, items_created=10)
        result = metrics.format_rate()
        assert "s/item" in result or "/s" in result

    def test_format_rate_no_data(self):
        """Test format_rate with no data."""
        metrics = PhaseMetrics(name="test")
        assert metrics.format_rate() == "N/A"


class TestBenchmarkTracker:
    """Tests for BenchmarkTracker class."""

    def test_init(self):
        """Test BenchmarkTracker initializes correctly."""
        tracker = BenchmarkTracker()
        assert tracker.phases == {}
        assert tracker.overall_start is None
        assert tracker.overall_end is None
        assert tracker.total_requests == 0
        assert tracker.rate_limited_requests == 0
        assert tracker.error_count == 0
        assert tracker._current_phase is None

    def test_start_overall(self):
        """Test start_overall sets time."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        assert tracker.overall_start is not None
        assert tracker.overall_start <= time.time()

    def test_end_overall(self):
        """Test end_overall sets time."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        time.sleep(0.01)
        tracker.end_overall()
        assert tracker.overall_end is not None
        assert tracker.overall_end >= tracker.overall_start

    def test_record_request(self):
        """Test record_request increments counter."""
        tracker = BenchmarkTracker()
        assert tracker.total_requests == 0
        tracker.record_request()
        assert tracker.total_requests == 1
        tracker.record_request()
        assert tracker.total_requests == 2

    def test_record_rate_limit(self):
        """Test record_rate_limit increments counter."""
        tracker = BenchmarkTracker()
        assert tracker.rate_limited_requests == 0
        tracker.record_rate_limit()
        assert tracker.rate_limited_requests == 1

    def test_record_rate_limit_per_phase(self):
        """Test record_rate_limit tracks per-phase."""
        tracker = BenchmarkTracker()
        tracker.start_phase("test_phase", 10)
        tracker.record_rate_limit()
        assert tracker.rate_limited_requests == 1
        assert tracker.phases["test_phase"].rate_limited == 1

    def test_record_error(self):
        """Test record_error increments counter."""
        tracker = BenchmarkTracker()
        assert tracker.error_count == 0
        tracker.record_error()
        assert tracker.error_count == 1

    def test_record_error_per_phase(self):
        """Test record_error tracks per-phase."""
        tracker = BenchmarkTracker()
        tracker.start_phase("test_phase", 10)
        tracker.record_error()
        assert tracker.error_count == 1
        assert tracker.phases["test_phase"].errors == 1

    def test_rate_limit_percentage_no_requests(self):
        """Test rate_limit_percentage with no requests."""
        tracker = BenchmarkTracker()
        assert tracker.rate_limit_percentage == 0.0

    def test_rate_limit_percentage_calculation(self):
        """Test rate_limit_percentage calculation."""
        tracker = BenchmarkTracker()
        for _ in range(100):
            tracker.record_request()
        for _ in range(10):
            tracker.record_rate_limit()
        assert tracker.rate_limit_percentage == 10.0

    def test_error_percentage_no_requests(self):
        """Test error_percentage with no requests."""
        tracker = BenchmarkTracker()
        assert tracker.error_percentage == 0.0

    def test_error_percentage_calculation(self):
        """Test error_percentage calculation."""
        tracker = BenchmarkTracker()
        for _ in range(100):
            tracker.record_request()
        for _ in range(5):
            tracker.record_error()
        assert tracker.error_percentage == 5.0

    def test_start_phase(self):
        """Test start_phase creates phase."""
        tracker = BenchmarkTracker()
        tracker.start_phase("issues", 100)
        assert "issues" in tracker.phases
        assert tracker.phases["issues"].name == "issues"
        assert tracker.phases["issues"].items_target == 100
        assert tracker.phases["issues"].start_time is not None
        assert tracker._current_phase == "issues"

    def test_end_phase(self):
        """Test end_phase completes phase."""
        tracker = BenchmarkTracker()
        tracker.start_phase("issues", 100)
        time.sleep(0.01)
        tracker.end_phase("issues", 100)
        assert tracker.phases["issues"].end_time is not None
        assert tracker.phases["issues"].items_created == 100
        assert tracker._current_phase is None

    def test_end_phase_nonexistent(self):
        """Test end_phase with nonexistent phase doesn't crash."""
        tracker = BenchmarkTracker()
        tracker.end_phase("nonexistent", 10)  # Should not raise

    def test_get_phase(self):
        """Test get_phase returns correct phase."""
        tracker = BenchmarkTracker()
        tracker.start_phase("test", 10)
        phase = tracker.get_phase("test")
        assert phase is not None
        assert phase.name == "test"

    def test_get_phase_nonexistent(self):
        """Test get_phase returns None for nonexistent phase."""
        tracker = BenchmarkTracker()
        assert tracker.get_phase("nonexistent") is None

    def test_total_duration_seconds_not_started(self):
        """Test total_duration_seconds when not started."""
        tracker = BenchmarkTracker()
        assert tracker.total_duration_seconds == 0.0

    def test_total_duration_seconds_in_progress(self):
        """Test total_duration_seconds while in progress."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        time.sleep(0.05)
        assert tracker.total_duration_seconds >= 0.04

    def test_total_duration_seconds_complete(self):
        """Test total_duration_seconds when complete."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        time.sleep(0.05)
        tracker.end_overall()
        assert 0.04 <= tracker.total_duration_seconds <= 0.2

    def test_total_items_created(self):
        """Test total_items_created sums all phases."""
        tracker = BenchmarkTracker()
        tracker.start_phase("phase1", 100)
        tracker.end_phase("phase1", 50)
        tracker.start_phase("phase2", 200)
        tracker.end_phase("phase2", 75)
        assert tracker.total_items_created == 125

    def test_extrapolate_time_no_issues(self):
        """Test extrapolate_time with no issues."""
        tracker = BenchmarkTracker()
        result = tracker.extrapolate_time(18000000, 0)
        assert "error" in result

    def test_extrapolate_time_calculation(self):
        """Test extrapolate_time calculation."""
        tracker = BenchmarkTracker()
        tracker.start_overall()

        # Simulate 100 issues
        tracker.start_phase("issues", 100)
        time.sleep(0.02)
        tracker.end_phase("issues", 100)

        # Simulate 480 comments
        tracker.start_phase("comments", 480)
        time.sleep(0.01)
        tracker.end_phase("comments", 480)

        tracker.end_overall()

        result = tracker.extrapolate_time(1000, 100)
        assert "target_issues" in result
        assert result["target_issues"] == 1000
        assert result["current_issues"] == 100
        assert result["scale_factor"] == 10.0
        assert "total_estimated_seconds" in result
        assert "phase_estimates" in result

    def test_format_extrapolation_no_issues(self):
        """Test format_extrapolation with no issues."""
        tracker = BenchmarkTracker()
        result = tracker.format_extrapolation(18000000, 0)
        assert "Cannot extrapolate" in result

    def test_format_extrapolation(self):
        """Test format_extrapolation output."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        tracker.start_phase("issues", 100)
        time.sleep(0.01)
        tracker.end_phase("issues", 100)
        tracker.end_overall()

        result = tracker.format_extrapolation(1000, 100)
        assert "TIME EXTRAPOLATION" in result
        assert "1,000" in result
        assert "Scale factor" in result

    def test_get_summary_report(self):
        """Test get_summary_report output."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        tracker.start_phase("issues", 100)
        tracker.record_request()
        tracker.end_phase("issues", 100)
        tracker.end_overall()

        report = tracker.get_summary_report()
        assert "BENCHMARK SUMMARY" in report
        assert "Total duration" in report
        assert "Phase breakdown" in report
        assert "Request statistics" in report

    def test_get_summary_report_dry_run(self):
        """Test get_summary_report in dry run mode (no requests)."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        tracker.end_overall()

        report = tracker.get_summary_report()
        assert "No requests recorded" in report

    def test_get_summary_report_with_rate_limits(self):
        """Test get_summary_report shows rate limit info."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        tracker.start_phase("issues", 100)
        for _ in range(10):
            tracker.record_request()
        tracker.record_rate_limit()
        tracker.record_error()
        tracker.end_phase("issues", 100)
        tracker.end_overall()

        report = tracker.get_summary_report()
        assert "Rate limited" in report or "429" in report

    def test_to_dict(self):
        """Test to_dict serialization."""
        tracker = BenchmarkTracker()
        tracker.start_overall()
        tracker.start_phase("issues", 100)
        tracker.record_request()
        tracker.record_rate_limit()
        tracker.record_error()
        tracker.end_phase("issues", 100)
        tracker.end_overall()

        result = tracker.to_dict()
        assert "overall_start" in result
        assert "overall_end" in result
        assert "total_duration_seconds" in result
        assert "total_items_created" in result
        assert "request_stats" in result
        assert "phases" in result

        # Check request stats
        assert result["request_stats"]["total_requests"] == 1
        assert result["request_stats"]["rate_limited"] == 1
        assert result["request_stats"]["errors"] == 1

        # Check phase data
        assert "issues" in result["phases"]
        assert result["phases"]["issues"]["items_created"] == 100

    def test_to_dict_not_started(self):
        """Test to_dict when not started."""
        tracker = BenchmarkTracker()
        result = tracker.to_dict()
        assert result["overall_start"] is None
        assert result["overall_end"] is None

    def test_phase_display_names(self):
        """Test phase_display_names mapping."""
        tracker = BenchmarkTracker()
        assert "issues" in tracker.phase_display_names
        assert tracker.phase_display_names["issues"] == "Issues"
        assert tracker.phase_display_names["comments"] == "Comments"
        assert tracker.phase_display_names["watchers"] == "Watchers"
