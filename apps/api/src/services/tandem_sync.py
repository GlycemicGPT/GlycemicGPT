"""Story 3.4 & 3.5: Tandem Pump Data Sync Service.

Handles fetching pump data from Tandem t:connect API and storing them,
including Control-IQ activity parsing.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from tconnectsync.api.common import ApiException
from tconnectsync.api.tandemsource import TandemSourceApi

from src.config import settings
from src.core.encryption import decrypt_credential
from src.logging_config import get_logger
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)
from src.models.pump_data import ControlIQMode, PumpEvent, PumpEventType
from src.models.pump_profile import PumpProfile

logger = get_logger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class TandemSyncError(Exception):
    """Base exception for Tandem sync errors."""

    pass


class TandemNotConfiguredError(TandemSyncError):
    """Tandem integration is not configured for this user."""

    pass


class TandemAuthError(TandemSyncError):
    """Authentication failed with Tandem."""

    pass


class TandemConnectionError(TandemSyncError):
    """Connection to Tandem failed."""

    pass


@dataclass
class ParsedEventData:
    """Parsed Control-IQ event data from tconnectsync."""

    event_type: PumpEventType
    is_automated: bool
    control_iq_reason: str | None
    control_iq_mode: ControlIQMode | None
    basal_adjustment_pct: float | None


def detect_control_iq_mode(event_data: dict) -> ControlIQMode | None:
    """Detect the Control-IQ mode active during an event.

    Args:
        event_data: Event dictionary from tconnectsync parser

    Returns:
        ControlIQMode or None if not determinable
    """
    # Check various field names that might indicate mode
    mode_indicators = [
        event_data.get("activityType", ""),
        event_data.get("activity_type", ""),
        event_data.get("mode", ""),
        event_data.get("controlIQMode", ""),
        event_data.get("control_iq_mode", ""),
    ]

    for indicator in mode_indicators:
        if not indicator:
            continue
        indicator_lower = str(indicator).lower()
        if "sleep" in indicator_lower:
            return ControlIQMode.SLEEP
        if "exercise" in indicator_lower:
            return ControlIQMode.EXERCISE
        if "standard" in indicator_lower or "normal" in indicator_lower:
            return ControlIQMode.STANDARD

    # Check for sleep/exercise flags
    if event_data.get("isSleepMode") or event_data.get("is_sleep_mode"):
        return ControlIQMode.SLEEP
    if event_data.get("isExerciseMode") or event_data.get("is_exercise_mode"):
        return ControlIQMode.EXERCISE

    return None


def calculate_basal_adjustment(event_data: dict) -> float | None:
    """Calculate the basal rate adjustment percentage from event data.

    Args:
        event_data: Event dictionary from tconnectsync parser

    Returns:
        Percentage adjustment (positive = increase, negative = decrease) or None
    """
    # Try to get direct adjustment percentage
    for pct_key in [
        "adjustmentPercent",
        "adjustment_percent",
        "percentChange",
        "percent_change",
    ]:
        if pct_key in event_data:
            try:
                return float(event_data[pct_key])
            except (ValueError, TypeError):
                pass

    # Try to calculate from profile rate vs actual rate
    profile_rate = None
    actual_rate = None

    for profile_key in [
        "profileRate",
        "profile_rate",
        "scheduledRate",
        "scheduled_rate",
    ]:
        if profile_key in event_data:
            try:
                profile_rate = float(event_data[profile_key])
                break
            except (ValueError, TypeError):
                pass

    for actual_key in ["rate", "actualRate", "actual_rate", "deliveredRate"]:
        if actual_key in event_data:
            try:
                actual_rate = float(event_data[actual_key])
                break
            except (ValueError, TypeError):
                pass

    if profile_rate and actual_rate and profile_rate > 0:
        # Calculate percentage difference
        adjustment = ((actual_rate - profile_rate) / profile_rate) * 100
        return round(adjustment, 1)

    return None


def map_event_type(event_data: dict) -> tuple[PumpEventType, bool, str | None]:
    """Map tconnectsync event data to our PumpEventType.

    Args:
        event_data: Event dictionary from tconnectsync parser

    Returns:
        Tuple of (event_type, is_automated, control_iq_reason)

    Note:
        For full Control-IQ parsing including mode and basal adjustment,
        use parse_control_iq_event() instead.
    """
    event_type_str = (event_data.get("type") or "").lower()

    # BG reading events are informational (IoB snapshot, not insulin delivery)
    if event_type_str == "bg_reading":
        return PumpEventType.BG_READING, False, None

    # Check automation flags from tconnectsync
    is_automated = (
        event_data.get("isAutomated", False)
        or event_data.get("is_automated", False)
        or "auto" in event_type_str
    )

    control_iq_reason = None

    # Determine event type - order matters for specificity
    if "suspend" in event_type_str:
        if is_automated:
            control_iq_reason = "suspend"
        return PumpEventType.SUSPEND, is_automated, control_iq_reason

    if "resume" in event_type_str:
        return PumpEventType.RESUME, is_automated, control_iq_reason

    if "correction" in event_type_str:
        # Corrections are always automated (Control-IQ)
        return PumpEventType.CORRECTION, True, "correction"

    if "bolus" in event_type_str:
        # Check if it's an automated correction bolus
        if is_automated:
            return PumpEventType.CORRECTION, True, "correction"
        return PumpEventType.BOLUS, False, None

    if "basal" in event_type_str:
        if is_automated:
            control_iq_reason = "basal_adjustment"
        return PumpEventType.BASAL, is_automated, control_iq_reason

    # Default to bolus for unknown types
    logger.warning("Unknown event type, defaulting to BOLUS", event_type=event_type_str)
    return PumpEventType.BOLUS, is_automated, control_iq_reason


def parse_control_iq_event(event_data: dict) -> ParsedEventData:
    """Parse a tconnectsync event with full Control-IQ activity data.

    This is the comprehensive parser for Story 3.5 that extracts:
    - Event type (basal, bolus, correction, suspend, resume)
    - Automation status (is this a Control-IQ action?)
    - Control-IQ reason (correction, basal_adjustment, suspend)
    - Control-IQ mode (Sleep, Exercise, Standard)
    - Basal adjustment percentage

    Args:
        event_data: Event dictionary from tconnectsync parser

    Returns:
        ParsedEventData with all Control-IQ fields populated
    """
    # Get basic event info
    event_type, is_automated, control_iq_reason = map_event_type(event_data)

    # Detect Control-IQ mode
    control_iq_mode = detect_control_iq_mode(event_data)

    # Calculate basal adjustment for basal events
    basal_adjustment_pct = None
    if event_type == PumpEventType.BASAL and is_automated:
        basal_adjustment_pct = calculate_basal_adjustment(event_data)

        # Refine the reason based on adjustment direction
        if basal_adjustment_pct is not None:
            if basal_adjustment_pct > 0:
                control_iq_reason = "basal_increase"
            elif basal_adjustment_pct < 0:
                control_iq_reason = "basal_decrease"
            else:
                control_iq_reason = "basal_unchanged"

    return ParsedEventData(
        event_type=event_type,
        is_automated=is_automated,
        control_iq_reason=control_iq_reason,
        control_iq_mode=control_iq_mode,
        basal_adjustment_pct=basal_adjustment_pct,
    )


# Map tconnectsync event IDs to our event type strings.
# See tconnectsync/eventparser/events.py for the full list.
_EVENT_ID_TYPE_MAP: dict[int, str] = {
    3: "basal",  # LidBasalRateChange
    16: "bg_reading",  # LidBgReadingTaken - has IoB and BG from pump
    # Event 20 (LidBolusCompleted) intentionally excluded — it duplicates
    # event 280 (LidBolusDelivery) for the same physical bolus with less data.
    279: "basal",  # LidBasalDelivery
    280: "bolus",  # LidBolusDelivery
    # We skip CGM events (399: LidCgmDataG7) — glucose comes from Dexcom directly
}

# LidBasalRateChange changetype values that indicate Control-IQ automation.
_AUTOMATED_BASAL_CHANGE_TYPES = {2, 3, 4, 5}


def _normalize_pump_event(event, _seen_ids: set | None = None) -> dict | None:
    """Convert a tconnectsync event object into a dict for storage.

    Maps tconnectsync field names to the names expected by our parsing layer
    (map_event_type, parse_control_iq_event, and the storage loop).

    Returns None for unsupported event types that should be skipped.
    """
    try:
        d = event.todict()
    except (AttributeError, TypeError):
        return None

    # tconnectsync uses "id" (string) for the event type ID
    raw_id = d.get("id") or d.get("eventId") or d.get("event_id")
    try:
        event_id = int(raw_id) if raw_id is not None else None
    except (ValueError, TypeError):
        event_id = None
    event_type = _EVENT_ID_TYPE_MAP.get(event_id)
    if not event_type:
        # Track unmapped event IDs for the caller's summary log
        if _seen_ids is not None:
            _seen_ids.add(event_id)
        return None

    # Normalize timestamp — may be Arrow, datetime, or ISO string
    ts = d.get("eventTimestamp")
    if ts is None:
        return None
    try:
        d["timestamp"] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    except Exception:
        return None
    # Also set eventDateTime for the storage loop's timestamp lookup
    d["eventDateTime"] = d["timestamp"]

    d["type"] = event_type

    # Helper: tconnectsync values may come as strings
    def _float(key: str) -> float | None:
        v = d.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _int(key: str) -> int | None:
        v = d.get(key)
        if v is None:
            return None
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None

    # Normalize insulin delivery (bolus events)
    for units_key in ("insulindelivered", "InsulinDelivered"):
        if units_key in d:
            d["units"] = _float(units_key)
            break

    # Event 280 (LidBolusDelivery): deliveredTotal is in milliunits
    if event_id == 280:
        # Skip "Bolus Started" (status 1) — only process "Bolus Completed" (status 0)
        # to avoid duplicate records for the same physical bolus.
        delivery_status = _int("bolusDeliveryStatusRaw")
        if delivery_status == 1:
            return None

        delivered_mu = _int("deliveredTotal")
        if delivered_mu is not None:
            d["units"] = delivered_mu / 1000.0
        # Detect Control-IQ correction bolus
        bolus_source = _int("bolusSourceRaw")
        bolus_type = _int("bolusTypeRaw")
        if bolus_source == 7:  # Algorithm (Control-IQ)
            d["isAutomated"] = True
        if bolus_type is not None and (bolus_type & 0x08):  # Correction bit
            d["isAutomated"] = True
            d["type"] = "correction"
        # Store correction portion separately if present
        correction_mu = _int("correction")
        if correction_mu and correction_mu > 0:
            d["correction_units"] = correction_mu / 1000.0

    # Event 279 (LidBasalDelivery): rates are in milliunits/hr
    if event_id == 279:
        commanded_mu = _int("commandedRate")
        profile_mu = _int("profileBasalRate")
        if commanded_mu is not None:
            d["actualRate"] = commanded_mu / 1000.0
            d["units"] = commanded_mu / 1000.0  # Store rate for aggregation
        if profile_mu is not None:
            d["profileRate"] = profile_mu / 1000.0
        # Detect Control-IQ automation via commandedRateSource
        rate_source = _int("commandedRateSourceRaw")
        if rate_source in (0, 3, 4):  # Suspended, Algorithm, TempRate+Algorithm
            d["isAutomated"] = True
        if rate_source == 0:
            d["type"] = "suspend"

    # Normalize IoB (uppercase in tconnectsync, present in event ID 16)
    if "IOB" in d:
        d["iob"] = _float("IOB")

    # Normalize BG from pump (event ID 16: LidBgReadingTaken)
    if "BG" in d:
        d["bg"] = _int("BG")

    # Normalize basal rates for adjustment calculation (event ID 3)
    if "commandedbasalrate" in d:
        d["actualRate"] = _float("commandedbasalrate")
        if d.get("actualRate") is not None:
            d["units"] = d["actualRate"]  # Store rate for aggregation
    if "basebasalrate" in d:
        d["profileRate"] = _float("basebasalrate")

    # Detect automation for basal rate changes (event ID 3)
    if event_id == 3:
        changetype = _int("changetypeRaw") or 0
        d["isAutomated"] = changetype in _AUTOMATED_BASAL_CHANGE_TYPES

    return d


def fetch_with_retry(
    api: TandemSourceApi,
    start_date: datetime,
    end_date: datetime,
    max_retries: int = MAX_RETRIES,
) -> tuple[list[dict], dict | None]:
    """Fetch pump events with retry logic for transient failures.

    Gets pump metadata to find device IDs, then fetches events via
    the pump_events() method and normalizes them into dicts. Also
    extracts raw pump settings from the metadata for profile storage.

    Args:
        api: TandemSourceApi instance
        start_date: Start of date range
        end_date: End of date range
        max_retries: Maximum retry attempts

    Returns:
        Tuple of (normalized event dicts, raw settings dict or None)

    Raises:
        ApiException: If all retries fail
    """
    import time

    # Get pump metadata to discover device IDs
    metadata = api.pump_event_metadata()
    if not metadata:
        logger.warning("No pumps found in Tandem account")
        return [], None

    # Handle both list and dict response structures
    if isinstance(metadata, dict):
        if "tconnectDeviceId" in metadata:
            metadata = [metadata]
        else:
            # Try common wrapper keys
            for key in ("pumps", "devices", "data"):
                if key in metadata and isinstance(metadata[key], list):
                    metadata = metadata[key]
                    break
            else:
                logger.warning(
                    "Unexpected pump_event_metadata structure",
                    keys=list(metadata.keys()),
                )
                return [], None

    # Format dates as YYYY-MM-DD strings (required by tconnectsync API)
    min_date_str = start_date.strftime("%Y-%m-%d")
    max_date_str = end_date.strftime("%Y-%m-%d")

    all_events: list[dict] = []
    raw_settings: dict | None = None

    for pump_info in metadata:
        device_id = pump_info.get("tconnectDeviceId")
        if not device_id:
            continue

        # Extract pump settings from the first pump that has them
        if raw_settings is None:
            last_upload = pump_info.get("lastUpload") or {}
            settings_data = last_upload.get("settings")
            if settings_data:
                raw_settings = settings_data
                logger.info(
                    "Found pump settings in metadata",
                    device_id=device_id,
                )

        serial = pump_info.get("serialNumber", "")
        redacted_serial = f"***{serial[-4:]}" if len(serial) >= 4 else "***"
        logger.info(
            "Fetching events for pump",
            device_id=device_id,
            serial=redacted_serial,
            min_date=min_date_str,
            max_date=max_date_str,
        )

        seen_ids: set = set()
        last_error = None
        for attempt in range(max_retries):
            try:
                events_gen = api.pump_events(
                    device_id,
                    min_date=min_date_str,
                    max_date=max_date_str,
                    fetch_all_event_types=True,
                )
                # Consume generator and normalize events
                raw_count = 0
                for event in events_gen:
                    raw_count += 1
                    normalized = _normalize_pump_event(event, _seen_ids=seen_ids)
                    if normalized:
                        all_events.append(normalized)
                logger.info(
                    "Processed pump events",
                    device_id=device_id,
                    raw_events=raw_count,
                    normalized_events=len(all_events),
                    skipped_event_ids=sorted(seen_ids - set(_EVENT_ID_TYPE_MAP.keys())),
                )
                break  # Success for this pump
            except ApiException as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(
                        "Tandem API call failed, retrying",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        device_id=device_id,
                        error=str(e),
                    )
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    raise
        if last_error and not all_events:
            raise last_error

    logger.info("Fetched pump events", total_events=len(all_events))
    return all_events, raw_settings


async def _store_pump_settings(
    db: AsyncSession,
    user_id: uuid.UUID,
    raw_settings: dict,
) -> int:
    """Parse and upsert pump profiles from Tandem metadata settings.

    Deserializes the raw settings dict via tconnectsync's PumpSettings
    dataclass, converts milliunits to units, and upserts each profile
    into the pump_profiles table.

    Args:
        db: Database session.
        user_id: User ID to associate profiles with.
        raw_settings: Raw settings dict from pump_event_metadata().

    Returns:
        Number of profiles stored.
    """
    from tconnectsync.domain.tandemsource.pump_settings import PumpSettings

    pump_settings = PumpSettings.from_dict(raw_settings)
    now = datetime.now(UTC)
    profiles_stored = 0

    active_idp = getattr(pump_settings.profiles, "activeIdp", None)
    profile_list = getattr(pump_settings.profiles, "profile", None) or []

    # Extract CGM alert thresholds
    cgm_high = None
    cgm_low = None
    try:
        cgm = pump_settings.cgmSettings
        if cgm.highGlucoseAlert and cgm.highGlucoseAlert.enabled:
            cgm_high = cgm.highGlucoseAlert.mgPerDl
        if cgm.lowGlucoseAlert and cgm.lowGlucoseAlert.enabled:
            cgm_low = cgm.lowGlucoseAlert.mgPerDl
    except (AttributeError, TypeError):
        pass

    skipped = 0
    for profile in profile_list:
        try:
            # Sanitize and truncate profile name to fit String(100) column
            raw_name = getattr(profile, "name", None) or "Unknown"
            profile_name = raw_name.replace("\x00", "")[:100]

            # Build segments JSONB array with defensive access
            segments = []
            for seg in getattr(profile, "tDependentSegs", None) or []:
                try:
                    start_time = int(getattr(seg, "startTime", 0) or 0)
                    # Clamp to valid range (0-1439 minutes in a day)
                    start_time = max(0, min(start_time, 1439))

                    hours = start_time // 60
                    minutes = start_time % 60
                    period = "AM" if hours < 12 else "PM"
                    display_hour = hours % 12 or 12
                    time_str = f"{display_hour}:{minutes:02d} {period}"

                    basal_raw = getattr(seg, "basalRate", 0) or 0
                    cr_raw = getattr(seg, "carbRatio", 0) or 0
                    segments.append(
                        {
                            "time": time_str,
                            "start_minutes": start_time,
                            "basal_rate": float(basal_raw) / 1000.0,
                            "correction_factor": int(getattr(seg, "isf", 0) or 0),
                            "carb_ratio": float(cr_raw) / 1000.0,
                            "target_bg": int(getattr(seg, "targetBg", 0) or 0),
                        }
                    )
                except (TypeError, ValueError, AttributeError):
                    logger.warning(
                        "Skipped malformed pump profile segment",
                        user_id=str(user_id),
                        profile_name=profile_name,
                    )
                    continue

            is_active = getattr(profile, "idp", None) == active_idp

            insulin_duration = getattr(profile, "insulinDuration", None)
            carb_entry = getattr(profile, "carbEntry", 1)
            max_bolus_raw = getattr(profile, "maxBolus", 0) or 0

            # Upsert using ON CONFLICT DO UPDATE on (user_id, profile_name)
            stmt = (
                insert(PumpProfile)
                .values(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    profile_name=profile_name,
                    is_active=is_active,
                    segments=segments,
                    insulin_duration_min=insulin_duration,
                    carb_entry_enabled=bool(carb_entry),
                    max_bolus_units=float(max_bolus_raw) / 1000.0,
                    cgm_high_alert_mgdl=cgm_high if is_active else None,
                    cgm_low_alert_mgdl=cgm_low if is_active else None,
                    synced_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_pump_profile_user_name",
                    set_={
                        "is_active": is_active,
                        "segments": segments,
                        "insulin_duration_min": insulin_duration,
                        "carb_entry_enabled": bool(carb_entry),
                        "max_bolus_units": float(max_bolus_raw) / 1000.0,
                        "cgm_high_alert_mgdl": cgm_high if is_active else None,
                        "cgm_low_alert_mgdl": cgm_low if is_active else None,
                        "synced_at": now,
                    },
                )
            )
            await db.execute(stmt)
            profiles_stored += 1
        except Exception:
            skipped += 1
            logger.warning(
                "Failed to store pump profile (skipping)",
                user_id=str(user_id),
                exc_info=True,
            )

    logger.info(
        "Stored pump profiles",
        user_id=str(user_id),
        profiles_stored=profiles_stored,
        skipped=skipped,
        active_idp=active_idp,
    )
    return profiles_stored


async def sync_tandem_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    hours_back: int | None = None,
) -> dict:
    """Sync Tandem pump data for a specific user.

    Args:
        db: Database session
        user_id: User ID to sync for
        hours_back: Hours of history to fetch (default from settings)

    Returns:
        Dict with sync results (events_fetched, events_stored, last_event)

    Raises:
        TandemNotConfiguredError: If integration is not configured
        TandemAuthError: If credentials are invalid
        TandemConnectionError: If connection fails
        TandemSyncError: For other sync errors
    """
    if hours_back is None:
        hours_back = getattr(settings, "tandem_sync_hours_back", 24)

    logger.info(
        "Starting Tandem sync for user",
        user_id=str(user_id),
        hours_back=hours_back,
    )

    # Get user's Tandem credentials
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == user_id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        logger.warning("No Tandem credentials found for user", user_id=str(user_id))
        raise TandemNotConfiguredError("Tandem integration not configured")

    if credential.status == IntegrationStatus.DISCONNECTED:
        logger.warning("Tandem integration is disconnected", user_id=str(user_id))
        raise TandemNotConfiguredError("Tandem integration is disconnected")

    # Decrypt credentials
    try:
        username = decrypt_credential(credential.encrypted_username)
        password = decrypt_credential(credential.encrypted_password)
    except ValueError as e:
        logger.error(
            "Failed to decrypt Tandem credentials",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = "Credential decryption failed"
        await db.commit()
        raise TandemSyncError("Failed to decrypt credentials") from e

    # Get region from credential (default to US for backwards compatibility)
    region = getattr(credential, "region", "US") or "US"

    # Connect to Tandem
    try:
        api = TandemSourceApi(email=username, password=password, region=region)
    except ValueError as e:
        logger.warning(
            "Tandem invalid region",
            user_id=str(user_id),
            region=region,
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = "Invalid region configuration"
        await db.commit()
        raise TandemAuthError("Invalid region") from e
    except ApiException as e:
        error_str = str(e).lower()
        if "login" in error_str or "credential" in error_str or "401" in error_str:
            logger.warning(
                "Tandem authentication failed",
                user_id=str(user_id),
                error=str(e),
            )
            credential.status = IntegrationStatus.ERROR
            credential.last_error = "Authentication failed - check credentials"
            await db.commit()
            raise TandemAuthError("Invalid Tandem credentials") from e
        logger.error(
            "Failed to connect to Tandem",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = f"Connection failed: {str(e)}"
        await db.commit()
        raise TandemConnectionError(f"Failed to connect: {str(e)}") from e
    except Exception as e:
        logger.error(
            "Unexpected error connecting to Tandem",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = f"Connection failed: {str(e)}"
        await db.commit()
        raise TandemConnectionError(f"Failed to connect: {str(e)}") from e

    # Calculate date range
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(hours=hours_back)

    # Fetch events from Tandem with retry logic
    try:
        # Run synchronous API call in thread pool to avoid blocking
        raw_events, raw_settings = await asyncio.to_thread(
            fetch_with_retry, api, start_date, end_date
        )
    except ApiException as e:
        logger.warning(
            "Tandem API error during fetch",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = "API error during data fetch"
        await db.commit()
        raise TandemConnectionError("API error during fetch") from e
    except Exception as e:
        logger.error(
            "Failed to fetch Tandem events",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = f"Fetch failed: {str(e)}"
        await db.commit()
        raise TandemSyncError(f"Failed to fetch events: {str(e)}") from e

    # Store pump settings profiles (graceful degradation - failure doesn't block events)
    profiles_stored = 0
    if raw_settings:
        try:
            profiles_stored = await _store_pump_settings(db, user_id, raw_settings)
        except Exception:
            logger.warning(
                "Failed to store pump settings profiles (non-fatal)",
                user_id=str(user_id),
                exc_info=True,
            )

    # raw_events is a flat list of normalized dicts from fetch_with_retry
    events = raw_events or []

    if not events:
        logger.info("No new events from Tandem", user_id=str(user_id))
        credential.status = IntegrationStatus.CONNECTED
        credential.last_sync_at = datetime.now(UTC)
        credential.last_error = None
        await db.commit()
        return {
            "events_fetched": 0,
            "events_stored": 0,
            "profiles_stored": profiles_stored,
            "last_event": None,
        }

    # Store events (using upsert to handle duplicates)
    now = datetime.now(UTC)
    stored_count = 0
    last_event = None

    for event_data in events:
        # Extract timestamp
        event_time = None
        for time_key in ["timestamp", "time", "datetime", "eventDateTime"]:
            if time_key in event_data:
                time_val = event_data[time_key]
                if isinstance(time_val, datetime):
                    event_time = time_val
                elif isinstance(time_val, str):
                    try:
                        event_time = datetime.fromisoformat(
                            time_val.replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass
                break

        if not event_time:
            continue

        # Parse Control-IQ event data (Story 3.5 enhanced parsing)
        parsed = parse_control_iq_event(event_data)

        # Extract insulin units
        units = None
        for units_key in ["units", "insulin", "deliveredUnits", "value"]:
            if units_key in event_data:
                try:
                    units = float(event_data[units_key])
                    break
                except (ValueError, TypeError):
                    pass

        # Extract duration for basal
        duration_minutes = None
        if parsed.event_type == PumpEventType.BASAL:
            for dur_key in ["duration", "durationMinutes", "duration_minutes"]:
                if dur_key in event_data:
                    try:
                        duration_minutes = int(event_data[dur_key])
                        break
                    except (ValueError, TypeError):
                        pass

        # Extract context values
        iob = None
        for iob_key in ["iob", "insulinOnBoard", "insulin_on_board"]:
            if iob_key in event_data:
                try:
                    iob = float(event_data[iob_key])
                    break
                except (ValueError, TypeError):
                    pass

        cob = None
        for cob_key in ["cob", "carbsOnBoard", "carbs_on_board"]:
            if cob_key in event_data:
                try:
                    cob = float(event_data[cob_key])
                    break
                except (ValueError, TypeError):
                    pass

        bg = None
        for bg_key in ["bg", "glucose", "bloodGlucose", "blood_glucose"]:
            if bg_key in event_data:
                try:
                    bg = int(event_data[bg_key])
                    break
                except (ValueError, TypeError):
                    pass

        # Use PostgreSQL upsert (INSERT ON CONFLICT DO NOTHING)
        stmt = (
            insert(PumpEvent)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                event_type=parsed.event_type,
                event_timestamp=event_time,
                units=units,
                duration_minutes=duration_minutes,
                is_automated=parsed.is_automated,
                control_iq_reason=parsed.control_iq_reason,
                control_iq_mode=parsed.control_iq_mode.value
                if parsed.control_iq_mode
                else None,
                basal_adjustment_pct=parsed.basal_adjustment_pct,
                iob_at_event=iob,
                cob_at_event=cob,
                bg_at_event=bg,
                received_at=now,
                source="tandem",
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "event_timestamp", "event_type"]
            )
        )

        result = await db.execute(stmt)
        if result.rowcount > 0:
            stored_count += 1

        # Track the most recent event
        if last_event is None or event_time > last_event["timestamp"]:
            last_event = {
                "event_type": parsed.event_type.value,
                "timestamp": event_time,
                "units": units,
                "is_automated": parsed.is_automated,
                "control_iq_mode": parsed.control_iq_mode.value
                if parsed.control_iq_mode
                else None,
            }

    # Update integration status
    credential.status = IntegrationStatus.CONNECTED
    credential.last_sync_at = now
    credential.last_error = None
    await db.commit()

    logger.info(
        "Tandem sync completed",
        user_id=str(user_id),
        events_fetched=len(events),
        events_stored=stored_count,
        profiles_stored=profiles_stored,
        last_event_type=last_event["event_type"] if last_event else None,
    )

    return {
        "events_fetched": len(events),
        "events_stored": stored_count,
        "profiles_stored": profiles_stored,
        "last_event": last_event,
    }


async def get_latest_pump_event(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> PumpEvent | None:
    """Get the most recent pump event for a user.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        Most recent PumpEvent or None
    """
    result = await db.execute(
        select(PumpEvent)
        .where(PumpEvent.user_id == user_id)
        .order_by(PumpEvent.event_timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_pump_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    hours: float = 24,
    limit: int = 100,
    event_type: PumpEventType | None = None,
) -> list[PumpEvent]:
    """Get recent pump events for a user.

    Args:
        db: Database session
        user_id: User ID
        hours: Number of hours of history (default 24)
        limit: Maximum events to return (default 100)
        event_type: Optional filter by event type (e.g., PumpEventType.BASAL)

    Returns:
        List of PumpEvent objects, ordered by timestamp descending
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    query = select(PumpEvent).where(
        PumpEvent.user_id == user_id,
        PumpEvent.event_timestamp >= cutoff,
    )

    if event_type:
        query = query.where(PumpEvent.event_type == event_type)

    query = query.order_by(PumpEvent.event_timestamp.desc()).limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_latest_pump_status(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, PumpEvent | None]:
    """Get the latest basal, battery, and reservoir events for a user.

    Returns a dict with keys 'basal', 'battery', 'reservoir' mapped to
    the most recent PumpEvent of each type, or None if no events exist.

    Uses PostgreSQL DISTINCT ON to fetch all three in a single query.
    """
    target_types = [
        PumpEventType.BASAL,
        PumpEventType.BATTERY,
        PumpEventType.RESERVOIR,
    ]
    query = (
        select(PumpEvent)
        .distinct(PumpEvent.event_type)
        .where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_type.in_(target_types),
        )
        .order_by(PumpEvent.event_type, PumpEvent.event_timestamp.desc())
    )
    rows = await db.execute(query)
    events = rows.scalars().all()
    result: dict[str, PumpEvent | None] = {t.value: None for t in target_types}
    for event in events:
        result[event.event_type.value] = event
    return result


@dataclass
class ControlIQActivitySummary:
    """Summary of Control-IQ activity over a time period."""

    total_events: int
    automated_events: int
    manual_events: int

    # Correction boluses
    correction_count: int
    total_correction_units: float

    # Basal adjustments
    basal_increase_count: int
    basal_decrease_count: int
    avg_basal_adjustment_pct: float | None

    # Suspends
    suspend_count: int
    automated_suspend_count: int

    # Mode activity
    sleep_mode_events: int
    exercise_mode_events: int
    standard_mode_events: int

    # Time range
    start_time: datetime
    end_time: datetime


async def get_control_iq_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    hours: int = 24,
) -> ControlIQActivitySummary:
    """Get a summary of Control-IQ activity for a user.

    This aggregates Control-IQ actions to provide context for AI analysis,
    helping the AI focus on what Control-IQ cannot adjust (carb ratios,
    correction factors) rather than what it's already handling automatically.

    Args:
        db: Database session
        user_id: User ID
        hours: Number of hours of history to analyze (default 24)

    Returns:
        ControlIQActivitySummary with aggregated Control-IQ metrics
    """
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(hours=hours)

    # Get all events in the time range
    events = await get_pump_events(db, user_id, hours=hours, limit=1000)

    # Initialize counters
    total_events = len(events)
    automated_events = 0
    manual_events = 0
    correction_count = 0
    total_correction_units = 0.0
    basal_increase_count = 0
    basal_decrease_count = 0
    basal_adjustments = []
    suspend_count = 0
    automated_suspend_count = 0
    sleep_mode_events = 0
    exercise_mode_events = 0
    standard_mode_events = 0

    for event in events:
        # Count automated vs manual
        if event.is_automated:
            automated_events += 1
        else:
            manual_events += 1

        # Count correction boluses
        if event.event_type == PumpEventType.CORRECTION:
            correction_count += 1
            if event.units:
                total_correction_units += event.units

        # Count basal adjustments
        if event.event_type == PumpEventType.BASAL and event.is_automated:
            if event.basal_adjustment_pct is not None:
                basal_adjustments.append(event.basal_adjustment_pct)
                if event.basal_adjustment_pct > 0:
                    basal_increase_count += 1
                elif event.basal_adjustment_pct < 0:
                    basal_decrease_count += 1

        # Count suspends
        if event.event_type == PumpEventType.SUSPEND:
            suspend_count += 1
            if event.is_automated:
                automated_suspend_count += 1

        # Count by mode
        if event.control_iq_mode:
            if event.control_iq_mode == ControlIQMode.SLEEP.value:
                sleep_mode_events += 1
            elif event.control_iq_mode == ControlIQMode.EXERCISE.value:
                exercise_mode_events += 1
            elif event.control_iq_mode == ControlIQMode.STANDARD.value:
                standard_mode_events += 1

    # Calculate average basal adjustment
    avg_basal_adjustment = None
    if basal_adjustments:
        avg_basal_adjustment = round(sum(basal_adjustments) / len(basal_adjustments), 1)

    return ControlIQActivitySummary(
        total_events=total_events,
        automated_events=automated_events,
        manual_events=manual_events,
        correction_count=correction_count,
        total_correction_units=round(total_correction_units, 2),
        basal_increase_count=basal_increase_count,
        basal_decrease_count=basal_decrease_count,
        avg_basal_adjustment_pct=avg_basal_adjustment,
        suspend_count=suspend_count,
        automated_suspend_count=automated_suspend_count,
        sleep_mode_events=sleep_mode_events,
        exercise_mode_events=exercise_mode_events,
        standard_mode_events=standard_mode_events,
        start_time=start_time,
        end_time=end_time,
    )


async def get_automated_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    hours: int = 24,
) -> list[PumpEvent]:
    """Get only Control-IQ automated events for a user.

    Useful for AI analysis to understand what Control-IQ is doing
    automatically before making suggestions.

    Args:
        db: Database session
        user_id: User ID
        hours: Number of hours of history

    Returns:
        List of automated PumpEvent objects
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    result = await db.execute(
        select(PumpEvent)
        .where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= cutoff,
            PumpEvent.is_automated == True,  # noqa: E712
        )
        .order_by(PumpEvent.event_timestamp.desc())
    )
    return list(result.scalars().all())
