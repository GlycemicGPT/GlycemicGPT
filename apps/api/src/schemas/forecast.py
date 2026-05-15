"""Pydantic schemas for the forecast read endpoint (Story 43.12 PR 3).

Shape consumers (in order they'll land):

- PR 4: frontend forecast-overlay picker reads `available_sources` to
  populate the dropdown; reads `forecast.curves_mgdl` +
  `default_curve_name` to draw the dotted line.
- PR 5: AI context builder reads `forecast.source_engine` and the
  default curve to talk honestly ("your Loop predicts..." not "your
  glucose is...").
- Mobile (eventual): same shape, no client-side adjustment.

`state`/`source`-style Literal types match the backend Pydantic
contract for PR 6's `LoopStatusResponse` so the frontend can mirror
the same union types end-to-end.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Known curve keys -- single-curve sources (Loop) populate `main`;
# OpenAPS family populates any subset of IOB / COB / UAM / ZT. A
# future curve name (e.g., a hypothetical AAPS extension) would
# require both this set AND `ForecastCurves` to grow; until then,
# unknown keys are logged + silently dropped on read so an
# unannounced wire-format change surfaces in logs rather than
# corrupting the response shape.
_KNOWN_CURVE_KEYS = frozenset({"main", "IOB", "COB", "UAM", "ZT"})

# Allow-list mirrors `forecast_settings.source` CHECK constraint (PR 3
# migration 057) and adds 'auto' / 'none' for the picker. The
# forecast-row-only engines from `forecast_snapshots.source_engine`
# are the subset producing actual rows; 'auto' / 'none' are
# picker-only states never persisted to `forecast_snapshots`.
ForecastSourcePreference = Literal[
    "auto",
    "none",
    "loop",
    "aaps",
    "trio",
    "oref0",
    "iaps",
    "glycemicgpt",
]

# Subset that can ever appear as the *effective* source: anything that
# can actually produce a forecast row. 'auto' / 'none' resolve to
# either one of these or `null`.
ForecastEngine = Literal[
    "loop",
    "aaps",
    "trio",
    "oref0",
    "iaps",
    "glycemicgpt",
]


# Why the forecast isn't rendering. `null` (omitted) is the happy
# path: `forecast` is populated and the chart draws the dotted line.
# Each non-null value maps to a distinct frontend message (PR 4):
#
# - `opted_out`     -> "Forecasts disabled in settings"
# - `needs_pick`    -> dropdown surfaces, no line draws yet
# - `no_sources`    -> hidden picker; "Connect Nightscout to see forecasts"
# - `source_silent` -> "Your <X> forecast paused (no recent data)"
# - `stale`         -> "Your <X> forecast paused (last reading too old)"
#
# Frontend reads this rather than reconstructing from
# `(source_preference, effective_source, forecast, available_sources)`.
ForecastUnavailableReason = Literal[
    "opted_out",
    "needs_pick",
    "no_sources",
    "source_silent",
    "stale",
]


class ForecastCurves(BaseModel):
    """The mg/dL curves (1-4) from a single forecast snapshot.

    Single-curve sources (Loop) populate just `main`. Multi-curve
    sources (AAPS / Trio / oref0 / iAPS) populate any subset of
    `IOB` / `COB` / `UAM` / `ZT`. Absent keys mean "this source
    didn't publish that curve this cycle" -- common for OpenAPS
    when carbs aren't active.

    The chart draws `default_curve_name` by default; a future power-
    user "show all curves" toggle (deferred) would read the rest.
    """

    model_config = ConfigDict(extra="forbid")

    main: list[float] | None = Field(
        default=None,
        description="Loop's single curve. Mutually exclusive with the OpenAPS curves in practice.",
    )
    IOB: list[float] | None = Field(default=None)  # noqa: N815 (mirrors wire shape)
    COB: list[float] | None = Field(default=None)  # noqa: N815
    UAM: list[float] | None = Field(default=None)  # noqa: N815
    ZT: list[float] | None = Field(default=None)  # noqa: N815


class ForecastPayload(BaseModel):
    """A single forecast snapshot, projected onto the chart's needs.

    Trimmed shape compared to `ForecastSnapshot` -- the read endpoint
    omits `nightscout_connection_id`, `dedupe_key`, and `received_at`
    because the chart / AI / mobile consumers don't need them.
    """

    source_engine: ForecastEngine
    source_uploader: str | None = Field(
        default=None,
        max_length=100,
        description="Original NS uploader name (denormalized from `device_status_snapshots.source_uploader`). Capped at 100 chars as defense-in-depth; the mapper truncates at 40 on write.",
    )
    issued_at: datetime = Field(
        ...,
        description="When the source loop emitted the forecast (its internal clock).",
    )
    start_at: datetime = Field(
        ...,
        description="t=0 of the forecast curve. For most sources == issued_at; Loop occasionally lags by a cycle.",
    )
    step_minutes: int = Field(..., gt=0, le=60)
    horizon_minutes: int = Field(..., gt=0, le=1440)
    curves_mgdl: ForecastCurves
    default_curve_name: str = Field(
        ...,
        description="Which key in `curves_mgdl` the chart should draw by default.",
    )


class ForecastReadResponse(BaseModel):
    """Response of `GET /api/integrations/forecast`.

    Composed shape so a single round-trip drives both the picker
    dropdown and the chart overlay:

    - `source_preference`: what the user picked (or `'auto'` default).
    - `effective_source`: which engine WOULD drive the overlay if a
      fresh forecast were available. Stays populated even when the
      latest snapshot is stale-suppressed -- the frontend uses this
      for legend / label rendering ("Loop forecast paused"). To know
      whether the chart should actually draw a line, the consumer
      should check `forecast != null` (or use
      `forecast_unavailable_reason`).
    - `available_sources`: every engine that emitted a forecast in
      the last 24h. Drives the picker dropdown. NOTE: this is the
      24h "is this source online" window, NOT the 30-min freshness
      window. An engine can be `available` (in the dropdown) but
      have its latest snapshot too stale to render -- the frontend
      surfaces that via the `stale` reason.
    - `forecast`: the latest snapshot from `effective_source`,
      suppressed when older than the 30-min freshness threshold so
      a stale dotted line never misaligns with the chart's "now".
    - `forecast_unavailable_reason`: explicit dispatch for "why no
      chart line." Null on the happy path. See `ForecastUnavailableReason`
      for the message-mapping table.
    """

    source_preference: ForecastSourcePreference
    effective_source: ForecastEngine | None
    available_sources: list[ForecastEngine] = Field(
        default_factory=list,
        description="Engines that emitted a forecast in the last 24h, sorted alphabetically for stable picker UI.",
    )
    forecast: ForecastPayload | None = None
    forecast_unavailable_reason: ForecastUnavailableReason | None = Field(
        default=None,
        description="Explicit reason `forecast` is null. Null when forecast is rendering normally.",
    )


class ForecastSourcePreferenceUpdate(BaseModel):
    """Body of `PUT /api/integrations/forecast/source`.

    Validates `source` against the allowed enum at the API boundary
    so a malformed pick returns 422 rather than a CHECK constraint
    violation at write time.
    """

    model_config = ConfigDict(extra="forbid")

    source: ForecastSourcePreference


class ForecastSourcePreferenceResponse(BaseModel):
    """Response of `PUT /api/integrations/forecast/source` and any
    future GET-just-the-preference path."""

    source_preference: ForecastSourcePreference


# ---------------------------------------------------------------------------
# Internal builder helpers (not part of the public schema surface)
# ---------------------------------------------------------------------------


def curves_from_jsonb(curves_json: Any) -> ForecastCurves:
    """Coerce a `forecast_snapshots.curves_mgdl_json` cell to the
    response schema.

    The DB column is JSONB with PR 1's range + length CHECKs already
    applied at write time. We trust the shape but pass each curve
    through Pydantic for type-narrowing on read. Unknown keys are
    logged + dropped: `ForecastCurves` uses `extra="forbid"` so
    silently widening the response surface would be a regression.
    Logging surfaces an unannounced wire-format change in operator
    logs without breaking the read path.
    """
    if not isinstance(curves_json, dict):
        return ForecastCurves()
    unknown_keys = set(curves_json.keys()) - _KNOWN_CURVE_KEYS
    if unknown_keys:
        logger.warning(
            "forecast_reader.unknown_curve_keys",
            extra={"unknown_keys": sorted(unknown_keys)},
        )
    return ForecastCurves(
        main=curves_json.get("main"),
        IOB=curves_json.get("IOB"),
        COB=curves_json.get("COB"),
        UAM=curves_json.get("UAM"),
        ZT=curves_json.get("ZT"),
    )
