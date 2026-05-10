"""Story 43.7a -- evaluate a Nightscout instance for the onboarding wizard.

Builds a `NightscoutDiscoveryReport` from a single round-trip to the
target Nightscout: tests the connection, samples recent entries +
treatments + devicestatus, derives uploader identity from the sample,
and pulls the profile if available. Result is cached on the connection
row (Story 43.7a AC9) so the wizard re-rendering doesn't hammer the
upstream.

Entry point: `evaluate_nightscout_for_connection(db, conn)`.

The router calls this inside an `asyncio.wait_for(..., timeout)`
envelope so a slow / unresponsive user-controlled NS URL can't pin a
request thread; the bound mirrors the Story 43.4 sync pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.encryption import decrypt_credential
from src.logging_config import get_logger
from src.models.nightscout_connection import NightscoutConnection
from src.schemas.nightscout import (
    NightscoutDiscoveryProfileSummary,
    NightscoutDiscoveryReport,
    NightscoutProfileSegmentDTO,
)

from .client import NightscoutClient
from .connection_test import test_connection
from .models import NightscoutProfile, detect_uploader

logger = get_logger(__name__)


# How many records to sample for uploader detection + count estimation.
# Per-resource page size for the evaluate probe. Big enough that a 7-day
# window of normal CGM data (288 entries/day * 7 = 2016) fits, small
# enough that a stale instance's 100K-entry retention doesn't transfer
# the whole archive on every wizard render.
_ENTRIES_RECENT_PROBE_COUNT = 2500
_ENTRIES_OLDEST_PROBE_COUNT = 1000  # for earliest_entry_at lookup
_TREATMENTS_PROBE_COUNT = 200
_DEVICESTATUS_PROBE_COUNT = 50
# Closed-loop labels we surface as `active_pump_loop`. Order is
# preference -- if multiple are present in the uploader sample, the
# first match wins. Anchors on the "real" loops; xdrip+ / xdrip4ios
# are CGM uploaders, not loops, and stay out of this list.
_LOOP_UPLOADERS = ("loop", "aaps", "trio", "oref0")


async def evaluate_nightscout_for_connection(
    conn: NightscoutConnection,
) -> NightscoutDiscoveryReport:
    """Sample the target Nightscout to build a discovery report.

    Pure read -- does NOT mutate the connection (the router commits
    `detected_uploaders_json` + `last_evaluated_at` after the report
    is built; keeping the side effect at the boundary makes this
    function easy to test with a mocked client).

    Caller is responsible for the 5-min cache lookup (AC9) and for
    bounding the call with `asyncio.wait_for`.

    Returns a report with `status_ok=False` and a populated `error`
    when the connection test fails -- the router intentionally does
    NOT cache failures (so a typo'd token can be retried immediately
    after fix). Profile-malformed cases (AC11) populate
    `has_profile=False` + `profile_summary.is_malformed=True` rather
    than raising, so the wizard's settings-import step can render
    a "skipped" state cleanly.

    **SSRF**: the user-controlled `conn.base_url` flows into
    `test_connection()` -> `NightscoutClient.create()` -> `httpx`.
    SSRF guards live one layer down, in
    `src/services/integrations/nightscout/ssrf.py`'s
    `ValidatedTarget`, which `NightscoutClient.create()` constructs
    before any network call. That validator rejects loopback /
    private / link-local / metadata IPs, IPv4+IPv6, and non-http(s)
    schemes. Story 43.2 owns the SSRF surface; this orchestrator
    inherits the protection.
    """
    evaluated_at = datetime.now(UTC)
    credential = decrypt_credential(conn.encrypted_credential)

    # Step 1: connection test reuses the proven path. Outcome carries
    # status_ok + server_version + the actual auth/version
    # negotiated.
    outcome = await test_connection(
        base_url=conn.base_url,
        auth_type=conn.auth_type,
        credential=credential,
        api_version=conn.api_version,
    )
    if not outcome.ok:
        return NightscoutDiscoveryReport(
            status_ok=False,
            server_version=outcome.server_version,
            evaluated_at=evaluated_at,
            error=outcome.error,
        )

    # Step 2: open a client for the per-resource probes. The
    # test_connection path above proved the credential/URL; the
    # client below reuses whatever auto-detected api_version the
    # test settled on (auto-detect is per-client, so we pay the
    # small extra round-trip on the second client -- a future
    # refactor could thread the negotiated version through, but the
    # cost is bounded by the router's `_EVALUATE_TIMEOUT_SECONDS`
    # envelope (25s).
    api_version = (
        outcome.api_version_detected
        if outcome.api_version_detected is not None
        else conn.api_version
    )
    # Track resources whose probe failed even though auth passed
    # -- e.g. tokens with entries-only scope. The wizard surfaces
    # this as "we couldn't read X -- your token might be scope-
    # restricted" rather than silently claiming the data is absent.
    partial_resources: list[str] = []
    async with await NightscoutClient.create(
        base_url=conn.base_url,
        auth_type=conn.auth_type,
        credential=credential,
        api_version=api_version,
    ) as client:
        recent_entries, recent_ok = await _safe_fetch(
            client.fetch_entries(
                since=evaluated_at - timedelta(days=7),
                count=_ENTRIES_RECENT_PROBE_COUNT,
            ),
            label="recent_entries",
        )
        if not recent_ok:
            partial_resources.append("recent_entries")
        # Earliest-entry lookup: a separate fetch WITHOUT the since
        # filter so we get the oldest tail of the page, not the
        # 7-day cutoff. NS returns newest-first so the LAST item of
        # this page is the earliest in our sample. For instances
        # with > _ENTRIES_OLDEST_PROBE_COUNT entries in retention,
        # this is a lower bound on "how far back can we go" rather
        # than an absolute earliest -- acceptable for the wizard's
        # "going back to 2024-08-12" prose.
        oldest_page, oldest_ok = await _safe_fetch(
            client.fetch_entries(count=_ENTRIES_OLDEST_PROBE_COUNT),
            label="oldest_entries",
        )
        if not oldest_ok:
            partial_resources.append("oldest_entries")
        treatments, treatments_ok = await _safe_fetch(
            client.fetch_treatments(count=_TREATMENTS_PROBE_COUNT),
            label="treatments",
        )
        if not treatments_ok:
            partial_resources.append("treatments")
        devicestatuses, devicestatus_ok = await _safe_fetch(
            client.fetch_devicestatus(count=_DEVICESTATUS_PROBE_COUNT),
            label="devicestatus",
        )
        if not devicestatus_ok:
            partial_resources.append("devicestatus")
        profile_records, profile_ok = await _safe_fetch(
            client.fetch_profile(),
            label="profile",
        )
        if not profile_ok:
            partial_resources.append("profile")

    earliest_entry_at = _earliest_entry_timestamp(oldest_page)
    recent_entry_count_7d = len(recent_entries)
    # Real estimate (CR feedback): extrapolate the last-7-day rate
    # across the (earliest..now) span. For steady CGM upload this
    # lands within ~10% of true total; for intermittent uploaders
    # it's a rough order-of-magnitude. Bounded below by the actual
    # sample size (`len(oldest_page)`) so we never under-report
    # what we directly observed. Capped above by an absolute
    # ceiling to keep the wizard prose sane on instances that have
    # been running for years (`100M` is well past any plausible
    # personal CGM retention).
    entry_count_estimate = _estimate_total_entries(
        recent_count_7d=recent_entry_count_7d,
        earliest_at=earliest_entry_at,
        sample_size=len(oldest_page),
        now=evaluated_at,
    )

    uploaders_detected = _detect_uploaders(
        recent_entries, treatments, devicestatuses
    )
    active_pump_loop = next(
        (u for u in _LOOP_UPLOADERS if u in uploaders_detected), None
    )

    has_profile, profile_summary = _summarize_profile(profile_records)

    return NightscoutDiscoveryReport(
        status_ok=True,
        server_version=outcome.server_version,
        earliest_entry_at=earliest_entry_at,
        entry_count_estimate=entry_count_estimate,
        recent_entry_count_7d=recent_entry_count_7d,
        uploaders_detected=sorted(uploaders_detected),
        has_treatments=len(treatments) > 0,
        treatment_count_estimate=len(treatments),
        has_devicestatus=len(devicestatuses) > 0,
        has_profile=has_profile,
        profile_summary=profile_summary,
        active_pump_loop=active_pump_loop,
        partial_resources=partial_resources,
        evaluated_at=evaluated_at,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _safe_fetch(
    coro: Any, *, label: str
) -> tuple[list[dict[str, Any]], bool]:
    """Run a fetch coroutine and swallow per-resource failures.

    The discovery report is degrade-gracefully by design: if
    treatments are unreachable but entries work, we still report the
    entries half. The connection test (step 1 in the orchestrator)
    has already confirmed the URL + credential are valid, so a per-
    resource error here means EITHER a 404 / 5xx on that specific
    endpoint OR a per-collection token scope restriction (v3
    instances can issue tokens that grant entries but not
    treatments). The orchestrator surfaces the failed resource
    name on `report.partial_resources` so the wizard can show
    "your token might be scope-restricted" instead of silently
    claiming the data is absent.

    Returns `(rows, success_flag)`. Logged at WARNING (not INFO)
    because partial failures change wizard UX and deserve operator
    visibility.
    """
    try:
        result = await coro
    except Exception as exc:  # noqa: BLE001 - report graceful degrade
        logger.warning(
            "nightscout_evaluate_partial",
            resource=label,
            error_type=type(exc).__name__,
        )
        return [], False
    rows = result if isinstance(result, list) else []
    return rows, True


def _earliest_entry_timestamp(entries: list[dict[str, Any]]) -> datetime | None:
    """Pull the oldest entry from a newest-first page.

    Tries `dateString` first (NS canonical) then `sysTime` as a
    backstop. Returns None when the page is empty or no parseable
    timestamp is present.
    """
    if not entries:
        return None
    # NS server returns newest-first; the LAST element is the oldest
    # in the page.
    candidate = entries[-1]
    for key in ("dateString", "sysTime"):
        value = candidate.get(key)
        if isinstance(value, str):
            parsed = _parse_iso(value)
            if parsed is not None:
                return parsed
    # date is epoch ms (the v1 entries collection's primary timestamp)
    date_ms = candidate.get("date")
    if isinstance(date_ms, int | float):
        try:
            return datetime.fromtimestamp(date_ms / 1000.0, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 string into a UTC datetime, or None on failure."""
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _detect_uploaders(
    entries: list[dict[str, Any]],
    treatments: list[dict[str, Any]],
    devicestatuses: list[dict[str, Any]],
) -> set[str]:
    """Fold `detect_uploader()` over a sample of records.

    Excludes "unknown" so a sparse / generic-uploader sample doesn't
    populate the wizard's chips with an unhelpful tag.
    """
    found: set[str] = set()
    for record in entries + treatments + devicestatuses:
        if not isinstance(record, dict):
            continue
        uploader = detect_uploader(
            record.get("enteredBy"), record.get("device")
        )
        if uploader != "unknown":
            found.add(uploader)
    return found


def _summarize_profile(
    profile_records: list[dict[str, Any]],
) -> tuple[bool, NightscoutDiscoveryProfileSummary | None]:
    """Build the profile_summary portion of the discovery report.

    AC11: malformed / unparseable profile returns
    `(False, summary(is_malformed=True))` so the wizard renders a
    "skipped" panel instead of crashing.
    """
    if not profile_records:
        return False, None

    # NS server returns newest-first by `startDate`; take the freshest
    # profile record. The wizard surfaces the active store via the
    # NightscoutProfile.active_profile() helper which already handles
    # the `defaultProfile` indirection.
    raw = profile_records[0]
    try:
        profile = NightscoutProfile.model_validate(raw)
    except Exception:  # noqa: BLE001 - AC11 graceful degrade
        logger.info("nightscout_evaluate_profile_unparseable")
        return False, NightscoutDiscoveryProfileSummary(is_malformed=True)

    active = profile.active_profile()
    if active is None:
        # Profile record exists but has no usable store -- treat as
        # missing rather than malformed; the wizard's "skip settings"
        # branch is the right UX.
        return False, None

    target_low_segments = active.target_low or None
    target_high_segments = active.target_high or None
    target_low_value = _safe_min_segment_value(target_low_segments)
    target_high_value = _safe_max_segment_value(target_high_segments)

    summary = NightscoutDiscoveryProfileSummary(
        target_low=target_low_value,
        target_high=target_high_value,
        dia_hours=active.dia,
        units=active.units or profile.units,
        timezone=active.timezone,
        carb_ratio_schedule=_to_segment_dtos(active.carbratio),
        isf_schedule=_to_segment_dtos(active.sens),
        basal_schedule=_to_segment_dtos(active.basal),
        target_low_schedule=_to_segment_dtos(target_low_segments),
        target_high_schedule=_to_segment_dtos(target_high_segments),
        is_malformed=False,
    )
    return True, summary


def _to_segment_dtos(
    raw: list[dict[str, Any]] | None,
) -> list[NightscoutProfileSegmentDTO] | None:
    """Convert raw profile segments into the response DTO list.

    Drops segments that are missing `time` or `value`; if the result
    is empty, returns None so the wizard's "schedule absent" branch
    fires cleanly.
    """
    if not raw:
        return None
    out: list[NightscoutProfileSegmentDTO] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        time_str = entry.get("time")
        value = entry.get("value")
        if not isinstance(time_str, str):
            continue
        try:
            float_value = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        out.append(
            NightscoutProfileSegmentDTO(time=time_str, value=float_value)
        )
    return out or None


def _safe_min_segment_value(
    segments: list[dict[str, Any]] | None,
) -> float | None:
    """Min `value` across segments, kept as float. None when absent.

    Float-precision matters for mmol/L profiles where targets are
    sub-ten decimals (e.g. 4.4-7.8). The wizard / 43.7b derive
    handles unit normalization at render / write time.
    """
    values = _segment_values(segments)
    return min(values) if values else None


def _safe_max_segment_value(
    segments: list[dict[str, Any]] | None,
) -> float | None:
    """Max `value` across segments, kept as float. None when absent."""
    values = _segment_values(segments)
    return max(values) if values else None


def _segment_values(
    segments: list[dict[str, Any]] | None,
) -> list[float]:
    """Coerce segment `value` fields to floats, dropping non-numeric."""
    if not segments:
        return []
    out: list[float] = []
    for entry in segments:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        try:
            out.append(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return out


# Maximum plausible per-instance entry count to surface in the
# wizard prose. CGM uploads at ~288 readings/day = ~105K/year; a
# 5-year retention plus treatments / devicestatus tops ~10M. 100M
# leaves a generous ceiling without blowing up if our extrapolation
# math goes haywire on a degenerate sample.
_ENTRY_COUNT_CEILING = 100_000_000


def _estimate_total_entries(
    *,
    recent_count_7d: int,
    earliest_at: datetime | None,
    sample_size: int,
    now: datetime,
) -> int:
    """Extrapolate total entry count from the recent-7d rate.

    Falls back to `sample_size` when extrapolation isn't viable:
    - no `earliest_at` (oldest probe failed)
    - `earliest_at` within 7 days of now (no extrapolation distance)
    - zero recent activity (rate would be 0; the actual sampled
      count is the better estimate)

    Always >= sample_size so we never report fewer entries than we
    directly observed; <= _ENTRY_COUNT_CEILING so a degenerate input
    doesn't blow up the wizard prose.
    """
    if (
        earliest_at is None
        or recent_count_7d <= 0
    ):
        return sample_size

    span_days = (now - earliest_at).total_seconds() / 86400
    if span_days < 7:
        # Less than a week of history; the 7-day count IS the total.
        return max(recent_count_7d, sample_size)

    per_day_rate = recent_count_7d / 7.0
    extrapolated = int(per_day_rate * span_days)
    estimate = max(extrapolated, sample_size)
    return min(estimate, _ENTRY_COUNT_CEILING)
