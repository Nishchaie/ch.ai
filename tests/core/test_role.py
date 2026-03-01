"""Tests for RoleRegistry and RoleDefinition."""

import pytest

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
