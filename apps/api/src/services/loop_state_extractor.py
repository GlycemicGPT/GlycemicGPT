"""Closed-loop runtime state extraction for the dashboard hero card.

Story 43.12 PR 6. Surfaces three additional pieces of information from
the latest `device_status_snapshots` row to the hero card:

1. **Loop status** -- "looping" / "not_looping" / "failed". Driven by
   `loop.failureReason` (set = failed) or the presence of
   `openaps.enacted` (= looping).
2. **Override** -- Loop's `override` subtree describing an active
   workout / pre-meal / sleep mode override. Loop-only in this PR;
   AAPS overrides are deferred (they ride on Temp Target treatments,
   not devicestatus -- different code path).
3. **COB** -- carbs-on-board in grams. Already extracted by
   `_devicestatus_mapper` into `device_status_snapshots.cob_grams` --
   this module just passes it through.

All data is read-only -- this module never writes to the DB and never
calls the Nightscout client. It is purely a projection over rows the
PR 43.3 / PR 43.12 translator already landed.

Staleness rule: if the latest devicestatus snapshot is older than
`_LOOP_STATUS_STALE_THRESHOLD`, the loop_status field is suppressed
(returned as None). Showing a "Looping" badge for a 30-minute-old
snapshot would lie to the user -- their loop may have stopped looping
since. COB is left numeric regardless because the chart already
handles freshness elsewhere via `received_at` cues, and a stale COB
value at the boundary is informationally useful ("you had ~24g
absorbing 18 min ago") rather than misleading.

Source attribution is preserved end-to-end so the AI context (PR 5)
and chart legend can talk honestly: "your Loop says..." not "your
glucose system says...".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device_status_snapshot import DeviceStatusSnapshot
from src.services.integrations.nightscout.source_detection import (
    detect_openaps_engine,
)

# Beyond this age, `loop_status` is suppressed. 15 min = 3 missed sync
# cycles at the default 5-min interval. Tunable if real-world cadence
# differs.
_LOOP_STATUS_STALE_THRESHOLD = timedelta(minutes=15)

# Future-clock safety margin. A user device or NS uploader with a
# clock set ahead of real time (rare, but seen in the wild) would
# otherwise post devicestatus rows with timestamps in our future,
# bypassing the staleness check (negative delta < 15 min positive
# threshold). We allow up to this much lead before rejecting the
# loop_status -- accommodates ordinary millisecond-scale skew between
# the user's phone and our server without rejecting legitimate rows.
_LOOP_STATUS_FUTURE_TOLERANCE = timedelta(minutes=2)

# Bounds for free-text strings flowing from the NS payload through to
# the UI tooltip. The badge's `title` attribute renders verbatim; a
# malicious or buggy uploader posting a 100KB string would make the
# tooltip unwieldy or slow the page. Truncate at the boundary.
_FAILURE_REASON_MAX_LEN = 200
_OVERRIDE_NAME_MAX_LEN = 80

# Bounds for COB. The DB column `device_status_snapshots.cob_grams`
# is a permissive float -- the schema-layer Field(ge=0, le=500) would
# 500 the whole /pump/status response if a bad value somehow got
# stored. Clamp at the extractor to None so the rest of the bundle
# (loop_status / override) still renders.
_COB_MAX_GRAMS = 500.0

# Bounds for medical-adjacent numeric fields in an override. Out-of-
# range values from a buggy / malicious uploader are dropped at the
# extractor (returned as None on the OverrideStatus) rather than
# 500-ing the entire `/pump/status` request. The override's text
# fields remain renderable even when its numeric details are dirty.
#
# Bounds chosen to admit all clinically plausible Loop overrides:
# - multiplier: Loop's `insulinNeedsScaleFactor` is bounded by the
#   app's UI at ~0.05-10.0; clinical use rarely exceeds 0.5-2.0.
# - target_*_mgdl: physiological glucose targets. 30-500 matches the
#   wider band used in PR 2's forecast clamp.
_MULTIPLIER_MIN = 0.05
_MULTIPLIER_MAX = 10.0
_TARGET_GLUCOSE_MIN_MGDL = 30.0
_TARGET_GLUCOSE_MAX_MGDL = 500.0

# Override duration ceiling. The NS payload's `duration` field flows
# straight into `timedelta(seconds=...)`, which raises OverflowError
# for values exceeding `timedelta.max.days = 999_999_999`. The
# subsequent `started_at + timedelta(...)` raises a separate
# OverflowError once the result lands beyond `datetime.max`. A
# malicious / buggy uploader posting `"duration": 1e20` would 500
# every `/pump/status` call for that user until the snapshot ages
# out (15-min staleness boundary).
#
# Loop's own UI caps override duration at 24h; AAPS / Trio overrides
# don't flow through this path at all (they ride Temp Target
# treatments, not devicestatus). 7 days is generous headroom for any
# clinically plausible value while keeping pathological values from
# reaching the timedelta/datetime arithmetic.
_OVERRIDE_DURATION_MAX_SECONDS = 7 * 24 * 3600


LoopStatusState = Literal["looping", "not_looping", "failed"]
LoopSourceEngine = Literal["loop", "aaps", "trio", "oref0", "iaps"]


@dataclass(frozen=True)
class LoopStatus:
    """Closed-loop runtime state extracted from a devicestatus snapshot."""

    state: LoopStatusState
    source: LoopSourceEngine
    issued_at: datetime
    failure_reason: str | None = None  # populated only when state == "failed"


@dataclass(frozen=True)
class OverrideStatus:
    """Active override (workout / pre-meal / sleep mode) -- Loop-only in PR 6.

    AAPS / Trio publish overrides as Temp Target treatments rather than
    on devicestatus. Deferred to a follow-up; this PR ships with the
    Loop wire format only. Multi-source priority is moot until AAPS
    support lands.
    """

    name: str
    started_at: datetime
    multiplier: float | None = None  # Loop's `insulinNeedsScaleFactor`
    target_low_mgdl: float | None = None
    target_high_mgdl: float | None = None
    ends_at: datetime | None = None  # None for indefinite overrides


@dataclass(frozen=True)
class LoopStateBundle:
    """The three hero-card-bound fields, packaged together.

    Each field is independently nullable: a user might have a `cob`
    reading but no active override; a healthy loop but a stale
    snapshot; etc. The endpoint surfaces them as nullable JSON.
    """

    loop_status: LoopStatus | None
    override: OverrideStatus | None
    cob_grams: float | None


async def get_latest_loop_state(
    db: AsyncSession, user_id: uuid.UUID
) -> LoopStateBundle:
    """Project the latest closed-loop state for the hero card.

    Returns an all-None bundle when:
    - The user has no NS-imported devicestatus snapshots (CGM-only or
      no integration).
    - The latest snapshot has no loop / openaps subtree at all
      (xDrip+ pure CGM relay).

    Returns a partial bundle when only some fields are populated
    (e.g., a Loop user with no active override returns
    `loop_status != None` + `override == None`).
    """
    # NOTE: multi-connection users (e.g., Loop on connection A AND
    # AAPS on connection B reporting at staggered cadences) will see
    # the badge attributed to whichever connection sync'd most
    # recently. Story 43.10's primary-source picker will deterministic
    # this; until then, accept the LRU behavior. The test suite pins
    # the current shape so a future refactor can't silently change it.
    latest = await _fetch_latest_snapshot(db, user_id)
    if latest is None:
        return LoopStateBundle(loop_status=None, override=None, cob_grams=None)

    now = datetime.now(UTC)
    snapshot_at = _ensure_aware(latest.snapshot_timestamp)
    age = now - snapshot_at

    # Two staleness gates:
    # - Past: > 15 min old -> loop may have stopped since; suppress.
    # - Future: > 2 min ahead of now -> uploader clock skew; we cannot
    #   honestly claim a state from data that hasn't happened.
    is_stale = (
        age > _LOOP_STATUS_STALE_THRESHOLD or age < -_LOOP_STATUS_FUTURE_TOLERANCE
    )

    loop_status = None if is_stale else _extract_loop_status(latest)
    override = _extract_override(latest, now=now)

    # COB sanity clamp. Match the schema-layer Field(ge=0, le=500)
    # bounds so an out-of-range DB value drops cleanly to None
    # rather than 500-ing the entire /pump/status response.
    cob = latest.cob_grams
    if cob is not None and not (0 <= cob <= _COB_MAX_GRAMS):
        cob = None

    return LoopStateBundle(
        loop_status=loop_status,
        override=override,
        cob_grams=cob,
    )


# ---------------------------------------------------------------------------
# Per-piece extractors (pure functions; trivially unit-testable)
# ---------------------------------------------------------------------------


def _extract_loop_status(ds: DeviceStatusSnapshot) -> LoopStatus | None:
    """Classify the loop runtime state from a single snapshot.

    Loop publishes `loop.failureReason` only when the loop has failed
    a cycle. Absence + presence of `loop` subtree = looping. OpenAPS
    family classifies by `enacted` subtree presence (= acted on the
    suggestion this cycle) vs `suggested` only (= computed but didn't
    enact -- which means not looping per the AAPS convention).

    Returns None when the payload has no closed-loop signal at all
    (xDrip+, CGM-only relays).
    """
    loop_subtree = _as_dict(ds.loop_subtree_json)
    if loop_subtree is not None:
        return _extract_loop_status_from_loop_subtree(
            loop_subtree, issued_at=ds.snapshot_timestamp
        )

    openaps_subtree = _as_dict(ds.openaps_subtree_json)
    if openaps_subtree is not None:
        return _extract_loop_status_from_openaps_subtree(
            openaps_subtree,
            device=ds.source_device,
            issued_at=ds.snapshot_timestamp,
        )

    return None


def _extract_loop_status_from_loop_subtree(
    loop_subtree: dict[str, Any], *, issued_at: datetime
) -> LoopStatus | None:
    """Loop's `loop.{failureReason,enacted}` -> state machine.

    - `failureReason` present and non-empty -> "failed" with reason.
    - `enacted` subtree present -> "looping".
    - `suggested` subtree only (no enacted) -> "not_looping".
    - Neither -> None (not a forecast-publishing loop cycle).
    """
    failure_reason = loop_subtree.get("failureReason")
    if isinstance(failure_reason, str) and failure_reason.strip():
        # Cap free-text length at the boundary. The badge's `title`
        # tooltip renders verbatim in the browser; a malicious or
        # buggy NS uploader posting a 100KB string would make the
        # tooltip unwieldy. 200 chars covers every real Loop failure
        # message (typically < 80 chars).
        return LoopStatus(
            state="failed",
            source="loop",
            issued_at=_ensure_aware(issued_at),
            failure_reason=failure_reason.strip()[:_FAILURE_REASON_MAX_LEN],
        )

    if isinstance(loop_subtree.get("enacted"), dict):
        return LoopStatus(
            state="looping",
            source="loop",
            issued_at=_ensure_aware(issued_at),
        )

    if isinstance(loop_subtree.get("suggested"), dict):
        return LoopStatus(
            state="not_looping",
            source="loop",
            issued_at=_ensure_aware(issued_at),
        )

    return None


def _extract_loop_status_from_openaps_subtree(
    openaps_subtree: dict[str, Any],
    *,
    device: str | None,
    issued_at: datetime,
) -> LoopStatus | None:
    """AAPS / Trio / oref0 / iAPS state via `openaps.{enacted,suggested}`.

    Same conventions as Loop:
    - `enacted` present -> "looping".
    - `suggested` only -> "not_looping".
    - Neither -> None.

    No `failureReason` equivalent exists in the OpenAPS wire format;
    failures surface as "not_looping" with the human-readable reason
    inside the `suggested.reason` text -- not promoted to a separate
    state because the OpenAPS family doesn't have the discrete
    failed-vs-not-looping distinction Loop carries.
    """
    source = detect_openaps_engine(device, openaps_subtree)
    if source is None:
        return None

    if isinstance(openaps_subtree.get("enacted"), dict):
        return LoopStatus(
            state="looping",
            source=source,
            issued_at=_ensure_aware(issued_at),
        )

    if isinstance(openaps_subtree.get("suggested"), dict):
        return LoopStatus(
            state="not_looping",
            source=source,
            issued_at=_ensure_aware(issued_at),
        )

    return None


def _extract_override(
    ds: DeviceStatusSnapshot, *, now: datetime | None = None
) -> OverrideStatus | None:
    """Pull an active override from Loop's `loop.override` subtree.

    Loop's `override` subtree shape (per `LoopKit/NightscoutKit`
    `OverrideTreatment.swift`):

    ```
    {
      "active": true,
      "name": "Pre-meal",
      "timestamp": "2026-05-13T14:00:00Z",      // started
      "duration": 1800,                          // SECONDS, not minutes
      "multiplier": 0.7,                         // optional
      "currentCorrectionRange": {
        "minValue": 70, "maxValue": 90
      }
    }
    ```

    AAPS / Trio overrides live on Temp Target *treatments* rather than
    devicestatus; supporting those is a separate code path and
    deferred to a follow-up. This extractor only consults the
    `loop_subtree_json` -- a snapshot with only `openaps_subtree_json`
    populated (AAPS-only user) returns None even if AAPS had an
    override running at that moment.

    Three independent rejection guards run alongside the canonical
    `active: true` check:

    1. **Past-end override**: if `ends_at < now`, the override has
       already ended even though Loop hasn't flipped `active`. Common
       when NS sync is delayed.
    2. **Future-start override**: if `started_at > now`, the
       uploader's clock is ahead and the override hasn't begun yet
       from our reference frame.
    3. **Name length cap**: protects the badge tooltip from
       malicious / buggy uploaders posting huge strings.

    The `now` parameter is injected for deterministic testing and so
    the caller can use a single `now` across all loop-state fields.
    """
    reference_now = now if now is not None else datetime.now(UTC)
    loop_subtree = _as_dict(ds.loop_subtree_json)
    if loop_subtree is None:
        return None

    override = loop_subtree.get("override")
    if not isinstance(override, dict):
        return None

    if override.get("active") is not True:
        return None

    name = override.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    started_at = _parse_iso(override.get("timestamp"))
    if started_at is None:
        return None

    # Future-start guard. Allow a small tolerance for ordinary clock
    # skew; reuse the loop-status future tolerance to keep the policy
    # consistent across both surfaces.
    if started_at > reference_now + _LOOP_STATUS_FUTURE_TOLERANCE:
        return None

    duration_seconds = override.get("duration")
    ends_at: datetime | None = None
    if (
        isinstance(duration_seconds, int | float)
        and not isinstance(duration_seconds, bool)
        and 0 < float(duration_seconds) <= _OVERRIDE_DURATION_MAX_SECONDS
    ):
        # The upper bound also prevents NaN / +inf from sneaking in:
        # both fail the `<= max` comparison. Bool was already rejected
        # by the isinstance guard above (Python's `True`/`False`
        # subclass int).
        ends_at = started_at + timedelta(seconds=float(duration_seconds))

    # Past-end guard. A stale snapshot can carry `active: true` for
    # an override that ended minutes ago; suppress rather than render
    # "ends in -5 min" or claim "ongoing" for finished work.
    if ends_at is not None and ends_at < reference_now:
        return None

    multiplier = override.get("multiplier")
    if not (isinstance(multiplier, int | float) and not isinstance(multiplier, bool)):
        multiplier = None
    elif not (_MULTIPLIER_MIN <= float(multiplier) <= _MULTIPLIER_MAX):
        # Out-of-range multiplier from a buggy uploader (e.g. NaN
        # serialized as 0, or a misread units conversion). Drop the
        # numeric detail; keep the override's name/start/end so the
        # user still sees "Pre-meal active, ends in 30 min" rather
        # than the whole override disappearing.
        multiplier = None

    correction_range = override.get("currentCorrectionRange")
    target_low: float | None = None
    target_high: float | None = None
    if isinstance(correction_range, dict):
        low_raw = correction_range.get("minValue")
        high_raw = correction_range.get("maxValue")
        if isinstance(low_raw, int | float) and not isinstance(low_raw, bool):
            low_candidate = float(low_raw)
            if _TARGET_GLUCOSE_MIN_MGDL <= low_candidate <= _TARGET_GLUCOSE_MAX_MGDL:
                target_low = low_candidate
        if isinstance(high_raw, int | float) and not isinstance(high_raw, bool):
            high_candidate = float(high_raw)
            if _TARGET_GLUCOSE_MIN_MGDL <= high_candidate <= _TARGET_GLUCOSE_MAX_MGDL:
                target_high = high_candidate

    # Logical consistency: if both targets parsed cleanly but
    # target_low > target_high, the band is inverted -- drop both.
    if target_low is not None and target_high is not None and target_low > target_high:
        target_low = None
        target_high = None

    return OverrideStatus(
        name=name.strip()[:_OVERRIDE_NAME_MAX_LEN],
        started_at=started_at,
        multiplier=float(multiplier) if multiplier is not None else None,
        target_low_mgdl=target_low,
        target_high_mgdl=target_high,
        ends_at=ends_at,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_latest_snapshot(
    db: AsyncSession, user_id: uuid.UUID
) -> DeviceStatusSnapshot | None:
    """Latest devicestatus snapshot across all NS connections for the user.

    Picks by `snapshot_timestamp` desc -- not `received_at` -- so a
    backfilled snapshot doesn't outrank a newer real-time one just
    because it was synced later. This matches the chart's
    glucose-reading ordering convention.
    """
    stmt = (
        select(DeviceStatusSnapshot)
        .where(DeviceStatusSnapshot.user_id == user_id)
        .order_by(DeviceStatusSnapshot.snapshot_timestamp.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _as_dict(value: Any) -> dict[str, Any] | None:
    """Coerce a JSONB column read to a dict, tolerating None / non-dict."""
    return value if isinstance(value, dict) else None


def _parse_iso(value: Any) -> datetime | None:
    """ISO 8601 string -> aware datetime (UTC). Returns None on garbage."""
    if not isinstance(value, str) or not value:
        return None
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _ensure_aware(dt: datetime) -> datetime:
    """Postgres TIMESTAMPTZ returns aware; safety net for naive sentinels."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
