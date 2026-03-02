"""Tests for ComplexityRouter heuristic classification."""

import pytest

from chai.core.router import ComplexityRouter, ExecutionStrategy


@pytest.fixture
def router() -> ComplexityRouter:
    return ComplexityRouter()


class TestComplexityRouter:

    def test_simple_typo_fix(self, router: ComplexityRouter) -> None:
        result = router.classify("fix the typo in README.md")
        assert result.strategy == ExecutionStrategy.DIRECT

    def test_simple_question(self, router: ComplexityRouter) -> None:
        result = router.classify("what does this function do?")
        assert result.strategy == ExecutionStrategy.DIRECT

    def test_simple_rename(self, router: ComplexityRouter) -> None:
        result = router.classify("rename the variable foo to bar")
        assert result.strategy == ExecutionStrategy.DIRECT

    def test_simple_add_comment(self, router: ComplexityRouter) -> None:
        result = router.classify("add a comment to the auth function")
        assert result.strategy == ExecutionStrategy.DIRECT

    def test_moderate_feature(self, router: ComplexityRouter) -> None:
        result = router.classify("add a search endpoint to the API that filters users by name")
        assert result.strategy in (ExecutionStrategy.SMALL_TEAM, ExecutionStrategy.DIRECT)

    def test_complex_cross_cutting(self, router: ComplexityRouter) -> None:
        result = router.classify(
            "implement a full end-to-end authentication system with frontend login page, "
            "backend API endpoints, database models, and e2e tests"
        )
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE

    def test_complex_multi_domain(self, router: ComplexityRouter) -> None:
        result = router.classify(
            "build a feature that adds a React component on the frontend "
            "and a new FastAPI endpoint on the backend with database integration "
            "plus comprehensive unit and integration tests"
        )
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE

    def test_moderate_refactor(self, router: ComplexityRouter) -> None:
        result = router.classify("refactor the provider module to use a factory pattern")
        assert result.strategy in (ExecutionStrategy.SMALL_TEAM, ExecutionStrategy.FULL_PIPELINE)

    def test_result_has_reason(self, router: ComplexityRouter) -> None:
        result = router.classify("fix a bug")
        assert result.reason
        assert isinstance(result.reason, str)

    def test_complex_suggests_roles(self, router: ComplexityRouter) -> None:
        result = router.classify(
            "implement a complete system with frontend React components "
            "and backend Python API endpoints and full e2e test coverage"
        )
        if result.strategy == ExecutionStrategy.FULL_PIPELINE:
            assert result.suggested_roles is not None

    def test_short_prompt_biases_direct(self, router: ComplexityRouter) -> None:
        result = router.classify("check the logs")
        assert result.strategy == ExecutionStrategy.DIRECT
