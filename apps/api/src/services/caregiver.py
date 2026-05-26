"""Stories 8.1 & 8.2: Caregiver invitation, linking, and permission service.

Handles invitation creation, acceptance, caregiver-patient linking,
and per-caregiver data access permission management.

Note: Permission enforcement in data-access paths (Telegram caregiver
handler, escalation engine) is implemented in stories 8.3-8.6.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.caregiver_invitation import (
    CaregiverInvitation,
    InvitationStatus,
)
from src.models.caregiver_link import CaregiverLink
from src.models.user import User, UserRole

logger = get_logger(__name__)

MAX_PENDING_INVITATIONS_PER_PATIENT = 10
MAX_PATIENTS_PER_CAREGIVER = 5


async def create_invitation(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> CaregiverInvitation:
    """Create a new caregiver invitation.

    Args:
        db: Database session.
        patient_id: The diabetic user creating the invitation.

    Returns:
        The created CaregiverInvitation.

    Raises:
        ValueError: If the patient already has too many pending invitations.
    """
    # Serialize concurrent invitation creation for this patient by locking the
    # patient's user row. PostgreSQL forbids FOR UPDATE on an aggregate query
    # (SELECT count(*) ... FOR UPDATE raises ProgrammingError), so we take the
    # row lock on `users` first, then count without a lock.
    await db.execute(select(User.id).where(User.id == patient_id).with_for_update())

    result = await db.execute(
        select(func.count())
        .select_from(CaregiverInvitation)
        .where(
            and_(
                CaregiverInvitation.patient_id == patient_id,
                CaregiverInvitation.status == InvitationStatus.PENDING.value,
            )
        )
    )
    pending_count = result.scalar_one()

    if pending_count >= MAX_PENDING_INVITATIONS_PER_PATIENT:
        msg = (
            f"Maximum of {MAX_PENDING_INVITATIONS_PER_PATIENT} "
            f"pending invitations allowed"
        )
        raise ValueError(msg)

    from src.models.caregiver_invitation import _default_expiry, _generate_token

    invitation = CaregiverInvitation(
        patient_id=patient_id,
        token=_generate_token(),
        expires_at=_default_expiry(),
        status=InvitationStatus.PENDING.value,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    logger.info(
        "Created caregiver invitation",
        patient_id=str(patient_id),
        invitation_id=str(invitation.id),
    )

    return invitation


async def list_invitations(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> list[CaregiverInvitation]:
    """List all invitations for a patient, newest first.

    Also auto-expires stale PENDING invitations before returning.
    """
    await _expire_stale_invitations_for_patient(db, patient_id)

    result = await db.execute(
        select(CaregiverInvitation)
        .where(CaregiverInvitation.patient_id == patient_id)
        .order_by(CaregiverInvitation.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_invitation(
    db: AsyncSession,
    patient_id: uuid.UUID,
    invitation_id: uuid.UUID,
) -> CaregiverInvitation | None:
    """Revoke a pending invitation.

    Args:
        db: Database session.
        patient_id: Owner patient ID (for authorization).
        invitation_id: The invitation to revoke.

    Returns:
        Updated invitation, or None if not found / not owned.

    Raises:
        ValueError: If the invitation is not in PENDING status.
    """
    result = await db.execute(
        select(CaregiverInvitation).where(
            and_(
                CaregiverInvitation.id == invitation_id,
                CaregiverInvitation.patient_id == patient_id,
            )
        )
    )
    invitation = result.scalar_one_or_none()

    if invitation is None:
        return None

    if invitation.status != InvitationStatus.PENDING.value:
        msg = f"Cannot revoke invitation with status '{invitation.status}'"
        raise ValueError(msg)

    invitation.status = InvitationStatus.REVOKED.value
    await db.commit()
    await db.refresh(invitation)

    logger.info(
        "Revoked caregiver invitation",
        invitation_id=str(invitation_id),
        patient_id=str(patient_id),
    )

    return invitation


async def get_invitation_by_token(
    db: AsyncSession,
    token: str,
) -> CaregiverInvitation | None:
    """Look up an invitation by token.

    Returns None if token not found, expired, or revoked.
    Auto-expires stale PENDING invitations.
    """
    result = await db.execute(
        select(CaregiverInvitation).where(CaregiverInvitation.token == token)
    )
    invitation = result.scalar_one_or_none()

    if invitation is None:
        return None

    # Auto-expire if past expiry
    if (
        invitation.status == InvitationStatus.PENDING.value
        and invitation.expires_at < datetime.now(UTC)
    ):
        invitation.status = InvitationStatus.EXPIRED.value
        await db.commit()
        await db.refresh(invitation)

    return invitation


async def accept_invitation(
    db: AsyncSession,
    token: str,
    email: str,
    hashed_password: str,
) -> tuple[User, CaregiverInvitation]:
    """Accept an invitation: register or link the caregiver.

    If the email belongs to an existing CAREGIVER user, creates a new
    CaregiverLink. If the email is new, creates a CAREGIVER user and
    then creates the link.

    Args:
        db: Database session.
        token: Invitation token.
        email: Caregiver's email.
        hashed_password: Pre-hashed password for new user creation.

    Returns:
        Tuple of (caregiver User, updated CaregiverInvitation).

    Raises:
        ValueError: If token is invalid/expired/revoked, if email belongs
            to a non-caregiver user, or if caregiver has too many patients.
    """
    # Look up invitation with lock
    result = await db.execute(
        select(CaregiverInvitation)
        .where(CaregiverInvitation.token == token)
        .with_for_update()
    )
    invitation = result.scalar_one_or_none()

    if invitation is None:
        raise ValueError("Invalid invitation token")

    # Auto-expire if past expiry
    if (
        invitation.status == InvitationStatus.PENDING.value
        and invitation.expires_at < datetime.now(UTC)
    ):
        invitation.status = InvitationStatus.EXPIRED.value
        await db.commit()
        raise ValueError("This invitation has expired")

    if invitation.status != InvitationStatus.PENDING.value:
        raise ValueError(
            f"This invitation is no longer valid (status: {invitation.status})"
        )

    # Prevent self-linking: caregiver email must not belong to the patient
    email_lower = email.lower()
    result = await db.execute(select(User).where(User.email == email_lower))
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        if existing_user.id == invitation.patient_id:
            raise ValueError("You cannot accept your own invitation")
        if existing_user.role == UserRole.CAREGIVER:
            caregiver = existing_user
        else:
            raise ValueError(
                "An account with this email already exists with a different role"
            )
    else:
        # Create new CAREGIVER user
        caregiver = User(
            email=email_lower,
            hashed_password=hashed_password,
            role=UserRole.CAREGIVER,
            is_active=True,
            email_verified=False,
            disclaimer_acknowledged=False,
        )
        db.add(caregiver)
        await db.flush()  # Get caregiver.id

    # Check max patients per caregiver
    link_count_result = await db.execute(
        select(func.count())
        .select_from(CaregiverLink)
        .where(CaregiverLink.caregiver_id == caregiver.id)
    )
    link_count = link_count_result.scalar_one()

    if link_count >= MAX_PATIENTS_PER_CAREGIVER:
        await db.rollback()
        raise ValueError(
            f"Caregiver already linked to maximum of "
            f"{MAX_PATIENTS_PER_CAREGIVER} patients"
        )

    # Create the CaregiverLink
    link = CaregiverLink(
        caregiver_id=caregiver.id,
        patient_id=invitation.patient_id,
    )
    db.add(link)

    # Mark invitation as accepted
    now = datetime.now(UTC)
    invitation.status = InvitationStatus.ACCEPTED.value
    invitation.accepted_by = caregiver.id
    invitation.accepted_at = now

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ValueError("This caregiver is already linked to this patient")

    await db.refresh(caregiver)
    await db.refresh(invitation)

    logger.info(
        "Caregiver invitation accepted",
        invitation_id=str(invitation.id),
        caregiver_id=str(caregiver.id),
        patient_id=str(invitation.patient_id),
    )

    return caregiver, invitation


async def get_linked_patients(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
) -> list[CaregiverLink]:
    """Get all patients linked to a caregiver.

    Eagerly loads the patient relationship.
    """
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(CaregiverLink)
        .where(CaregiverLink.caregiver_id == caregiver_id)
        .options(selectinload(CaregiverLink.patient))
        .order_by(CaregiverLink.created_at)
    )
    return list(result.scalars().all())


# ── Story 8.2: Permission management ──

# Valid permission field names on CaregiverLink
PERMISSION_FIELDS = frozenset(
    {
        "can_view_glucose",
        "can_view_history",
        "can_view_iob",
        "can_view_ai_suggestions",
        "can_receive_alerts",
    }
)


async def get_linked_caregivers(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> list[CaregiverLink]:
    """Get all caregivers linked to a patient.

    Eagerly loads the caregiver relationship for email access.
    """
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(CaregiverLink)
        .where(CaregiverLink.patient_id == patient_id)
        .options(selectinload(CaregiverLink.caregiver))
        .order_by(CaregiverLink.created_at)
    )
    return list(result.scalars().all())


async def get_link_permissions(
    db: AsyncSession,
    patient_id: uuid.UUID,
    link_id: uuid.UUID,
) -> CaregiverLink | None:
    """Get a single CaregiverLink by ID, verifying patient ownership.

    Returns None if not found or not owned by this patient.
    """
    result = await db.execute(
        select(CaregiverLink).where(
            and_(
                CaregiverLink.id == link_id,
                CaregiverLink.patient_id == patient_id,
            )
        )
    )
    return result.scalar_one_or_none()


async def update_link_permissions(
    db: AsyncSession,
    patient_id: uuid.UUID,
    link_id: uuid.UUID,
    **kwargs: bool,
) -> CaregiverLink | None:
    """Update permission flags on a CaregiverLink.

    Only valid permission field names are applied. Returns None
    if the link is not found or not owned by this patient.
    """
    link = await get_link_permissions(db, patient_id, link_id)
    if link is None:
        return None

    changed = False
    for field, value in kwargs.items():
        if field in PERMISSION_FIELDS and value is not None:
            if not isinstance(value, bool):
                logger.warning(
                    "Non-boolean permission value ignored",
                    field=field,
                    value_type=type(value).__name__,
                )
                continue
            setattr(link, field, value)
            changed = True

    if changed:
        await db.commit()
        await db.refresh(link)

        logger.info(
            "Updated caregiver permissions",
            link_id=str(link_id),
            patient_id=str(patient_id),
            caregiver_id=str(link.caregiver_id),
            changes={
                k: v
                for k, v in kwargs.items()
                if k in PERMISSION_FIELDS and v is not None
            },
        )

    return link


async def check_caregiver_permission(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
    patient_id: uuid.UUID,
    permission: str,
) -> bool:
    """Check whether a caregiver has a specific permission for a patient.

    This function is called by stories 8.3-8.6 to enforce data access
    permissions in Telegram caregiver handler and escalation engine.

    Args:
        db: Database session.
        caregiver_id: The caregiver's user ID.
        patient_id: The patient's user ID.
        permission: One of the PERMISSION_FIELDS values.

    Returns:
        True if the permission is granted, False otherwise.
    """
    if permission not in PERMISSION_FIELDS:
        logger.warning(
            "Invalid permission name requested",
            permission=permission,
            caregiver_id=str(caregiver_id),
            patient_id=str(patient_id),
        )
        return False

    result = await db.execute(
        select(CaregiverLink).where(
            and_(
                CaregiverLink.caregiver_id == caregiver_id,
                CaregiverLink.patient_id == patient_id,
            )
        )
    )
    link = result.scalar_one_or_none()

    if link is None:
        return False

    return bool(getattr(link, permission, False))


async def _expire_stale_invitations_for_patient(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> int:
    """Expire PENDING invitations past their expiry for a specific patient.

    Returns the number of invitations expired.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(CaregiverInvitation).where(
            and_(
                CaregiverInvitation.patient_id == patient_id,
                CaregiverInvitation.status == InvitationStatus.PENDING.value,
                CaregiverInvitation.expires_at < now,
            )
        )
    )
    stale = list(result.scalars().all())

    for inv in stale:
        inv.status = InvitationStatus.EXPIRED.value

    if stale:
        await db.commit()

    return len(stale)


async def expire_stale_invitations(db: AsyncSession) -> int:
    """Bulk expire all PENDING invitations past their expiry.

    Returns the number of invitations expired.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(CaregiverInvitation).where(
            and_(
                CaregiverInvitation.status == InvitationStatus.PENDING.value,
                CaregiverInvitation.expires_at < now,
            )
        )
    )
    stale = list(result.scalars().all())

    for inv in stale:
        inv.status = InvitationStatus.EXPIRED.value

    if stale:
        await db.commit()

    return len(stale)
