"""Round-trip tests for the Nightscout translator.

Covers:
- Per-fixture round-trip: load JSON -> translate -> query DB -> assert
- Dedupe: re-running translation upserts cleanly (no duplicate rows)
- Soft-delete: isValid=false records are skipped
- Meal-bolus pair split: bolus + carbs rows share meal_event_id
- Profile snapshot upsert: re-fetching overwrites the latest row

The unit-test layer (`test_nightscout_models.py`) covers the routing
decisions the input-model layer makes. These tests exercise the
translator's DB-write side -- ORM mapping, dedupe via partial unique
indexes, and the per-target conflict resolution.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.models.device_status_snapshot import DeviceStatusSnapshot
from src.models.glucose import GlucoseReading
from src.models.nightscout_connection import (
    NightscoutAuthType,
    NightscoutConnection,
)
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User
from src.services.integrations.nightscout.translator import (
    translate_devicestatuses,
    translate_entries,
    translate_profile,
    translate_treatments,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nightscout"


def _load(category: str, name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / category / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# Fixtures: ephemeral User + NightscoutConnection
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def translator_ctx() -> AsyncGenerator[
    tuple[AsyncSession, uuid.UUID, uuid.UUID], None
]:
    """Provide a session + a fresh User + NightscoutConnection.

    Mirrors the seed_session pattern in test_knowledge_seed.py: opens
    its own session via the shared session_maker (avoids cross-loop
    issues that come from sharing the conftest db_session fixture
    with translator code that opens its own connections).

    Setup commits the user + connection so they're visible to the
    translator's writes. Teardown explicitly DELETEs them and any
    rows the test created. Teardown swallows asyncpg cross-loop
    RuntimeErrors -- same noise the seed_session fixture documents.
    """
    session_maker = get_session_maker()
    session = session_maker()
    email = f"translator_{uuid.uuid4().hex[:10]}@example.com"
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()
    user_id = user.id

    connection = NightscoutConnection(
        user_id=user_id,
        name="test-connection",
        base_url="https://example.com",
        auth_type=NightscoutAuthType.SECRET,
        encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
    )
    session.add(connection)
    await session.flush()
    connection_id = connection.id
    await session.commit()

    try:
        yield session, user_id, connection_id
    finally:
        try:
            # Roll back any uncommitted in-progress transaction the
            # test left open before issuing the cleanup statements.
            await session.rollback()
            await session.execute(
                delete(GlucoseReading).where(GlucoseReading.user_id == user_id)
            )
            await session.execute(delete(PumpEvent).where(PumpEvent.user_id == user_id))
            await session.execute(
                delete(DeviceStatusSnapshot).where(
                    DeviceStatusSnapshot.user_id == user_id
                )
            )
            await session.execute(
                delete(NightscoutProfileSnapshot).where(
                    NightscoutProfileSnapshot.user_id == user_id
                )
            )
            await session.execute(
                delete(NightscoutConnection).where(
                    NightscoutConnection.id == connection_id
                )
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        except RuntimeError:
            # asyncpg / pytest-asyncio cross-loop teardown noise --
            # cosmetic, the engine pool will clean up regardless.
            pass
        finally:
            try:
                await session.close()
            except RuntimeError:
                pass


# ---------------------------------------------------------------------------
# Entries path -> glucose_readings
# ---------------------------------------------------------------------------


class TestEntriesPath:
    @pytest.mark.asyncio
    async def test_xdrip_sgv_inserts_glucose_reading(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        outcome = await translate_entries(
            [_load("entries", "xdrip_sgv")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert outcome.inserted == 1
        assert outcome.skipped == 0
        assert outcome.failed == 0

        rows = (
            (
                await session.execute(
                    select(GlucoseReading).where(GlucoseReading.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.value == 120
        assert row.source == f"nightscout:{conn_id}"
        assert row.ns_id is not None

    @pytest.mark.asyncio
    async def test_cal_entry_dropped(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        outcome = await translate_entries(
            [_load("entries", "cal_calibration")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert outcome.inserted == 0
        assert outcome.skipped == 1

    @pytest.mark.asyncio
    async def test_dedupe_via_ns_id_partial_index(self, translator_ctx):
        """Re-running translation on the same entry must not double-insert."""
        session, user_id, conn_id = translator_ctx
        raw = _load("entries", "xdrip_sgv")

        first = await translate_entries(
            [raw], session=session, user_id=str(user_id), connection_id=str(conn_id)
        )
        await session.flush()
        assert first.inserted == 1

        second = await translate_entries(
            [raw], session=session, user_id=str(user_id), connection_id=str(conn_id)
        )
        await session.flush()
        assert second.inserted == 0
        assert second.skipped == 1

        rows = (
            (
                await session.execute(
                    select(GlucoseReading).where(GlucoseReading.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_mbg_fingerstick_routes_to_glucose_readings(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        outcome = await translate_entries(
            [_load("entries", "xdrip_mbg_fingerstick")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert outcome.inserted == 1


# ---------------------------------------------------------------------------
# Treatments path -> pump_events (+ glucose_readings for fingerstick)
# ---------------------------------------------------------------------------


class TestTreatmentsPath:
    @pytest.mark.asyncio
    async def test_loop_correction_bolus_inserts_pump_event(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        pump_outcome, glucose_outcome = await translate_treatments(
            [_load("treatments", "loop_correction_bolus")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert pump_outcome.inserted == 1
        assert glucose_outcome.inserted == 0  # not a fingerstick

        rows = (
            (
                await session.execute(
                    select(PumpEvent).where(PumpEvent.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        ev = rows[0]
        assert ev.event_type == PumpEventType.BOLUS
        assert ev.units == 0.45
        assert ev.is_automated is True  # Loop SMB
        assert ev.metadata_json["bolus_subtype"] == "smb"
        assert ev.metadata_json["source_uploader"] == "loop"

    @pytest.mark.asyncio
    async def test_meal_bolus_pair_splits_into_two_linked_rows(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        await translate_treatments(
            [_load("treatments", "careportal_meal_bolus")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()

        rows = (
            (
                await session.execute(
                    select(PumpEvent)
                    .where(PumpEvent.user_id == user_id)
                    .order_by(PumpEvent.event_type)
                )
            )
            .scalars()
            .all()
        )
        # Two rows: bolus + carbs
        assert len(rows) == 2
        types = {r.event_type for r in rows}
        assert types == {PumpEventType.BOLUS, PumpEventType.CARBS}
        # Linked via shared meal_event_id
        meal_ids = {r.meal_event_id for r in rows}
        assert len(meal_ids) == 1
        assert next(iter(meal_ids)) is not None
        # The bolus row carries the insulin units; the carbs row does not
        bolus = next(r for r in rows if r.event_type == PumpEventType.BOLUS)
        carb = next(r for r in rows if r.event_type == PumpEventType.CARBS)
        assert bolus.units == 5.0
        assert carb.units is None
        assert carb.metadata_json["carbs_grams"] == 60

    @pytest.mark.asyncio
    async def test_xdrip4ios_bg_check_routes_to_glucose_readings(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        pump_outcome, glucose_outcome = await translate_treatments(
            [_load("treatments", "xdrip4ios_bg_check_treatment")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert pump_outcome.inserted == 0
        assert glucose_outcome.inserted == 1

        rows = (
            (
                await session.execute(
                    select(GlucoseReading).where(GlucoseReading.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].value == 120

    @pytest.mark.asyncio
    async def test_loop_pump_suspend_routes_to_suspend_event(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        await translate_treatments(
            [_load("treatments", "loop_pump_suspend_as_temp_basal")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        rows = (
            (
                await session.execute(
                    select(PumpEvent).where(PumpEvent.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].event_type == PumpEventType.SUSPEND
        assert rows[0].metadata_json.get("reason") == "suspend"

    @pytest.mark.asyncio
    async def test_aaps_effective_profile_switch_routes_correctly(self, translator_ctx):
        """Note + originalProfileName -> profile_switch (not note)."""
        session, user_id, conn_id = translator_ctx
        await translate_treatments(
            [_load("treatments", "aaps_effective_profile_switch_as_note")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        rows = (
            (
                await session.execute(
                    select(PumpEvent).where(PumpEvent.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].event_type == PumpEventType.PROFILE_SWITCH
        assert rows[0].metadata_json["effective_profile_switch_via_note"] is True

    @pytest.mark.asyncio
    async def test_soft_delete_is_skipped(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        # Forge a soft-delete by setting isValid=false on a Tier-1 fixture
        raw = _load("treatments", "aaps_v1_smb_correction_bolus")
        raw["isValid"] = False
        pump_outcome, _ = await translate_treatments(
            [raw],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert pump_outcome.inserted == 0
        assert pump_outcome.skipped == 1
        rows = (
            (
                await session.execute(
                    select(PumpEvent).where(PumpEvent.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# Devicestatus path -> device_status_snapshots
# ---------------------------------------------------------------------------


class TestDevicestatusPath:
    @pytest.mark.asyncio
    async def test_loop_devicestatus_inserts_snapshot(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        outcome = await translate_devicestatuses(
            [_load("devicestatus", "loop_devicestatus")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert outcome.inserted == 1

        rows = (
            (
                await session.execute(
                    select(DeviceStatusSnapshot).where(
                        DeviceStatusSnapshot.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        snap = rows[0]
        # IOB extracted from loop.iob (pump.iob is null for Loop)
        assert snap.iob_units == 1.2
        assert snap.cob_grams == 12.0
        assert snap.pump_battery_percent == 87
        assert snap.pump_suspended is False
        assert snap.source_uploader == "loop"
        # Subtree blobs preserved verbatim
        assert isinstance(snap.loop_subtree_json, dict)
        assert isinstance(snap.pump_subtree_json, dict)

    @pytest.mark.asyncio
    async def test_loop_failure_devicestatus_captures_failure_reason(
        self, translator_ctx
    ):
        session, user_id, conn_id = translator_ctx
        await translate_devicestatuses(
            [_load("devicestatus", "loop_failure_devicestatus")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        rows = (
            (
                await session.execute(
                    select(DeviceStatusSnapshot).where(
                        DeviceStatusSnapshot.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].loop_failure_reason is not None
        assert "communicationFailure" in rows[0].loop_failure_reason

    @pytest.mark.asyncio
    async def test_dedupe_via_connection_nsid(self, translator_ctx):
        """Re-running devicestatus translation must not double-insert."""
        session, user_id, conn_id = translator_ctx
        raw = _load("devicestatus", "loop_devicestatus")
        await translate_devicestatuses(
            [raw], session=session, user_id=str(user_id), connection_id=str(conn_id)
        )
        await session.flush()
        outcome2 = await translate_devicestatuses(
            [raw], session=session, user_id=str(user_id), connection_id=str(conn_id)
        )
        await session.flush()
        assert outcome2.inserted == 0
        assert outcome2.skipped == 1
        rows = (
            (
                await session.execute(
                    select(DeviceStatusSnapshot).where(
                        DeviceStatusSnapshot.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Profile path -> nightscout_profile_snapshots (single row, upsert)
# ---------------------------------------------------------------------------


class TestProfilePath:
    @pytest.mark.asyncio
    async def test_profile_inserts_snapshot(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        ok = await translate_profile(
            _load("profile", "multi_store_profile"),
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert ok is True

        rows = (
            (
                await session.execute(
                    select(NightscoutProfileSnapshot).where(
                        NightscoutProfileSnapshot.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        snap = rows[0]
        assert snap.source_default_profile_name == "Default"
        assert snap.source_units == "mg/dl"
        assert snap.source_dia_hours == 5.0
        assert isinstance(snap.basal_segments, list)
        assert len(snap.basal_segments) == 3

    @pytest.mark.asyncio
    async def test_profile_re_fetch_upserts_overwrites(self, translator_ctx):
        """Re-running translate_profile updates the existing row, not creates."""
        session, user_id, conn_id = translator_ctx
        raw = _load("profile", "multi_store_profile")

        await translate_profile(
            raw,
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
            fetched_at=datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC),
        )
        await session.flush()

        # Modify and re-run
        raw_mut = dict(raw)
        raw_mut["store"] = dict(raw["store"])
        raw_mut["store"]["Default"] = dict(raw["store"]["Default"])
        raw_mut["store"]["Default"]["dia"] = 6
        await translate_profile(
            raw_mut,
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
            fetched_at=datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC),
        )
        await session.flush()

        rows = (
            (
                await session.execute(
                    select(NightscoutProfileSnapshot).where(
                        NightscoutProfileSnapshot.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1, "should remain a single row after re-fetch"
        snap = rows[0]
        assert snap.source_dia_hours == 6.0  # updated value


# ---------------------------------------------------------------------------
# Bulk fixture round-trip -- every Tier-1 + Tier-2 fixture must translate
# ---------------------------------------------------------------------------


class TestBulkFixtureRoundTrip:
    @pytest.mark.asyncio
    async def test_all_entry_fixtures_translate(self, translator_ctx):
        """Every entry fixture either inserts or is intentionally dropped."""
        session, user_id, conn_id = translator_ctx
        entries_dir = FIXTURE_ROOT / "entries"
        for path in sorted(entries_dir.glob("*.json")):
            raw = json.loads(path.read_text())
            outcome = await translate_entries(
                [raw],
                session=session,
                user_id=str(user_id),
                connection_id=str(conn_id),
            )
            await session.flush()
            assert outcome.failed == 0, f"{path.name} parse failed"

    @pytest.mark.asyncio
    async def test_all_treatment_fixtures_translate(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        treatments_dir = FIXTURE_ROOT / "treatments"
        for path in sorted(treatments_dir.glob("*.json")):
            raw = json.loads(path.read_text())
            pump_outcome, glucose_outcome = await translate_treatments(
                [raw],
                session=session,
                user_id=str(user_id),
                connection_id=str(conn_id),
            )
            await session.flush()
            assert pump_outcome.failed == 0, f"{path.name} parse failed"
            assert glucose_outcome.failed == 0

    @pytest.mark.asyncio
    async def test_all_devicestatus_fixtures_translate(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        ds_dir = FIXTURE_ROOT / "devicestatus"
        for path in sorted(ds_dir.glob("*.json")):
            raw = json.loads(path.read_text())
            outcome = await translate_devicestatuses(
                [raw],
                session=session,
                user_id=str(user_id),
                connection_id=str(conn_id),
            )
            await session.flush()
            assert outcome.failed == 0, f"{path.name} parse failed"


# ---------------------------------------------------------------------------
# Read endpoints exercised end-to-end via the FastAPI app
# ---------------------------------------------------------------------------


class TestReadEndpoints:
    """Translator writes -> HTTP read endpoints return what we wrote.

    Uses the connection-test register-and-login pattern so the
    endpoints exercise auth + RBAC alongside the data filter.
    """

    @pytest.mark.asyncio
    async def test_data_endpoint_returns_written_rows(self, translator_ctx):
        from httpx import ASGITransport, AsyncClient

        from src.config import settings
        from src.main import app

        session, user_id, conn_id = translator_ctx
        # Translate two entries + one bolus treatment so the endpoint
        # has both arrays to return.
        await translate_entries(
            [
                _load("entries", "xdrip_sgv"),
                _load("entries", "dexcom_bridge_sgv"),
            ],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await translate_treatments(
            [_load("treatments", "loop_correction_bolus")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        # Issue a JWT directly so we can call the protected endpoint
        # without going through register/login (the user already
        # exists from the fixture).
        from src.core.security import create_access_token

        token = create_access_token(
            user_id=user_id, email="test@example.com", role="diabetic"
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                f"/api/integrations/nightscout/{conn_id}/data",
                cookies={settings.jwt_cookie_name: token},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["connection_id"] == str(conn_id)
        assert len(body["glucose_readings"]) == 2
        assert len(body["pump_events"]) == 1
        # Source attribution preserved on every row
        assert all(
            g["source"] == f"nightscout:{conn_id}" for g in body["glucose_readings"]
        )
        assert all(e["source"] == f"nightscout:{conn_id}" for e in body["pump_events"])

    @pytest.mark.asyncio
    async def test_data_endpoint_filters_by_since_cursor(self, translator_ctx):
        from httpx import ASGITransport, AsyncClient

        from src.config import settings
        from src.core.security import create_access_token
        from src.main import app

        session, user_id, conn_id = translator_ctx
        await translate_entries(
            [
                _load("entries", "xdrip_sgv"),
                _load("entries", "dexcom_bridge_sgv"),
            ],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        token = create_access_token(
            user_id=user_id, email="test@example.com", role="diabetic"
        )
        # `since` cursor between the two entry timestamps
        # (xdrip is 2026-05-06T12:00:00Z, dexcom is 12:05:00Z)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                f"/api/integrations/nightscout/{conn_id}/data",
                params={"since": "2026-05-06T12:02:00Z"},
                cookies={settings.jwt_cookie_name: token},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Only the later entry should appear
        assert len(body["glucose_readings"]) == 1

    @pytest.mark.asyncio
    async def test_profile_snapshot_endpoint_empty_state(self, translator_ctx):
        """Connection with no profile sync yet returns has_snapshot=False."""
        from httpx import ASGITransport, AsyncClient

        from src.config import settings
        from src.core.security import create_access_token
        from src.main import app

        session, user_id, conn_id = translator_ctx
        token = create_access_token(
            user_id=user_id, email="test@example.com", role="diabetic"
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                f"/api/integrations/nightscout/{conn_id}/profile-snapshot",
                cookies={settings.jwt_cookie_name: token},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["has_snapshot"] is False
        assert body["fetched_at"] is None

    @pytest.mark.asyncio
    async def test_profile_snapshot_endpoint_returns_translated(self, translator_ctx):
        from httpx import ASGITransport, AsyncClient

        from src.config import settings
        from src.core.security import create_access_token
        from src.main import app

        session, user_id, conn_id = translator_ctx
        await translate_profile(
            _load("profile", "multi_store_profile"),
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        token = create_access_token(
            user_id=user_id, email="test@example.com", role="diabetic"
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                f"/api/integrations/nightscout/{conn_id}/profile-snapshot",
                cookies={settings.jwt_cookie_name: token},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["has_snapshot"] is True
        assert body["source_default_profile_name"] == "Default"
        assert body["source_units"] == "mg/dl"
        assert body["source_dia_hours"] == 5.0
        assert isinstance(body["basal_segments"], list)
        assert len(body["basal_segments"]) == 3

    @pytest.mark.asyncio
    async def test_data_endpoint_rejects_other_users_connection(self, translator_ctx):
        """Cross-tenant access returns 404, not 403, to avoid leaking IDs."""
        from httpx import ASGITransport, AsyncClient

        from src.config import settings
        from src.core.security import create_access_token
        from src.main import app

        session, user_id, conn_id = translator_ctx

        # Create a second user with no claim on conn_id
        other = User(
            email=f"other_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="not-a-real-hash",
        )
        session.add(other)
        await session.flush()
        other_id = other.id
        await session.commit()

        token = create_access_token(
            user_id=other_id, email="other@example.com", role="diabetic"
        )
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get(
                    f"/api/integrations/nightscout/{conn_id}/data",
                    cookies={settings.jwt_cookie_name: token},
                )
            assert resp.status_code == 404
        finally:
            from sqlalchemy import delete

            await session.execute(delete(User).where(User.id == other_id))
            await session.commit()
