"""
Integration Test: User Value Validation in Gates.

Activity: 2.12
Ref: docs/design/fde-core-brain-development.md Wave 2
"""

import pytest

from src.core.governance.user_value_validator import UserValueValidator


@pytest.fixture
def validator():
    return UserValueValidator()


class TestUserValueScoring:
    def test_full_user_story_scores_high(self, validator):
        result = validator.validate(
            spec_text="As a developer, I want automated testing so that I can ship with confidence",
            acceptance_criteria=["Developer can run tests locally", "CI pipeline validates on push"],
        )
        assert result.score >= 60
        assert result.status == "pass"
        assert result.user_role == "developer"
        assert result.action is not None
        assert result.value is not None

    def test_missing_user_role_scores_lower(self, validator):
        result = validator.validate(
            spec_text="I want to implement caching so that response times improve",
            acceptance_criteria=["Cache hit rate > 90%"],
        )
        assert result.user_role is None
        assert result.score < 75

    def test_purely_technical_spec_rejected(self, validator):
        result = validator.validate(
            spec_text="Refactor the database connection pool to use HikariCP instead of C3P0",
            acceptance_criteria=["Connection pool uses HikariCP", "No performance regression"],
        )
        assert result.score < 40
        assert result.status == "reject"

    def test_infrastructure_task_gets_base_score(self, validator):
        result = validator.validate(
            spec_text="Update Terraform infrastructure to add monitoring and alerting for the deployment pipeline",
            acceptance_criteria=["CloudWatch alarms configured", "Dashboard deployed"],
        )
        assert result.is_infrastructure_task is True
        assert result.score >= 50
        assert result.status in ("pass", "warning")

    def test_partial_user_story_warns(self, validator):
        result = validator.validate(
            spec_text="As a platform engineer, I want to add retry logic to the webhook handler",
            acceptance_criteria=["Retries configured with exponential backoff"],
        )
        assert result.user_role is not None
        assert result.action is not None
        assert result.score >= 40


class TestUserValueExtraction:
    def test_extracts_role_from_as_a_pattern(self, validator):
        result = validator.validate("As a data scientist, I want model versioning so that experiments are reproducible")
        assert result.user_role == "data scientist"

    def test_extracts_action_from_i_want_pattern(self, validator):
        result = validator.validate("As a user, I want to filter search results, so that I find relevant items faster")
        assert result.action is not None
        assert "filter" in result.action.lower()

    def test_extracts_value_from_so_that_pattern(self, validator):
        result = validator.validate("As a manager, I want weekly reports so that I can track team progress")
        assert result.value is not None
        assert "track" in result.value.lower()

    def test_user_value_statement_reconstruction(self, validator):
        result = validator.validate("As a developer, I want hot reload so that I iterate faster")
        statement = result.user_value_statement
        assert "developer" in statement


class TestEdgeCases:
    def test_empty_spec_rejected(self, validator):
        result = validator.validate("")
        assert result.score < 40
        assert result.status == "reject"

    def test_very_long_spec_handled(self, validator):
        long_text = "As a user, I want features " + "that work well " * 500 + "so that I am productive"
        result = validator.validate(long_text)
        assert result.score > 0
        assert result.user_role is not None
