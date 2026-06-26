"""Story 4.5 & 6.3: Real-Time Glucose & Alert Streaming via SSE.

This router provides a real-time data stream for glucose readings
and predictive alerts, allowing the frontend dashboard to receive
updates as they occur.
"""

import asyncio
import json
import uuid as uuid_mod
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.core.auth import DiabeticOrAdminUser
from src.database import get_db_session
from src.logging_config import get_logger
from src.services.cgm_source import get_excluded_cgm_sources
from src.services.dexcom_sync import get_latest_glucose_reading
from src.services.iob_projection import get_iob_projection, get_user_dia
from src.services.predictive_alerts import get_active_alerts

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/glucose", tags=["glucose-stream"])


def format_sse_event(event_type: str, data: dict, event_id: str | None = None) -> str:
    """Format data as an SSE event.

    Args:
        event_type: The event type (e.g., 'glucose', 'heartbeat')
        data: Dictionary to serialize as JSON data
        event_id: Optional event ID for client tracking

    Returns:
        Formatted SSE event string
    """
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")  # Empty line to end the event
    return "\n".join(lines) + "\n"


async def generate_glucose_stream(
    user_id: str,
    request: Request,
) -> None:
    """Async generator that yields SSE events with glucose data.

    Sends glucose updates every 60 seconds and heartbeats every 30 seconds.
    Handles client disconnection gracefully.

    Note: Creates a fresh database session for each query to avoid
    connection pool exhaustion and stale session issues.

    Args:
        user_id: The authenticated user's ID
        request: The HTTP request (for disconnect detection)

    Yields:
        SSE-formatted event strings
    """
    heartbeat_interval = 30  # seconds
    glucose_interval = 60  # seconds
    last_glucose_check = 0
    event_counter = 0
    delivered_alert_ids: set[str] = set()  # Track alerts sent this connection

    logger.info("SSE stream started", user_id=user_id)

    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                logger.info("SSE client disconnected", user_id=user_id)
                break

            current_time = asyncio.get_event_loop().time()
            event_counter += 1

            # Send glucose data every 60 seconds (or immediately on first request)
            if (
                current_time - last_glucose_check >= glucose_interval
                or last_glucose_check == 0
            ):
                last_glucose_check = current_time

                try:
                    # Create fresh database session for each query (Issue 4 fix)
                    async with get_db_session() as db:
                        # Get latest glucose reading from the primary CGM
                        # source only (Story 43.10) so the live tile doesn't
                        # flip between two sources reporting the same sensor.
                        excluded = await get_excluded_cgm_sources(db, user_id)
                        latest = await get_latest_glucose_reading(
                            db, user_id, excluded_sources=excluded
                        )

                        if latest:
                            now = datetime.now(UTC)
                            reading_time = latest.reading_timestamp
                            if reading_time.tzinfo is None:
                                reading_time = reading_time.replace(tzinfo=UTC)

                            minutes_ago = int((now - reading_time).total_seconds() / 60)
                            is_stale = minutes_ago > 10

                            # Get IoB projection if available
                            iob_data = None
                            try:
                                dia = await get_user_dia(db, user_id)
                                projection = await get_iob_projection(
                                    db, user_id, dia_hours=dia
                                )
                                if projection:
                                    iob_data = {
                                        "current": projection.projected_iob,
                                        "is_stale": projection.is_stale,
                                    }
                            except Exception as e:
                                logger.warning(
                                    "Failed to get IoB projection", error=str(e)
                                )

                            glucose_event = {
                                # Canonical mg/dL. Clients render using
                                # the user's glucose_unit preference.
                                "value": latest.value,
                                "trend": latest.trend.value
                                if latest.trend
                                else "Unknown",
                                "trend_rate": latest.trend_rate,
                                "reading_timestamp": latest.reading_timestamp.isoformat(),
                                "minutes_ago": minutes_ago,
                                "is_stale": is_stale,
                                "iob": iob_data,
                                "timestamp": now.isoformat(),
                            }

                            yield format_sse_event(
                                event_type="glucose",
                                data=glucose_event,
                                event_id=str(event_counter),
                            )
                        else:
                            # No readings available
                            yield format_sse_event(
                                event_type="no_data",
                                data={
                                    "message": "No glucose readings available",
                                    "timestamp": datetime.now(UTC).isoformat(),
                                },
                                event_id=str(event_counter),
                            )

                except Exception as e:
                    logger.error("Error fetching glucose data for SSE", error=str(e))
                    yield format_sse_event(
                        event_type="error",
                        data={
                            "message": "Failed to fetch glucose data",
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                        event_id=str(event_counter),
                    )

                # Story 6.3: Check for new active alerts to deliver
                try:
                    async with get_db_session() as alert_db:
                        user_uuid = uuid_mod.UUID(user_id)
                        active_alerts = await get_active_alerts(
                            alert_db, user_uuid, limit=10
                        )
                        for alert in active_alerts:
                            alert_id_str = str(alert.id)
                            if alert_id_str not in delivered_alert_ids:
                                delivered_alert_ids.add(alert_id_str)
                                event_counter += 1
                                yield format_sse_event(
                                    event_type="alert",
                                    data={
                                        "id": alert_id_str,
                                        "alert_type": alert.alert_type.value,
                                        "severity": alert.severity.value,
                                        "current_value": alert.current_value,
                                        "predicted_value": alert.predicted_value,
                                        "prediction_minutes": alert.prediction_minutes,
                                        "iob_value": alert.iob_value,
                                        "message": alert.message,
                                        "trend_rate": alert.trend_rate,
                                        "source": alert.source,
                                        "created_at": alert.created_at.isoformat(),
                                        "expires_at": alert.expires_at.isoformat(),
                                    },
                                    event_id=str(event_counter),
                                )
                except Exception as e:
                    logger.warning(
                        "Error checking alerts for SSE",
                        user_id=user_id,
                        error=str(e),
                    )

            # Wait for heartbeat interval then send heartbeat
            await asyncio.sleep(heartbeat_interval)

            # Check for disconnect again after sleep
            if await request.is_disconnected():
                logger.info("SSE client disconnected during sleep", user_id=user_id)
                break

            event_counter += 1
            yield format_sse_event(
                event_type="heartbeat",
                data={"timestamp": datetime.now(UTC).isoformat()},
                event_id=str(event_counter),
            )

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled", user_id=user_id)
    except Exception as e:
        logger.error("SSE stream error", user_id=user_id, error=str(e))
        raise
    finally:
        logger.info("SSE stream ended", user_id=user_id)


@router.get(
    "/stream",
    responses={
        200: {
            "description": "SSE stream of glucose updates",
            "content": {"text/event-stream": {}},
        },
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
    },
)
async def stream_glucose(
    request: Request,
    current_user: DiabeticOrAdminUser,
) -> StreamingResponse:
    """Stream glucose updates via Server-Sent Events.

    Provides real-time glucose data and alerts for the dashboard. Events include:
    - `glucose`: Current glucose reading with trend and IoB data
    - `alert`: New predictive or threshold-based alert (Story 6.3)
    - `heartbeat`: Keep-alive signal every 30 seconds
    - `no_data`: Sent when no glucose readings are available
    - `error`: Sent when there's an error fetching data

    The stream sends glucose updates every 60 seconds to match
    the CGM update frequency (Dexcom G6/G7 updates every 5 minutes,
    but we check more frequently for freshness).

    Returns:
        StreamingResponse with SSE content type
    """
    logger.info(
        "SSE stream requested",
        user_id=str(current_user.id),
        email=current_user.email,
    )

    # Issue 1 fix: Remove CORS header - let CORS middleware handle it
    return StreamingResponse(
        generate_glucose_stream(str(current_user.id), request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
