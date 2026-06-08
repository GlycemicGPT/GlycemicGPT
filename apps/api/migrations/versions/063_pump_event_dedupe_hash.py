"""Cross-source pump-event dedupe hash (Story 43.11).

Adds ``pump_events.dedupe_hash`` -- a coarse content hash that collapses
the same physical bolus / basal change when it is reported by two
integrations (e.g. Tandem cloud sync + a Loop-via-Nightscout connection
describing the same pump). New writes populate it via
``compute_pump_event_dedupe_hash``; a partial unique index on
``(user_id, dedupe_hash) WHERE dedupe_hash IS NOT NULL`` enforces the
collapse through ``ON CONFLICT DO NOTHING``.

This migration backfills hashes for existing insulin-bearing rows using
the *same* formula as the application helper (inlined here so the
migration is self-contained). Rows whose hash would collide with an
already-hashed row are deliberately left NULL: the dedupe is
forward-looking, so we keep historical duplicates rather than dropping
data, and leaving collisions NULL also lets the unique index build
cleanly.

Revision ID: 063_pump_event_dedupe_hash
Revises: 062_glooko_consent_ack
Create Date: 2026-06-08
"""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "063_pump_event_dedupe_hash"
down_revision: str | None = "062_glooko_consent_ack"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIT_QUANTUM = Decimal("0.1")
_TIME_BUCKET_SECONDS = 30
_BACKFILL_BATCH = 1000


def _round_to_bucket(ts: datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    epoch = Decimal(str(ts.timestamp()))
    buckets = (epoch / _TIME_BUCKET_SECONDS).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(buckets) * _TIME_BUCKET_SECONDS


def _dedupe_hash(
    user_id: object,
    event_type: str,
    event_timestamp: datetime,
    units: float | None,
    duration_minutes: int | None,
) -> str | None:
    """Inlined copy of ``compute_pump_event_dedupe_hash`` (kept in sync)."""
    if units is None:
        return None
    ts_bucket = _round_to_bucket(event_timestamp)
    units_q = Decimal(str(units)).quantize(_UNIT_QUANTUM, rounding=ROUND_HALF_UP)
    duration = duration_minutes or 0
    payload = f"{user_id}|{event_type}|{ts_bucket}|{units_q}|{duration}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.add_column(
        "pump_events",
        sa.Column("dedupe_hash", sa.Text(), nullable=True),
    )

    bind = op.get_bind()
    # Backfill insulin-bearing rows. Order by (user_id, received_at, id) so
    # the earliest-stored row of any pre-existing duplicate group keeps the
    # hash and later duplicates stay NULL (first-writer-wins, matching the
    # runtime ON CONFLICT DO NOTHING semantics).
    select_stmt = sa.text(
        """
        SELECT id, user_id, event_type, event_timestamp, units, duration_minutes
        FROM pump_events
        WHERE units IS NOT NULL
        ORDER BY user_id, received_at, id
        """
    )
    update_stmt = sa.text("UPDATE pump_events SET dedupe_hash = :hash WHERE id = :id")

    seen: set[tuple] = set()
    pending: list[dict] = []
    # stream_results bounds client-side memory to the server cursor rather
    # than materializing every insulin-bearing row; the `seen` set and the
    # batched writes are the only unbounded buffers, both modest.
    result = bind.execution_options(stream_results=True).execute(select_stmt)
    for row in result:
        h = _dedupe_hash(
            row.user_id,
            row.event_type,
            row.event_timestamp,
            row.units,
            row.duration_minutes,
        )
        if h is None:
            continue
        key = (row.user_id, h)
        if key in seen:
            # Pre-existing cross-source duplicate -- leave NULL so the
            # unique index can build and historical data is preserved.
            continue
        seen.add(key)
        pending.append({"id": row.id, "hash": h})
        if len(pending) >= _BACKFILL_BATCH:
            bind.execute(update_stmt, pending)
            pending = []
    if pending:
        bind.execute(update_stmt, pending)

    # Built in-transaction (not CONCURRENTLY) to match every other index in
    # this migration tree and keep the backfill + index atomic. CONCURRENTLY
    # cannot run inside Alembic's transactional migration; if pump_events
    # grows large enough that the SHARE lock during the build becomes a
    # write-availability concern, split this into a separate non-transactional
    # CONCURRENTLY step then.
    op.create_index(
        "ix_pump_events_user_dedupe_hash",
        "pump_events",
        ["user_id", "dedupe_hash"],
        unique=True,
        postgresql_where=sa.text("dedupe_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pump_events_user_dedupe_hash",
        table_name="pump_events",
    )
    op.drop_column("pump_events", "dedupe_hash")
