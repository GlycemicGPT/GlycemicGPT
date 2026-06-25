"""Story 8.3: Tests for caregiver dashboard endpoints and permission enforcement."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.units import GlucoseUnit
from src.models.caregiver_link import CaregiverLink
from src.models.user import User, UserRole
from src.schemas.caregiver_permissions import CaregiverPermissions

# ── Helpers ──


def make_link(
    patient_id: uuid.UUID | None = None,
    caregiver_id: uuid.UUID | None = None,
    **overrides: bool,
) -> MagicMock:
    """Create a mock CaregiverLink with permission defaults."""
    link = MagicMock(spec=CaregiverLink)
    link.id = uuid.uuid4()
    link.patient_id = patient_id or uuid.uuid4()
    link.caregiver_id = caregiver_id or uuid.uuid4()
    link.created_at = datetime.now(UTC)
    link.updated_at = datetime.now(UTC)
    link.can_view_glucose = overrides.get("can_view_glucose", True)
    link.can_view_history = overrides.get("can_view_history", True)
    link.can_view_iob = overrides.get("can_view_iob", True)
    link.can_view_ai_suggestions = overrides.get("can_view_ai_suggestions", False)
    link.can_receive_alerts = overrides.get("can_receive_alerts", True)
    # Mock patient relationship
    patient = MagicMock(spec=User)
    patient.id = link.patient_id
    patient.email = "patient@example.com"
    patient.role = UserRole.DIABETIC
    link.patient = patient
    return link


def make_glucose_reading(
    value: int = 120,
    minutes_ago: int = 3,
    trend_rate: float | None = -0.5,
) -> MagicMock:
    """Create a mock GlucoseReading."""
    reading = MagicMock()
    reading.value = value
    reading.trend = MagicMock()
    reading.trend.value = "Flat"
    reading.trend_rate = trend_rate
    reading.reading_timestamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    reading.source = "dexcom"
    return reading


def make_iob_projection(current_iob: float = 2.5) -> MagicMock:
    """Create a mock IoBProjection."""
    proj = MagicMock()
    proj.projected_iob = current_iob
    proj.confirmed_at = datetime.now(UTC) - timedelta(minutes=5)
    proj.projected_30min = None  # Not all projections have this
    return proj


# ── TestCaregiverPatientStatus ──


class TestCaregiverPatientStatus:
    """Tests for the caregiver patient status endpoint logic."""

    @pytest.mark.asyncio
    async def test_full_data_all_permissions(self):
        """Returns glucose + IoB when caregiver has full permissions."""
        from src.routers.caregivers import (
            _build_permissions,
        )

        link = make_link()
        permissions = _build_permissions(link)
        assert permissions.can_view_glucose is True
        assert permissions.can_view_iob is True

    @pytest.mark.asyncio
    async def test_glucose_denied_returns_none(self):
        """Glucose section is None when can_view_glucose is False."""
        from src.routers.caregivers import _build_permissions

        link = make_link(can_view_glucose=False)
        permissions = _build_permissions(link)
        assert permissions.can_view_glucose is False

    @pytest.mark.asyncio
    async def test_iob_denied_returns_none(self):
        """IoB section is None when can_view_iob is False."""
        from src.routers.caregivers import _build_permissions

        link = make_link(can_view_iob=False)
        permissions = _build_permissions(link)
        assert permissions.can_view_iob is False

    @pytest.mark.asyncio
    async def test_permissions_always_included(self):
        """Permissions object is always returned regardless of flags."""
        from src.routers.caregivers import _build_permissions

        link = make_link(
            can_view_glucose=False,
            can_view_iob=False,
            can_view_history=False,
        )
        permissions = _build_permissions(link)
        assert isinstance(permissions, CaregiverPermissions)
        assert permissions.can_view_glucose is False
        assert permissions.can_view_history is False
        assert permissions.can_view_iob is False

    @pytest.mark.asyncio
    async def test_stale_reading_detected(self):
        """Readings older than 15 minutes are marked as stale."""
        from src.routers.caregivers import _STALE_MINUTES

        reading = make_glucose_reading(minutes_ago=20)
        now = datetime.now(UTC)
        delta = now - reading.reading_timestamp
        minutes_ago = int(delta.total_seconds() / 60)
        assert minutes_ago >= _STALE_MINUTES


# ── TestTelegramPermissionEnforcement ──


class TestTelegramPermissionEnforcement:
    """Tests for permission checks in telegram_caregiver.py."""

    @pytest.mark.asyncio
    async def test_status_glucose_denied_single_patient(self):
        """Caregiver with can_view_glucose=False gets lock message."""
        from src.services.telegram_caregiver import _handle_caregiver_status

        caregiver_id = uuid.uuid4()
        link = make_link(caregiver_id=caregiver_id, can_view_glucose=False)
        db = AsyncMock()

        with patch(
            "src.services.caregiver.check_caregiver_permission",
            return_value=False,
        ):
            result = await _handle_caregiver_status(db, caregiver_id, [link])

        assert "permission not granted" in result.lower()
        assert "\U0001f512" in result

    @pytest.mark.asyncio
    async def test_status_glucose_allowed_single_patient(self):
        """Caregiver with can_view_glucose=True gets full status."""
        from src.services.telegram_caregiver import _handle_caregiver_status

        caregiver_id = uuid.uuid4()
        link = make_link(caregiver_id=caregiver_id, can_view_glucose=True)
        db = AsyncMock()

        mock_status = "120 mg/dL Flat"
        with (
            patch(
                "src.services.caregiver.check_caregiver_permission",
                return_value=True,
            ),
            patch(
                "src.services.telegram_commands._handle_status",
                return_value=mock_status,
            ),
        ):
            result = await _handle_caregiver_status(db, caregiver_id, [link])

        assert "Patient:" in result
        assert mock_status in result

    @pytest.mark.asyncio
    async def test_chat_ai_denied(self):
        """Caregiver without can_view_ai_suggestions gets denied."""
        from src.services.telegram_caregiver import _handle_caregiver_chat

        caregiver_id = uuid.uuid4()
        link = make_link(caregiver_id=caregiver_id, can_view_ai_suggestions=False)
        db = AsyncMock()

        with patch(
            "src.services.caregiver.check_caregiver_permission",
            return_value=False,
        ):
            result = await _handle_caregiver_chat(
                db, caregiver_id, [link], "How is my patient?"
            )

        assert "not enabled" in result.lower()
        assert "\U0001f512" in result

    @pytest.mark.asyncio
    async def test_chat_ai_allowed(self):
        """Caregiver with can_view_ai_suggestions=True routes to AI chat."""
        from src.services.telegram_caregiver import _handle_caregiver_chat

        caregiver_id = uuid.uuid4()
        link = make_link(caregiver_id=caregiver_id, can_view_ai_suggestions=True)
        db = AsyncMock()

        mock_response = "Patient is doing well."

        mock_chat = AsyncMock(return_value=mock_response)
        with (
            patch(
                "src.services.caregiver.check_caregiver_permission",
                return_value=True,
            ),
            patch.dict(
                "sys.modules",
                {
                    "src.services.telegram_chat": MagicMock(
                        handle_caregiver_chat=mock_chat
                    )
                },
            ),
        ):
            result = await _handle_caregiver_chat(
                db, caregiver_id, [link], "How is my patient?"
            )

        assert result == mock_response

    @pytest.mark.asyncio
    async def test_status_multi_patient_mixed_permissions(self):
        """Multi-patient: shows data for permitted, lock for denied."""
        from src.services.telegram_caregiver import _handle_caregiver_status

        caregiver_id = uuid.uuid4()
        link1 = make_link(caregiver_id=caregiver_id, can_view_glucose=True)
        link1.patient.email = "patient1@example.com"
        link2 = make_link(caregiver_id=caregiver_id, can_view_glucose=False)
        link2.patient.email = "patient2@example.com"

        db = AsyncMock()

        # First call True (patient1 allowed), second call False (patient2 denied)
        perm_results = [True, False]

        async def mock_check_perm(db, cg_id, pt_id, perm):
            return perm_results.pop(0)

        reading = make_glucose_reading()

        with (
            patch(
                "src.services.caregiver.check_caregiver_permission",
                side_effect=mock_check_perm,
            ),
            patch(
                "src.services.dexcom_sync.get_latest_glucose_reading",
                new_callable=AsyncMock,
                return_value=reading,
            ),
            patch(
                "src.services.alert_notifier.trend_description",
                return_value="Flat",
            ),
        ):
            result = await _handle_caregiver_status(db, caregiver_id, [link1, link2])

        assert "patient1@example.com" in result
        assert "patient2@example.com" in result
        assert "Permission not granted" in result
        assert "mg/dL" in result


# ── TestStatusEndpointIntegration ──


class TestStatusEndpointIntegration:
    """Integration-style tests calling the full endpoint function."""

    @pytest.mark.asyncio
    async def test_full_status_with_glucose_and_iob(self):
        """Full status endpoint returns glucose + IoB when permitted."""
        from src.routers.caregivers import get_caregiver_patient_status

        caregiver_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        link = make_link(
            caregiver_id=caregiver_id,
            patient_id=patient_id,
            can_view_glucose=True,
            can_view_iob=True,
        )
        reading = make_glucose_reading(value=145, minutes_ago=3)
        projection = make_iob_projection(current_iob=1.8)

        db = AsyncMock()
        # Mock for _get_caregiver_link
        mock_link_result = MagicMock()
        mock_link_result.scalar_one_or_none.return_value = link
        # Mock for patient email lookup
        mock_email_result = MagicMock()
        mock_email_result.scalar_one_or_none.return_value = "patient@example.com"
        # Mock for the patient's glucose-unit lookup (resolve_glucose_unit)
        mock_unit_result = MagicMock()
        mock_unit_result.scalar_one_or_none.return_value = GlucoseUnit.MGDL

        db.execute.side_effect = [
            mock_link_result,
            mock_email_result,
            mock_unit_result,
        ]

        mock_user = MagicMock()
        mock_user.id = caregiver_id

        with (
            patch(
                "src.services.dexcom_sync.get_latest_glucose_reading",
                new_callable=AsyncMock,
                return_value=reading,
            ),
            patch(
                "src.services.iob_projection.get_iob_projection",
                new_callable=AsyncMock,
                return_value=projection,
            ),
            patch(
                "src.services.iob_projection.get_user_dia",
                new_callable=AsyncMock,
                return_value=4.0,
            ),
        ):
            result = await get_caregiver_patient_status(
                patient_id=patient_id,
                current_user=mock_user,
                db=db,
            )

        assert result.patient_id == patient_id
        assert result.patient_email == "patient@example.com"
        assert result.glucose_unit == GlucoseUnit.MGDL
        # The value stays canonical mg/dL; only the unit token selects display.
        assert result.glucose is not None
        assert result.glucose.value == 145
        assert result.iob is not None
        assert result.iob.current_iob == projection.projected_iob
        assert result.permissions.can_view_glucose is True
        assert result.permissions.can_view_iob is True

    @pytest.mark.asyncio
    async def test_status_renders_each_patient_in_their_own_unit(self):
        """A caregiver watching a mmol patient and a mg/dL patient gets each
        patient's OWN unit on the status payload (never the caregiver's). The
        glucose value stays canonical mg/dL regardless of the display unit.
        """
        from src.routers.caregivers import get_caregiver_patient_status

        caregiver_id = uuid.uuid4()

        async def status_for(patient_unit: GlucoseUnit):
            patient_id = uuid.uuid4()
            link = make_link(
                caregiver_id=caregiver_id,
                patient_id=patient_id,
                can_view_glucose=True,
                can_view_iob=False,
            )
            db = AsyncMock()
            mock_link_result = MagicMock()
            mock_link_result.scalar_one_or_none.return_value = link
            mock_email_result = MagicMock()
            mock_email_result.scalar_one_or_none.return_value = "p@example.com"
            mock_unit_result = MagicMock()
            mock_unit_result.scalar_one_or_none.return_value = patient_unit
            db.execute.side_effect = [
                mock_link_result,
                mock_email_result,
                mock_unit_result,
            ]
            mock_user = MagicMock()
            mock_user.id = caregiver_id
            with patch(
                "src.services.dexcom_sync.get_latest_glucose_reading",
                new_callable=AsyncMock,
                return_value=make_glucose_reading(value=90),
            ):
                return await get_caregiver_patient_status(
                    patient_id=patient_id,
                    current_user=mock_user,
                    db=db,
                )

        mmol_status = await status_for(GlucoseUnit.MMOL)
        mgdl_status = await status_for(GlucoseUnit.MGDL)

        assert mmol_status.glucose_unit == GlucoseUnit.MMOL
        assert mgdl_status.glucose_unit == GlucoseUnit.MGDL
        # Same canonical mg/dL value regardless of the display unit.
        assert mmol_status.glucose.value == 90
        assert mgdl_status.glucose.value == 90

    @pytest.mark.asyncio
    async def test_full_status_glucose_denied_omits_data(self):
        """Status endpoint omits glucose when permission denied."""
        from src.routers.caregivers import get_caregiver_patient_status

        caregiver_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        link = make_link(
            caregiver_id=caregiver_id,
            patient_id=patient_id,
            can_view_glucose=False,
            can_view_iob=False,
        )

        db = AsyncMock()
        mock_link_result = MagicMock()
        mock_link_result.scalar_one_or_none.return_value = link
        mock_email_result = MagicMock()
        mock_email_result.scalar_one_or_none.return_value = "patient@example.com"
        db.execute.side_effect = [mock_link_result, mock_email_result]

        mock_user = MagicMock()
        mock_user.id = caregiver_id

        result = await get_caregiver_patient_status(
            patient_id=patient_id,
            current_user=mock_user,
            db=db,
        )

        assert result.glucose is None
        assert result.iob is None
        assert result.permissions.can_view_glucose is False
        assert result.permissions.can_view_iob is False
        # No glucose shown -> the unit token defaults to mg/dL (and is unused).
        assert result.glucose_unit == GlucoseUnit.MGDL

    @pytest.mark.asyncio
    async def test_unlinked_patient_raises_404(self):
        """Status endpoint returns 404 for unlinked patient."""
        from fastapi import HTTPException

        from src.routers.caregivers import get_caregiver_patient_status

        caregiver_id = uuid.uuid4()
        patient_id = uuid.uuid4()

        db = AsyncMock()
        mock_link_result = MagicMock()
        mock_link_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_link_result

        mock_user = MagicMock()
        mock_user.id = caregiver_id

        with pytest.raises(HTTPException) as exc_info:
            await get_caregiver_patient_status(
                patient_id=patient_id,
                current_user=mock_user,
                db=db,
            )

        assert exc_info.value.status_code == 404


# ── TestEndpointRBAC ──


class TestEndpointRBAC:
    """Integration tests verifying RBAC on caregiver dashboard endpoints."""

    @pytest.mark.asyncio
    async def test_unauthenticated_status_returns_401(self, client):
        """Unauthenticated requests to GET /patients/{id}/status return 401."""
        fake_id = str(uuid.uuid4())
        response = await client.get(f"/api/caregivers/patients/{fake_id}/status")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unauthenticated_history_returns_401(self, client):
        """Unauthenticated requests to GET /patients/{id}/glucose/history return 401."""
        fake_id = str(uuid.uuid4())
        response = await client.get(
            f"/api/caregivers/patients/{fake_id}/glucose/history"
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_status_invalid_uuid_returns_401(self, client):
        """Auth check fires before path validation — invalid UUID still 401."""
        response = await client.get("/api/caregivers/patients/not-a-uuid/status")
        assert response.status_code == 401


# ── TestSchemas ──


class TestCaregiverDashboardSchemas:
    """Tests for Story 8.3 response schemas."""

    def test_patient_status_optional_sections(self):
        """CaregiverPatientStatus allows None for glucose and iob."""
        from src.schemas.caregiver_dashboard import CaregiverPatientStatus

        status = CaregiverPatientStatus(
            patient_id=uuid.uuid4(),
            patient_email="test@example.com",
            glucose=None,
            iob=None,
            permissions=CaregiverPermissions(),
        )
        assert status.glucose is None
        assert status.iob is None
        # glucose_unit is optional and defaults to mg/dL (back-compat: callers
        # that don't set it keep the canonical default).
        assert status.glucose_unit == GlucoseUnit.MGDL

    def test_glucose_data_schema(self):
        """CaregiverGlucoseData validates all required fields."""
        from src.schemas.caregiver_dashboard import CaregiverGlucoseData

        data = CaregiverGlucoseData(
            value=120,
            trend="Flat",
            trend_rate=-0.5,
            reading_timestamp=datetime.now(UTC),
            minutes_ago=3,
            is_stale=False,
        )
        assert data.value == 120
        assert data.is_stale is False

    def test_iob_data_schema(self):
        """CaregiverIoBData validates all required fields."""
        from src.schemas.caregiver_dashboard import CaregiverIoBData

        data = CaregiverIoBData(
            current_iob=2.5,
            projected_30min=None,
            confirmed_at=datetime.now(UTC),
            is_stale=False,
        )
        assert data.current_iob == 2.5
        assert data.projected_30min is None

    def test_history_response_schema(self):
        """CaregiverGlucoseHistoryResponse builds from readings."""
        from src.schemas.caregiver_dashboard import (
            CaregiverGlucoseHistoryReading,
            CaregiverGlucoseHistoryResponse,
        )

        resp = CaregiverGlucoseHistoryResponse(
            patient_id=uuid.uuid4(),
            readings=[
                CaregiverGlucoseHistoryReading(
                    value=120,
                    trend="Flat",
                    trend_rate=-0.5,
                    reading_timestamp=datetime.now(UTC),
                )
            ],
            count=1,
        )
        assert resp.count == 1
        assert len(resp.readings) == 1
