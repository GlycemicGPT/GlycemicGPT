"""Stories 8.1–8.3: Caregiver invitation, linking, permissions, and dashboard router.

Endpoints for creating/managing invitations (diabetic users),
accepting invitations (unauthenticated caregivers),
configuring per-caregiver data access permissions, and
serving permission-filtered patient data to caregivers.
"""

import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import CurrentUser, require_caregiver, require_diabetic
from src.core.security import hash_password
from src.core.units import GlucoseUnit
from src.database import get_db
from src.logging_config import get_logger
from src.models.caregiver_link import CaregiverLink
from src.models.user import User
from src.schemas.caregiver import (
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    InvitationCreateResponse,
    InvitationDetailResponse,
    InvitationListItem,
    InvitationListResponse,
    LinkedPatientResponse,
    LinkedPatientsListResponse,
)
from src.schemas.caregiver_dashboard import (
    CaregiverChatRequest,
    CaregiverChatResponse,
    CaregiverGlucoseData,
    CaregiverGlucoseHistoryReading,
    CaregiverGlucoseHistoryResponse,
    CaregiverIoBData,
    CaregiverPatientStatus,
)
from src.schemas.caregiver_permissions import (
    CaregiverPermissions,
    LinkedCaregiverItem,
    LinkedCaregiversResponse,
    PermissionsUpdateRequest,
    PermissionsUpdateResponse,
)
from src.services.caregiver import (
    accept_invitation,
    create_invitation,
    get_invitation_by_token,
    get_link_permissions,
    get_linked_caregivers,
    get_linked_patients,
    list_invitations,
    revoke_invitation,
    update_link_permissions,
)

router = APIRouter(prefix="/api/caregivers", tags=["caregivers"])
logger = get_logger(__name__)

# Frontend base URL for building invite links
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "")


def _mask_email(email: str) -> str:
    """Mask an email address for display to unauthenticated users.

    Example: 'patient@example.com' → 'p*****t@example.com'
    """
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        masked_local = local[0] + "*" * max(len(local) - 1, 1)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def _build_invite_url(request: Request, token: str) -> str:
    """Build the frontend invite URL from the current request."""
    if FRONTEND_BASE_URL:
        return f"{FRONTEND_BASE_URL.rstrip('/')}/invite/{token}"
    # Fallback: derive from request base URL
    base = str(request.base_url).rstrip("/")
    return f"{base}/invite/{token}"


@router.post(
    "/invitations",
    response_model=InvitationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_diabetic)],
)
async def create_caregiver_invitation(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> InvitationCreateResponse:
    """Create a new caregiver invitation.

    Generates a unique token that can be shared with a caregiver.
    Maximum 10 pending invitations per patient.
    """
    try:
        invitation = await create_invitation(db, current_user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return InvitationCreateResponse(
        id=invitation.id,
        token=invitation.token,
        expires_at=invitation.expires_at,
        invite_url=_build_invite_url(request, invitation.token),
    )


@router.get(
    "/invitations",
    response_model=InvitationListResponse,
    dependencies=[Depends(require_diabetic)],
)
async def list_caregiver_invitations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> InvitationListResponse:
    """List all caregiver invitations for the current patient."""
    invitations = await list_invitations(db, current_user.id)

    # Batch-resolve accepted_by emails to avoid N+1 queries
    acceptor_ids = [inv.accepted_by for inv in invitations if inv.accepted_by]
    email_map: dict[uuid.UUID, str] = {}
    if acceptor_ids:
        result = await db.execute(
            select(User.id, User.email).where(User.id.in_(acceptor_ids))
        )
        email_map = {row.id: row.email for row in result.all()}

    items = [
        InvitationListItem(
            id=inv.id,
            status=inv.status,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
            accepted_by_email=email_map.get(inv.accepted_by)
            if inv.accepted_by
            else None,
        )
        for inv in invitations
    ]

    return InvitationListResponse(invitations=items, count=len(items))


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_diabetic)],
)
async def revoke_caregiver_invitation(
    invitation_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a pending caregiver invitation."""
    try:
        result = await revoke_invitation(db, current_user.id, invitation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )


@router.get(
    "/invitations/{token}/details",
    response_model=InvitationDetailResponse,
)
async def get_invitation_details(
    token: str = Path(..., min_length=20, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> InvitationDetailResponse:
    """Get public invitation details for the acceptance page.

    No authentication required — the token acts as authorization.
    Patient email is masked for privacy.
    """
    invitation = await get_invitation_by_token(db, token)

    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )

    # Resolve patient email (masked for privacy on public endpoint)
    result = await db.execute(
        select(User.email).where(User.id == invitation.patient_id)
    )
    raw_email = result.scalar_one_or_none() or "Unknown"
    masked = _mask_email(raw_email)

    return InvitationDetailResponse(
        patient_email=masked,
        status=invitation.status,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/accept",
    response_model=AcceptInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_caregiver_invitation(
    data: AcceptInvitationRequest,
    db: AsyncSession = Depends(get_db),
) -> AcceptInvitationResponse:
    """Accept a caregiver invitation.

    Creates a new CAREGIVER account (or links existing caregiver)
    and establishes the caregiver-patient link.
    No authentication required — the token acts as authorization.
    """
    hashed_pw = hash_password(data.password)

    try:
        caregiver, _invitation = await accept_invitation(
            db, data.token, data.email, hashed_pw
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return AcceptInvitationResponse(
        message="Invitation accepted successfully",
        user_id=caregiver.id,
    )


@router.get(
    "/patients",
    response_model=LinkedPatientsListResponse,
    dependencies=[Depends(require_caregiver)],
)
async def list_linked_patients(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> LinkedPatientsListResponse:
    """List all patients linked to the current caregiver."""
    links = await get_linked_patients(db, current_user.id)

    patients = [
        LinkedPatientResponse(
            patient_id=link.patient_id,
            patient_email=link.patient.email if link.patient else "Unknown",
            linked_at=link.created_at,
        )
        for link in links
    ]

    return LinkedPatientsListResponse(patients=patients, count=len(patients))


# ── Story 8.2: Caregiver permission endpoints ──


@router.get(
    "/linked",
    response_model=LinkedCaregiversResponse,
    dependencies=[Depends(require_diabetic)],
)
async def list_linked_caregivers_endpoint(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> LinkedCaregiversResponse:
    """List all caregivers linked to the current patient, with permissions."""
    links = await get_linked_caregivers(db, current_user.id)

    caregivers = [
        LinkedCaregiverItem(
            link_id=link.id,
            caregiver_id=link.caregiver_id,
            caregiver_email=link.caregiver.email if link.caregiver else "Unknown",
            linked_at=link.created_at,
            permissions=CaregiverPermissions(
                can_view_glucose=link.can_view_glucose,
                can_view_history=link.can_view_history,
                can_view_iob=link.can_view_iob,
                can_view_ai_suggestions=link.can_view_ai_suggestions,
                can_receive_alerts=link.can_receive_alerts,
            ),
        )
        for link in links
    ]

    return LinkedCaregiversResponse(caregivers=caregivers, count=len(caregivers))


@router.get(
    "/linked/{link_id}/permissions",
    response_model=PermissionsUpdateResponse,
    dependencies=[Depends(require_diabetic)],
)
async def get_caregiver_permissions_endpoint(
    link_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PermissionsUpdateResponse:
    """Get permissions for a specific caregiver link."""
    link = await get_link_permissions(db, current_user.id, link_id)

    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Caregiver link not found",
        )

    return PermissionsUpdateResponse(
        link_id=link.id,
        permissions=CaregiverPermissions(
            can_view_glucose=link.can_view_glucose,
            can_view_history=link.can_view_history,
            can_view_iob=link.can_view_iob,
            can_view_ai_suggestions=link.can_view_ai_suggestions,
            can_receive_alerts=link.can_receive_alerts,
        ),
    )


@router.patch(
    "/linked/{link_id}/permissions",
    response_model=PermissionsUpdateResponse,
    dependencies=[Depends(require_diabetic)],
)
async def update_caregiver_permissions_endpoint(
    link_id: uuid.UUID,
    data: PermissionsUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PermissionsUpdateResponse:
    """Update permissions for a specific caregiver link.

    Only provided fields are updated; omitted fields remain unchanged.
    Changes take effect immediately.
    """
    updates = data.model_dump(exclude_unset=True)

    if not updates:
        # No fields provided — just return current state
        link = await get_link_permissions(db, current_user.id, link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Caregiver link not found",
            )
    else:
        link = await update_link_permissions(db, current_user.id, link_id, **updates)

    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Caregiver link not found",
        )

    return PermissionsUpdateResponse(
        link_id=link.id,
        permissions=CaregiverPermissions(
            can_view_glucose=link.can_view_glucose,
            can_view_history=link.can_view_history,
            can_view_iob=link.can_view_iob,
            can_view_ai_suggestions=link.can_view_ai_suggestions,
            can_receive_alerts=link.can_receive_alerts,
        ),
    )


# ── Story 8.3: Caregiver dashboard data endpoints ──

# Staleness threshold: readings older than this are marked stale
_STALE_MINUTES = 15


def _build_permissions(link: CaregiverLink) -> CaregiverPermissions:
    """Extract CaregiverPermissions from a CaregiverLink.

    Defaults to False (deny) for any missing attributes as a fail-safe.
    """
    return CaregiverPermissions(
        can_view_glucose=getattr(link, "can_view_glucose", False),
        can_view_history=getattr(link, "can_view_history", False),
        can_view_iob=getattr(link, "can_view_iob", False),
        can_view_ai_suggestions=getattr(link, "can_view_ai_suggestions", False),
        can_receive_alerts=getattr(link, "can_receive_alerts", False),
    )


async def _get_caregiver_link(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
    patient_id: uuid.UUID,
) -> CaregiverLink:
    """Look up a CaregiverLink between caregiver and patient.

    Raises HTTPException(404) if no link exists.
    """
    from sqlalchemy import and_

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not linked to your account",
        )
    return link


@router.get(
    "/patients/{patient_id}/status",
    response_model=CaregiverPatientStatus,
    dependencies=[Depends(require_caregiver)],
)
async def get_caregiver_patient_status(
    patient_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CaregiverPatientStatus:
    """Get permission-filtered patient status for caregiver dashboard.

    Returns current glucose and/or IoB data based on the caregiver's
    permission flags. The `permissions` field always shows which
    categories are enabled.
    """
    link = await _get_caregiver_link(db, current_user.id, patient_id)
    permissions = _build_permissions(link)

    # Resolve patient email
    result = await db.execute(select(User.email).where(User.id == patient_id))
    patient_email = result.scalar_one_or_none() or "Unknown"

    glucose_data: CaregiverGlucoseData | None = None
    iob_data: CaregiverIoBData | None = None
    # The PATIENT's display unit (never the caregiver's). Only meaningful when a
    # glucose value is actually returned, so it is resolved alongside the reading
    # and defaults to mg/dL otherwise.
    glucose_unit = GlucoseUnit.MGDL

    # Glucose data (if permitted)
    if permissions.can_view_glucose:
        from src.services.dexcom_sync import get_latest_glucose_reading

        reading = await get_latest_glucose_reading(db, patient_id)
        if reading is not None:
            from src.services.glucose_unit import resolve_glucose_unit

            glucose_unit = await resolve_glucose_unit(db, patient_id)
            now = datetime.now(UTC)
            delta = now - reading.reading_timestamp
            minutes_ago = int(delta.total_seconds() / 60)
            glucose_data = CaregiverGlucoseData(
                value=reading.value,
                trend=reading.trend.value
                if hasattr(reading.trend, "value")
                else str(reading.trend),
                trend_rate=reading.trend_rate,
                reading_timestamp=reading.reading_timestamp,
                minutes_ago=minutes_ago,
                is_stale=minutes_ago >= _STALE_MINUTES,
            )

    # IoB data (if permitted)
    # Note: current_iob is the decay-adjusted projected IoB, not the raw pump value
    if permissions.can_view_iob:
        from src.services.iob_projection import get_iob_projection, get_user_dia

        dia = await get_user_dia(db, patient_id)
        projection = await get_iob_projection(db, patient_id, dia_hours=dia)
        if projection is not None:
            now = datetime.now(UTC)
            delta = now - projection.confirmed_at
            minutes_since = int(delta.total_seconds() / 60)
            iob_data = CaregiverIoBData(
                current_iob=projection.projected_iob,
                projected_30min=projection.projected_30min,
                confirmed_at=projection.confirmed_at,
                is_stale=minutes_since >= _STALE_MINUTES,
            )

    return CaregiverPatientStatus(
        patient_id=patient_id,
        patient_email=patient_email,
        glucose=glucose_data,
        iob=iob_data,
        permissions=permissions,
        glucose_unit=glucose_unit,
    )


@router.get(
    "/patients/{patient_id}/glucose/history",
    response_model=CaregiverGlucoseHistoryResponse,
    dependencies=[Depends(require_caregiver)],
)
async def get_caregiver_glucose_history(
    patient_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    minutes: int = Query(default=180, ge=5, le=1440),
    limit: int = Query(default=36, ge=1, le=288),
) -> CaregiverGlucoseHistoryResponse:
    """Get glucose history for a linked patient.

    Requires the `can_view_history` permission. Returns 403 if denied.
    """
    link = await _get_caregiver_link(db, current_user.id, patient_id)

    if not getattr(link, "can_view_history", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="History access not permitted",
        )

    from src.services.dexcom_sync import get_glucose_readings

    readings = await get_glucose_readings(db, patient_id, minutes=minutes, limit=limit)

    return CaregiverGlucoseHistoryResponse(
        patient_id=patient_id,
        readings=[
            CaregiverGlucoseHistoryReading(
                value=r.value,
                trend=r.trend.value if hasattr(r.trend, "value") else str(r.trend),
                trend_rate=r.trend_rate,
                reading_timestamp=r.reading_timestamp,
            )
            for r in readings
        ],
        count=len(readings),
    )


# ── Story 8.4: Caregiver AI chat endpoint ──


@router.post(
    "/patients/{patient_id}/chat",
    response_model=CaregiverChatResponse,
    dependencies=[Depends(require_caregiver)],
)
async def caregiver_ai_chat(
    patient_id: uuid.UUID,
    data: CaregiverChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CaregiverChatResponse:
    """Ask an AI question about a linked patient's glucose data.

    Requires ``can_view_ai_suggestions`` permission. Uses the patient's
    AI provider configuration and glucose data to generate a response.
    """
    link = await _get_caregiver_link(db, current_user.id, patient_id)

    if not getattr(link, "can_view_ai_suggestions", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI suggestions access not permitted",
        )

    from src.services.telegram_chat import handle_caregiver_chat_web

    response_text = await handle_caregiver_chat_web(
        db, current_user.id, patient_id, data.message
    )

    return CaregiverChatResponse(response=response_text)
