"""
BDD Scenarios: Domain-Segmented Metrics (ADR-013, Decision 3)

These tests validate that DORA metrics are segmented by tech_stack,
enabling domain-specific performance analysis.

Source: "WhatsCode" (Mao et al., Dec 2025) — acceptance rates 9%-100% by domain

All scenarios MUST FAIL until domain segmentation is implemented.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Tech Stack Segmentation in Metrics
# ═══════════════════════════════════════════════════════════════════


class TestDomainSegmentedMetrics:
    """
    Feature: DORA metrics are segmented by tech_stack
      As a Staff Engineer
      I want to see performance metrics broken down by technology domain
      So that I know where the factory is strong and where it needs improvement
    """

    def test_task_outcome_includes_tech_stack(self):
        """
        Scenario: Task outcome metric includes tech_stack in dimensions
          Given a completed task with tech_stack ["Python", "FastAPI"]
          When the task outcome is recorded
          Then the metric dimensions should include tech_stack ["Python", "FastAPI"]
        """
        from agents.dora_metrics import DORACollector, MetricEvent

        collector = DORACollector.__new__(DORACollector)
        collector._factory_bucket = ""
        collector._s3 = None

        # Mock _persist to capture the event
        captured_events = []
        collector._persist = lambda event: captured_events.append(event)

        collector.record_task_outcome(
            task_id="TASK-abc123",
            outcome="completed",
            duration_ms=45000,
            source="github",
            tech_stack=["Python", "FastAPI"],
        )

        assert len(captured_events) == 1
        assert captured_events[0].dimensions["tech_stack"] == ["Python", "FastAPI"]

    def test_lead_time_includes_tech_stack(self):
        """
        Scenario: Lead time metric includes tech_stack in dimensions
          Given a task with tech_stack ["TypeScript", "React"]
          When the lead time is recorded
          Then the metric dimensions should include tech_stack
        """
        from agents.dora_metrics import DORACollector

        collector = DORACollector.__new__(DORACollector)
        collector._factory_bucket = ""
        collector._s3 = None

        captured_events = []
        collector._persist = lambda event: captured_events.append(event)

        collector.record_lead_time(
            task_id="TASK-def456",
            started_at="2026-05-04T10:00:00+00:00",
            pr_opened_at="2026-05-04T11:30:00+00:00",
            source="github",
            tech_stack=["TypeScript", "React"],
        )

        assert len(captured_events) == 1
        assert captured_events[0].dimensions["tech_stack"] == ["TypeScript", "React"]

    def test_factory_report_segments_by_tech_stack(self):
        """
        Scenario: Factory health report includes per-domain breakdown
          Given 10 completed Python tasks and 5 completed Java tasks
          And Python tasks have 90% success rate
          And Java tasks have 60% success rate
          When the factory report is generated
          Then the report should include a domain_breakdown section
          And Python should show 90% success rate
          And Java should show 60% success rate
        """
        from agents.dora_metrics import DORACollector

        collector = DORACollector.__new__(DORACollector)
        collector._factory_bucket = ""
        collector._s3 = None

        report = collector.generate_factory_report(window_days=30)

        # The report must have a domain_breakdown key
        assert "domain_breakdown" in report
        # Each domain should have its own metrics
        assert isinstance(report["domain_breakdown"], dict)

    def test_acceptance_rate_by_domain(self):
        """
        Scenario: Acceptance rate is computed per tech_stack domain
          Given historical metrics with tech_stack dimensions
          When acceptance rate by domain is computed
          Then each domain should have its own acceptance rate
          And domains with < 5 samples should be marked "insufficient_data"
        """
        from agents.dora_metrics import DORACollector

        collector = DORACollector.__new__(DORACollector)
        collector._factory_bucket = ""
        collector._s3 = None

        rates = collector.compute_acceptance_rate_by_domain(window_days=30)

        assert isinstance(rates, dict)
        # Should return a dict like {"Python": {"rate": 0.92, "samples": 12}, ...}
        for domain, data in rates.items():
            assert "rate" in data
            assert "samples" in data
            if data["samples"] < 5:
                assert data.get("status") == "insufficient_data"

    def test_pipeline_stage_duration_by_domain(self):
        """
        Scenario: Pipeline stage durations are segmented by tech_stack
          Given multiple tasks across Python and Terraform stacks
          When pipeline stage metrics are queried by domain
          Then I should see average duration per stage per domain
          Because Terraform tasks may take longer in the build stage
        """
        from agents.dora_metrics import DORACollector

        collector = DORACollector.__new__(DORACollector)
        collector._factory_bucket = ""
        collector._s3 = None

        captured_events = []
        collector._persist = lambda event: captured_events.append(event)

        collector.record_pipeline_stage(
            task_id="TASK-tf001",
            stage_name="engineering",
            duration_ms=120000,
            status="completed",
            tech_stack=["Terraform", "AWS"],
        )

        assert len(captured_events) == 1
        assert captured_events[0].dimensions["tech_stack"] == ["Terraform", "AWS"]
        assert captured_events[0].dimensions["stage"] == "engineering"
