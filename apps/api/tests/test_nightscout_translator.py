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
import os
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
    async def test_meal_bolus_pair_dedupes_on_refetch(self, translator_ctx):
        """Re-translating the same meal_bolus_pair must not double-insert.

        Regression for the bug where the synthesized ns_id suffix
        included a fresh uuid4(), making (source, ns_id) different on
        each sync cycle so the partial unique index never matched.
        """
        session, user_id, conn_id = translator_ctx
        raw = _load("treatments", "careportal_meal_bolus")

        # First fetch: 2 rows inserted (bolus + carbs).
        first_pump, _ = await translate_treatments(
            [raw],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert first_pump.inserted == 2

        # Second fetch of the same record: 0 inserts, 2 dedupe-skips.
        second_pump, _ = await translate_treatments(
            [raw],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert second_pump.inserted == 0
        assert second_pump.skipped == 2

        # Verify the DB still has exactly 2 rows.
        rows = (
            (
                await session.execute(
                    select(PumpEvent).where(PumpEvent.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2

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


# ---------------------------------------------------------------------------
# Storage-side PII allowlist -- identifier-shaped values from the upstream
# wire format must NOT reach metadata_json.
# ---------------------------------------------------------------------------


class TestMetadataAllowlist:
    """The translator filters metadata_json through a storage-side
    allowlist so identifier-shaped values (`remoteAddress`,
    `syncIdentifier`, AAPS `pumpId`/`pumpType`/`pumpSerial`) and the
    per-treatment `enteredBy` username/email never land in JSONB.

    Defense in depth: a future allowlist gap surfaces here, before
    the wire DTO ever sees the value.
    """

    @pytest.mark.asyncio
    async def test_remote_address_dropped_from_override_metadata(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        await translate_treatments(
            [_load("treatments", "loop_override_with_remote_address")],
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
        md = rows[0].metadata_json or {}
        # The fixture has remoteAddress="device-token-stub" -- must not
        # reach storage.
        assert "remote_address" not in md
        assert "remoteAddress" not in md
        # Source attribution (`source` at row level) covers what we need;
        # the per-treatment entered_by username should never persist.
        assert "source_entered_by" not in md
        # Sanity: clinically-meaningful keys still made it through.
        assert md.get("correction_range") == [140, 160]

    @pytest.mark.asyncio
    async def test_aaps_pump_dedupe_triple_dropped_from_bolus_metadata(
        self, translator_ctx
    ):
        session, user_id, conn_id = translator_ctx
        await translate_treatments(
            [_load("treatments", "aaps_v3_smb_correction_bolus")],
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
        md = rows[0].metadata_json or {}
        # AAPS pump composite dedup triple -- never persisted.
        assert "pump_id" not in md
        assert "pump_type" not in md
        assert "pump_serial" not in md
        # And the raw enteredBy value never persists either.
        assert "source_entered_by" not in md
        # Clinical keys preserved.
        assert md.get("bolus_subtype") == "smb"

    def test_allowlist_covers_every_literal_key_the_mappers_set(self):
        """Drift guard: every literal key the mappers write into extras
        MUST appear in `_METADATA_ALLOWLIST`, otherwise a clinically-
        meaningful key would be silently filtered away.

        Parses the mapper module's source for `extras["<key>"] = ...`
        literals + the inline-dict literals the mappers initialize
        with -- catches the static call sites without needing each
        fixture to flex every branch.
        """
        import ast
        import inspect

        from src.services.integrations.nightscout import _pump_events_mapper
        from src.services.integrations.nightscout._pump_events_mapper import (
            _METADATA_ALLOWLIST,
        )

        # Read source through `inspect.getsource` so the test is
        # independent of the pytest CWD (which can differ between
        # local runs and CI).
        tree = ast.parse(inspect.getsource(_pump_events_mapper))

        keys: set[str] = set()
        # `extras["<key>"] = ...`
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(t := node.targets[0], ast.Subscript)
                and isinstance(t.value, ast.Name)
                and t.value.id == "extras"
                and isinstance(t.slice, ast.Constant)
                and isinstance(t.slice.value, str)
            ):
                keys.add(t.slice.value)
            # `extras: dict[...] = {"<key>": ..., ...}` initialisers
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "extras"
                and isinstance(node.value, ast.Dict)
            ):
                for k in node.value.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        keys.add(k.value)

        # Sanity: scan picked SOMETHING up (catch a future syntactic
        # refactor that hides the writes from this AST walk).
        assert len(keys) >= 20, f"AST scan looks broken: only found {keys}"

        missing = keys - _METADATA_ALLOWLIST
        assert not missing, (
            f"Mapper writes these extras keys that aren't on the allowlist; "
            f"either add them or stop writing them: {sorted(missing)}"
        )

    @pytest.mark.asyncio
    async def test_loop_sync_identifier_dropped_from_bolus_metadata(
        self, translator_ctx
    ):
        session, user_id, conn_id = translator_ctx
        await translate_treatments(
            [_load("treatments", "loop_correction_bolus")],
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
        md = rows[0].metadata_json or {}
        # Loop syncIdentifier (HealthKit dedupe key) -- never persisted.
        assert "sync_identifier" not in md
        assert "syncIdentifier" not in md


# ---------------------------------------------------------------------------
# Cross-source coexistence -- partial-index relaxation must allow a Tandem
# direct row and a Nightscout-relayed row to share the same
# (user_id, event_timestamp, event_type) without conflict.
# ---------------------------------------------------------------------------


class TestCrossSourceCoexistence:
    """DDL-level regression locks for the partial unique indexes.

    These tests insert PumpEvent rows directly (bypassing the translator
    and its ON CONFLICT path) to pin the schema invariant: the relaxed
    `ix_pump_events_user_event_unique` (`WHERE ns_id IS NULL`) and
    `ix_pump_events_source_nsid` (`WHERE ns_id IS NOT NULL`) must allow
    a direct-integration row and a Nightscout-sourced row -- or two
    Nightscout-sourced rows with different `_id`s -- to coexist at the
    same timestamp + event_type.

    The full upsert path (translator + ON CONFLICT) is exercised by
    `TestLiveEndToEndPipeline`; these tests fail fast if someone
    "tightens" the index again without thinking through the
    cross-source case, even before the live tests would catch it.
    """

    @pytest.mark.asyncio
    async def test_tandem_direct_and_nightscout_at_same_timestamp_both_persist(
        self, translator_ctx
    ):
        from sqlalchemy import select

        from src.models.pump_data import PumpEvent, PumpEventType

        session, user_id, conn_id = translator_ctx
        same_ts = datetime(2026, 5, 6, 14, 30, 0, tzinfo=UTC)
        now = datetime.now(UTC)

        # 1. Direct-integration row (Tandem-shaped: ns_id IS NULL)
        tandem_row = PumpEvent(
            user_id=user_id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=same_ts,
            units=0.5,
            is_automated=True,
            received_at=now,
            source="tandem",
            ns_id=None,
        )
        session.add(tandem_row)
        await session.flush()

        # 2. Nightscout-relayed row at SAME timestamp + same event_type
        # but with ns_id set. Different source tag, different ns_id, so
        # the partial unique index `ix_pump_events_source_nsid` doesn't
        # conflict either.
        ns_row = PumpEvent(
            user_id=user_id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=same_ts,
            units=0.3,
            is_automated=True,
            received_at=now,
            source=f"nightscout:{conn_id}",
            ns_id="65f4b1a2c8e3d2f1a0b1c999",
            metadata_json={"bolus_subtype": "smb", "source_uploader": "loop"},
        )
        session.add(ns_row)
        await session.flush()

        # Both rows should coexist
        rows = (
            (
                await session.execute(
                    select(PumpEvent).where(PumpEvent.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        sources = {r.source for r in rows}
        assert sources == {"tandem", f"nightscout:{conn_id}"}

    @pytest.mark.asyncio
    async def test_two_nightscout_smbs_at_same_second_both_persist(
        self, translator_ctx
    ):
        """The exact scenario the partial-index relaxation was built for:
        two AAPS SMBs at the same second with different `_id`s -- the
        old (non-partial) unique index would have dropped one.
        """
        from sqlalchemy import select

        from src.models.pump_data import PumpEvent, PumpEventType

        session, user_id, conn_id = translator_ctx
        same_ts = datetime(2026, 5, 6, 14, 30, 0, tzinfo=UTC)
        now = datetime.now(UTC)
        source = f"nightscout:{conn_id}"

        for ns_id, units in [
            ("65f4b1a2c8e3d2f1a0b1d001", 0.1),
            ("65f4b1a2c8e3d2f1a0b1d002", 0.2),
        ]:
            session.add(
                PumpEvent(
                    user_id=user_id,
                    event_type=PumpEventType.BOLUS,
                    event_timestamp=same_ts,
                    units=units,
                    is_automated=True,
                    received_at=now,
                    source=source,
                    ns_id=ns_id,
                )
            )
        await session.flush()

        rows = (
            (
                await session.execute(
                    select(PumpEvent)
                    .where(PumpEvent.user_id == user_id)
                    .order_by(PumpEvent.units.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert [r.units for r in rows] == [0.1, 0.2]


# ---------------------------------------------------------------------------
# Live end-to-end pipeline: NightscoutClient.fetch -> translator -> DB.
# Gated by NIGHTSCOUT_TEST_URL env var; skipped in CI. Catches drift
# between what the live cgm-remote-monitor returns and what the translator
# expects -- the seam our isolated unit tests cannot exercise.
# ---------------------------------------------------------------------------

_NS_URL = os.environ.get("NIGHTSCOUT_TEST_URL")
_NS_SECRET = os.environ.get("NIGHTSCOUT_TEST_SECRET")
_skip_no_live = pytest.mark.skipif(
    not _NS_URL or not _NS_SECRET,
    reason="set both NIGHTSCOUT_TEST_URL and NIGHTSCOUT_TEST_SECRET to run "
    "live integration tests against a real Nightscout instance",
)


@_skip_no_live
@pytest.mark.integration
class TestLiveEndToEndPipeline:
    """Fetch real data via NightscoutClient, translate it, query the DB.

    Validates the seam between:
    - The HTTP client (ships entries/treatments/devicestatus dicts)
    - The translator (parses dicts via Pydantic models, routes via
      semantic_kind, writes to ORM)
    - The DB (partial unique indexes, dedupe, source attribution)

    Wire-format issues that would only surface here include: schema
    drift between cgm-remote-monitor versions and our Pydantic models;
    UTF-8 in `enteredBy` that breaks the metadata_json serialization;
    timezone or timestamp-format anomalies the synthetic fixtures miss.
    """

    @pytest.mark.asyncio
    async def test_live_entries_round_trip_to_glucose_readings(self, translator_ctx):
        from sqlalchemy import select

        from src.models.glucose import GlucoseReading
        from src.models.nightscout_connection import (
            NightscoutApiVersion,
            NightscoutAuthType,
        )
        from src.services.integrations.nightscout.client import NightscoutClient

        session, user_id, conn_id = translator_ctx

        # Fetch real entries from the local instance
        async with await NightscoutClient.create(
            base_url=_NS_URL,
            auth_type=NightscoutAuthType.SECRET,
            credential=_NS_SECRET,
            api_version=NightscoutApiVersion.V1,
        ) as client:
            entries = await client.fetch_entries(count=200)

        # Translate -> ORM
        outcome = await translate_entries(
            entries,
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        # No parse failures -- if real cgm-remote-monitor responses
        # don't fit our Pydantic model, this is where it surfaces.
        assert outcome.failed == 0, "live entries failed Pydantic parse"

        # Inserted count + skipped (gaps) should equal the fetch count
        # exactly (modulo cal entries which we drop entirely)
        assert outcome.inserted + outcome.skipped == len(entries)

        # Spot-check the inserted rows
        rows = (
            (
                await session.execute(
                    select(GlucoseReading).where(
                        GlucoseReading.user_id == user_id,
                        GlucoseReading.source == f"nightscout:{conn_id}",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == outcome.inserted
        # Glucose values fall in the physiological range (catches a
        # mg/dL <-> mmol/L unit-conversion regression at the seam).
        # Project guideline: physiological range is 40-400 mg/dL.
        # mg/dL <-> mmol/L misconversion would land far outside this.
        assert all(40 <= r.value <= 400 for r in rows)

    @pytest.mark.asyncio
    async def test_live_treatments_round_trip_through_translator(self, translator_ctx):
        from sqlalchemy import select

        from src.models.nightscout_connection import (
            NightscoutApiVersion,
            NightscoutAuthType,
        )
        from src.models.pump_data import PumpEvent
        from src.services.integrations.nightscout.client import NightscoutClient

        session, user_id, conn_id = translator_ctx

        async with await NightscoutClient.create(
            base_url=_NS_URL,
            auth_type=NightscoutAuthType.SECRET,
            credential=_NS_SECRET,
            api_version=NightscoutApiVersion.V1,
        ) as client:
            treatments = await client.fetch_treatments(count=200)

        # Pre-compute the expected pump_events row count by mirroring
        # the translator's routing decisions: fingerstick treatments
        # divert to glucose_readings; the mapper hard-drops
        # temp_basal_cancel / fingerstick_bg_check / unknown (the last
        # also covers soft-deletes); meal_bolus_pair splits to two rows;
        # else one row. Records without a resolvable timestamp drop too.
        from src.services.integrations.nightscout.models import NightscoutTreatment

        drop_kinds = {"temp_basal_cancel", "fingerstick_bg_check", "unknown"}
        expected_pump_rows = 0
        for raw in treatments:
            try:
                t = NightscoutTreatment.model_validate(raw)
            except Exception:
                continue
            if t.is_fingerstick_treatment:
                continue
            if t.semantic_kind in drop_kinds:
                continue
            if t.canonical_timestamp is None:
                continue
            expected_pump_rows += 2 if t.semantic_kind == "meal_bolus_pair" else 1

        pump_outcome, _glucose_outcome = await translate_treatments(
            treatments,
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        assert pump_outcome.failed == 0, "live treatments failed Pydantic parse"

        rows = (
            (
                await session.execute(
                    select(PumpEvent).where(
                        PumpEvent.user_id == user_id,
                        PumpEvent.source == f"nightscout:{conn_id}",
                    )
                )
            )
            .scalars()
            .all()
        )
        # Cardinality match against the kind-derived expectation -- this
        # would catch a mapper that silently drops a kind, an upsert
        # that double-inserts, or a pair-splitter regression.
        assert len(rows) == expected_pump_rows, (
            f"expected {expected_pump_rows} pump_events rows from "
            f"{len(treatments)} treatments, got {len(rows)}"
        )

    @pytest.mark.asyncio
    async def test_live_pipeline_is_idempotent_on_refetch(self, translator_ctx):
        """Run the full pipeline twice -- second run must dedupe to zero."""
        from sqlalchemy import func, select

        from src.models.glucose import GlucoseReading
        from src.models.nightscout_connection import (
            NightscoutApiVersion,
            NightscoutAuthType,
        )
        from src.services.integrations.nightscout.client import NightscoutClient

        session, user_id, conn_id = translator_ctx

        async with await NightscoutClient.create(
            base_url=_NS_URL,
            auth_type=NightscoutAuthType.SECRET,
            credential=_NS_SECRET,
            api_version=NightscoutApiVersion.V1,
        ) as client:
            entries = await client.fetch_entries(count=100)

        first = await translate_entries(
            entries,
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        # Snapshot row count after pass 1 -- a regression that both
        # double-inserts AND under-counts in the outcome counter would
        # slip past `second.inserted == 0` alone.
        count_after_first = await session.scalar(
            select(func.count(GlucoseReading.id)).where(
                GlucoseReading.user_id == user_id
            )
        )

        second = await translate_entries(
            entries,
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        assert second.inserted == 0, (
            "re-fetching the same entries inserted duplicates -- "
            "dedupe via (source, ns_id) partial index isn't holding"
        )
        # Everything in `entries` either landed first time (inserted)
        # or was skipped (cal records / gap readings / no timestamp).
        # Second time around, the inserted-on-first-pass rows hit the
        # ON CONFLICT skip path; the rejected ones are skipped at the
        # mapper layer like before.
        assert second.skipped + second.failed >= first.inserted

        count_after_second = await session.scalar(
            select(func.count(GlucoseReading.id)).where(
                GlucoseReading.user_id == user_id
            )
        )
        assert count_after_second == count_after_first, (
            f"row count drifted across re-fetch: "
            f"{count_after_first} -> {count_after_second}"
        )
