"""Forecast picker read service (Story 43.12 PR 3).

Pure functions + thin DB queries that compose the `GET
/api/integrations/forecast` response. Read-only end-to-end: no writes
to `forecast_snapshots`, no Nightscout client calls. The mutation
path (`PUT .../source`) lives in the router as a single UPSERT.

Key responsibilities:

1. `get_or_create_forecast_settings`: lazy-creates the per-user
   preference row on first read so the API can always return a
   sensible default (`'auto'`).
2. `get_available_sources`: returns the engines that emitted at
   least one forecast in the last 24h. Drives the picker dropdown.
3. `resolve_effective_source`: pure function -- given a preference
   and the available list, what does the chart actually draw? Table
   of cases in the docstring; matches design doc Section 3 exactly.
4. `get_latest_forecast`: returns the latest snapshot for a given
   source, suppressed when older than the freshness threshold so a
   stale dotted line doesn't lie about t=0.

`AVAILABLE_SOURCES_WINDOW` and `FORECAST_FRESHNESS_THRESHOLD` are
intentionally different time bands:
- 24h for available_sources: lets a user who took a phone break
  yesterday still see their loop in the dropdown.
- 30min for the returned forecast: a forecast's t=0 is set when the
  source loop emitted it; rendering a 30-min-old dotted line
  starting at "30 min ago" would misalign with the chart's "now".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.forecast_settings import ForecastSettings
from src.models.forecast_snapshot import ForecastSnapshot
from src.schemas.forecast import ForecastEngine, ForecastSourcePreference

# Beyond this age, a source is considered "gone silent" and is dropped
# from the picker dropdown. 24h accommodates ordinary phone-off-overnight
# patterns without keeping ancient stale sources around.
AVAILABLE_SOURCES_WINDOW = timedelta(hours=24)

# Beyond this age, the returned `forecast` field is suppressed even
# when an effective source resolves. Forecasts have a lookahead
# horizon (Loop ~6h, AAPS ~3h, oref0 ~30min); rendering a 30-min-old
# dotted line whose t=0 was 30 min ago would visibly misalign with
# the actual reading at "now". The picker dropdown stays unaffected
# -- the source is still in `available_sources` so the user knows
# it's online, even if the latest specific forecast is too stale.
FORECAST_FRESHNESS_THRESHOLD = timedelta(minutes=30)


# ---------------------------------------------------------------------------
# Preference (forecast_settings) helpers
# ---------------------------------------------------------------------------


async def read_forecast_preference(
    db: AsyncSession, user_id: uuid.UUID
) -> ForecastSourcePreference:
    """Read-only path for the GET endpoint -- never writes.

    Returns `'auto'` for users without a stored row. This avoids the
    REST anti-pattern of a GET that has side effects: a brand-new
    user's first dashboard load no longer INSERTs a settings row. The
    row gets persisted on the first PUT instead, where it belongs.

    Falls back to `'auto'` (not raising) so the GET path can always
    return a sensible default, even if a future schema migration is
    in flight.
    """
    result = await db.execute(
        select(ForecastSettings.source).where(ForecastSettings.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return "auto"
    # The CHECK constraint bounds row to the Literal set; type-narrow.
    return row  # type: ignore[return-value]


async def get_or_create_forecast_settings(
    db: AsyncSession, user_id: uuid.UUID
) -> ForecastSettings:
    """Fetch the user's settings row, creating with default `'auto'`
    on first access.

    Handles the race where two concurrent first-reads both miss the
    row and try to insert: the UNIQUE constraint on `user_id` lets
    the loser fall back to a SELECT.

    The INSERT runs inside a SAVEPOINT (`session.begin_nested()`) so
    a losing-race IntegrityError rolls back ONLY the failed INSERT --
    NOT the entire outer transaction. This is critical for callers
    that may have already done other work in the same session (e.g.,
    `set_forecast_source` mutates an existing row before flush; a
    naive `db.rollback()` would discard that mutation alongside the
    failed insert).
    """
    existing = await db.execute(
        select(ForecastSettings).where(ForecastSettings.user_id == user_id)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    new_row = ForecastSettings(user_id=user_id, source="auto")
    try:
        async with db.begin_nested():
            db.add(new_row)
            await db.flush()
        return new_row
    except IntegrityError:
        # SAVEPOINT auto-rolled back the failed INSERT only. The
        # outer transaction is intact. Pull the winning row.
        retry = await db.execute(
            select(ForecastSettings).where(ForecastSettings.user_id == user_id)
        )
        return retry.scalar_one()


async def set_forecast_source(
    db: AsyncSession, user_id: uuid.UUID, source: ForecastSourcePreference
) -> ForecastSettings:
    """Persist the user's pick. UPSERT semantics via
    `get_or_create_forecast_settings`.

    The `source` parameter is typed `Literal` so the router's Pydantic
    body validation rejects unknown values at the API boundary; this
    function trusts the caller's typing and does not re-validate
    against the CHECK constraint -- the DB is the final guard if
    invariants somehow drift.
    """
    settings = await get_or_create_forecast_settings(db, user_id)
    settings.source = source
    await db.flush()
    return settings


# ---------------------------------------------------------------------------
# Source availability (forecast_snapshots projection)
# ---------------------------------------------------------------------------


async def get_available_sources(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> list[ForecastEngine]:
    """Distinct `source_engine` values for this user in the last 24h.

    Sorted alphabetically for a stable picker dropdown ordering --
    user shouldn't see entries reshuffle between renders.

    The `now` parameter is injected for deterministic testing; in
    production callers pass `None` and the function uses
    `datetime.now(UTC)`.
    """
    reference_now = now if now is not None else datetime.now(UTC)
    cutoff = reference_now - AVAILABLE_SOURCES_WINDOW

    stmt = (
        select(ForecastSnapshot.source_engine)
        .where(
            ForecastSnapshot.user_id == user_id,
            ForecastSnapshot.issued_at >= cutoff,
        )
        .distinct()
        .order_by(ForecastSnapshot.source_engine.asc())
    )
    rows = await db.execute(stmt)
    return list(rows.scalars().all())  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Effective-source resolution (pure function, table-driven tests)
# ---------------------------------------------------------------------------


def resolve_effective_source(
    preference: ForecastSourcePreference,
    available: list[ForecastEngine],
) -> ForecastEngine | None:
    """Map (preference, available_sources) -> the engine the chart
    should actually draw, or None.

    Resolution table (matches design doc Section 3):

    | preference          | available                  | result      |
    | ------------------- | -------------------------- | ----------- |
    | 'none'              | (any)                      | None        |
    | 'auto'              | []                         | None        |
    | 'auto'              | [single]                   | that engine |
    | 'auto'              | [multiple]                 | None        |
    | specific engine     | contains engine            | that engine |
    | specific engine     | doesn't contain engine     | None        |

    The "multiple sources under 'auto' -> None" rule is the explicit
    no-silent-guessing decision from the design doc: a user with both
    Loop and AAPS gets the dropdown surfaced, not an arbitrary pick.

    The "specific but missing -> None" rule (no fallback) is the
    honest "your X stopped publishing" stance: we never silently
    substitute Loop for AAPS because the user asked for AAPS.
    """
    if preference == "none":
        return None
    if preference == "auto":
        if len(available) == 1:
            return available[0]
        return None
    # Specific engine: only resolves if it's still publishing.
    if preference in available:
        return preference  # type: ignore[return-value]
    return None


# ---------------------------------------------------------------------------
# Latest-forecast retrieval (per source)
# ---------------------------------------------------------------------------


async def get_latest_forecast(
    db: AsyncSession,
    user_id: uuid.UUID,
    source_engine: ForecastEngine,
    *,
    now: datetime | None = None,
) -> ForecastSnapshot | None:
    """Latest `forecast_snapshots` row for the user + source, or None
    when the latest is older than `FORECAST_FRESHNESS_THRESHOLD`.

    Ordered by `issued_at` DESC -- the engine's own clock at emit
    time, NOT `received_at`. A backfilled snapshot from a one-hour-
    ago devicestatus must not outrank a live one just because it was
    synced to our DB more recently.

    Returns None (not raises) when no row exists or the only row is
    stale; the caller folds this directly into the response's nullable
    `forecast` field.
    """
    reference_now = now if now is not None else datetime.now(UTC)

    stmt = (
        select(ForecastSnapshot)
        .where(
            ForecastSnapshot.user_id == user_id,
            ForecastSnapshot.source_engine == source_engine,
        )
        .order_by(ForecastSnapshot.issued_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None

    # Aware datetimes only -- the column is TIMESTAMPTZ; this guard
    # is a safety net for any future code path that bypasses the
    # column's default.
    issued = row.issued_at
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=UTC)

    if reference_now - issued > FORECAST_FRESHNESS_THRESHOLD:
        return None
    return row
