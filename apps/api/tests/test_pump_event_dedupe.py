"""Tests for cross-source pump-event dedupe (Story 43.11).

Covers the dedupe hash semantics (units/timestamp granularity), the
within-batch collapse helper, and the cross-source partial unique index
behavior through the real insert paths -- mobile push endpoint and the
shared bare ``ON CONFLICT DO NOTHING`` mechanism that Tandem sync, mobile
push, and the Nightscout translator all use.
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
from src.services.pump_event_dedupe import compute_pump_event_dedupe_hash

# Anchor on a 30-second epoch boundary so timestamp offsets land in the
# bucket we intend regardless of when the suite runs.
_BUCKET_BASE = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _hash(user_id, event_type="bolus", *, ts=_BUCKET_BASE, units=2.5, duration=None):
    return compute_pump_event_dedupe_hash(
        user_id=user_id,
        event_type=event_type,
        event_timestamp=ts,
        units=units,
        duration_minutes=duration,
    )


class TestPumpEventDedupeHash:
    """Pure-function semantics of the dedupe hash."""

    def test_returns_none_when_units_none(self):
        # Notes / site changes carry no insulin amount -> opt out of the index.
        assert _hash("u1", event_type="note", units=None) is None

    def test_deterministic(self):
        uid = uuid.uuid4()
        assert _hash(uid) == _hash(uid)

    def test_enum_and_value_hash_identically(self):
        uid = uuid.uuid4()
        from_enum = _hash(uid, event_type=PumpEventType.BOLUS)
        from_value = _hash(uid, event_type="bolus")
        assert from_enum == from_value

    def test_user_scoped(self):
        assert _hash(uuid.uuid4()) != _hash(uuid.uuid4())

    def test_near_match_units_collapse(self):
        # 0.05 U apart within the same 0.1 U bucket -> same hash (AC4 basis).
        uid = uuid.uuid4()
        assert _hash(uid, units=2.50) == _hash(uid, units=2.54)

    def test_near_match_timestamp_collapse(self):
        # A few seconds apart inside the same 30 s bucket -> same hash.
        uid = uuid.uuid4()
        a = _hash(uid, ts=_BUCKET_BASE + timedelta(seconds=3))
        b = _hash(uid, ts=_BUCKET_BASE + timedelta(seconds=11))
        assert a == b

    def test_distinct_units_persist(self):
        # > 0.1 U apart -> different hash (AC5 basis).
        uid = uuid.uuid4()
        assert _hash(uid, units=2.5) != _hash(uid, units=3.0)

    def test_distinct_timestamp_persist(self):
        # > 30 s apart -> different bucket -> different hash (AC5 basis).
        uid = uuid.uuid4()
        a = _hash(uid, ts=_BUCKET_BASE)
        b = _hash(uid, ts=_BUCKET_BASE + timedelta(seconds=45))
        assert a != b

    def test_event_type_distinguishes(self):
        uid = uuid.uuid4()
        assert _hash(uid, event_type="bolus") != _hash(uid, event_type="correction")

    def test_duration_distinguishes(self):
        # Temp basals of the same rate but different duration are distinct.
        uid = uuid.uuid4()
        assert _hash(uid, event_type="basal", duration=30) != _hash(
            uid, event_type="basal", duration=60
        )

    def test_naive_timestamp_treated_as_utc(self):
        uid = uuid.uuid4()
        aware = _hash(uid, ts=_BUCKET_BASE)
        naive = _hash(uid, ts=_BUCKET_BASE.replace(tzinfo=None))
        assert aware == naive

    def test_non_finite_units_return_none(self):
        # inf/nan are nonsensical insulin and would raise in the quantizer;
        # the helper opts them out instead of crashing.
        uid = uuid.uuid4()
        assert _hash(uid, units=float("inf")) is None
        assert _hash(uid, units=float("-inf")) is None
        assert _hash(uid, units=float("nan")) is None

    def test_telemetry_events_not_hashed(self):
        # RESERVOIR/BATTERY carry `units` (units-remaining / percentage) but are
        # status snapshots, not deliveries -- they must not collapse.
        uid = uuid.uuid4()
        assert _hash(uid, event_type="reservoir", units=150.0) is None
        assert _hash(uid, event_type="battery", units=80.0) is None
        # Deliveries still hash.
        assert _hash(uid, event_type="bolus", units=2.5) is not None
        assert _hash(uid, event_type="basal", units=0.65) is not None


class TestMigrationHashParity:
    """The migration inlines a copy of the hash; pin them together."""

    def test_inlined_migration_hash_matches_helper(self):
        # Load the Alembic migration module by path and assert its inlined
        # `_dedupe_hash` produces the identical digest to the app helper for a
        # fixed vector. A future divergence (rounding, format, bucket math)
        # would silently mis-backfill historical rows -> this fails loudly.
        import importlib.util
        from pathlib import Path

        mig_path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "063_pump_event_dedupe_hash.py"
        )
        spec = importlib.util.spec_from_file_location("_mig063", mig_path)
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)

        uid = uuid.uuid4()
        ts = _BUCKET_BASE + timedelta(seconds=7)
        helper = compute_pump_event_dedupe_hash(
            user_id=uid,
            event_type=PumpEventType.BOLUS,
            event_timestamp=ts,
            units=2.55,
            duration_minutes=None,
        )
        inlined = mig._dedupe_hash(uid, "bolus", ts, 2.55, None)
        assert helper == inlined
        # And the None-units opt-out matches too.
        assert mig._dedupe_hash(uid, "note", ts, None, None) is None
        # ...as does the telemetry (non-delivery) opt-out.
        assert mig._dedupe_hash(uid, "reservoir", ts, 150.0, None) is None
        assert (
            compute_pump_event_dedupe_hash(
                user_id=uid,
                event_type=PumpEventType.RESERVOIR,
                event_timestamp=ts,
                units=150.0,
                duration_minutes=None,
            )
            is None
        )


async def _register(client: AsyncClient) -> uuid.UUID:
    email = f"dedupe-{uuid.uuid4().hex[:10]}@example.com"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": "SecurePass123"}
    )
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    cookie = login.cookies.get(settings.jwt_cookie_name)
    me = await client.get("/api/auth/me", cookies={settings.jwt_cookie_name: cookie})
    return uuid.UUID(me.json()["id"])


async def _register_mobile(client: AsyncClient) -> tuple[str, uuid.UUID]:
    """Register a user and return (bearer_token, user_id)."""
    email = f"dedupe-{uuid.uuid4().hex[:10]}@example.com"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": "SecurePass123"}
    )
    assert reg.status_code == 201, reg.text
    resp = await client.post(
        "/api/auth/mobile/login",
        json={"email": email, "password": "SecurePass123"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, uuid.UUID(me.json()["id"])


def _row(uid, *, source, ns_id=None, ts, units, event_type=PumpEventType.BOLUS):
    now = datetime.now(UTC)
    return {
        "id": uuid.uuid4(),
        "user_id": uid,
        "event_type": event_type,
        "event_timestamp": ts,
        "units": units,
        "duration_minutes": None,
        "is_automated": False,
        "received_at": now,
        "source": source,
        "ns_id": ns_id,
        "dedupe_hash": compute_pump_event_dedupe_hash(
            user_id=uid,
            event_type=event_type,
            event_timestamp=ts,
            units=units,
            duration_minutes=None,
        ),
    }


async def _insert(db, row):
    """Insert one row via the production bare ON CONFLICT DO NOTHING path.

    Counts via RETURNING (not rowcount) -- rowcount is unreliable under
    ON CONFLICT DO NOTHING on asyncpg, matching the production insert paths.
    """
    stmt = (
        insert(PumpEvent).values([row]).on_conflict_do_nothing().returning(PumpEvent.id)
    )
    result = await db.execute(stmt)
    await db.commit()
    return len(result.scalars().all())


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


@pytest.mark.asyncio
class TestCrossSourcePumpDedupe:
    """The (user_id, dedupe_hash) partial unique index across sources."""

    async def test_near_match_collapses_first_writer_wins(self):
        # AC4: a Tandem-cloud bolus then the same physical bolus relayed via
        # Loop-over-Nightscout (0.04 U apart, same 30 s bucket, distinct
        # timestamps so the natural key does NOT collapse them) -> one row,
        # attributed to the first writer (tandem).
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                t_tandem = _BUCKET_BASE + timedelta(seconds=4)
                t_loop = _BUCKET_BASE + timedelta(seconds=12)
                tandem = _row(uid, source="tandem", ts=t_tandem, units=2.50)
                loop = _row(
                    uid,
                    source="nightscout:1",
                    # Unique per run: the (source, ns_id) index is global,
                    # not per-user, so a hardcoded id would collide with a
                    # prior run's committed row and skew rowcount.
                    ns_id=f"loop-{uuid.uuid4().hex}",
                    ts=t_loop,
                    units=2.54,
                )
                # Precondition: distinct natural keys, identical dedupe hash.
                assert tandem["event_timestamp"] != loop["event_timestamp"]
                assert tandem["dedupe_hash"] == loop["dedupe_hash"]

                assert await _insert(db, tandem) == 1
                assert await _insert(db, loop) == 0  # suppressed

                assert await _bolus_count(db, uid) == 1
                kept = await db.execute(
                    select(PumpEvent.source).where(PumpEvent.user_id == uid)
                )
                assert kept.scalar_one() == "tandem"
                break

    async def test_genuinely_distinct_both_persist(self):
        # AC5: > 30 s apart AND > 0.1 U different -> two distinct deliveries.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                tandem = _row(uid, source="tandem", ts=_BUCKET_BASE, units=2.5)
                loop = _row(
                    uid,
                    source="nightscout:1",
                    ns_id=f"loop-{uuid.uuid4().hex}",
                    ts=_BUCKET_BASE + timedelta(seconds=90),
                    units=3.0,
                )
                assert tandem["dedupe_hash"] != loop["dedupe_hash"]
                assert await _insert(db, tandem) == 1
                assert await _insert(db, loop) == 1
                assert await _bolus_count(db, uid) == 2
                break


@pytest.mark.asyncio
class TestMobilePushCrossSourceDedupe:
    """End-to-end wiring: the mobile push endpoint populates dedupe_hash."""

    async def test_near_match_suppressed_count_monotonic(self):
        # AC3 (mobile) + AC4 + AC6: two boluses at distinct timestamps inside
        # the same 30 s / 0.1 U bucket -> the natural key would keep both, but
        # the dedupe hash collapses them; bolus_count stays 1.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            token, uid = await _register_mobile(client)
            t1 = _BUCKET_BASE + timedelta(seconds=3)
            t2 = _BUCKET_BASE + timedelta(seconds=10)
            # Precondition: same hash, different natural key.
            assert _hash(uid, ts=t1, units=2.5) == _hash(uid, ts=t2, units=2.53)
            assert t1 != t2

            headers = {"Authorization": f"Bearer {token}"}

            r1 = await client.post(
                "/api/integrations/pump/push",
                headers=headers,
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": t1.isoformat(),
                            "units": 2.5,
                        }
                    ],
                    "source": "mobile",
                },
            )
            assert r1.status_code == 200
            assert r1.json()["accepted"] == 1

            r2 = await client.post(
                "/api/integrations/pump/push",
                headers=headers,
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": t2.isoformat(),
                            "units": 2.53,
                        }
                    ],
                    "source": "mobile",
                },
            )
            assert r2.status_code == 200
            assert r2.json()["accepted"] == 0  # collapsed by dedupe hash
            assert r2.json()["duplicates"] == 1

            async for db in get_db():
                assert await _bolus_count(db, uid) == 1
                row = await db.execute(
                    select(PumpEvent.dedupe_hash).where(PumpEvent.user_id == uid)
                )
                assert row.scalar_one() is not None
                break

    async def test_non_finite_units_do_not_crash_push(self):
        # A non-finite `units` must NOT crash the dedupe-hash quantizer
        # (Story 43.11 security gate). The helper opts the row out of the
        # cross-source index (dedupe_hash NULL); the row still persists.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            token, uid = await _register_mobile(client)
            # Raw body so the `Infinity` JSON token reaches the endpoint
            # (httpx's encoder refuses to serialize float('inf')).
            body = (
                '{"events":[{"event_type":"bolus",'
                f'"event_timestamp":"{_BUCKET_BASE.isoformat()}",'
                '"units":Infinity}],"source":"mobile"}'
            )
            resp = await client.post(
                "/api/integrations/pump/push",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                content=body,
            )
            assert resp.status_code == 200
            assert resp.json()["accepted"] == 1
            async for db in get_db():
                row = await db.execute(
                    select(PumpEvent.dedupe_hash).where(PumpEvent.user_id == uid)
                )
                assert row.scalar_one() is None  # opted out, no crash
                break

    async def test_within_batch_collapse_single_request(self):
        # A single multi-row push containing two near-match boluses (distinct
        # timestamps, same 30 s / 0.1 U bucket) collapses to one row in ONE
        # statement -- exercising the multi-row path and Postgres' intra-
        # statement DO NOTHING handling (no app-side pre-dedupe).
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            token, uid = await _register_mobile(client)
            t1 = _BUCKET_BASE + timedelta(seconds=2)
            t2 = _BUCKET_BASE + timedelta(seconds=9)
            assert _hash(uid, ts=t1, units=4.0) == _hash(uid, ts=t2, units=4.04)
            assert t1 != t2

            resp = await client.post(
                "/api/integrations/pump/push",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": t1.isoformat(),
                            "units": 4.0,
                        },
                        {
                            "event_type": "bolus",
                            "event_timestamp": t2.isoformat(),
                            "units": 4.04,
                        },
                    ],
                    "source": "mobile",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["accepted"] == 1
            assert resp.json()["duplicates"] == 1

            async for db in get_db():
                assert await _bolus_count(db, uid) == 1
                break


@pytest.mark.asyncio
class TestNightscoutTranslatorDedupe:
    """The Nightscout `_upsert_pump_events` path populates dedupe_hash."""

    async def test_ns_bolus_collapses_against_direct_and_meal_pair_excluded(self):
        from src.services.integrations.nightscout.translator import (
            _upsert_pump_events,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uid = await _register(client)
            async for db in get_db():
                # A direct-integration bolus lands first.
                direct = _row(
                    uid,
                    source="tandem",
                    ts=_BUCKET_BASE + timedelta(seconds=5),
                    units=1.5,
                )
                assert await _insert(db, direct) == 1

                # The Nightscout translator sees the same physical bolus (same
                # bucket, 0.03 U apart) plus a meal-paired bolus that must NOT
                # be deduped (it carries a meal_event_id sibling-link).
                meal_id = uuid.uuid4()
                ns_rows = [
                    {
                        "id": uuid.uuid4(),
                        "user_id": uid,
                        "event_type": PumpEventType.BOLUS,
                        "event_timestamp": _BUCKET_BASE + timedelta(seconds=11),
                        "units": 1.53,
                        "received_at": datetime.now(UTC),
                        "source": "nightscout:9",
                        "ns_id": f"loop-{uuid.uuid4().hex}",
                    },
                    {
                        "id": uuid.uuid4(),
                        "user_id": uid,
                        "event_type": PumpEventType.BOLUS,
                        "event_timestamp": _BUCKET_BASE + timedelta(seconds=5),
                        "units": 1.5,  # same bucket/units as `direct`...
                        "received_at": datetime.now(UTC),
                        "source": "nightscout:9",
                        "ns_id": f"loop-{uuid.uuid4().hex}",
                        "meal_event_id": meal_id,  # ...but meal-paired -> not deduped
                    },
                ]
                inserted = await _upsert_pump_events(db, ns_rows)
                await db.commit()

                # The plain NS bolus collapsed against `direct`; the meal-paired
                # bolus survived despite sharing the bucket -> 1 of 2 inserted.
                assert inserted == 1
                # 2 total: the direct bolus + the meal-paired NS bolus. The
                # plain NS bolus collapsed against `direct`.
                count = await db.execute(
                    select(func.count())
                    .select_from(PumpEvent)
                    .where(PumpEvent.user_id == uid)
                )
                assert count.scalar_one() == 2
                # The meal-paired row kept its link and opted out of the hash.
                paired = await db.execute(
                    select(PumpEvent.dedupe_hash).where(
                        PumpEvent.user_id == uid,
                        PumpEvent.meal_event_id == meal_id,
                    )
                )
                assert paired.scalar_one() is None
                break
