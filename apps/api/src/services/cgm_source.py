"""Cross-source CGM roles + primary-source resolution (Story 43.10).

A user can have more than one CGM-providing integration feeding
``glucose_readings`` -- e.g. Dexcom Share AND a Loop-via-Nightscout
connection that reads the same Dexcom sensor and reposts it. Without a
preference the same physical reading lands twice (different ``source``
strings) and doubles AGP / TIR / CGM-summary.

Each CGM source carries a ``cgm_role`` (``primary`` / ``secondary`` /
``off``) on its own row -- on ``IntegrationCredential`` for Dexcom and on
``NightscoutConnection`` for a Nightscout connection. The glucose read
endpoints exclude ``secondary`` / ``off`` source strings by default
(``?include_secondary=true`` re-includes ``secondary``), so only the
primary source drives widgets while the others stay queryable for audit.

A source is identified everywhere by its ``glucose_readings.source``
string: ``"dexcom"`` for the Dexcom integration and
``"nightscout:<connection_id>"`` for a Nightscout connection.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.integration import (
    IntegrationCredential,
    IntegrationType,
)
from src.models.nightscout_connection import NightscoutConnection

CGM_ROLE_PRIMARY = "primary"
CGM_ROLE_SECONDARY = "secondary"
CGM_ROLE_OFF = "off"
VALID_CGM_ROLES = frozenset({CGM_ROLE_PRIMARY, CGM_ROLE_SECONDARY, CGM_ROLE_OFF})

_DEXCOM_SOURCE = "dexcom"
_NS_SOURCE_PREFIX = "nightscout:"


@dataclass(frozen=True)
class CgmSource:
    """A CGM-providing integration the user has configured."""

    source: str  # glucose_readings.source string -- the stable key
    label: str  # human-readable name for the picker
    role: str  # cgm_role
    kind: str  # "dexcom" | "nightscout"


async def list_cgm_sources(db: AsyncSession, user_id: uuid.UUID) -> list[CgmSource]:
    """List the user's CGM-providing integrations (Dexcom + Nightscout).

    Pump-only integrations (Tandem) are excluded -- they don't write
    ``glucose_readings``. Order is stable: Dexcom first, then Nightscout
    connections by creation order.
    """
    sources: list[CgmSource] = []

    dexcom = (
        await db.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.user_id == user_id,
                IntegrationCredential.integration_type == IntegrationType.DEXCOM,
            )
        )
    ).scalar_one_or_none()
    if dexcom is not None:
        sources.append(
            CgmSource(
                source=_DEXCOM_SOURCE,
                label="Dexcom",
                role=dexcom.cgm_role,
                kind="dexcom",
            )
        )

    ns_conns = (
        (
            await db.execute(
                select(NightscoutConnection)
                .where(
                    NightscoutConnection.user_id == user_id,
                    NightscoutConnection.is_active.is_(True),
                )
                .order_by(NightscoutConnection.created_at)
            )
        )
        .scalars()
        .all()
    )
    for conn in ns_conns:
        sources.append(
            CgmSource(
                source=f"{_NS_SOURCE_PREFIX}{conn.id}",
                label=conn.name,
                role=conn.cgm_role,
                kind="nightscout",
            )
        )

    return sources


async def get_excluded_cgm_sources(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_secondary: bool = False,
) -> list[str]:
    """Return ``source`` strings to exclude from default glucose widgets.

    ``off`` sources are always excluded; ``secondary`` sources are excluded
    unless ``include_secondary`` is set. A user with zero or one CGM source
    yields an empty list (nothing to exclude), so single-source users are
    never filtered -- the dedupe only takes effect once a second source is
    demoted to secondary/off.
    """
    excluded: list[str] = []
    for src in await list_cgm_sources(db, user_id):
        if src.role == CGM_ROLE_OFF or (
            src.role == CGM_ROLE_SECONDARY and not include_secondary
        ):
            excluded.append(src.source)
    return excluded


async def has_primary_cgm(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the user already has a CGM source marked ``primary``."""
    return any(s.role == CGM_ROLE_PRIMARY for s in await list_cgm_sources(db, user_id))


async def default_cgm_role_for_new_source(
    db: AsyncSession, user_id: uuid.UUID
) -> str:
    """Role to assign a NEW CGM source: primary iff the user has none yet.

    Call before inserting the new row so it doesn't count itself.
    """
    return CGM_ROLE_SECONDARY if await has_primary_cgm(db, user_id) else CGM_ROLE_PRIMARY


async def set_primary_cgm_source(
    db: AsyncSession, user_id: uuid.UUID, source: str
) -> bool:
    """Promote ``source`` to primary and demote every other CGM source.

    Atomic across the user's CGM sources (single flush, caller commits).
    Returns ``False`` if ``source`` isn't one of the user's CGM sources.
    """
    known = {s.source for s in await list_cgm_sources(db, user_id)}
    if source not in known:
        return False

    # Demote all, then promote the chosen one -- single source of truth, no
    # window where two rows are primary.
    dexcom = (
        await db.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.user_id == user_id,
                IntegrationCredential.integration_type == IntegrationType.DEXCOM,
            )
        )
    ).scalar_one_or_none()
    if dexcom is not None:
        dexcom.cgm_role = (
            CGM_ROLE_PRIMARY if source == _DEXCOM_SOURCE else CGM_ROLE_SECONDARY
        )

    ns_conns = (
        (
            await db.execute(
                select(NightscoutConnection).where(
                    NightscoutConnection.user_id == user_id,
                    NightscoutConnection.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for conn in ns_conns:
        conn.cgm_role = (
            CGM_ROLE_PRIMARY
            if source == f"{_NS_SOURCE_PREFIX}{conn.id}"
            else CGM_ROLE_SECONDARY
        )

    await db.flush()
    return True
