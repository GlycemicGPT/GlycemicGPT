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

Scope: this story covers Dexcom + Nightscout (the two CGM feeds named in
the story). Other CGM-writing integrations added later (Glooko cloud,
Medtronic Connect) keep their own state tables without a ``cgm_role`` and
are therefore not yet role-managed -- their readings are additive, never
hidden. Extending dedupe to them is a follow-up (needs a ``cgm_role`` on
those tables + picker entries).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.glucose import GlucoseReading
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)
from src.models.nightscout_connection import NightscoutConnection

CGM_ROLE_PRIMARY = "primary"
CGM_ROLE_SECONDARY = "secondary"
# Reserved third state: a source explicitly disabled by the user. It is
# permitted by the DB CHECK constraint and honored by the exclusion filter
# (always excluded when a primary exists), but this story's picker only
# toggles primary/secondary -- "off" is settable by a future UI / manual op.
CGM_ROLE_OFF = "off"

DEXCOM_SOURCE = "dexcom"
_NS_SOURCE_PREFIX = "nightscout:"


def nightscout_source(connection_id: uuid.UUID | str) -> str:
    """Canonical ``glucose_readings.source`` string for a NS connection.

    Mirrors the Nightscout translator's ``_build_source``; a pinning test
    keeps the two in sync so the dedupe filter never silently stops
    matching real rows if the format changes.
    """
    return f"{_NS_SOURCE_PREFIX}{connection_id}"


def glucose_source_exclusion_clause(excluded: list[str] | None) -> list:
    """SQLAlchemy WHERE fragment that drops the excluded CGM sources.

    Returns an empty list when there's nothing to exclude so callers can
    splat it unconditionally (`*glucose_source_exclusion_clause(excluded)`)
    without emitting a degenerate `source NOT IN ()`.
    """
    if not excluded:
        return []
    return [GlucoseReading.source.notin_(excluded)]


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

    # Only a CONNECTED Dexcom counts as an active CGM source -- mirrors the
    # `is_active` filter on Nightscout connections. An errored / disconnected
    # Dexcom must not occupy the primary slot and block a working secondary
    # (the dashboard would go dark while the secondary keeps syncing).
    dexcom = (
        await db.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.user_id == user_id,
                IntegrationCredential.integration_type == IntegrationType.DEXCOM,
                IntegrationCredential.status == IntegrationStatus.CONNECTED,
            )
        )
    ).scalar_one_or_none()
    if dexcom is not None:
        sources.append(
            CgmSource(
                source=DEXCOM_SOURCE,
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
                source=nightscout_source(conn.id),
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

    Safety invariant: if NO source is currently ``primary`` (e.g. the user
    disconnected their primary and only a secondary survives, or a soft-
    deleted primary left no active winner) we exclude NOTHING. Hiding every
    secondary while no primary drives the widgets would blank the dashboard
    even though a working CGM is still syncing -- showing the survivor is
    always safer than going dark.
    """
    sources = await list_cgm_sources(db, user_id)
    if not any(s.role == CGM_ROLE_PRIMARY for s in sources):
        return []
    excluded: list[str] = []
    for src in sources:
        if src.role == CGM_ROLE_OFF or (
            src.role == CGM_ROLE_SECONDARY and not include_secondary
        ):
            excluded.append(src.source)
    return excluded


async def has_primary_cgm(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the user already has a CGM source marked ``primary``."""
    return any(s.role == CGM_ROLE_PRIMARY for s in await list_cgm_sources(db, user_id))


async def default_cgm_role_for_new_source(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Role to assign a NEW CGM source: primary iff the user has none yet.

    Call before inserting the new row so it doesn't count itself.

    This is a read-then-write, so two concurrent source-creation requests can
    both observe "no primary" and both persist ``primary``. That race is
    deliberately tolerated because it is *fail-safe*: ``get_excluded_cgm_sources``
    only excludes secondaries when a primary exists, and with two primaries
    (and no secondary) the exclusion set is empty -- both sources simply
    display, so no glucose is ever wrongly hidden. The picker lets the user
    resolve to a single primary on first use. A hard guarantee would need a
    per-user advisory lock spanning role-selection + insert (the insert happens
    in the caller); not worth the contention for a benign, rare race.
    """
    return (
        CGM_ROLE_SECONDARY if await has_primary_cgm(db, user_id) else CGM_ROLE_PRIMARY
    )


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
    # window where two rows are primary. `chosen_found` makes the return
    # value reflect what actually got promoted rather than trusting the
    # upstream `known` membership check alone.
    chosen_found = False
    dexcom = (
        await db.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.user_id == user_id,
                IntegrationCredential.integration_type == IntegrationType.DEXCOM,
            )
        )
    ).scalar_one_or_none()
    if dexcom is not None:
        is_chosen = source == DEXCOM_SOURCE
        dexcom.cgm_role = _demote_unless_chosen(dexcom.cgm_role, is_chosen)
        chosen_found = chosen_found or is_chosen

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
        is_chosen = source == nightscout_source(conn.id)
        conn.cgm_role = _demote_unless_chosen(conn.cgm_role, is_chosen)
        chosen_found = chosen_found or is_chosen

    await db.flush()
    return chosen_found


def _demote_unless_chosen(current_role: str, is_chosen: bool) -> str:
    """Resolve a source's role during a primary switch.

    The chosen source becomes ``primary``. Others are demoted to
    ``secondary`` -- except a source the user explicitly turned ``off``,
    which stays off (switching the primary must not silently re-enable a
    disabled source).
    """
    if is_chosen:
        return CGM_ROLE_PRIMARY
    if current_role == CGM_ROLE_OFF:
        return CGM_ROLE_OFF
    return CGM_ROLE_SECONDARY
