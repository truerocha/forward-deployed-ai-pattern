"""
Integration Test: Fidelity Scoring Pipeline.

Activity: 2.11
Ref: docs/design/fde-core-brain-development.md Wave 2
"""

import os

import pytest

from src.core.brain_sim.emulation_classifier import EmulationClassifier, ExecutionClass
from src.core.brain_sim.fidelity_score import FidelityScorer

pytestmark = pytest.mark.skipif(
    not os.environ.get("FDE_INTEGRATION_TESTS_ENABLED"),
    reason="Set FDE_INTEGRATION_TESTS_ENABLED=1 to run integration tests",
)


@pytest.fixture
def scorer():
    return FidelityScorer(project_id="test-fidelity", metrics_table=os.environ.get("METRICS_TABLE", "fde-dev-metrics"))


@pytest.fixture
def classifier():
    return EmulationClassifier(project_id="test-fidelity", metrics_table=os.environ.get("METRICS_TABLE", "fde-dev-metrics"))


class TestFidelityScoringDimensions:
    def test_high_fidelity_execution(self, scorer):
        result = scorer.score(
            task_id="test-high-fidelity",
            spec={"acceptance_criteria": ["implement auth flow", "add unit tests", "update documentation"]},
            execution_output={
                "code_changes": ["auth_handler.py", "test_auth.py"],
                "test_results": [{"name": "test_auth_flow", "status": "passed"}, {"name": "test_auth_error", "status": "passed"}],
                "reasoning": "Implemented OAuth2 PKCE flow because ADR-019 mandates this pattern.",
                "references": ["ADR-019", "governance rule: stateless services"],
            },
            gate_results=[{"gate": "dor", "status": "passed"}, {"gate": "adversarial", "status": "passed"}, {"gate": "dod", "status": "passed"}],
            context_available={"adrs": ["ADR-019", "ADR-014"], "memory": ["auth_pattern_v1"]},
            context_used={"adrs": ["ADR-019"], "memory": ["auth_pattern_v1"]},
            user_value_statement="As a developer, I want secure authentication so that user data is protected",
        )
        assert result.composite_score >= 0.5
        assert len(result.dimensions) == 5
        assert all(0.0 <= d.score <= 1.0 for d in result.dimensions.values())

    def test_low_fidelity_execution(self, scorer):
        result = scorer.score(
            task_id="test-low-fidelity",
            spec={"acceptance_criteria": ["implement caching", "add performance tests"]},
            execution_output={"code_changes": ["cache.py"], "test_results": []},
            gate_results=[{"gate": "adversarial", "status": "rejected"}, {"gate": "adversarial", "status": "rejected"}],
            context_available={"adrs": ["ADR-005", "ADR-009"], "memory": ["cache_strategy"]},
            context_used={},
            user_value_statement="",
        )
        assert result.composite_score < 0.7
        assert result.classification in ("simulation", "degraded")


class TestEmulationClassification:
    def test_degraded_classification(self, scorer, classifier):
        fidelity = scorer.score(
            task_id="test-degraded", spec={"acceptance_criteria": []},
            execution_output={}, gate_results=[{"gate": "adversarial", "status": "overridden"}],
            context_available={"adrs": ["ADR-001", "ADR-002", "ADR-003"]},
            context_used={}, user_value_statement="",
        )
        classification = classifier.classify(fidelity)
        assert classification.classification == ExecutionClass.DEGRADED
