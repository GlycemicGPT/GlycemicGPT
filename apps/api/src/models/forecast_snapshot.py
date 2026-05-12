"""Forecast snapshot models (Story 43.12 PR 1).

`ForecastSnapshot` is a normalized per-cycle row capturing a single
closed-loop's BG forecast. The translator writes one row per
Nightscout devicestatus payload that carries forecast data (Loop's
`predicted.values[]`, AAPS / Trio / oref0's `predBGs.{IOB,COB,UAM,ZT}`).

This is a separate table from `device_status_snapshots` (which holds
verbatim JSONB subtrees) by design:

- Multiple consumers need a clean shape: chart overlay, AI context
  builder, future calibration / training-signal pipeline.
- Future GlycemicGPT prediction engine outputs aren't NS payloads --
  having a neutral table lets us land engine-emitted rows alongside
  NS-imported ones without lying about the source.
- Write-time normalization moves per-uploader shape parsing out of
  every read path.

`ForecastEvaluation` lands as schema-only in this PR. The pairing-
to-actual-CGM-reading job that populates it is deferred to a
follow-up; see design doc Section 5.2.

Design doc:
    `_bmad-output/planning-artifacts/story-43.12-forecast-overlay-design.md`
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class ForecastSnapshot(Base):
    """A single point-in-time closed-loop BG forecast."""

    __tablename__ = "forecast_snapshots"

    __table_args__ = (
        # Idempotency: same Nightscout devicestatus `_id` -> same
        # forecast row across sync cycles. The translator UPSERTs on
        # this key. Engine-emitted rows mint a fresh UUID dedupe key.
        UniqueConstraint(
            "source_engine",
            "dedupe_key",
            name="uq_forecast_snapshots_source_dedupe",
        ),
        # Mirror of migration CHECKs. Keeping them on the ORM means
        # autogenerate diffs stay quiet and the invariants are visible
        # next to the columns they constrain.
        CheckConstraint(
            "source_engine IN ('loop','aaps','trio','oref0','iaps','glycemicgpt')",
            name="ck_forecast_source_engine_known",
        ),
        CheckConstraint(
            "step_minutes > 0 AND horizon_minutes > 0",
            name="ck_forecast_step_horizon_positive",
        ),
        CheckConstraint(
            "curves_mgdl_json ? default_curve_name",
            name="ck_forecast_default_curve_in_curves",
        ),
        CheckConstraint(
            "char_length(dedupe_key) BETWEEN 1 AND 128",
            name="ck_forecast_dedupe_key_length",
        ),
        # "Latest forecast for this user, any source." Indexes the
        # default dashboard read path. DESC matches migration so
        # autogenerate stays quiet.
        Index(
            "ix_forecast_user_issued",
            "user_id",
            text("issued_at DESC"),
        ),
        # "Latest forecast for this user from THIS source." Indexes
        # the picker-aware read path ("user picked Loop; give me their
        # latest Loop forecast").
        Index(
            "ix_forecast_user_source_issued",
            "user_id",
            "source_engine",
            text("issued_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Nullable so non-NS sources can attach without a connection FK.
    # Future direct-integration paths and the GlycemicGPT engine
    # use source_engine alone for attribution; nightscout_connection_id
    # is NULL for those rows.
    nightscout_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nightscout_connections.id", ondelete="CASCADE"),
        nullable=True,
    )

    # 'loop' | 'aaps' | 'trio' | 'oref0' | 'iaps' | 'glycemicgpt'.
    # Stored as Text (not a Postgres ENUM type) so adding a new
    # engine is a one-line CHECK update -- not a CREATE TYPE /
    # ALTER TYPE dance. The CHECK constraint
    # `ck_forecast_source_engine_known` bounds the allowed set as
    # defense-in-depth so translator typos (`"AAPS"` vs `"aaps"`)
    # fail at the DB boundary instead of silently minting phantom
    # engines. Adding a new uploader is intentionally a migration
    # event so the read endpoint, AI context builder, and any
    # eventual scoring job stay in sync with what the DB accepts.
    source_engine: Mapped[str] = mapped_column(Text, nullable=False)

    # Denormalized from `device_status_snapshots.source_uploader` so
    # chart rendering doesn't need a join. Same values + nullability
    # semantics as the source column.
    source_uploader: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When the engine *issued* the forecast (its internal clock).
    # NOT when we ingested it. For Loop: `loop_subtree_json.timestamp`.
    # For AAPS / Trio / oref0: `suggested.deliverAt`. Future engine:
    # compute wall clock at emit time.
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # t=0 on the chart for this forecast. For most sources this equals
    # `issued_at`. Loop occasionally posts `predicted.startDate` lagging
    # the devicestatus timestamp by a cycle when its sync cadence and
    # NS upload cadence diverge -- the chart anchors the dotted line at
    # `start_at`, not `issued_at`, so the first forecast point lines up
    # with the actual reading underneath it.
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    step_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # JSONB shape:
    #   {
    #     "IOB":  [120, 122, 125, ...],
    #     "COB":  [120, 124, 130, ...],  -- optional
    #     "UAM":  [...],                  -- optional
    #     "ZT":   [...]                   -- optional
    #   }
    # Loop (single curve): {"main": [...]}.
    #
    # Single-curve and multi-curve sources both fit this shape.
    # `default_curve_name` picks which key the chart draws by default.
    curves_mgdl_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    # Which curve to draw on the chart by default for this source.
    # Loop -> "main". AAPS / Trio / oref0 / iAPS -> "IOB" when present
    # (the source's own UI default), else the first available curve.
    # Computed at translate time so chart render doesn't re-derive.
    default_curve_name: Mapped[str] = mapped_column(Text, nullable=False)

    # NS devicestatus `_id` for NS-imported rows; UUID for engine
    # rows. UNIQUE with `source_engine` keeps Loop's `_id` and AAPS's
    # `_id` from accidentally colliding even though both look like
    # 24-hex strings.
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ---- Relationships ---------------------------------------------------

    user = relationship("User")
    connection = relationship("NightscoutConnection")
    evaluations: Mapped[list[ForecastEvaluation]] = relationship(
        "ForecastEvaluation",
        back_populates="forecast_snapshot",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<ForecastSnapshot(user_id={self.user_id}, "
            f"source={self.source_engine!r}, "
            f"issued_at={self.issued_at}, "
            f"horizon_minutes={self.horizon_minutes})>"
        )


class ForecastEvaluation(Base):
    """One pairing of `(forecast_point, actual_CGM_reading)`.

    Populated by a scoring job (deferred, not in this PR) that runs
    just past each forecast's horizon time and looks up the actual
    CGM reading at each forecast offset. The result feeds:

    - Per-user / per-source accuracy reports ("your Loop's 30-min
      MAE is 12 mg/dL over the last week").
    - Calibration features for the future GlycemicGPT prediction
      engine ("Loop is consistently over-predicting at night for
      this user; weight its forecast lower in the nighttime model").

    Schema-only in this PR. The job lands later.
    """

    __tablename__ = "forecast_evaluations"

    __table_args__ = (
        # One evaluation row per (forecast, offset). Re-running the
        # scoring job is idempotent: it UPSERTs by this key.
        UniqueConstraint(
            "forecast_snapshot_id",
            "offset_minutes",
            name="uq_forecast_eval_snapshot_offset",
        ),
        Index("ix_forecast_eval_snapshot", "forecast_snapshot_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    forecast_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("forecast_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Minutes past `forecast_snapshots.start_at`. Typically 5-min
    # multiples up to `horizon_minutes`. Same offset values regardless
    # of source.
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    predicted_mgdl: Mapped[float] = mapped_column(Float, nullable=False)

    # NULL when no CGM reading landed within the tolerance window for
    # this offset (sensor warm-up, transmitter dropout, etc.). NULL is
    # data -- aggregations should report it as "coverage gap" rather
    # than skipping the row, otherwise we under-count missed forecasts.
    actual_mgdl: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Signed delta in seconds between the matched reading's actual
    # timestamp and the target offset. 0 = exact; negative = reading
    # arrived *before* the target offset; positive = after. Useful for
    # "is this user's CGM cadence reliable enough to score accurately?"
    # debugging. The scoring job (deferred) clamps absolute value to a
    # tolerance window.
    actual_offset_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    forecast_snapshot: Mapped[ForecastSnapshot] = relationship(
        "ForecastSnapshot",
        back_populates="evaluations",
    )

    def __repr__(self) -> str:
        return (
            f"<ForecastEvaluation(forecast_snapshot_id={self.forecast_snapshot_id}, "
            f"offset_minutes={self.offset_minutes}, "
            f"predicted={self.predicted_mgdl}, "
            f"actual={self.actual_mgdl})>"
        )
