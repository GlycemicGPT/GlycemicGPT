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
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.models.device_status_snapshot import DeviceStatusSnapshot
from src.models.forecast_snapshot import ForecastSnapshot
from src.models.glucose import GlucoseReading
from src.models.nightscout_connection import (
    NightscoutAuthType,
    NightscoutConnection,
)
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User
from src.services.integrations.nightscout._forecast_mapper import (
    map_devicestatus_to_forecast,
)
from src.services.integrations.nightscout.models import NightscoutDeviceStatus
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
    # Forecast snapshots are uniquely keyed by
    # `(source_engine, dedupe_key)` GLOBALLY -- not per-user. Stale rows
    # from prior test runs (or from sibling test files that hardcode
    # `_id` values) would collide with our deterministic test `_id`s and
    # the ON CONFLICT DO NOTHING upsert would silently drop the insert.
    # Truncate up front to ensure each test starts with a clean
    # forecast table. Pump events / glucose / snapshots are per-user so
    # don't have this hazard.
    #
    # NOTE: assumes single-worker pytest. A future move to pytest-xdist
    # with a shared DB would race this TRUNCATE against other workers'
    # in-flight rows; if that lands, partition the forecast tables per
    # worker or scope the fixture differently.
    await session.execute(
        text("TRUNCATE forecast_evaluations, forecast_snapshots CASCADE")
    )
    await session.commit()
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
                delete(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
            )
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
    async def test_long_acting_injection_routes_to_basal_injection(
        self, translator_ctx
    ):
        """MDI long-acting pen dose -> BASAL_INJECTION, NOT a rapid bolus (#728).

        Before this, a long-acting dose fell through to the has_insulin -> bolus
        default and polluted rapid-acting IoB/TDD.
        """
        session, user_id, conn_id = translator_ctx
        pump_outcome, _ = await translate_treatments(
            [
                {
                    "_id": "basalinj0000000000000001",
                    "eventType": "External Insulin",
                    "insulin": 24.0,
                    "insulinType": "Tresiba",
                    "enteredBy": "Trio",
                    "created_at": "2026-05-06T07:00:00Z",
                }
            ],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()
        assert pump_outcome.inserted == 1

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
        assert ev.event_type == PumpEventType.BASAL_INJECTION
        assert ev.units == 24.0
        assert ev.is_automated is False  # a pen injection is never automated
        assert ev.metadata_json["insulin_type"] == "Tresiba"

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

    @pytest.mark.asyncio
    async def test_devicestatus_backfills_iob_context_on_recent_boluses(
        self, translator_ctx
    ):
        """After devicestatus translation, NS-sourced bolus rows that
        were inserted without iob_at_event get the context backfilled
        from the nearest preceding devicestatus snapshot.

        Regression case: Loop / AAPS / Trio post boluses as treatments
        WITHOUT in-band IoB context -- it lives in devicestatus posted
        around the same time. Without the backfill, the dashboard's
        Recent Boluses table shows `---` in the IoB column for every
        NS-sourced bolus.
        """
        session, user_id, conn_id = translator_ctx

        # Insert a bolus first via the treatments path; it'll have
        # iob_at_event=None (Loop's bolus payload has no IoB field).
        await translate_treatments(
            [_load("treatments", "loop_correction_bolus")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()

        # Now run devicestatus translation -- the loop_devicestatus fixture
        # has iob.iob = 1.2; the loop_correction_bolus fixture is ~2 min later,
        # so the backfill correlates them via the 15-min window rule.
        #
        # The backfill window is `received_at - 14 days`, defaulting to now().
        # Anchor it to the devicestatus fixture's own timestamp (derived, not
        # hard-coded) so the test stays deterministic instead of aging out once
        # the wall clock drifts >14 days past the fixed-date fixtures.
        devicestatus = _load("devicestatus", "loop_devicestatus")
        fixture_received_at = datetime.fromisoformat(
            devicestatus["created_at"].replace("Z", "+00:00")
        )
        await translate_devicestatuses(
            [devicestatus],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
            received_at=fixture_received_at,
        )
        await session.flush()

        from src.models.pump_data import PumpEvent, PumpEventType

        bolus_row = (
            await session.execute(
                select(PumpEvent).where(
                    PumpEvent.user_id == user_id,
                    PumpEvent.event_type == PumpEventType.BOLUS,
                )
            )
        ).scalar_one()
        assert bolus_row.iob_at_event == 1.2
        assert bolus_row.cob_at_event == 12.0

    @pytest.mark.asyncio
    async def test_backfill_skips_bolus_with_no_preceding_snapshot(
        self, translator_ctx
    ):
        """If a bolus has no devicestatus posted in the 15-min window
        before it, the backfill leaves iob_at_event NULL -- we don't
        invent context."""
        session, user_id, conn_id = translator_ctx

        # Bolus only, no devicestatus translation at all.
        await translate_treatments(
            [_load("treatments", "loop_correction_bolus")],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()

        # Run devicestatus translation with NO devicestatus rows.
        await translate_devicestatuses(
            [],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.flush()

        from src.models.pump_data import PumpEvent, PumpEventType

        bolus_row = (
            await session.execute(
                select(PumpEvent).where(
                    PumpEvent.user_id == user_id,
                    PumpEvent.event_type == PumpEventType.BOLUS,
                )
            )
        ).scalar_one()
        assert bolus_row.iob_at_event is None


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


# ---------------------------------------------------------------------------
# Forecast path -> forecast_snapshots  (Story 43.12 PR 2)
# ---------------------------------------------------------------------------


def _ds(payload: dict[str, Any]) -> NightscoutDeviceStatus:
    """Shorthand to build a parsed devicestatus from a raw payload."""
    return NightscoutDeviceStatus.model_validate(payload)


def _loop_ds(
    *,
    ns_id: str = "loop123abc456def789012345",
    created_at: str = "2026-05-12T14:30:00.000Z",
    values: list[float] | None = None,
    start_date: str | None = "2026-05-12T14:30:00.000Z",
    device: str = "loop://iPhone",
) -> NightscoutDeviceStatus:
    """Build a Loop devicestatus carrying `loop.predicted.values[]`."""
    payload: dict[str, Any] = {
        "_id": ns_id,
        "created_at": created_at,
        "device": device,
        "loop": {
            "predicted": {
                "values": values
                if values is not None
                else [120, 122, 125, 128, 130, 131, 130, 128, 125],
            },
        },
    }
    if start_date is not None:
        payload["loop"]["predicted"]["startDate"] = start_date
    return _ds(payload)


def _openaps_ds(
    *,
    ns_id: str = "aaps123abc456def789012345",
    created_at: str = "2026-05-12T14:30:00.000Z",
    pred_bgs: dict[str, list[float]] | None = None,
    block: str = "suggested",
    device: str = "openaps://AndroidAPS",
) -> NightscoutDeviceStatus:
    """Build an OpenAPS-family devicestatus carrying `predBGs`."""
    if pred_bgs is None:
        pred_bgs = {
            "IOB": [120, 124, 130, 135, 138],
            "COB": [120, 130, 145, 160, 170],
            "UAM": [120, 125, 131, 138, 142],
            "ZT": [120, 125, 130, 132, 132],
        }
    return _ds(
        {
            "_id": ns_id,
            "created_at": created_at,
            "device": device,
            "openaps": {block: {"predBGs": pred_bgs}},
        }
    )


class TestForecastMapperExtraction:
    """Unit-level: per-source forecast extraction.

    Pins the mapper's per-platform wire-shape contract without touching
    the DB. Round-trip / dedupe / FK behavior lives in `TestForecastPath`
    below.
    """

    def test_loop_single_curve_maps_to_main(self):
        row = map_devicestatus_to_forecast(
            _loop_ds(values=[120, 122, 125, 128, 130]),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["source_engine"] == "loop"
        assert row["curves_mgdl_json"] == {"main": [120, 122, 125, 128, 130]}
        assert row["default_curve_name"] == "main"
        assert row["step_minutes"] == 5
        assert row["horizon_minutes"] == 25  # 5 points x 5 min

    def test_loop_start_date_anchors_t0(self):
        row = map_devicestatus_to_forecast(
            _loop_ds(
                created_at="2026-05-12T14:30:00.000Z",
                start_date="2026-05-12T14:25:00.000Z",
            ),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["issued_at"] == datetime(2026, 5, 12, 14, 30, tzinfo=UTC)
        # start_at falls back to startDate, NOT issued_at.
        assert row["start_at"] == datetime(2026, 5, 12, 14, 25, tzinfo=UTC)

    def test_loop_missing_start_date_falls_back_to_issued_at(self):
        row = map_devicestatus_to_forecast(
            _loop_ds(start_date=None),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["start_at"] == row["issued_at"]

    def test_aaps_all_four_curves_extracted(self):
        row = map_devicestatus_to_forecast(
            _openaps_ds(),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["source_engine"] == "aaps"
        assert set(row["curves_mgdl_json"].keys()) == {"IOB", "COB", "UAM", "ZT"}
        assert row["default_curve_name"] == "IOB"

    def test_aaps_only_iob_present(self):
        row = map_devicestatus_to_forecast(
            _openaps_ds(pred_bgs={"IOB": [120, 122, 125, 128]}),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["curves_mgdl_json"] == {"IOB": [120, 122, 125, 128]}
        assert row["default_curve_name"] == "IOB"

    def test_aaps_only_uam_falls_back_to_uam_default(self):
        """When the canonical priorities (IOB, COB) are absent but UAM
        is present, the mapper picks UAM as the default curve rather
        than dropping the row entirely."""
        row = map_devicestatus_to_forecast(
            _openaps_ds(pred_bgs={"UAM": [120, 125, 131]}),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["default_curve_name"] == "UAM"
        assert row["curves_mgdl_json"] == {"UAM": [120, 125, 131]}

    def test_trio_determination_block_preferred_over_suggested(self):
        """Trio writes both `determination.predBGs` AND
        `suggested.predBGs`. The mapper must read `determination`
        (the post-decision view that matches Trio's own UI) when
        both are present."""
        ds = _ds(
            {
                "_id": "trio123abc456def789012345",
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "Trio",
                "openaps": {
                    "suggested": {"predBGs": {"IOB": [100, 101, 102]}},
                    "determination": {"predBGs": {"IOB": [200, 201, 202]}},
                },
            }
        )
        row = map_devicestatus_to_forecast(
            ds, user_id="u1", nightscout_connection_id="c1"
        )
        assert row is not None
        assert row["source_engine"] == "trio"
        assert row["curves_mgdl_json"] == {"IOB": [200, 201, 202]}

    def test_oref0_detected_from_device_uri(self):
        """oref0 emits `device: openaps://<host>/<pump-ref>` (two-segment
        URI). Distinguished from AAPS's degenerate one-segment form."""
        row = map_devicestatus_to_forecast(
            _openaps_ds(
                pred_bgs={"IOB": [120, 122, 125, 127, 128, 128, 127]},
                device="openaps://edison-rig/medtronic-722",
            ),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["source_engine"] == "oref0"

    def test_devicestatus_without_forecast_returns_none(self):
        """xDrip+ / xDrip4iOS / share2ns regression guard: a payload
        that carries only `uploader.battery` (no loop, no openaps) must
        not create a forecast row."""
        ds = _ds(
            {
                "_id": "xdrip123abc456def789012",
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "xdrip-android",
                "uploader": {"battery": 87},
            }
        )
        row = map_devicestatus_to_forecast(
            ds, user_id="u1", nightscout_connection_id="c1"
        )
        assert row is None

    def test_loop_without_predicted_returns_none(self):
        """A Loop devicestatus with `loop.iob` but no `loop.predicted`
        (e.g., loop running but not posting predictions this cycle) is
        not a forecast and must skip."""
        ds = _ds(
            {
                "_id": "loop123abc456def789012345",
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "loop://iPhone",
                "loop": {"iob": {"iob": 2.5}},
            }
        )
        assert (
            map_devicestatus_to_forecast(
                ds, user_id="u1", nightscout_connection_id="c1"
            )
            is None
        )

    def test_loop_empty_values_returns_none(self):
        """An empty `predicted.values: []` array is not a usable
        forecast -- skip rather than land a 0-horizon row."""
        assert (
            map_devicestatus_to_forecast(
                _loop_ds(values=[]),
                user_id="u1",
                nightscout_connection_id="c1",
            )
            is None
        )

    def test_loop_malformed_values_returns_none(self):
        """Non-numeric entry in `values` rejects the whole curve --
        half-coerced curves are subtly worse than no curve."""
        assert (
            map_devicestatus_to_forecast(
                _loop_ds(values=[120, "broken", 125]),
                user_id="u1",
                nightscout_connection_id="c1",
            )
            is None
        )

    def test_loop_bool_in_values_rejected(self):
        """`isinstance(True, int)` is True in Python; a misbehaving
        uploader sending `[120, True, 122]` must NOT slip in as 1.0."""
        assert (
            map_devicestatus_to_forecast(
                _loop_ds(values=[120, True, 125]),
                user_id="u1",
                nightscout_connection_id="c1",
            )
            is None
        )

    def test_missing_ns_id_returns_none(self):
        """No `_id` means no dedupe key. Skip rather than invent one --
        consistent with the snapshot mapper's behavior."""
        ds = _ds(
            {
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "loop://iPhone",
                "loop": {"predicted": {"values": [120, 122, 125]}},
            }
        )
        assert (
            map_devicestatus_to_forecast(
                ds, user_id="u1", nightscout_connection_id="c1"
            )
            is None
        )

    def test_missing_created_at_returns_none(self):
        """No `created_at` means no `issued_at` -- the AI / chart
        legend would have nothing to anchor on."""
        ds = _ds(
            {
                "_id": "loop123abc456def789012345",
                "device": "loop://iPhone",
                "loop": {"predicted": {"values": [120, 122, 125]}},
            }
        )
        assert (
            map_devicestatus_to_forecast(
                ds, user_id="u1", nightscout_connection_id="c1"
            )
            is None
        )

    def test_unknown_openaps_engine_returns_none(self):
        """An OpenAPS-family payload whose device string can't be
        classified is skipped rather than mis-attributed. The CHECK
        constraint on the DB would reject `source_engine = "unknown"`
        anyway."""
        ds = _ds(
            {
                "_id": "mystery123abc456def78901",
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "some-future-uploader",
                "openaps": {"suggested": {"predBGs": {"IOB": [120, 122, 125]}}},
            }
        )
        assert (
            map_devicestatus_to_forecast(
                ds, user_id="u1", nightscout_connection_id="c1"
            )
            is None
        )

    def test_horizon_derived_from_default_curve_length(self):
        """Horizon = step * len(default curve). oref0's short ~7-point
        IOB curve must yield ~30 min horizon (oref0's known short
        forecast window)."""
        row = map_devicestatus_to_forecast(
            _openaps_ds(
                pred_bgs={
                    "IOB": [120, 121, 122, 123, 124, 125, 126],  # 7 pts
                    "COB": [120, 122, 124, 126, 128, 130, 132, 134],  # 8 pts
                },
                device="openaps://edison/medtronic",
            ),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        # Horizon driven by default (IOB), not the longer COB.
        assert row["horizon_minutes"] == 35

    def test_oversized_ns_id_returns_none(self):
        """The DB CHECK bounds dedupe_key to 128 chars. Mapper-level
        guard catches a verbose v3 envelope `_id` before the DB does."""
        ds = _ds(
            {
                "_id": "x" * 200,
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "loop://iPhone",
                "loop": {"predicted": {"values": [120, 122, 125]}},
            }
        )
        assert (
            map_devicestatus_to_forecast(
                ds, user_id="u1", nightscout_connection_id="c1"
            )
            is None
        )


class TestForecastPath:
    """Integration-level: translate_devicestatuses -> forecast_snapshots.

    Exercises the SAVEPOINT-isolated forecast write path that
    `translate_devicestatuses` runs alongside the snapshot + pump-event
    promotions.
    """

    @pytest.mark.asyncio
    async def test_loop_devicestatus_writes_forecast_row(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        raw = {
            "_id": "loop123abc456def789012345",
            "created_at": "2026-05-12T14:30:00.000Z",
            "device": "loop://iPhone",
            "loop": {
                "iob": {"iob": 2.1},
                "predicted": {
                    "startDate": "2026-05-12T14:30:00.000Z",
                    "values": [120, 122, 125, 128, 130, 131, 130, 128, 125],
                },
            },
        }
        outcome = await translate_devicestatuses(
            [raw],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()
        assert outcome.inserted == 1

        rows = (
            (
                await session.execute(
                    select(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].source_engine == "loop"
        assert rows[0].default_curve_name == "main"
        assert rows[0].curves_mgdl_json == {
            "main": [120, 122, 125, 128, 130, 131, 130, 128, 125]
        }
        # Snapshot row landed too -- forecast path doesn't replace it.
        assert (
            await session.scalar(
                select(func.count(DeviceStatusSnapshot.id)).where(
                    DeviceStatusSnapshot.user_id == user_id
                )
            )
            == 1
        )

    @pytest.mark.asyncio
    async def test_aaps_devicestatus_writes_multi_curve_forecast(self, translator_ctx):
        session, user_id, conn_id = translator_ctx
        raw = {
            "_id": "aaps123abc456def789012345",
            "created_at": "2026-05-12T14:30:00.000Z",
            "device": "openaps://AndroidAPS",
            "openaps": {
                "suggested": {
                    "predBGs": {
                        "IOB": [120, 124, 130, 135, 138],
                        "COB": [120, 130, 145, 160, 170],
                        "UAM": [120, 125, 131, 138, 142],
                        "ZT": [120, 125, 130, 132, 132],
                    },
                },
            },
        }
        await translate_devicestatuses(
            [raw],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        row = (
            await session.execute(
                select(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
            )
        ).scalar_one()
        assert row.source_engine == "aaps"
        assert set(row.curves_mgdl_json.keys()) == {"IOB", "COB", "UAM", "ZT"}

    @pytest.mark.asyncio
    async def test_re_translation_does_not_duplicate_forecast(self, translator_ctx):
        """Same NS `_id` arriving in two sync cycles produces one
        `forecast_snapshots` row, deduped via
        `(source_engine, dedupe_key)`."""
        session, user_id, conn_id = translator_ctx
        raw = {
            "_id": "stable123abc456def78901234",
            "created_at": "2026-05-12T14:30:00.000Z",
            "device": "loop://iPhone",
            "loop": {
                "predicted": {
                    "startDate": "2026-05-12T14:30:00.000Z",
                    "values": [120, 122, 125, 128],
                }
            },
        }
        for _ in range(2):
            await translate_devicestatuses(
                [raw],
                session=session,
                user_id=str(user_id),
                connection_id=str(conn_id),
            )
            await session.commit()

        count = await session.scalar(
            select(func.count(ForecastSnapshot.id)).where(
                ForecastSnapshot.user_id == user_id
            )
        )
        assert count == 1

    @pytest.mark.asyncio
    async def test_cgm_only_devicestatus_does_not_create_forecast(self, translator_ctx):
        """xDrip+ regression guard. A CGM-relay devicestatus must produce
        a `device_status_snapshots` row (battery / metadata) but NO
        `forecast_snapshots` row -- design Section 1 confirms xDrip+
        publishes no forecasts."""
        session, user_id, conn_id = translator_ctx
        raw = {
            "_id": "xdrip123abc456def789012",
            "created_at": "2026-05-12T14:30:00.000Z",
            "device": "xdrip-android",
            "uploader": {"battery": 87},
        }
        await translate_devicestatuses(
            [raw],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        ds_count = await session.scalar(
            select(func.count(DeviceStatusSnapshot.id)).where(
                DeviceStatusSnapshot.user_id == user_id
            )
        )
        fc_count = await session.scalar(
            select(func.count(ForecastSnapshot.id)).where(
                ForecastSnapshot.user_id == user_id
            )
        )
        assert ds_count == 1
        assert fc_count == 0

    @pytest.mark.asyncio
    async def test_mixed_batch_with_and_without_forecasts(self, translator_ctx):
        """A batch with one Loop forecast + one xDrip+ status + one
        AAPS forecast must produce exactly 2 forecast rows, 3 snapshots."""
        session, user_id, conn_id = translator_ctx
        raws = [
            {
                "_id": "loop_mixed_1abc456def789012345",
                "created_at": "2026-05-12T14:25:00.000Z",
                "device": "loop://iPhone",
                "loop": {"predicted": {"values": [120, 121, 122, 123]}},
            },
            {
                "_id": "xdrip_mixed_abc456def7890123",
                "created_at": "2026-05-12T14:27:00.000Z",
                "device": "xdrip-android",
                "uploader": {"battery": 84},
            },
            {
                "_id": "aaps_mixed_1abc456def789012345",
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "openaps://AndroidAPS",
                "openaps": {"suggested": {"predBGs": {"IOB": [110, 112, 114, 116]}}},
            },
        ]
        await translate_devicestatuses(
            raws,
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        ds_count = await session.scalar(
            select(func.count(DeviceStatusSnapshot.id)).where(
                DeviceStatusSnapshot.user_id == user_id
            )
        )
        fc_count = await session.scalar(
            select(func.count(ForecastSnapshot.id)).where(
                ForecastSnapshot.user_id == user_id
            )
        )
        assert ds_count == 3
        assert fc_count == 2
        engines = {
            r.source_engine
            for r in (
                await session.execute(
                    select(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
                )
            ).scalars()
        }
        assert engines == {"loop", "aaps"}


# ---------------------------------------------------------------------------
# Adversarial-review follow-up tests
# ---------------------------------------------------------------------------


class TestForecastMapperEdgeCases:
    """Pins behaviors that the adversarial review identified as
    structurally important but not previously covered: iAPS detection,
    Loop-vs-OpenAPS priority when both subtrees coexist, and the
    physiological-range clamp on curve values.
    """

    def test_iaps_detected_from_device_substring(self):
        """iAPS (iOS AAPS fork) carries `iAPS` as a literal substring
        in its device string. The mapper classifies as `iaps` even
        though `detect_uploader()` doesn't know about it yet -- we
        check inline before falling through. This keeps PR 1's shared
        helper untouched while wiring the migration-allowed
        `source_engine='iaps'` value to actual data."""
        ds = _ds(
            {
                "_id": "iaps123abc456def789012345",
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "iAPS-2.7.0",
                "openaps": {"suggested": {"predBGs": {"IOB": [120, 122, 125, 128]}}},
            }
        )
        row = map_devicestatus_to_forecast(
            ds, user_id="u1", nightscout_connection_id="c1"
        )
        assert row is not None
        assert row["source_engine"] == "iaps"

    def test_aaps_device_does_not_misclassify_as_iaps(self):
        """Regression guard: the canonical AAPS device strings
        (`openaps://AndroidAPS` for V1, `openaps://AndroidAPS-NSClientV3`
        for V3) do not contain the substring `iaps`. The iAPS branch's
        `"aaps" not in device_lower` guard also catches any hybrid
        like `iAPS-AAPS-bridge` and routes such payloads back to AAPS
        classification rather than mis-attributing to iAPS."""
        for device in (
            "openaps://AndroidAPS",
            "openaps://AndroidAPS-NSClientV3",
        ):
            row = map_devicestatus_to_forecast(
                _ds(
                    {
                        "_id": f"aaps_{uuid.uuid4().hex[:18]}",
                        "created_at": "2026-05-12T14:30:00.000Z",
                        "device": device,
                        "openaps": {"suggested": {"predBGs": {"IOB": [120, 122, 125]}}},
                    }
                ),
                user_id="u1",
                nightscout_connection_id="c1",
            )
            assert row is not None, f"AAPS variant {device!r} unexpectedly skipped"
            assert row["source_engine"] == "aaps", (
                f"AAPS device {device!r} mis-attributed as {row['source_engine']!r}"
            )

    def test_iaps_aaps_hybrid_routes_back_to_aaps(self):
        """If a (hypothetical) device string contains both `iaps` and
        `aaps` substrings, the iAPS branch's `"aaps" not in
        device_lower` guard rejects it and the AAPS classification
        wins via `detect_uploader()`. Belt-and-braces test against
        regressing the guard to a bare `"iaps" in device_lower`
        check."""
        row = map_devicestatus_to_forecast(
            _ds(
                {
                    "_id": "hybrid_iaps_aaps_abc456789",
                    "created_at": "2026-05-12T14:30:00.000Z",
                    "device": "openaps://AndroidAPS-iAPS-bridge",
                    "openaps": {"suggested": {"predBGs": {"IOB": [120, 122, 125]}}},
                }
            ),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["source_engine"] == "aaps"

    def test_loop_subtree_wins_when_both_loop_and_openaps_present(self):
        """A payload carrying BOTH `loop.predicted` and
        `openaps.suggested.predBGs` is rare (cross-bridge / dev
        sandbox setups) but possible. The mapper's documented
        priority is Loop -> OpenAPS; pin it so a future refactor
        can't silently flip the order."""
        ds = _ds(
            {
                "_id": "hybrid123abc456def78901234",
                "created_at": "2026-05-12T14:30:00.000Z",
                "device": "loop://iPhone",
                "loop": {"predicted": {"values": [200, 205, 210]}},
                "openaps": {"suggested": {"predBGs": {"IOB": [100, 101, 102]}}},
            }
        )
        row = map_devicestatus_to_forecast(
            ds, user_id="u1", nightscout_connection_id="c1"
        )
        assert row is not None
        assert row["source_engine"] == "loop"
        assert row["curves_mgdl_json"] == {"main": [200.0, 205.0, 210.0]}

    def test_curve_value_below_physiological_floor_rejected(self):
        """A glucose value of -50 mg/dL is sensor / data corruption.
        Storing it would let PR 4's chart render nonsensical extremes
        and PR 5's AI context repeat the absurd value to the user.
        Reject the whole curve, consistent with the strict
        non-numeric-entry policy."""
        assert (
            map_devicestatus_to_forecast(
                _loop_ds(values=[120, -50, 125, 128]),
                user_id="u1",
                nightscout_connection_id="c1",
            )
            is None
        )

    def test_curve_value_above_physiological_ceiling_rejected(self):
        """5000 mg/dL is impossible; reject same as below-floor."""
        assert (
            map_devicestatus_to_forecast(
                _loop_ds(values=[120, 122, 5000, 128]),
                user_id="u1",
                nightscout_connection_id="c1",
            )
            is None
        )

    def test_curve_values_at_band_edges_accepted(self):
        """Values exactly at 20 and 800 mg/dL are physiologically
        plausible (severe hypo and severe hyper); the clamp is
        inclusive of the bounds."""
        row = map_devicestatus_to_forecast(
            _loop_ds(values=[20, 100, 400, 800]),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert row["curves_mgdl_json"] == {"main": [20.0, 100.0, 400.0, 800.0]}

    def test_oversized_curve_rejected(self):
        """A malicious upstream Nightscout server posting a curve with
        > 288 points (a full day at 5-min step) would let the
        translator allocate unbounded memory and TOAST-bloat the JSONB
        column. Real forecasts max out at ~73 points (Loop's 6h
        horizon at 5-min step); 288 is generous future headroom.
        Defense-in-depth against curve-length DoS."""
        # 289 valid in-range points -- just past the cap.
        oversized = [120] * 289
        assert (
            map_devicestatus_to_forecast(
                _loop_ds(values=oversized),
                user_id="u1",
                nightscout_connection_id="c1",
            )
            is None
        )

    def test_curve_at_max_length_accepted(self):
        """288 points (a full day at 5-min) is the boundary -- last
        accepted size. Confirms the cap is inclusive."""
        full_day = [120] * 288
        row = map_devicestatus_to_forecast(
            _loop_ds(values=full_day),
            user_id="u1",
            nightscout_connection_id="c1",
        )
        assert row is not None
        assert len(row["curves_mgdl_json"]["main"]) == 288
        # horizon = step (5 min) * 288 points = 1440 min = 24h
        assert row["horizon_minutes"] == 1440


class TestForecastSavepointIsolation:
    """The central design claim of the translator's forecast hook is
    that a forecast-side failure does NOT roll back the device-status
    snapshots that already landed. This suite pins it directly --
    inject a failing forecast upsert and assert the snapshot still
    persists.
    """

    @pytest.mark.asyncio
    async def test_forecast_upsert_failure_does_not_roll_back_snapshot(
        self, translator_ctx, monkeypatch
    ):
        """Patch `_upsert_forecast_snapshots` to raise unconditionally.
        The translator's `try/except` around the savepoint must catch
        the error and let the device-status snapshot row stand.
        Without the SAVEPOINT isolation the outer transaction would
        be in a NEEDS_ROLLBACK state and the caller's `commit()`
        would either silently drop the snapshot or raise
        PendingRollbackError."""
        from src.services.integrations.nightscout import translator as translator_mod

        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated forecast write failure")

        monkeypatch.setattr(translator_mod, "_upsert_forecast_snapshots", _boom)

        session, user_id, conn_id = translator_ctx
        raw = {
            "_id": "isolation123abc456def78901",
            "created_at": "2026-05-12T14:30:00.000Z",
            "device": "loop://iPhone",
            "loop": {
                "predicted": {
                    "startDate": "2026-05-12T14:30:00.000Z",
                    "values": [120, 122, 125, 128, 130],
                }
            },
        }
        outcome = await translate_devicestatuses(
            [raw],
            session=session,
            user_id=str(user_id),
            connection_id=str(conn_id),
        )
        await session.commit()

        # Snapshot landed.
        assert outcome.inserted == 1
        assert (
            await session.scalar(
                select(func.count(DeviceStatusSnapshot.id)).where(
                    DeviceStatusSnapshot.user_id == user_id
                )
            )
            == 1
        )
        # Forecast did NOT land (the SAVEPOINT rolled back its work).
        assert (
            await session.scalar(
                select(func.count(ForecastSnapshot.id)).where(
                    ForecastSnapshot.user_id == user_id
                )
            )
            == 0
        )
