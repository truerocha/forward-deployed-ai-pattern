"""
Data Journey Integration Test — Validates the full contract flow per platform.

This test simulates real ALM events from GitHub, GitLab, and Asana,
and verifies that the data contract flows correctly through:
  Router → Constraint Extractor → DoR Gate → Agent Builder

Each platform fixture represents a real-world task with:
- Acceptance criteria
- Tech stack
- Constraints
- Related docs

The test validates:
1. The Router extracts the correct data contract fields from each platform
2. The Constraint Extractor finds constraints in the text
3. The DoR Gate passes (constraints do not conflict with tech_stack)
4. The Agent Builder provisions the correct agent type

Run: PYTHONPATH=../../infra/docker python3 -m pytest test_data_journey.py -v
"""

import sys
import os

# Add the agent modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'infra', 'docker'))

import pytest
from agents.router import AgentRouter
from agents.constraint_extractor import ConstraintExtractor, extract_rules_based
from agents.autonomy import compute_autonomy_level
from agents.scope_boundaries import check_scope


# ═══════════════════════════════════════════════════════════════════
# FIXTURES: Real platform event payloads
# ═══════════════════════════════════════════════════════════════════

GITHUB_EVENT = {
    "source": "fde.github.webhook",
    "detail-type": "issue.labeled",
    "detail": {
        "action": "labeled",
        "issue": {
            "number": 42,
            "title": "[FACTORY] Add pagination to /users endpoint",
            "body": (
                "### Task Type\n\nfeature\n\n"
                "### Priority\n\nP2 (medium)\n\n"
                "### Engineering Level\n\nL3 (cross-module)\n\n"
                "### Description\n\nAdd offset-based pagination to the users list API.\n\n"
                "### Acceptance Criteria\n\n"
                "- [x] GET /users accepts page and page_size params\n"
                "- [x] Response includes total_count and next_page\n"
                "- [x] Default page_size is 20\n\n"
                "### Tech Stack\n\n"
                "- [X] Python\n"
                "- [X] FastAPI / Flask / Django\n"
                "- [ ] TypeScript / JavaScript\n\n"
                "### Target Environment\n\n"
                "- [X] AWS\n\n"
                "### Constraints\n\nMust not change the existing /users response format. "
                "Python 3.11 required. Latency p99 < 200ms.\n\n"
                "### Related Documents\n\n"
                "- docs/design/pagination-strategy.md\n\n"
                "### Dependencies\n\n"
            ),
            "labels": [{"name": "factory-ready"}],
            "repository_url": "https://api.github.com/repos/acme/web-app",
        },
    },
}

GITLAB_EVENT = {
    "source": "fde.gitlab.webhook",
    "detail-type": "issue.updated",
    "detail": {
        "object_attributes": {
            "iid": 15,
            "title": "Implement rate limiting middleware",
            "description": (
                "### Description\n\nAdd rate limiting to all API endpoints.\n\n"
                "### Acceptance Criteria\n\n"
                "- [x] Rate limit of 100 requests per minute per IP\n"
                "- [x] Returns 429 with Retry-After header\n"
                "- [x] Configurable per endpoint\n\n"
                "### Constraints\n\nMust use Redis for state. Requires JWT authentication.\n\n"
                "### Related Documents\n\n"
                "- docs/design/rate-limiting.md\n"
            ),
        },
        "labels": [
            {"title": "type::feature"},
            {"title": "priority::P1"},
            {"title": "level::L3"},
            {"title": "stack::Python"},
            {"title": "stack::Redis"},
        ],
        "project": {"id": 789},
    },
}

ASANA_EVENT = {
    "source": "fde.asana.webhook",
    "detail-type": "task.moved",
    "detail": {
        "resource": {
            "gid": "1234567890",
            "name": "Fix authentication token refresh",
            "notes": (
                "### Description\n\nThe OAuth2 refresh token flow is not working "
                "when the access token expires during a long-running operation.\n\n"
                "### Acceptance Criteria\n\n"
                "- [x] Token refresh happens transparently\n"
                "- [x] No user-facing errors during refresh\n\n"
                "### Constraints\n\nMust use OAuth2. Must not change the public API.\n\n"
            ),
            "custom_fields": [
                {"name": "Type", "display_value": "bugfix"},
                {"name": "Priority", "display_value": "P1"},
                {"name": "Engineering Level", "display_value": "L2"},
                {"name": "Tech Stack", "display_value": "Python, FastAPI"},
            ],
        },
    },
}


# ═══════════════════════════════════════════════════════════════════
# TEST: Full data journey per platform
# ═══════════════════════════════════════════════════════════════════


class TestGitHubDataJourney:
    """Validates the complete data flow for a GitHub issue event."""

    def setup_method(self):
        self.router = AgentRouter()
        self.decision = self.router.route_event(GITHUB_EVENT)

    def test_router_extracts_data_contract(self):
        """Router produces a data contract with all required fields."""
        contract = self.decision.data_contract
        assert contract["source"] == "github"
        assert contract["type"] == "feature"
        assert contract["priority"] == "P2"
        assert contract["level"] == "L3"
        assert "Python" in contract["tech_stack"]
        assert len(contract["acceptance_criteria"]) == 3
        assert "python 3.11" in contract["constraints"].lower()

    def test_constraint_extraction_finds_rules(self):
        """Constraint Extractor finds version pin and latency threshold."""
        contract = self.decision.data_contract
        extractor = ConstraintExtractor()
        result = extractor.extract(contract)

        subjects = [c.subject for c in result.constraints]
        assert "python_version" in subjects, f"Expected python_version in {subjects}"
        assert "latency_ms" in subjects, f"Expected latency_ms in {subjects}"

    def test_scope_boundaries_accept(self):
        """Scope Boundaries accept this well-formed task."""
        contract = self.decision.data_contract
        scope_result = check_scope(contract)
        assert scope_result.in_scope is True
        assert scope_result.confidence_level == "high"

    def test_autonomy_level_computed(self):
        """Autonomy level is L4 (Approver) for a feature L3 task."""
        contract = self.decision.data_contract
        autonomy = compute_autonomy_level(contract)
        assert autonomy.level == "L4"
        assert autonomy.name == "Approver"

    def test_routing_decision_targets_reconnaissance(self):
        """Router targets the reconnaissance agent for new tasks."""
        assert self.decision.agent_name == "reconnaissance"
        assert self.decision.should_process is True


class TestGitLabDataJourney:
    """Validates the complete data flow for a GitLab issue event."""

    def setup_method(self):
        self.router = AgentRouter()
        self.decision = self.router.route_event(GITLAB_EVENT)

    def test_router_extracts_scoped_labels(self):
        """Router extracts type, priority, level, and stack from scoped labels."""
        contract = self.decision.data_contract
        assert contract["source"] == "gitlab"
        assert contract["type"] == "feature"
        assert contract["priority"] == "P1"
        assert contract["level"] == "L3"
        assert "Python" in contract["tech_stack"]
        assert "Redis" in contract["tech_stack"]

    def test_constraint_extraction_finds_auth_mandate(self):
        """Constraint Extractor finds JWT auth requirement."""
        contract = self.decision.data_contract
        extractor = ConstraintExtractor()
        result = extractor.extract(contract)

        subjects = [c.subject for c in result.constraints]
        assert "auth_method" in subjects, f"Expected auth_method in {subjects}"

    def test_scope_boundaries_accept(self):
        """Scope Boundaries accept this task with acceptance criteria."""
        contract = self.decision.data_contract
        scope_result = check_scope(contract)
        assert scope_result.in_scope is True

    def test_routing_targets_reconnaissance(self):
        """Router targets reconnaissance for GitLab events."""
        assert self.decision.agent_name == "reconnaissance"
        assert self.decision.should_process is True


class TestAsanaDataJourney:
    """Validates the complete data flow for an Asana task event."""

    def setup_method(self):
        self.router = AgentRouter()
        self.decision = self.router.route_event(ASANA_EVENT)

    def test_router_extracts_custom_fields(self):
        """Router extracts type, priority, and tech_stack from Asana custom fields."""
        contract = self.decision.data_contract
        assert contract["source"] == "asana"
        assert contract["type"] == "bugfix"
        assert contract["priority"] == "P1"
        assert "Python" in contract["tech_stack"]

    def test_constraint_extraction_finds_oauth2(self):
        """Constraint Extractor finds OAuth2 mandate from constraints text."""
        contract = self.decision.data_contract
        extractor = ConstraintExtractor()
        result = extractor.extract(contract)

        subjects = [c.subject for c in result.constraints]
        assert "auth_method" in subjects, f"Expected auth_method in {subjects}"

    def test_autonomy_level_is_observer_for_bugfix(self):
        """Bugfix L2 gets L5 (Observer) autonomy — maximum autonomy."""
        contract = self.decision.data_contract
        autonomy = compute_autonomy_level(contract)
        assert autonomy.level == "L5"
        assert autonomy.name == "Observer"
        assert autonomy.fast_path is True

    def test_routing_targets_reconnaissance(self):
        """Router targets reconnaissance for Asana events."""
        assert self.decision.agent_name == "reconnaissance"
        assert self.decision.should_process is True
