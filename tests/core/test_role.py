"""Tests for RoleRegistry and RoleDefinition."""

import pytest

from chai.config import StackConfig
from chai.core.role import RoleDefinition, RoleRegistry
from chai.types import AutonomyLevel, RoleType


class TestRoleRegistry:
    """Test RoleRegistry operations."""

    def test_register_and_get(self) -> None:
        reg = RoleRegistry()
        rd = RoleDefinition(
            role_type=RoleType.CUSTOM,
            name="Custom",
            description="A custom role",
            system_prompt_template="Do {task}",
            default_autonomy=AutonomyLevel.MEDIUM,
        )
        reg.register_role(rd)
        assert reg.get_role(RoleType.CUSTOM) is rd

    def test_get_default_roles(self) -> None:
        reg = RoleRegistry()
        for rt in (RoleType.LEAD, RoleType.FRONTEND, RoleType.BACKEND, RoleType.QA):
            r = reg.get_role(rt)
            assert r is not None
            assert r.role_type == rt

    def test_list_roles(self) -> None:
        reg = RoleRegistry()
        roles = reg.list_roles()
        assert len(roles) >= 7
        types = {r.role_type for r in roles}
        assert RoleType.LEAD in types
        assert RoleType.BACKEND in types

    def test_has_role(self) -> None:
        reg = RoleRegistry()
        assert reg.has_role(RoleType.LEAD)
        assert reg.has_role(RoleType.BACKEND)
        assert not reg.has_role(RoleType.CUSTOM)

    def test_default_roles_exist(self) -> None:
        reg = RoleRegistry()
        default_roles = [
            RoleType.LEAD,
            RoleType.FRONTEND,
            RoleType.BACKEND,
            RoleType.PROMPT,
            RoleType.RESEARCHER,
            RoleType.QA,
            RoleType.DEPLOYMENT,
        ]
        for rt in default_roles:
            assert reg.has_role(rt), f"Missing role {rt}"
            r = reg.get_role(rt)
            assert r.name
            assert r.system_prompt_template
            if rt != RoleType.LEAD:
                assert "{task}" in r.system_prompt_template
            else:
                assert "json" in r.system_prompt_template.lower() or "decompose" in r.system_prompt_template.lower()

    def test_register_overwrites(self) -> None:
        reg = RoleRegistry()
        rd = RoleDefinition(
            role_type=RoleType.BACKEND,
            name="Custom Backend",
            description="Overwritten",
            system_prompt_template="{task}",
        )
        reg.register_role(rd)
        assert reg.get_role(RoleType.BACKEND).name == "Custom Backend"

    def test_custom_stack_in_prompts(self) -> None:
        stack = StackConfig(
            frontend="Vue 3, TypeScript",
            backend="Go, Gin",
            qa="Go testing",
            deployment="Kubernetes",
        )
        reg = RoleRegistry(stack)

        fe = reg.get_role(RoleType.FRONTEND)
        assert "Vue 3" in fe.system_prompt_template
        assert "React" not in fe.system_prompt_template

        be = reg.get_role(RoleType.BACKEND)
        assert "Go, Gin" in be.system_prompt_template
        assert "FastAPI" not in be.system_prompt_template

        qa = reg.get_role(RoleType.QA)
        assert "Go testing" in qa.system_prompt_template
        assert "pytest" not in qa.system_prompt_template

        dep = reg.get_role(RoleType.DEPLOYMENT)
        assert "Kubernetes" in dep.system_prompt_template
        assert "Docker" not in dep.system_prompt_template

    def test_default_stack_matches_original_prompts(self) -> None:
        """No-arg RoleRegistry() still produces the same prompts as the old hardcoded strings."""
        reg = RoleRegistry()
        assert "React, TypeScript" in reg.get_role(RoleType.FRONTEND).system_prompt_template
        assert "Python, FastAPI" in reg.get_role(RoleType.BACKEND).system_prompt_template
        assert "pytest" in reg.get_role(RoleType.QA).system_prompt_template
        assert "Docker" in reg.get_role(RoleType.DEPLOYMENT).system_prompt_template

    def test_task_placeholder_preserved_with_custom_stack(self) -> None:
        stack = StackConfig(frontend="Svelte", backend="Rust, Axum")
        reg = RoleRegistry(stack)
        for rt in (RoleType.FRONTEND, RoleType.BACKEND, RoleType.QA, RoleType.DEPLOYMENT):
            assert "{task}" in reg.get_role(rt).system_prompt_template
