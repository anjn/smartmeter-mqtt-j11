"""Tests for main module — FailureTracker only."""

from j11_meter.main import FailureTracker


class TestFailureTracker:
    def test_initial_status_connected(self):
        tracker = FailureTracker()
        assert tracker.status == "connected"

    def test_one_failure_degraded(self):
        tracker = FailureTracker()
        tracker.record_failure()
        assert tracker.status == "degraded"

    def test_two_failures_still_degraded(self):
        tracker = FailureTracker()
        tracker.record_failure()
        tracker.record_failure()
        assert tracker.status == "degraded"

    def test_three_failures_disconnected(self):
        tracker = FailureTracker(disconnect_threshold=3)
        tracker.record_failure()
        tracker.record_failure()
        tracker.record_failure()
        assert tracker.status == "disconnected"

    def test_success_resets_to_connected(self):
        tracker = FailureTracker()
        tracker.record_failure()
        tracker.record_failure()
        assert tracker.status == "degraded"
        tracker.record_success()
        assert tracker.status == "connected"

    def test_failure_count_resets_on_success(self):
        tracker = FailureTracker()
        tracker.record_failure()
        tracker.record_failure()
        tracker.record_success()
        tracker.record_failure()
        assert tracker.status == "degraded"  # Not disconnected

    def test_custom_threshold(self):
        tracker = FailureTracker(disconnect_threshold=5)
        for _ in range(4):
            tracker.record_failure()
        assert tracker.status == "degraded"
        tracker.record_failure()
        assert tracker.status == "disconnected"

    def test_failure_count_property(self):
        tracker = FailureTracker()
        assert tracker.failure_count == 0
        tracker.record_failure()
        assert tracker.failure_count == 1
        tracker.record_failure()
        assert tracker.failure_count == 2
        tracker.record_success()
        assert tracker.failure_count == 0
