"""Tests for Glooko record persistence (cross-source dedupe + idempotency).

Focus: ``store_glooko_records`` now stamps every insulin-delivery row with the
shared cross-source ``dedupe_hash`` (Story 43.11) and upserts via a bare
``ON CONFLICT DO NOTHING`` so a dose typed into Glooko collapses against the
same physical dose relayed via Nightscout careportal -- without breaking the
existing ``(source, ns_id)`` / natural-key re-sync idempotency.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.config import settings
from src.database import get_db
from src.main import app
from src.models.pump_data import PumpEvent, PumpEventType
from src.services.integrations.glooko.mapper import (
    SOURCE,
    MappedPumpEvent,
    MappedRecords,
)
from src.services.integrations.glooko.storage import store_glooko_records
from src.services.pump_event_dedupe import compute_pump_event_dedupe_hash

# Anchor on a 30-second epoch boundary so timestamp offsets land in the bucket
# we intend regardless of when the suite runs.
_BUCKET_BASE = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


async def _register(client: AsyncClient) -> uuid.UUID:
    email = f"glstore-{uuid.uuid4().hex[:10]}@example.com"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": "SecurePass123"}
    )
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    assert login.status_code == 200, login.text
    cookie = login.cookies.get(settings.jwt_cookie_name)
    me = await client.get("/api/auth/me", cookies={settings.jwt_cookie_name: cookie})
    return uuid.UUID(me.json()["id"])


async def _insert_other_source(db, uid, *, ts, units, source, event_type="bolus"):
    """Insert a non-Glooko delivery row via the production bare insert path."""
    row = {
        "id": uuid.uuid4(),
        "user_id": uid,
        "event_type": event_type,
        "event_timestamp": ts,
        "units": units,
        "duration_minutes": None,
        "is_automated": False,
        "received_at": datetime.now(UTC),
        "source": source,
        "ns_id": f"other-{uuid.uuid4().hex}",
        "dedupe_hash": compute_pump_event_dedupe_hash(
            user_id=uid,
            event_type=event_type,
            event_timestamp=ts,
            units=units,
            duration_minutes=None,
        ),
    }
    stmt = (
        insert(PumpEvent).values([row]).on_conflict_do_nothing().returning(PumpEvent.id)
    )
    res = await db.execute(stmt)
    await db.commit()
    return len(res.scalars().all())


async def _bolus_count(db, uid) -> int:
    res = await db.execute(
        select(func.count())
        .select_from(PumpEvent)
        .where(
            PumpEvent.user_id == uid,
            PumpEvent.event_type == PumpEventType.BOLUS,
        )
    )
    return res.scalar_one()


def _glooko_bolus(*, ts, units, guid=None):
    return MappedPumpEvent(
        event_type=PumpEventType.BOLUS,
        timestamp=ts,
        ns_id=guid,
        units=units,
    )


@pytest.mark.asyncio
class TestGlookoCrossSourceDedupe:
    async def test_same_dose_two_sources_collapses(self):
        # A dose relayed via Nightscout careportal then the same physical dose
        # typed into Glooko (0.03 U apart, same 30 s bucket, distinct seconds so
        # the natural key would NOT collapse them) -> one row, first writer wins.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                t_ns = _BUCKET_BASE + timedelta(seconds=4)
                t_glooko = _BUCKET_BASE + timedelta(seconds=12)
                assert (
                    await _insert_other_source(
                        db, uid, ts=t_ns, units=2.50, source="nightscout:1"
                    )
                    == 1
                )

                records = MappedRecords(
                    pump_events=[
                        _glooko_bolus(
                            ts=t_glooko, units=2.53, guid=f"g-{uuid.uuid4().hex}"
                        )
                    ]
                )
                result = await store_glooko_records(db, uid, records)

                assert result.events_stored == 0  # suppressed by dedupe_hash
                assert await _bolus_count(db, uid) == 1
                kept = await db.execute(
                    select(PumpEvent.source).where(PumpEvent.user_id == uid)
                )
                assert kept.scalar_one() == "nightscout:1"
                break

    async def test_distinct_doses_31s_apart_both_persist(self):
        # 31 s apart -> different 30 s buckets -> different hashes -> both kept.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                t_ns = _BUCKET_BASE
                t_glooko = _BUCKET_BASE + timedelta(seconds=31)
                assert (
                    await _insert_other_source(
                        db, uid, ts=t_ns, units=2.50, source="nightscout:1"
                    )
                    == 1
                )

                records = MappedRecords(
                    pump_events=[
                        _glooko_bolus(
                            ts=t_glooko, units=2.50, guid=f"g-{uuid.uuid4().hex}"
                        )
                    ]
                )
                result = await store_glooko_records(db, uid, records)

                assert result.events_stored == 1
                assert await _bolus_count(db, uid) == 2
                break

    async def test_same_hash_two_guids_one_batch_collapses(self):
        # Two distinct Glooko guids in ONE sync batch that quantize to the same
        # dedupe bucket (same units, distinct seconds inside one 30 s window).
        # Both land in the guid batch, so a single multi-row INSERT under bare
        # ON CONFLICT DO NOTHING must collapse them on the (user_id, dedupe_hash)
        # index rather than raise unique_violation.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                records = MappedRecords(
                    pump_events=[
                        _glooko_bolus(
                            ts=_BUCKET_BASE + timedelta(seconds=4),
                            units=2.5,
                            guid=f"g-{uuid.uuid4().hex}",
                        ),
                        _glooko_bolus(
                            ts=_BUCKET_BASE + timedelta(seconds=12),
                            units=2.5,
                            guid=f"g-{uuid.uuid4().hex}",
                        ),
                    ]
                )
                result = await store_glooko_records(db, uid, records)

                assert result.events_stored == 1
                assert await _bolus_count(db, uid) == 1
                break


@pytest.mark.asyncio
class TestGlookoResyncIdempotency:
    async def test_guid_bolus_resync_is_idempotent(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                guid = f"g-{uuid.uuid4().hex}"
                records = MappedRecords(
                    pump_events=[_glooko_bolus(ts=_BUCKET_BASE, units=4.0, guid=guid)]
                )
                first = await store_glooko_records(db, uid, records)
                assert first.events_stored == 1

                # Re-sync the exact same record: the (source, ns_id) index must
                # still arbitrate even though dedupe_hash is now populated.
                second = await store_glooko_records(
                    db,
                    uid,
                    MappedRecords(
                        pump_events=[
                            _glooko_bolus(ts=_BUCKET_BASE, units=4.0, guid=guid)
                        ]
                    ),
                )
                assert second.events_stored == 0
                assert await _bolus_count(db, uid) == 1
                break

    async def test_guidless_event_resync_is_idempotent(self):
        # SUSPEND carries no units and no guid -> dedupe_hash is None (opts out
        # of the cross-source index); the natural key must still dedupe re-syncs.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                event = MappedPumpEvent(
                    event_type=PumpEventType.SUSPEND, timestamp=_BUCKET_BASE
                )
                first = await store_glooko_records(
                    db, uid, MappedRecords(pump_events=[event])
                )
                assert first.events_stored == 1
                second = await store_glooko_records(
                    db,
                    uid,
                    MappedRecords(
                        pump_events=[
                            MappedPumpEvent(
                                event_type=PumpEventType.SUSPEND, timestamp=_BUCKET_BASE
                            )
                        ]
                    ),
                )
                assert second.events_stored == 0
                res = await db.execute(
                    select(func.count())
                    .select_from(PumpEvent)
                    .where(
                        PumpEvent.user_id == uid,
                        PumpEvent.event_type == PumpEventType.SUSPEND,
                    )
                )
                assert res.scalar_one() == 1
                break


@pytest.mark.asyncio
class TestGlookoDedupeHashPopulation:
    """BOLUS and BASAL get a hash; non-delivery telemetry opts out (None)."""

    async def test_delivery_rows_hashed_telemetry_opts_out(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                records = MappedRecords(
                    pump_events=[
                        _glooko_bolus(
                            ts=_BUCKET_BASE, units=3.0, guid=f"g-{uuid.uuid4().hex}"
                        ),
                        MappedPumpEvent(
                            event_type=PumpEventType.BASAL,
                            timestamp=_BUCKET_BASE + timedelta(minutes=5),
                            ns_id=f"g-{uuid.uuid4().hex}",
                            units=0.8,
                            duration_minutes=30,
                        ),
                        MappedPumpEvent(
                            event_type=PumpEventType.DEVICE_EVENT,
                            timestamp=_BUCKET_BASE + timedelta(minutes=10),
                            ns_id=f"g-{uuid.uuid4().hex}",
                            metadata_json={"glooko_type": "reservoir_change"},
                        ),
                    ]
                )
                await store_glooko_records(db, uid, records)

                rows = await db.execute(
                    select(PumpEvent.event_type, PumpEvent.dedupe_hash).where(
                        PumpEvent.user_id == uid, PumpEvent.source == SOURCE
                    )
                )
                by_type = dict(rows.all())
                assert by_type[PumpEventType.BOLUS] is not None
                assert by_type[PumpEventType.BASAL] is not None
                assert by_type[PumpEventType.DEVICE_EVENT] is None
                break
