"""Story 8.1: Tests for caregiver invitation and linking."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.caregiver_invitation import (
    INVITATION_EXPIRY_DAYS,
    CaregiverInvitation,
    InvitationStatus,
)
from src.models.caregiver_link import CaregiverLink
from src.models.user import User, UserRole
from src.services.caregiver import (
    MAX_PATIENTS_PER_CAREGIVER,
    MAX_PENDING_INVITATIONS_PER_PATIENT,
    accept_invitation,
    create_invitation,
    expire_stale_invitations,
    get_invitation_by_token,
    get_linked_patients,
    list_invitations,
    revoke_invitation,
)

# ── Helpers ──


def make_invitation(
    status: str = InvitationStatus.PENDING.value,
    token: str = "test-token-abc",
    patient_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    """Create a mock CaregiverInvitation."""
    inv = MagicMock(spec=CaregiverInvitation)
    inv.id = uuid.uuid4()
    inv.patient_id = patient_id or uuid.uuid4()
    inv.token = token
    inv.status = status
    inv.expires_at = expires_at or (datetime.now(UTC) + timedelta(days=7))
    inv.accepted_by = None
    inv.accepted_at = None
    inv.created_at = datetime.now(UTC)
    inv.updated_at = datetime.now(UTC)
    return inv


def make_user(
    role: UserRole = UserRole.DIABETIC,
    email: str = "patient@example.com",
) -> MagicMock:
    """Create a mock User."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.role = role
    return user


# ── TestCaregiverInvitationModel ──


class TestCaregiverInvitationModel:
    """Tests for CaregiverInvitation model attributes."""

    def test_tablename(self):
        assert CaregiverInvitation.__tablename__ == "caregiver_invitations"

    def test_repr(self):
        patient_id = uuid.uuid4()
        inv = CaregiverInvitation(patient_id=patient_id)
        repr_str = repr(inv)
        assert "CaregiverInvitation" in repr_str
        assert str(patient_id) in repr_str

    def test_invitation_status_values(self):
        assert InvitationStatus.PENDING.value == "pending"
        assert InvitationStatus.ACCEPTED.value == "accepted"
        assert InvitationStatus.EXPIRED.value == "expired"
        assert InvitationStatus.REVOKED.value == "revoked"

    def test_expiry_default(self):
        """Default expiry is INVITATION_EXPIRY_DAYS (7) days from now."""
        assert INVITATION_EXPIRY_DAYS == 7


# ── TestCreateInvitation ──


class TestCreateInvitation:
    """Tests for create_invitation."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Creates invitation and commits to DB."""
        db = AsyncMock()

        # Mock pending count query
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        db.execute.return_value = mock_count_result

        invitation = await create_invitation(db, uuid.uuid4())

        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()
        assert invitation is not None

    @pytest.mark.asyncio
    async def test_max_pending_limit(self):
        """Raises ValueError when max pending invitations reached."""
        db = AsyncMock()

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = MAX_PENDING_INVITATIONS_PER_PATIENT
        db.execute.return_value = mock_count_result

        with pytest.raises(ValueError, match="pending invitations"):
            await create_invitation(db, uuid.uuid4())

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_is_generated(self):
        """Created invitation has a token."""
        db = AsyncMock()

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        db.execute.return_value = mock_count_result

        await create_invitation(db, uuid.uuid4())

        added = db.add.call_args[0][0]
        assert added.token is not None
        assert len(added.token) > 20

    @pytest.mark.asyncio
    async def test_expiry_is_7_days(self):
        """Created invitation expires in ~7 days."""
        db = AsyncMock()

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        db.execute.return_value = mock_count_result

        await create_invitation(db, uuid.uuid4())

        added = db.add.call_args[0][0]
        now = datetime.now(UTC)
        delta = added.expires_at - now
        assert 6.9 < delta.total_seconds() / 86400 < 7.1


# ── TestListInvitations ──


class TestListInvitations:
    """Tests for list_invitations."""

    @pytest.mark.asyncio
    @patch(
        "src.services.caregiver._expire_stale_invitations_for_patient",
        new_callable=AsyncMock,
    )
    async def test_returns_invitations(self, mock_expire):
        """Returns all invitations for the patient."""
        inv1 = make_invitation()
        inv2 = make_invitation(status=InvitationStatus.ACCEPTED.value)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [inv1, inv2]

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await list_invitations(db, uuid.uuid4())
        assert len(result) == 2

    @pytest.mark.asyncio
    @patch(
        "src.services.caregiver._expire_stale_invitations_for_patient",
        new_callable=AsyncMock,
    )
    async def test_empty_list(self, mock_expire):
        """Returns empty list when no invitations exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await list_invitations(db, uuid.uuid4())
        assert result == []


# ── TestRevokeInvitation ──


class TestRevokeInvitation:
    """Tests for revoke_invitation."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Revokes a pending invitation."""
        inv = make_invitation()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inv

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await revoke_invitation(db, inv.patient_id, inv.id)

        assert inv.status == InvitationStatus.REVOKED.value
        db.commit.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_not_found(self):
        """Returns None when invitation not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await revoke_invitation(db, uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_already_accepted(self):
        """Raises ValueError when invitation is not pending."""
        inv = make_invitation(status=InvitationStatus.ACCEPTED.value)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inv

        db = AsyncMock()
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Cannot revoke"):
            await revoke_invitation(db, inv.patient_id, inv.id)


# ── TestGetInvitationByToken ──


class TestGetInvitationByToken:
    """Tests for get_invitation_by_token."""

    @pytest.mark.asyncio
    async def test_valid_token(self):
        """Returns invitation for a valid token."""
        inv = make_invitation()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inv

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_invitation_by_token(db, "test-token-abc")
        assert result is inv

    @pytest.mark.asyncio
    async def test_expired_auto_marks(self):
        """Auto-marks expired PENDING invitations."""
        inv = make_invitation(
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inv

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_invitation_by_token(db, "test-token-abc")
        assert result.status == InvitationStatus.EXPIRED.value
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_found(self):
        """Returns None for unknown token."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_invitation_by_token(db, "bogus")
        assert result is None


# ── TestAcceptInvitation ──


class TestAcceptInvitation:
    """Tests for accept_invitation."""

    @pytest.mark.asyncio
    async def test_new_user_created_as_caregiver(self):
        """Creates a new CAREGIVER user when email is new."""
        patient_id = uuid.uuid4()
        inv = make_invitation(patient_id=patient_id)

        # First execute: invitation lookup (with_for_update)
        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = inv

        # Second execute: user lookup (email)
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = None

        # Third execute: link count
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        db = AsyncMock()
        db.execute.side_effect = [
            mock_inv_result,
            mock_user_result,
            mock_count_result,
        ]

        caregiver, returned_inv = await accept_invitation(
            db, "test-token-abc", "carer@example.com", "hashed_pw"
        )

        # Should have added 2 objects: User + CaregiverLink
        assert db.add.call_count == 2
        added_objects = [call[0][0] for call in db.add.call_args_list]

        new_user = next((o for o in added_objects if isinstance(o, User)), None)
        new_link = next(
            (o for o in added_objects if isinstance(o, CaregiverLink)), None
        )

        assert new_user is not None
        assert new_user.role == UserRole.CAREGIVER
        assert new_user.email == "carer@example.com"

        assert new_link is not None
        assert new_link.patient_id == patient_id

        assert inv.status == InvitationStatus.ACCEPTED.value
        assert inv.accepted_at is not None

    @pytest.mark.asyncio
    async def test_existing_caregiver_linked(self):
        """Links existing CAREGIVER user to a new patient."""
        patient_id = uuid.uuid4()
        inv = make_invitation(patient_id=patient_id)
        existing_caregiver = make_user(
            role=UserRole.CAREGIVER, email="carer@example.com"
        )

        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = inv

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = existing_caregiver

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        db = AsyncMock()
        db.execute.side_effect = [
            mock_inv_result,
            mock_user_result,
            mock_count_result,
        ]

        caregiver, returned_inv = await accept_invitation(
            db, "test-token-abc", "carer@example.com", "hashed_pw"
        )

        # Should only add CaregiverLink, not a new User
        assert db.add.call_count == 1
        added = db.add.call_args[0][0]
        assert isinstance(added, CaregiverLink)

    @pytest.mark.asyncio
    async def test_self_link_prevented(self):
        """Raises ValueError when patient tries to accept own invitation."""
        patient_id = uuid.uuid4()
        inv = make_invitation(patient_id=patient_id)
        # The patient themselves tries to accept
        patient_user = make_user(role=UserRole.DIABETIC, email="patient@example.com")
        patient_user.id = patient_id

        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = inv

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = patient_user

        db = AsyncMock()
        db.execute.side_effect = [mock_inv_result, mock_user_result]

        with pytest.raises(ValueError, match="cannot accept your own"):
            await accept_invitation(
                db, "test-token-abc", "patient@example.com", "hashed_pw"
            )

    @pytest.mark.asyncio
    async def test_non_caregiver_email_rejected(self):
        """Raises ValueError when email belongs to a DIABETIC user."""
        inv = make_invitation()
        existing_diabetic = make_user(
            role=UserRole.DIABETIC, email="patient@example.com"
        )

        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = inv

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = existing_diabetic

        db = AsyncMock()
        db.execute.side_effect = [mock_inv_result, mock_user_result]

        with pytest.raises(ValueError, match="different role"):
            await accept_invitation(
                db, "test-token-abc", "patient@example.com", "hashed_pw"
            )

    @pytest.mark.asyncio
    async def test_max_patients_enforced_with_rollback(self):
        """Raises ValueError and rolls back when caregiver has too many patients."""
        inv = make_invitation()

        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = inv

        # No existing user — new user path (will create then rollback)
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = None

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = MAX_PATIENTS_PER_CAREGIVER

        db = AsyncMock()
        db.execute.side_effect = [
            mock_inv_result,
            mock_user_result,
            mock_count_result,
        ]

        with pytest.raises(ValueError, match="maximum"):
            await accept_invitation(
                db, "test-token-abc", "carer@example.com", "hashed_pw"
            )

        # Verify rollback was called to prevent orphaned user
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self):
        """Raises ValueError for expired token."""
        inv = make_invitation(
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = inv

        db = AsyncMock()
        db.execute.return_value = mock_inv_result

        with pytest.raises(ValueError, match="expired"):
            await accept_invitation(
                db, "test-token-abc", "carer@example.com", "hashed_pw"
            )

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self):
        """Raises ValueError for unknown token."""
        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_inv_result

        with pytest.raises(ValueError, match="Invalid"):
            await accept_invitation(db, "bogus-token", "carer@example.com", "hashed_pw")

    @pytest.mark.asyncio
    async def test_already_accepted_rejected(self):
        """Raises ValueError for already-accepted invitation."""
        inv = make_invitation(status=InvitationStatus.ACCEPTED.value)

        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = inv

        db = AsyncMock()
        db.execute.return_value = mock_inv_result

        with pytest.raises(ValueError, match="no longer valid"):
            await accept_invitation(
                db, "test-token-abc", "carer@example.com", "hashed_pw"
            )


# ── TestGetLinkedPatients ──


class TestGetLinkedPatients:
    """Tests for get_linked_patients."""

    @pytest.mark.asyncio
    async def test_returns_linked_patients(self):
        """Returns CaregiverLinks for a caregiver."""
        link = MagicMock(spec=CaregiverLink)
        link.patient_id = uuid.uuid4()
        link.created_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [link]

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_linked_patients(db, uuid.uuid4())
        assert len(result) == 1
        assert result[0] is link

    @pytest.mark.asyncio
    async def test_empty_when_no_links(self):
        """Returns empty list when caregiver has no links."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_linked_patients(db, uuid.uuid4())
        assert result == []


# ── TestExpireStaleInvitations ──


class TestExpireStaleInvitations:
    """Tests for expire_stale_invitations."""

    @pytest.mark.asyncio
    async def test_expires_old_pending(self):
        """Marks stale PENDING invitations as EXPIRED."""
        inv = make_invitation(
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [inv]

        db = AsyncMock()
        db.execute.return_value = mock_result

        count = await expire_stale_invitations(db)
        assert count == 1
        assert inv.status == InvitationStatus.EXPIRED.value
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_non_pending(self):
        """Doesn't expire non-PENDING invitations."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute.return_value = mock_result

        count = await expire_stale_invitations(db)
        assert count == 0
        db.commit.assert_not_called()


# ── TestMaskEmail ──


class TestMaskEmail:
    """Tests for _mask_email helper."""

    def test_normal_email(self):
        from src.routers.caregivers import _mask_email

        assert _mask_email("patient@example.com") == "p*****t@example.com"

    def test_short_local_part(self):
        from src.routers.caregivers import _mask_email

        assert _mask_email("ab@example.com") == "a*@example.com"

    def test_single_char_local(self):
        from src.routers.caregivers import _mask_email

        assert _mask_email("a@example.com") == "a*@example.com"

    def test_no_domain(self):
        from src.routers.caregivers import _mask_email

        assert _mask_email("nodomain") == "***"

    def test_unknown(self):
        from src.routers.caregivers import _mask_email

        assert _mask_email("Unknown") == "***"


# ── Integration tests (real database) ──
#
# Regression coverage for the invite-creation 500: create_invitation previously
# used `select(func.count()).with_for_update()`, which PostgreSQL rejects
# ("FOR UPDATE is not allowed with aggregate functions"). The mocked unit tests
# above never issue real SQL, so they could not catch it. These tests run
# against the real database session and exercise the actual query path.


class TestCreateInvitationIntegration:
    """Real-DB tests for create_invitation (exercises actual SQL)."""

    async def _make_patient(self, db_session) -> User:
        patient = User(
            email=f"patient-{uuid.uuid4().hex}@integration.test",
            hashed_password="x" * 60,  # noqa: S106 -- not a real hash, test-only
            role=UserRole.DIABETIC,
        )
        db_session.add(patient)
        await db_session.commit()
        await db_session.refresh(patient)
        return patient

    async def _cleanup(self, db_session, patient_id: uuid.UUID) -> None:
        from sqlalchemy import delete

        # If the test left the transaction aborted (e.g. the pre-fix FOR UPDATE
        # error), roll back first so the deletes can run and we don't leak users.
        await db_session.rollback()
        await db_session.execute(
            delete(CaregiverInvitation).where(
                CaregiverInvitation.patient_id == patient_id
            )
        )
        await db_session.execute(delete(User).where(User.id == patient_id))
        await db_session.commit()

    @pytest.mark.asyncio
    async def test_create_invitation_succeeds_against_real_db(self, db_session):
        """A diabetic user can create an invitation (no 500 from FOR UPDATE)."""
        patient = await self._make_patient(db_session)
        try:
            invitation = await create_invitation(db_session, patient.id)

            assert invitation.id is not None
            assert invitation.token
            assert invitation.patient_id == patient.id
            assert invitation.status == InvitationStatus.PENDING.value
            assert invitation.expires_at is not None
        finally:
            await self._cleanup(db_session, patient.id)

    @pytest.mark.asyncio
    async def test_create_invitation_enforces_max_pending(self, db_session):
        """The pending-count limit still holds after the FOR UPDATE fix."""
        patient = await self._make_patient(db_session)
        try:
            for _ in range(MAX_PENDING_INVITATIONS_PER_PATIENT):
                await create_invitation(db_session, patient.id)

            with pytest.raises(ValueError, match="Maximum"):
                await create_invitation(db_session, patient.id)
        finally:
            await self._cleanup(db_session, patient.id)
