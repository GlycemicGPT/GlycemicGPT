"""Forecast snapshots + evaluation pairs (Story 43.12 PR 1).

Adds the storage layer for closed-loop forecast data. PR #572's
translator captures each Nightscout devicestatus payload verbatim
into `device_status_snapshots.{loop_subtree_json, openaps_subtree_json}`
and nothing currently reads from those JSON columns -- the forecast
arrays sit unused.

This migration introduces a normalized table the translator writes
to on each devicestatus fetch when a forecast is present. Chart
overlay, AI context, and a future calibration / training-signal
pipeline all read from the same shape.

See `_bmad-output/planning-artifacts/story-43.12-forecast-overlay-design.md`
for the full design discussion (why a separate table vs JSON-extract
on read; why JSONB curves vs typed columns; why per-user picker
instead of per-connection toggle).

`forecast_evaluations` lands empty here. The scoring job that
populates it is deferred to a follow-up. Schema cost is essentially
zero (empty table) but having it in place now means when the future
GlycemicGPT prediction engine team starts work, they have a labelled
dataset waiting -- not a year of un-captured forecasts to lament.

Revision ID: 055_forecast_snapshots
Revises: 054_ns_entry_object_id_cursor
Create Date: 2026-05-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "055_forecast_snapshots"
down_revision = "054_ns_entry_object_id_cursor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable so non-NS sources can attach rows by source_engine
        # alone (future direct-integration paths, our own engine).
        sa.Column(
            "nightscout_connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nightscout_connections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # 'loop' | 'aaps' | 'trio' | 'oref0' | 'iaps' | 'glycemicgpt'.
        # Free-form text rather than an enum to absorb the iAPS / Trio
        # variant landscape without schema changes; the read endpoint
        # validates the set it knows about.
        sa.Column("source_engine", sa.Text(), nullable=False),
        # Bounded set. Adding a new engine is a one-line migration; the
        # cost of catching translator typos (`"AAPS"` vs `"aaps"`) at
        # the DB boundary is worth it.
        sa.CheckConstraint(
            "source_engine IN ('loop','aaps','trio','oref0','iaps','glycemicgpt')",
            name="ck_forecast_source_engine_known",
        ),
        # Denormalized from device_status_snapshots.source_uploader so
        # the forecast row is self-sufficient for chart rendering
        # without a join.
        sa.Column("source_uploader", sa.Text(), nullable=True),
        # When the engine *issued* the forecast (its internal clock).
        # For Loop this is `loop_subtree_json.timestamp`; for AAPS it's
        # the `suggested.deliverAt`; for our engine it'll be wall clock
        # at compute time. NOT when we ingested it (see `received_at`).
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        # t=0 on the chart for this forecast. For most sources ==
        # issued_at; for Loop it's `predicted.startDate` which can lag
        # the devicestatus timestamp by a cycle. The chart anchors the
        # dotted line at start_at, not issued_at.
        sa.Column(
            "start_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("step_minutes", sa.Integer(), nullable=False),
        sa.Column("horizon_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "step_minutes > 0 AND horizon_minutes > 0",
            name="ck_forecast_step_horizon_positive",
        ),
        # JSONB shape:
        #   {
        #     "IOB":  [120, 122, 125, ...],
        #     "COB":  [120, 124, 130, ...],   // optional
        #     "UAM":  [...],                  // optional
        #     "ZT":   [...]                   // optional
        #   }
        # Loop (single curve): {"main": [...]}.
        sa.Column(
            "curves_mgdl_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        # Which key in `curves_mgdl_json` the source's UI defaults to
        # drawing. Loop -> "main"; AAPS/Trio/oref0 -> "IOB" when
        # present, else first available. Computed at translate time so
        # the chart doesn't have to re-derive on every render.
        sa.Column(
            "default_curve_name",
            sa.Text(),
            nullable=False,
        ),
        # The chart will KeyError on render if these drift. Pin the
        # invariant at the DB boundary so a buggy translator can't land
        # a row the read path can't display.
        sa.CheckConstraint(
            "curves_mgdl_json ? default_curve_name",
            name="ck_forecast_default_curve_in_curves",
        ),
        # Idempotency key. For NS-imported rows this is the
        # devicestatus `_id` (same value used on
        # `device_status_snapshots.ns_id`). For engine outputs it's a
        # UUID we mint. Lets re-translating the same devicestatus
        # upsert in place rather than duplicating.
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "char_length(dedupe_key) BETWEEN 1 AND 128",
            name="ck_forecast_dedupe_key_length",
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "source_engine",
            "dedupe_key",
            name="uq_forecast_snapshots_source_dedupe",
        ),
    )
    op.create_index(
        "ix_forecast_user_issued",
        "forecast_snapshots",
        ["user_id", sa.text("issued_at DESC")],
    )
    # Lets us answer "what does this user's chart need right now"
    # cheaply per-source. Same indexing strategy as our other
    # source-attributed time-series.
    op.create_index(
        "ix_forecast_user_source_issued",
        "forecast_snapshots",
        ["user_id", "source_engine", sa.text("issued_at DESC")],
    )

    # ------------------------------------------------------------------
    # `forecast_evaluations` lands empty. The scoring job that pairs
    # each forecast point against the actual CGM reading at the
    # matching horizon time is deferred to a follow-up. See design
    # doc Section 5.2 for the eventual job semantics.
    # ------------------------------------------------------------------
    op.create_table(
        "forecast_evaluations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "forecast_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("forecast_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Minutes past `start_at`. e.g. step_minutes=5 means rows
        # at offsets 0, 5, 10, 15, ... up to horizon_minutes.
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
        # A negative offset would mean a forecast point *before* the
        # forecast was issued -- nonsense, and would corrupt MAE /
        # coverage rollups. Pin at the DB boundary so a buggy scoring
        # job can't quietly land bad data.
        sa.CheckConstraint(
            "offset_minutes >= 0",
            name="ck_forecast_eval_offset_nonnegative",
        ),
        sa.Column("predicted_mgdl", sa.Float(), nullable=False),
        # NULL when no CGM reading landed within the tolerance window
        # (e.g., user's CGM dropped out during the forecast horizon).
        # Don't drop the row -- a NULL is data ("we couldn't score
        # this point") and feeds into MAE-with-coverage metrics.
        sa.Column("actual_mgdl", sa.Float(), nullable=True),
        # Signed delta in seconds between the matched reading's actual
        # timestamp and the target offset. 0 = exact; negative = reading
        # arrived *before* the target offset; positive = after. The
        # scoring job clamps to a tolerance window (deferred PR sets the
        # bound) so this column is bounded in practice.
        sa.Column("actual_offset_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "forecast_snapshot_id",
            "offset_minutes",
            name="uq_forecast_eval_snapshot_offset",
        ),
    )
    op.create_index(
        "ix_forecast_eval_snapshot",
        "forecast_evaluations",
        ["forecast_snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_eval_snapshot", table_name="forecast_evaluations")
    op.drop_table("forecast_evaluations")
    op.drop_index("ix_forecast_user_source_issued", table_name="forecast_snapshots")
    op.drop_index("ix_forecast_user_issued", table_name="forecast_snapshots")
    op.drop_table("forecast_snapshots")
