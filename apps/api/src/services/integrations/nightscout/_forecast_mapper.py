"""Map Nightscout devicestatus records to ForecastSnapshot rows.

Story 43.12 PR 2. Extends the devicestatus translator to write a
`forecast_snapshots` row each time a payload carries a closed-loop
forecast (Loop's `loop.predicted.values[]` or AAPS / Trio / oref0 /
iAPS's `openaps.suggested.predBGs.*`).

Design rules (from `_bmad-output/planning-artifacts/story-43.12-forecast-overlay-design.md`):

1. **Tolerate missing curves.** AAPS may post only IOB, or any subset
   of (IOB, COB, UAM, ZT). Loop posts a single curve.
2. **Source attribution preserved.** `source_engine` (`'loop'` /
   `'aaps'` / `'trio'` / `'oref0'` / `'iaps'`) drives the AI context
   and chart legend. Reuse the existing `detect_uploader()` heuristic
   from `models.py` rather than re-implement.
3. **Skip silently on indeterminate / malformed payloads.** Return
   `None`; the translator counts that as a skip. No exceptions cross
   the mapper boundary so a buggy uploader never blocks the
   devicestatus-snapshot insert path.
4. **Idempotent via dedupe_key = NS `_id`.** Same devicestatus arriving
   in two sync cycles UPSERTs the same forecast row.

What the AI sees later (PR 5): each row carries `issued_at`,
`source_engine`, and the `default_curve_name` so the context builder
can label honestly: "your Loop predicts...", not "your glucose is..."
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from src.services.integrations.nightscout.models import NightscoutDeviceStatus
from src.services.integrations.nightscout.source_detection import (
    detect_openaps_engine,
)

logger = logging.getLogger(__name__)


# Default-curve priority for OpenAPS multi-curve sources. Per design
# doc Section 1: AAPS / Trio / oref0 phone UIs render IOB by default
# when present, falling back to COB when carbs are active. Mirror that
# heuristic so the chart's default line matches what the source's own
# UI shows.
_OPENAPS_DEFAULT_CURVE_PRIORITY = ("IOB", "COB", "UAM", "ZT")

# Physiologically plausible glucose range, mg/dL. Curves with any
# value outside this band are rejected wholesale (same strict policy
# as `_coerce_curve` for non-numeric entries) -- a forecast that
# claims BG of -50 or 5000 is corrupted data, and silently storing
# it would poison both the chart overlay and the deferred scoring
# job. Bounds match the entries-side gap rule (`SGV_MIN_VALID` /
# `SGV_MAX_VALID` in `models.py`) plus a small headroom for forecast
# extrapolation peaks.
_FORECAST_VALUE_MIN_MGDL = 20.0
_FORECAST_VALUE_MAX_MGDL = 800.0

# Defensive cap on curve length. The JSONB column has no DB-side
# size CHECK and the sync scheduler fetches up to ~1000 devicestatus
# rows per cycle, so a malicious upstream Nightscout server (a user's
# own attacker-controlled instance is the threat model) posting
# `predBGs.IOB: [120] * 1_000_000` would let the mapper allocate
# gigabytes per cycle and TOAST-bloat the JSONB column.
#
# Real forecasts run at 5-min step for at most 6h (Loop) -- 73
# points. 288 = a full day at 5-min step, generous future headroom
# without giving uploaders unbounded memory authority over our
# translator. Match the philosophy of `_DEDUPE_KEY_MAX_LEN`.
_MAX_CURVE_POINTS = 288

# `dedupe_key` is bounded by the migration CHECK
# (`char_length BETWEEN 1 AND 128`). NS Mongo `_id`s are 24 hex chars,
# well inside this bound -- defensive cap below catches a malformed
# upstream `_id` (e.g., a verbose v3 envelope string) before the DB
# rejects it.
_DEDUPE_KEY_MAX_LEN = 128


def map_devicestatus_to_forecast(
    ds: NightscoutDeviceStatus,
    *,
    user_id: str,
    nightscout_connection_id: str,
    received_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Map a Nightscout devicestatus to a `forecast_snapshots` insert dict.

    Returns `None` when the payload carries no forecast, the source
    engine cannot be classified, the dedupe key is missing or oversized,
    or curve extraction failed. Caller treats `None` as "skip" -- the
    devicestatus snapshot row still lands via the sibling mapper.
    """
    if not ds.id:
        return None
    if len(ds.id) > _DEDUPE_KEY_MAX_LEN:
        logger.warning(
            "forecast_mapper.dedupe_key_too_long",
            extra={"ns_id_len": len(ds.id), "user_id": user_id},
        )
        return None

    issued_at = _parse_iso_timestamp(ds.created_at)
    if issued_at is None:
        return None

    # Try Loop first -- its subtree presence is unambiguous and wins
    # over OpenAPS in the rare case both are populated (cross-bridge
    # uploads). Then fall through to OpenAPS family.
    extracted = _extract_loop_forecast(ds, issued_at)
    if extracted is None:
        extracted = _extract_openaps_forecast(ds, issued_at)
    if extracted is None:
        return None

    curves, default_curve, step_minutes, start_at, source_engine = extracted

    horizon_minutes = step_minutes * len(curves[default_curve])
    source_uploader = ds.uploader_name if ds.uploader_name != "unknown" else None

    return {
        "user_id": user_id,
        "nightscout_connection_id": nightscout_connection_id,
        "source_engine": source_engine,
        "source_uploader": source_uploader,
        "issued_at": issued_at,
        "start_at": start_at,
        "step_minutes": step_minutes,
        "horizon_minutes": horizon_minutes,
        "curves_mgdl_json": curves,
        "default_curve_name": default_curve,
        "dedupe_key": ds.id,
        "received_at": received_at or datetime.now(UTC),
    }


# ---------------------------------------------------------------------------
# Per-source extractors
# ---------------------------------------------------------------------------


def _extract_loop_forecast(
    ds: NightscoutDeviceStatus, issued_at: datetime
) -> tuple[dict[str, list[float]], str, int, datetime, str] | None:
    """Pull Loop's single-curve forecast from `loop.predicted.values[]`.

    Returns `(curves, default_curve_name, step_minutes, start_at,
    source_engine)` or `None` when no Loop forecast is present.

    Loop publishes `loop.predicted.values` (an array of numbers,
    typically 73 points at 5-min spacing for 6h horizon) and
    `loop.predicted.startDate` (ISO 8601). When `startDate` is missing
    we anchor to `issued_at`.
    """
    if not ds.loop:
        return None
    predicted = ds.loop.get("predicted")
    if not isinstance(predicted, dict):
        return None
    values = _coerce_curve(predicted.get("values"))
    if values is None or not values:
        return None

    start_at = _parse_iso_timestamp(predicted.get("startDate")) or issued_at
    # Loop's interval is 5 min by convention. The wire format doesn't
    # publish it; the design doc treats this as a known constant
    # across the codebase. If a future Loop variant changes this we'd
    # need to re-derive from successive `startDate` deltas.
    step_minutes = 5
    return ({"main": values}, "main", step_minutes, start_at, "loop")


def _extract_openaps_forecast(
    ds: NightscoutDeviceStatus, issued_at: datetime
) -> tuple[dict[str, list[float]], str, int, datetime, str] | None:
    """Pull OpenAPS multi-curve forecast from `openaps.{suggested,determination}.predBGs`.

    AAPS posts under `openaps.suggested.predBGs`. Trio additionally
    posts `openaps.determination.predBGs` (same shape). When both
    exist, `determination` wins -- it's the post-decision view that
    Trio's own UI renders. oref0 / iAPS / AAPS-only-suggested fall back
    to `suggested`.
    """
    if not ds.openaps:
        return None

    pred_bgs = _find_pred_bgs(ds.openaps)
    if pred_bgs is None:
        return None

    # Tolerate missing curves. Iterate the known names in priority
    # order; collect whatever is present and well-formed.
    curves: dict[str, list[float]] = {}
    for name in _OPENAPS_DEFAULT_CURVE_PRIORITY:
        values = _coerce_curve(pred_bgs.get(name))
        if values is not None and values:
            curves[name] = values
    if not curves:
        return None

    # `curves` is built by iterating `_OPENAPS_DEFAULT_CURVE_PRIORITY`,
    # so any key in `curves` is also in the priority tuple. A match
    # is guaranteed; no fallback needed.
    default_curve = next(n for n in _OPENAPS_DEFAULT_CURVE_PRIORITY if n in curves)

    source_engine = detect_openaps_engine(ds.device, ds.openaps)
    if source_engine is None:
        # Indeterminate -- log and skip rather than guess. The CHECK
        # constraint would reject an unknown value anyway, but logging
        # here surfaces the unrecognized uploader for future heuristics.
        logger.warning(
            "forecast_mapper.unknown_openaps_engine",
            extra={"device": ds.device},
        )
        return None

    step_minutes = 5
    start_at = issued_at  # OpenAPS doesn't publish a separate startDate
    return (curves, default_curve, step_minutes, start_at, source_engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_pred_bgs(openaps: dict[str, Any]) -> dict[str, Any] | None:
    """Locate the predBGs subtree across `determination` / `suggested`.

    Trio writes both blocks; its `determination` is the post-decision
    view and matches what the Trio UI renders, so prefer it. AAPS /
    oref0 / iAPS only emit `suggested`.
    """
    for block_name in ("determination", "suggested"):
        block = openaps.get(block_name)
        if isinstance(block, dict):
            pred = block.get("predBGs")
            if isinstance(pred, dict) and pred:
                return pred
    return None


def _coerce_curve(value: Any) -> list[float] | None:
    """Coerce a curve to `list[float]`, returning `None` on malformed input.

    Tolerates int / float entries; rejects non-numeric ones rather than
    silently introducing zeros. A single bad entry makes the whole curve
    `None` -- a half-coerced curve would be subtly worse for downstream
    scoring than no curve at all. (Trade-off documented in PR 2's
    adversarial review: production may show real `null` entries from
    AAPS that warrant graceful degradation; revisit then.)

    Values outside the physiological glucose band
    (`[_FORECAST_VALUE_MIN_MGDL, _FORECAST_VALUE_MAX_MGDL]`) are
    treated as corruption and reject the whole curve. The chart
    overlay would otherwise render nonsensical extremes and the AI
    context (PR 5) would repeat them to the user.
    """
    if not isinstance(value, list):
        return None
    if len(value) > _MAX_CURVE_POINTS:
        return None
    out: list[float] = []
    for item in value:
        # Explicitly reject bool: `isinstance(True, int)` is True in
        # Python, and a misbehaving uploader emitting `True` for a
        # predicted reading must not slip in as 1.0.
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        coerced = float(item)
        if not (_FORECAST_VALUE_MIN_MGDL <= coerced <= _FORECAST_VALUE_MAX_MGDL):
            return None
        out.append(coerced)
    return out


def _parse_iso_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 string (with optional trailing `Z`) to aware datetime.

    Sibling of `_devicestatus_mapper._parse_created_at`; duplicated
    rather than shared to keep both mappers independently understandable.
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
