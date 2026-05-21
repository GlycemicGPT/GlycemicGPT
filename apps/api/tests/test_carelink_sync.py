"""End-to-end orchestrator test: CareLink export -> parse -> map -> store."""

import uuid
from datetime import UTC, date, timedelta, timezone

import httpx
from sqlalchemy import select

from src.database import get_session_maker
from src.models.glucose import GlucoseReading
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User
from src.services.integrations.medtronic.client import CareLinkClient
from src.services.integrations.medtronic.sync import sync_carelink_for_user

_CSV = (
    "Index,Date,Time,Basal Rate (U/h),Bolus Volume Delivered (U),"
    "Bolus Source,Sensor Glucose (mg/dL)\n"
    "0,2025/01/20,12:00:00,0.85,,,\n"
    "1,2025/01/20,12:05:00,,2.0,BOLUS_WIZARD,\n"
    "2,2025/01/20,12:05:00,,,,140\n"
)


async def _bearer() -> str:
    return "tok"


def _client() -> CareLinkClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/patient/users/me":
            return httpx.Response(200, json={"patientId": "P1"})
        if path == "/patient/reports/generateReport":
            return httpx.Response(200, json={"uuid": "u1"})
        if path == "/patient/reports/reportStatus":
            return httpx.Response(200, json={"status": "COMPLETE"})
        if path == "/patient/reports/reportCsv":
            return httpx.Response(200, text=_CSV)
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CareLinkClient(bearer_provider=_bearer, client=http, poll_interval_seconds=0)


async def _make_user(db) -> uuid.UUID:
    user = User(
        email=f"carelink_sync_{uuid.uuid4().hex[:8]}@example.com", hashed_password="x"
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def test_sync_end_to_end_stores_records():
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        async with _client() as client:
            res = await sync_carelink_for_user(
                db,
                uid,
                start_date=date(2025, 1, 20),
                end_date=date(2025, 1, 20),
                client=client,
            )
        assert res.patient_id == "P1"
        assert res.glucose_stored == 1  # the one Sensor Glucose row
        assert res.events_stored == 2  # basal + bolus

        glucose = (
            (
                await db.execute(
                    select(GlucoseReading).where(GlucoseReading.user_id == uid)
                )
            )
            .scalars()
            .all()
        )
        assert [g.value for g in glucose] == [140]
        event_types = {
            e.event_type
            for e in (
                await db.execute(select(PumpEvent).where(PumpEvent.user_id == uid))
            ).scalars()
        }
        assert event_types == {PumpEventType.BASAL, PumpEventType.BOLUS}


async def test_sync_localizes_naive_times_with_tz():
    """With tz=-05:00, the naive 12:00 pump time is stored as 17:00 UTC."""
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        async with _client() as client:
            await sync_carelink_for_user(
                db,
                uid,
                start_date=date(2025, 1, 20),
                end_date=date(2025, 1, 20),
                client=client,
                tz=timezone(timedelta(hours=-5)),
            )
        sg = (
            await db.execute(
                select(GlucoseReading).where(GlucoseReading.user_id == uid)
            )
        ).scalar_one()
        # 12:05 local (-05:00) -> 17:05 UTC
        assert sg.reading_timestamp.astimezone(UTC).hour == 17
        assert sg.reading_timestamp.astimezone(UTC).minute == 5
