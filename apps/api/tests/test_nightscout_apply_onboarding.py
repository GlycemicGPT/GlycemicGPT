"""Tests for the smart-onboarding apply + derivation endpoints.

End-to-end coverage of:
  * GET /api/integrations/nightscout/{id}/onboarding-derivation
  * POST /api/integrations/nightscout/{id}/apply-onboarding

The pure derivation logic is covered by `test_nightscout_onboarding_derive`.
This file focuses on endpoint behavior: auth/RBAC, soft-delete, snapshot
loading, schema-level overrides, the units-unknown gate, settings
persistence, and the bounded first-sync envelope.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.main import app
from src.models.insulin_config import InsulinConfig
from src.models.nightscout_connection import (
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_profile import PumpProfile
from src.models.target_glucose_range import TargetGlucoseRange
from src.models.user import User
from src.services.integrations.nightscout.connection_test import ConnectionTestOutcome
from src.services.integrations.nightscout.sync import SyncResult


# ---------------------------------------------------------------------------
# Auth / fixtures
# ---------------------------------------------------------------------------


def _unique_email(stem: str) -> str:
    return f"{stem}_{uuid.uuid4().hex[:10]}@example.com"


async def _register_and_login(client, email: str, password: str = "Test1234!"):
    from src.config import settings

    reg = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    cookie = resp.cookies.get(settings.jwt_cookie_name)
    assert cookie, "login did not set the auth cookie"
    return {settings.jwt_cookie_name: cookie}


async def _cleanup(emails: list[str]) -> None:
    async with get_session_maker()() as db:
        result = await db.execute(User.__table__.select().where(User.email.in_(emails)))
        ids = [row.id for row in result.fetchall()]
        if ids:
            # Snapshots first (FK to connection AND user).
            await db.execute(
                delete(NightscoutProfileSnapshot).where(
                    NightscoutProfileSnapshot.user_id.in_(ids)
                )
            )
            await db.execute(
                delete(NightscoutConnection).where(
                    NightscoutConnection.user_id.in_(ids)
                )
            )
            await db.execute(
                delete(PumpProfile).where(PumpProfile.user_id.in_(ids))
            )
            await db.execute(
                delete(TargetGlucoseRange).where(
                    TargetGlucoseRange.user_id.in_(ids)
                )
            )
            await db.execute(
                delete(InsulinConfig).where(InsulinConfig.user_id.in_(ids))
            )
            await db.execute(delete(User).where(User.id.in_(ids)))
            await db.commit()


@pytest_asyncio.fixture
async def http_client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Connection + snapshot seeders
# ---------------------------------------------------------------------------


def _ok_outcome() -> ConnectionTestOutcome:
    return ConnectionTestOutcome(
        ok=True,
        server_version="15.0.3",
        api_version_detected=None,
        auth_validated=True,
    )


async def _create_conn(http_client, cookies, name: str = "Apply NS") -> str:
    """Create a connection via the real POST endpoint (mocked test stub)."""
    with patch(
        "src.routers.nightscout.test_connection",
        new=AsyncMock(return_value=_ok_outcome()),
    ):
        resp = await http_client.post(
            "/api/integrations/nightscout",
            cookies=cookies,
            json={
                "name": name,
                "base_url": "https://example.com",
                "auth_type": "secret",
                "credential": "test-secret-12chars",
                "api_version": "v1",
            },
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["connection"]["id"]


async def _seed_snapshot(
    *,
    connection_id: str,
    user_email: str,
    units: str = "mg/dl",
    dia_hours: float | None = 5.0,
    basal_segments: list[dict] | None = None,
    carb_ratio_segments: list[dict] | None = None,
    sensitivity_segments: list[dict] | None = None,
    target_low_segments: list[dict] | None = None,
    target_high_segments: list[dict] | None = None,
) -> None:
    """Persist a minimal NightscoutProfileSnapshot tied to (connection, user)."""
    async with get_session_maker()() as db:
        user_row = await db.execute(
            User.__table__.select().where(User.email == user_email)
        )
        user_id = user_row.fetchone().id
        snap = NightscoutProfileSnapshot(
            id=uuid.uuid4(),
            user_id=user_id,
            nightscout_connection_id=uuid.UUID(connection_id),
            fetched_at=datetime.now(UTC),
            source_default_profile_name="Default",
            source_units=units,
            source_timezone="UTC",
            source_dia_hours=dia_hours,
            basal_segments=basal_segments,
            carb_ratio_segments=carb_ratio_segments,
            sensitivity_segments=sensitivity_segments,
            target_low_segments=target_low_segments,
            target_high_segments=target_high_segments,
        )
        db.add(snap)
        await db.commit()


def _loop_segments() -> dict:
    """Realistic single-segment Loop schedules + targets for an mg/dL profile."""
    return {
        "basal_segments": [{"time": "00:00", "timeAsSeconds": 0, "value": 0.65}],
        "carb_ratio_segments": [{"time": "00:00", "timeAsSeconds": 0, "value": 12.0}],
        "sensitivity_segments": [{"time": "00:00", "timeAsSeconds": 0, "value": 50.0}],
        "target_low_segments": [{"time": "00:00", "timeAsSeconds": 0, "value": 90.0}],
        "target_high_segments": [{"time": "00:00", "timeAsSeconds": 0, "value": 120.0}],
    }


# ---------------------------------------------------------------------------
# Sync stubs (apply tests)
# ---------------------------------------------------------------------------


def _ok_sync_result(connection_id: uuid.UUID) -> SyncResult:
    return SyncResult(
        connection_id=connection_id,
        status=NightscoutSyncStatus.OK,
        entries_inserted=1,
        entries_skipped=0,
        entries_failed=0,
        treatments_inserted_pump=0,
        treatments_inserted_glucose=0,
        treatments_failed=0,
        devicestatuses_inserted=0,
        devicestatuses_failed=0,
        profile_synced=False,
        duration_ms=12,
        error=None,
    )


def _patch_sync_ok():
    return patch(
        "src.routers.nightscout.sync_nightscout_for_connection",
        new=AsyncMock(side_effect=lambda db, conn: _ok_sync_result(conn.id)),
    )


def _patch_sync_timeout():
    async def _raise(db, conn):
        raise TimeoutError("simulated upstream hang")

    return patch(
        "src.routers.nightscout.sync_nightscout_for_connection",
        new=AsyncMock(side_effect=_raise),
    )


def _patch_sync_orchestrator_error(connection_id_factory):
    async def _err(db, conn):
        return SyncResult(
            connection_id=connection_id_factory(conn),
            status=NightscoutSyncStatus.AUTH_FAILED,
            entries_inserted=0,
            entries_skipped=0,
            entries_failed=0,
            treatments_inserted_pump=0,
            treatments_inserted_glucose=0,
            treatments_failed=0,
            devicestatuses_inserted=0,
            devicestatuses_failed=0,
            profile_synced=False,
            duration_ms=5,
            error="Authentication rejected",
        )

    return patch(
        "src.routers.nightscout.sync_nightscout_for_connection",
        new=AsyncMock(side_effect=_err),
    )


# ---------------------------------------------------------------------------
# GET /onboarding-derivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derivation_returns_proposals_when_snapshot_present(http_client):
    email = _unique_email("ns_derive_ok")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        resp = await http_client.get(
            f"/api/integrations/nightscout/{connection_id}/onboarding-derivation",
            cookies=cookies,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["has_profile"] is True
        assert body["units_unknown"] is False
        assert body["target_low"]["proposed_value"] == 90.0
        assert body["target_high"]["proposed_value"] == 120.0
        assert body["dia_hours"]["proposed_value"] == 5.0
        assert len(body["basal_schedule"]["proposed_segments"]) == 1
        assert body["basal_schedule"]["proposed_segments"][0]["value"] == 0.65
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_derivation_returns_empty_when_no_snapshot(http_client):
    email = _unique_email("ns_derive_empty")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        resp = await http_client.get(
            f"/api/integrations/nightscout/{connection_id}/onboarding-derivation",
            cookies=cookies,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["has_profile"] is False
        assert body["target_low"]["proposed_value"] is None
        assert body["basal_schedule"]["proposed_segments"] is None
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_derivation_unauthenticated_rejected(http_client):
    resp = await http_client.get(
        f"/api/integrations/nightscout/{uuid.uuid4()}/onboarding-derivation",
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_derivation_cross_tenant_404(http_client):
    email_a = _unique_email("ns_derive_a")
    email_b = _unique_email("ns_derive_b")
    cookies_a = await _register_and_login(http_client, email_a)
    cookies_b = await _register_and_login(http_client, email_b)
    try:
        connection_id = await _create_conn(http_client, cookies_a)
        resp = await http_client.get(
            f"/api/integrations/nightscout/{connection_id}/onboarding-derivation",
            cookies=cookies_b,
        )
        assert resp.status_code == 404
    finally:
        await _cleanup([email_a, email_b])


@pytest.mark.asyncio
async def test_derivation_404s_soft_deleted_connection(http_client):
    email = _unique_email("ns_derive_softdel")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        # Soft-delete by flipping is_active in the DB.
        async with get_session_maker()() as db:
            row = (
                await db.execute(
                    NightscoutConnection.__table__.select().where(
                        NightscoutConnection.id == uuid.UUID(connection_id)
                    )
                )
            ).fetchone()
            assert row is not None
            await db.execute(
                NightscoutConnection.__table__.update()
                .where(NightscoutConnection.id == uuid.UUID(connection_id))
                .values(is_active=False)
            )
            await db.commit()
        resp = await http_client.get(
            f"/api/integrations/nightscout/{connection_id}/onboarding-derivation",
            cookies=cookies,
        )
        assert resp.status_code == 404
    finally:
        await _cleanup([email])


# ---------------------------------------------------------------------------
# POST /apply-onboarding -- request schema validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_rejects_override_without_import_flag(http_client):
    email = _unique_email("ns_apply_override")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        resp = await http_client.post(
            f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
            cookies=cookies,
            json={
                # No import_target_low flag, but override given.
                "override_target_low": 85.0,
            },
        )
        assert resp.status_code == 422, resp.text
        assert "override_target_low" in resp.text
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_rejects_unsupported_initial_sync_window(http_client):
    email = _unique_email("ns_apply_window")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        resp = await http_client.post(
            f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
            cookies=cookies,
            json={"initial_sync_window_days": 14},
        )
        assert resp.status_code == 422, resp.text
    finally:
        await _cleanup([email])


# ---------------------------------------------------------------------------
# POST /apply-onboarding -- units-unknown gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_409s_units_unknown_without_confirm(http_client):
    email = _unique_email("ns_apply_unitsq")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            units="weird_unit",
            **_loop_segments(),
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={"import_target_low": True},
            )
        assert resp.status_code == 409, resp.text
        assert "units" in resp.text.lower()
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_passes_units_unknown_for_non_glucose_imports(http_client):
    """Importing only basal/DIA when units are unknown is safe -- those are
    unit-agnostic. The 409 gate must NOT fire."""
    email = _unique_email("ns_apply_unitsok")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            units="weird_unit",
            **_loop_segments(),
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_basal_schedule": True,
                    "import_dia_hours": True,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["applied"]["basal_schedule"] is True
        assert body["applied"]["dia_hours"] is True
        assert body["first_sync_status"] == "ok"
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_passes_units_unknown_with_explicit_confirm(http_client):
    email = _unique_email("ns_apply_unitsconfirm")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            units="weird_unit",
            **_loop_segments(),
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_target_low": True,
                    "import_target_high": True,
                    "confirm_units_unknown": True,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["applied"]["target_low"] is True
        assert body["applied"]["target_high"] is True
    finally:
        await _cleanup([email])


# ---------------------------------------------------------------------------
# POST /apply-onboarding -- happy path + persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_persists_settings_and_returns_first_sync_ok(http_client):
    email = _unique_email("ns_apply_happy")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_target_low": True,
                    "import_target_high": True,
                    "import_dia_hours": True,
                    "import_basal_schedule": True,
                    "import_carb_ratio_schedule": True,
                    "import_isf_schedule": True,
                    "initial_sync_window_days": 30,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["first_sync_status"] == "ok"
        assert body["sync_result"] is not None
        assert body["applied"]["target_low"] is True
        assert body["applied"]["target_high"] is True
        assert body["applied"]["dia_hours"] is True
        assert body["applied"]["basal_schedule"] is True
        assert body["applied"]["initial_sync_window_days"] is True
        assert body["target_glucose_range"]["low_target"] == 90.0
        assert body["target_glucose_range"]["high_target"] == 120.0
        assert body["insulin_config"]["dia_hours"] == 5.0
        assert body["pump_profile_id"] is not None

        # Persistence: row state matches the response shape.
        async with get_session_maker()() as db:
            user = (
                await db.execute(User.__table__.select().where(User.email == email))
            ).fetchone()
            tgr = (
                await db.execute(
                    TargetGlucoseRange.__table__.select().where(
                        TargetGlucoseRange.user_id == user.id
                    )
                )
            ).fetchone()
            assert tgr.low_target == 90.0
            assert tgr.high_target == 120.0

            ic = (
                await db.execute(
                    InsulinConfig.__table__.select().where(
                        InsulinConfig.user_id == user.id
                    )
                )
            ).fetchone()
            assert ic.dia_hours == 5.0

            pp = (
                await db.execute(
                    PumpProfile.__table__.select().where(
                        PumpProfile.user_id == user.id,
                    )
                )
            ).fetchone()
            assert pp.profile_name == "Nightscout"
            assert pp.is_active is True
            assert len(pp.segments) >= 1
            assert pp.segments[0]["basal_rate"] == 0.65
            assert pp.segments[0]["correction_factor"] == 50.0
            assert pp.segments[0]["carb_ratio"] == 12.0

            conn = (
                await db.execute(
                    NightscoutConnection.__table__.select().where(
                        NightscoutConnection.id == uuid.UUID(connection_id)
                    )
                )
            ).fetchone()
            assert conn.initial_sync_window_days == 30
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_idempotent_rerun_does_not_duplicate_pump_profile(http_client):
    email = _unique_email("ns_apply_idem")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        body = {
            "import_basal_schedule": True,
            "import_carb_ratio_schedule": True,
            "import_isf_schedule": True,
        }
        with _patch_sync_ok():
            r1 = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json=body,
            )
            r2 = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json=body,
            )
        assert r1.status_code == 200
        assert r2.status_code == 200
        # Same row UPSERTed, not two rows.
        async with get_session_maker()() as db:
            user = (
                await db.execute(User.__table__.select().where(User.email == email))
            ).fetchone()
            rows = (
                await db.execute(
                    PumpProfile.__table__.select().where(
                        PumpProfile.user_id == user.id,
                        PumpProfile.profile_name == "Nightscout",
                    )
                )
            ).fetchall()
            assert len(rows) == 1
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_uses_override_value_when_provided(http_client):
    email = _unique_email("ns_apply_override_val")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_target_low": True,
                    "import_target_high": True,
                    "override_target_low": 95.0,
                    "override_target_high": 130.0,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Override value wins over the proposal.
        assert body["target_glucose_range"]["low_target"] == 95.0
        assert body["target_glucose_range"]["high_target"] == 130.0
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_returns_200_with_timeout_on_first_sync_hang(http_client):
    """Settings persisted; sync timed out. 200 + first_sync_status='timeout'."""
    email = _unique_email("ns_apply_timeout")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        with _patch_sync_timeout():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={"import_dia_hours": True},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["first_sync_status"] == "timeout"
        assert body["first_sync_error"] is not None
        assert body["sync_result"] is None
        # Settings still landed.
        assert body["applied"]["dia_hours"] is True

        # Connection row marked NETWORK.
        async with get_session_maker()() as db:
            row = (
                await db.execute(
                    NightscoutConnection.__table__.select().where(
                        NightscoutConnection.id == uuid.UUID(connection_id)
                    )
                )
            ).fetchone()
            assert row.last_sync_status == NightscoutSyncStatus.NETWORK
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_returns_200_with_error_on_orchestrator_non_ok(http_client):
    email = _unique_email("ns_apply_syncerr")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        with _patch_sync_orchestrator_error(lambda c: c.id):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={"import_dia_hours": True},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["first_sync_status"] == "error"
        assert "auth" in (body["first_sync_error"] or "").lower()
        # Sync result still surfaced for the wizard's progress UI.
        assert body["sync_result"]["status"] == NightscoutSyncStatus.AUTH_FAILED.value
        # Connection row mirrors the orchestrator-reported status.
        async with get_session_maker()() as db:
            row = (
                await db.execute(
                    NightscoutConnection.__table__.select().where(
                        NightscoutConnection.id == uuid.UUID(connection_id)
                    )
                )
            ).fetchone()
            # The orchestrator MOCK returns a SyncResult without
            # updating the connection row itself; in production the
            # real orchestrator persists `last_sync_status`. Under
            # the mock the row stays at NEVER (creation default),
            # which is what we assert here.
            assert row.last_sync_status == NightscoutSyncStatus.NEVER
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_unauthenticated_rejected(http_client):
    resp = await http_client.post(
        f"/api/integrations/nightscout/{uuid.uuid4()}/apply-onboarding",
        json={"import_dia_hours": True},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_apply_cross_tenant_404(http_client):
    email_a = _unique_email("ns_apply_xt_a")
    email_b = _unique_email("ns_apply_xt_b")
    cookies_a = await _register_and_login(http_client, email_a)
    cookies_b = await _register_and_login(http_client, email_b)
    try:
        connection_id = await _create_conn(http_client, cookies_a)
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies_b,
                json={"import_dia_hours": True},
            )
        assert resp.status_code == 404
    finally:
        await _cleanup([email_a, email_b])


@pytest.mark.asyncio
async def test_apply_preserves_fractional_isf_precision(http_client):
    """mmol-converted ISFs land as floats; integer truncation would
    silently shift the user's correction factor by up to ~0.5 mg/dL/U."""
    email = _unique_email("ns_apply_isf_float")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        # mmol/L profile: ISF=1.8 mmol/L/U converts to 32.4 mg/dL/U.
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            units="mmol",
            sensitivity_segments=[
                {"time": "00:00", "timeAsSeconds": 0, "value": 1.8},
            ],
            basal_segments=[{"time": "00:00", "timeAsSeconds": 0, "value": 0.5}],
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_isf_schedule": True,
                    "import_basal_schedule": True,
                    "confirm_units_unknown": False,
                },
            )
        assert resp.status_code == 200, resp.text
        async with get_session_maker()() as db:
            user = (
                await db.execute(User.__table__.select().where(User.email == email))
            ).fetchone()
            pp = (
                await db.execute(
                    PumpProfile.__table__.select().where(
                        PumpProfile.user_id == user.id,
                    )
                )
            ).fetchone()
            cf = pp.segments[0]["correction_factor"]
            # Float, not int; precision preserved (1.8 mmol/L/U * 18.0182 = 32.43...).
            assert isinstance(cf, float)
            assert 32.0 < cf < 33.0
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_rejects_target_low_above_target_high(http_client):
    """Pre-flight ordering check rejects bad merges before any writer commits."""
    email = _unique_email("ns_apply_ordering")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_target_low": True,
                    "import_target_high": True,
                    "override_target_low": 200.0,
                    "override_target_high": 150.0,
                },
            )
        assert resp.status_code == 422, resp.text
        # Critically: NOTHING should have committed -- target range
        # row should not exist at all.
        async with get_session_maker()() as db:
            user = (
                await db.execute(User.__table__.select().where(User.email == email))
            ).fetchone()
            row = (
                await db.execute(
                    TargetGlucoseRange.__table__.select().where(
                        TargetGlucoseRange.user_id == user.id
                    )
                )
            ).fetchone()
            assert row is None
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_handles_null_segments_gracefully(http_client):
    """Snapshot with null/empty schedule fields must not crash; the
    derivation surfaces None proposals and apply leaves pump_profile
    untouched without error."""
    email = _unique_email("ns_apply_nullseg")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            basal_segments=None,
            carb_ratio_segments=None,
            sensitivity_segments=None,
            target_low_segments=[],
            target_high_segments=[],
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_basal_schedule": True,
                    "import_carb_ratio_schedule": True,
                    "import_isf_schedule": True,
                    "import_target_low": True,
                    "import_target_high": True,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Flags were set but no proposals to apply -> nothing landed.
        assert body["applied"]["target_low"] is False
        assert body["applied"]["target_high"] is False
        assert body["applied"]["basal_schedule"] is False
        assert body["applied"]["carb_ratio_schedule"] is False
        assert body["applied"]["isf_schedule"] is False
        assert body["pump_profile_id"] is None
        assert body["target_glucose_range"] is None
        assert body["first_sync_status"] == "ok"
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_at_realistic_glucose_edges_persists(http_client):
    """Targets at the upper end of the typical user range (low=80,
    high=200) must apply within the writer's ordering invariant
    (default urgent_low=55, urgent_high=250)."""
    email = _unique_email("ns_apply_edges")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_target_low": True,
                    "import_target_high": True,
                    "override_target_low": 80.0,
                    "override_target_high": 200.0,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["target_glucose_range"]["low_target"] == 80.0
        assert body["target_glucose_range"]["high_target"] == 200.0
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_rejects_low_target_below_urgent_low_default(http_client):
    """Override below the default urgent_low (55) must 422 with the
    writer's ordering message -- the apply pre-flight only checks
    low<high; deeper invariants are caught by `update_range`."""
    email = _unique_email("ns_apply_low_urgent")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        await _seed_snapshot(
            connection_id=connection_id,
            user_email=email,
            **_loop_segments(),
        )
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={
                    "import_target_low": True,
                    "override_target_low": 50.0,  # below urgent_low default of 55
                },
            )
        # 422 from the inner writer's ordering invariant.
        assert resp.status_code == 422, resp.text
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_apply_no_imports_returns_skipped(http_client):
    """All flags false -> no settings written, sync still kicks (skipped status
    is reserved for the no-sync path; here sync runs OK)."""
    email = _unique_email("ns_apply_noop")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)
        with _patch_sync_ok():
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/apply-onboarding",
                cookies=cookies,
                json={},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["target_glucose_range"] is None
        assert body["insulin_config"] is None
        assert body["pump_profile_id"] is None
        assert all(v is False for v in body["applied"].values())
    finally:
        await _cleanup([email])
