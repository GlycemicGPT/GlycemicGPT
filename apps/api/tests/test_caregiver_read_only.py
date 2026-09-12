"""Story 8.6: Tests for caregiver read-only enforcement.

Verifies that caregiver users receive 403 Forbidden on all diabetic-only
endpoints (alerts, settings, emergency contacts, escalation, insights).
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.core.auth import RoleChecker
from src.models.user import User, UserRole

# ── Helpers ──


def _make_user(role: UserRole = UserRole.CAREGIVER) -> MagicMock:
    """Create a mock user with the given role."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = f"{role.value}@example.com"
    user.role = role
    return user


def _make_request(path: str = "/api/test", method: str = "GET") -> MagicMock:
    """Create a mock Request object."""
    request = MagicMock()
    request.url.path = path
    request.method = method
    request.client.host = "127.0.0.1"
    return request


# ── TestRoleCheckerDirect ──


class TestRoleCheckerDirect:
    """Direct tests on the RoleChecker dependency to verify 403 for caregivers."""

    @pytest.mark.asyncio
    async def test_caregiver_blocked_by_require_diabetic_or_admin(self):
        """Caregiver receives 403 from require_diabetic_or_admin checker."""
        checker = RoleChecker([UserRole.DIABETIC, UserRole.ADMIN])
        caregiver = _make_user(UserRole.CAREGIVER)
        request = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            await checker(request, caregiver)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_diabetic_allowed_by_require_diabetic_or_admin(self):
        """Diabetic user passes require_diabetic_or_admin checker."""
        checker = RoleChecker([UserRole.DIABETIC, UserRole.ADMIN])
        diabetic = _make_user(UserRole.DIABETIC)
        request = _make_request()

        result = await checker(request, diabetic)
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_allowed_by_require_diabetic_or_admin(self):
        """Admin user passes require_diabetic_or_admin checker."""
        checker = RoleChecker([UserRole.DIABETIC, UserRole.ADMIN])
        admin = _make_user(UserRole.ADMIN)
        request = _make_request()

        result = await checker(request, admin)
        assert result is True

    @pytest.mark.asyncio
    async def test_caregiver_allowed_by_require_caregiver(self):
        """Caregiver passes require_caregiver checker."""
        checker = RoleChecker([UserRole.CAREGIVER])
        caregiver = _make_user(UserRole.CAREGIVER)
        request = _make_request()

        result = await checker(request, caregiver)
        assert result is True

    @pytest.mark.asyncio
    async def test_diabetic_blocked_by_require_caregiver(self):
        """Diabetic user receives 403 from require_caregiver checker."""
        checker = RoleChecker([UserRole.CAREGIVER])
        diabetic = _make_user(UserRole.DIABETIC)
        request = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            await checker(request, diabetic)

        assert exc_info.value.status_code == 403


# ── TestRouterDependenciesIncludeRoleCheck ──


class TestRouterDependenciesIncludeRoleCheck:
    """Verify that each protected endpoint has require_diabetic in its dependencies.

    This is a structural test that inspects the route configuration directly,
    ensuring the dependency is wired correctly at the framework level.
    Route paths include the router prefix (e.g., /api/alerts/active).
    """

    def _get_route_dependencies(self, router, path: str, method: str) -> list:
        """Extract dependencies list from a specific route (full path with prefix)."""
        for route in router.routes:
            if hasattr(route, "path") and hasattr(route, "methods"):
                if route.path == path and method.upper() in route.methods:
                    return route.dependencies
        return []

    def _get_role_checker(self, router, path: str, method: str) -> RoleChecker | None:
        """Return the RoleChecker among a route's dependencies, or None.

        Position-independent: a route may carry other dependencies before its
        role check (e.g. the settings router's router-level ``require_first_party``
        guard), so search by type rather than assuming index 0.
        """
        for dep in self._get_route_dependencies(router, path, method):
            if isinstance(dep.dependency, RoleChecker):
                return dep.dependency
        return None

    # ── Alerts ──

    def test_alerts_active_has_require_diabetic(self):
        """GET /api/alerts/active has require_diabetic dependency."""
        from src.routers.alerts import router

        deps = self._get_route_dependencies(router, "/api/alerts/active", "GET")
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_alerts_acknowledge_has_require_diabetic(self):
        """PATCH /api/alerts/{alert_id}/acknowledge has require_diabetic."""
        from src.routers.alerts import router

        deps = self._get_route_dependencies(
            router, "/api/alerts/{alert_id}/acknowledge", "PATCH"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    # ── Settings ──

    def test_settings_get_thresholds_has_require_diabetic(self):
        """GET /api/settings/alert-thresholds has require_diabetic."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/alert-thresholds", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_settings_patch_thresholds_has_require_diabetic(self):
        """PATCH /api/settings/alert-thresholds has require_diabetic."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/alert-thresholds", "PATCH"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_settings_get_escalation_has_require_diabetic(self):
        """GET /api/settings/escalation-config has require_diabetic."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/escalation-config", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_settings_patch_escalation_has_require_diabetic(self):
        """PATCH /api/settings/escalation-config has require_diabetic."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/escalation-config", "PATCH"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    # ── Target Glucose Range (Story 9.1) ──

    def test_settings_get_target_glucose_range_has_require_diabetic(self):
        """GET /api/settings/target-glucose-range has require_diabetic."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/target-glucose-range", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_settings_patch_target_glucose_range_has_require_diabetic(self):
        """PATCH /api/settings/target-glucose-range has require_diabetic."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/target-glucose-range", "PATCH"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_target_glucose_range_defaults_no_role_check(self):
        """GET /api/settings/target-glucose-range/defaults has no role check."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/target-glucose-range/defaults", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker not in dep_classes

    def test_target_glucose_range_role_blocks_caregiver(self):
        """Target glucose range role check blocks CAREGIVER."""
        from src.routers.settings import router

        role_checker = self._get_role_checker(
            router, "/api/settings/target-glucose-range", "GET"
        )
        assert role_checker is not None
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    # ── Brief Delivery (Story 9.2) ──

    def test_settings_get_brief_delivery_has_require_diabetic(self):
        """GET /api/settings/brief-delivery has require_diabetic."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/brief-delivery", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_settings_patch_brief_delivery_has_require_diabetic(self):
        """PATCH /api/settings/brief-delivery has require_diabetic."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/brief-delivery", "PATCH"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_brief_delivery_defaults_no_role_check(self):
        """GET /api/settings/brief-delivery/defaults has no role check."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/brief-delivery/defaults", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker not in dep_classes

    def test_brief_delivery_role_blocks_caregiver(self):
        """Brief delivery role check blocks CAREGIVER."""
        from src.routers.settings import router

        role_checker = self._get_role_checker(
            router, "/api/settings/brief-delivery", "GET"
        )
        assert role_checker is not None
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    # ── Emergency Contacts ──

    def test_emergency_contacts_get_has_require_diabetic(self):
        """GET /api/settings/emergency-contacts has require_diabetic."""
        from src.routers.emergency_contacts import router

        deps = self._get_route_dependencies(
            router, "/api/settings/emergency-contacts", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_emergency_contacts_post_has_require_diabetic(self):
        """POST /api/settings/emergency-contacts has require_diabetic."""
        from src.routers.emergency_contacts import router

        deps = self._get_route_dependencies(
            router, "/api/settings/emergency-contacts", "POST"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_emergency_contacts_patch_has_require_diabetic(self):
        """PATCH /api/settings/emergency-contacts/{contact_id} has require_diabetic."""
        from src.routers.emergency_contacts import router

        deps = self._get_route_dependencies(
            router, "/api/settings/emergency-contacts/{contact_id}", "PATCH"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_emergency_contacts_delete_has_require_diabetic(self):
        """DELETE /api/settings/emergency-contacts/{contact_id} has require_diabetic."""
        from src.routers.emergency_contacts import router

        deps = self._get_route_dependencies(
            router, "/api/settings/emergency-contacts/{contact_id}", "DELETE"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    # ── Escalation ──

    def test_escalation_timeline_has_require_diabetic(self):
        """GET /api/escalation/alerts/{alert_id}/timeline has require_diabetic."""
        from src.routers.escalation import router

        deps = self._get_route_dependencies(
            router, "/api/escalation/alerts/{alert_id}/timeline", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    # ── Insights ──

    def test_insights_list_has_require_diabetic(self):
        """GET /api/ai/insights has require_diabetic."""
        from src.routers.insights import router

        deps = self._get_route_dependencies(router, "/api/ai/insights", "GET")
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_insights_detail_has_require_diabetic(self):
        """GET /api/ai/insights/{analysis_type}/{analysis_id} has require_diabetic."""
        from src.routers.insights import router

        deps = self._get_route_dependencies(
            router, "/api/ai/insights/{analysis_type}/{analysis_id}", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_insights_respond_has_require_diabetic(self):
        """POST /api/ai/insights/{analysis_type}/{analysis_id}/respond has require_diabetic."""
        from src.routers.insights import router

        deps = self._get_route_dependencies(
            router,
            "/api/ai/insights/{analysis_type}/{analysis_id}/respond",
            "POST",
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    # ── Defaults (should NOT have role checks — public reference data) ──

    def test_threshold_defaults_no_role_check(self):
        """GET /api/settings/alert-thresholds/defaults has no role check."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/alert-thresholds/defaults", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker not in dep_classes

    def test_escalation_defaults_no_role_check(self):
        """GET /api/settings/escalation-config/defaults has no role check."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/escalation-config/defaults", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker not in dep_classes

    # ── Verify allowed_roles is DIABETIC + ADMIN (blocks caregiver) ──

    def test_alerts_role_is_diabetic_or_admin(self):
        """Alerts role check allows DIABETIC and ADMIN, blocks CAREGIVER."""
        from src.routers.alerts import router

        deps = self._get_route_dependencies(router, "/api/alerts/active", "GET")
        role_checker = deps[0].dependency
        assert UserRole.DIABETIC in role_checker.allowed_roles
        assert UserRole.ADMIN in role_checker.allowed_roles
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    def test_settings_role_blocks_caregiver(self):
        """Settings role check blocks CAREGIVER."""
        from src.routers.settings import router

        role_checker = self._get_role_checker(
            router, "/api/settings/alert-thresholds", "GET"
        )
        assert role_checker is not None
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    def test_emergency_contacts_role_blocks_caregiver(self):
        """Emergency contacts role check blocks CAREGIVER."""
        from src.routers.emergency_contacts import router

        deps = self._get_route_dependencies(
            router, "/api/settings/emergency-contacts", "GET"
        )
        role_checker = deps[0].dependency
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    def test_escalation_role_blocks_caregiver(self):
        """Escalation role check blocks CAREGIVER."""
        from src.routers.escalation import router

        deps = self._get_route_dependencies(
            router, "/api/escalation/alerts/{alert_id}/timeline", "GET"
        )
        role_checker = deps[0].dependency
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    def test_insights_role_blocks_caregiver(self):
        """Insights role check blocks CAREGIVER."""
        from src.routers.insights import router

        deps = self._get_route_dependencies(router, "/api/ai/insights", "GET")
        role_checker = deps[0].dependency
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    # ── Story 9.3: Data Retention ──

    def test_data_retention_get_has_require_diabetic(self):
        """GET /api/settings/data-retention has require_diabetic_or_admin."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/data-retention", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_data_retention_patch_has_require_diabetic(self):
        """PATCH /api/settings/data-retention has require_diabetic_or_admin."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/data-retention", "PATCH"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_data_retention_usage_has_require_diabetic(self):
        """GET /api/settings/data-retention/usage has require_diabetic_or_admin."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/data-retention/usage", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_data_retention_defaults_no_role_check(self):
        """GET /api/settings/data-retention/defaults has no role check."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/data-retention/defaults", "GET"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker not in dep_classes

    def test_data_retention_role_blocks_caregiver(self):
        """Data retention role check blocks CAREGIVER."""
        from src.routers.settings import router

        role_checker = self._get_role_checker(
            router, "/api/settings/data-retention", "GET"
        )
        assert role_checker is not None
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    # ── Story 9.4: Data Purge ──

    def test_data_purge_has_require_diabetic(self):
        """POST /api/settings/data-retention/purge has require_diabetic_or_admin."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(
            router, "/api/settings/data-retention/purge", "POST"
        )
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_data_purge_role_blocks_caregiver(self):
        """Data purge role check blocks CAREGIVER."""
        from src.routers.settings import router

        role_checker = self._get_role_checker(
            router, "/api/settings/data-retention/purge", "POST"
        )
        assert role_checker is not None
        assert UserRole.CAREGIVER not in role_checker.allowed_roles

    # ── Story 9.5: Settings export ──

    def test_settings_export_has_require_diabetic(self):
        """POST /api/settings/export has require_diabetic_or_admin."""
        from src.routers.settings import router

        deps = self._get_route_dependencies(router, "/api/settings/export", "POST")
        dep_classes = [type(d.dependency) for d in deps]
        assert RoleChecker in dep_classes

    def test_settings_export_role_blocks_caregiver(self):
        """Settings export role check blocks CAREGIVER."""
        from src.routers.settings import router

        role_checker = self._get_role_checker(router, "/api/settings/export", "POST")
        assert role_checker is not None
        assert UserRole.CAREGIVER not in role_checker.allowed_roles
