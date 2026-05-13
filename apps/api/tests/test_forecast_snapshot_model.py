"""Model + schema tests for `forecast_snapshots` and `forecast_evaluations`.

Story 43.12 PR 1. The translator that writes to these tables lands in
PR 2 of the story; the read endpoint in PR 3. This file pins:

- Insert / round-trip of a representative ForecastSnapshot row for
  each of the wire-format families captured by the design doc
  (Loop single-curve, AAPS / Trio / oref0 multi-curve).
- The `(source_engine, dedupe_key)` uniqueness constraint -- the
  translator's UPSERT correctness rides on this.
- `forecast_evaluations` schema accepts the partial-row shape the
  future scoring job will write (actual_mgdl NULL when no CGM
  reading lands in the tolerance window).
- ON DELETE CASCADE wiring: dropping the parent snapshot drops its
  evaluations; dropping the user drops everything.

Design doc:
    `_bmad-output/planning-artifacts/story-43.12-forecast-overlay-design.md`
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.models.forecast_snapshot import ForecastEvaluation, ForecastSnapshot
from src.models.nightscout_connection import (
    NightscoutAuthType,
    NightscoutConnection,
)
from src.models.user import User

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fc_ctx() -> AsyncGenerator[
    tuple[AsyncSession, uuid.UUID, NightscoutConnection], None
]:
    """Per-test session + user + connection.

    Same shape as test_nightscout_sync.py's `sync_ctx` -- own
    session_maker so cross-loop teardown doesn't crash. Returns the
    session, the user's id, and a connection row so tests can attach
    forecast snapshots either to the connection (NS-imported path)
    or unattached (future engine path).
    """
    session_maker = get_session_maker()
    session = session_maker()
    # Pre-yield TRUNCATE: bulletproof against rows leaked by a malformed
    # prior test (NULL user_id, partially-rolled-back commit, etc.).
    # Teardown delete is best-effort; this is belt-and-braces.
    await session.execute(
        text("TRUNCATE forecast_evaluations, forecast_snapshots CASCADE")
    )
    await session.commit()
    email = f"forecast_{uuid.uuid4().hex[:10]}@example.com"
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()
    user_id = user.id

    conn = NightscoutConnection(
        user_id=user_id,
        name="test-forecast",
        base_url="https://example.com",
        auth_type=NightscoutAuthType.SECRET,
        encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
        initial_sync_window_days=7,
    )
    session.add(conn)
    await session.flush()
    await session.commit()

    try:
        yield session, user_id, conn
    finally:
        try:
            await session.rollback()
            # Explicit deletion in dependency order rather than relying
            # on FK cascade. Cascade is correct in healthy state, but
            # if a test left the session in an error state the cascade
            # didn't reliably fire here -- rows leaked into the next
            # test run, which then saw multiple-results errors on
            # source_engine queries that don't filter by user_id.
            # Defensive explicit deletes match the pattern in
            # test_nightscout_sync.py's sync_ctx fixture.
            await session.execute(
                delete(ForecastEvaluation).where(
                    ForecastEvaluation.forecast_snapshot_id.in_(
                        select(ForecastSnapshot.id).where(
                            ForecastSnapshot.user_id == user_id
                        )
                    )
                )
            )
            await session.execute(
                delete(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        except RuntimeError:
            pass
        finally:
            try:
                await session.close()
            except RuntimeError:
                pass


# ---------------------------------------------------------------------------
# Sample payload builders (per source family)
# ---------------------------------------------------------------------------


def _loop_curve() -> tuple[dict, str]:
    """Loop's single-curve shape. {default_curve_name} == "main"."""
    return ({"main": [120, 122, 125, 128, 130, 131, 130, 128, 125]}, "main")


def _aaps_curves() -> tuple[dict, str]:
    """AAPS / Trio / oref0 multi-curve shape. Default to "IOB" curve
    because that's the source's own default; the picker lets a power
    user switch later (deferred)."""
    return (
        {
            "IOB": [120, 124, 130, 135, 138],
            "COB": [120, 130, 145, 160, 170],
            "UAM": [120, 125, 131, 138, 142],
            "ZT": [120, 125, 130, 132, 132],
        },
        "IOB",
    )


def _aaps_curves_iob_only() -> tuple[dict, str]:
    """AAPS sometimes posts only IOB (no carbs active, no UAM
    detected, no zero-temp scenario). Translator must tolerate."""
    return ({"IOB": [120, 122, 125, 128]}, "IOB")


# ---------------------------------------------------------------------------
# Insert + round-trip tests
# ---------------------------------------------------------------------------


class TestForecastSnapshotInsert:
    """Round-trip insertion tests for the wire-format families captured
    by the design doc: Loop single-curve, AAPS / Trio / oref0 multi-curve,
    and the future engine-emitted path (no NS connection FK)."""

    @pytest.mark.asyncio
    async def test_loop_single_curve_round_trip(self, fc_ctx):
        """Loop's single-curve payload round-trips intact, including
        the server-defaulted `received_at`."""
        session, user_id, conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _loop_curve()

        snap = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=conn.id,
            source_engine="loop",
            source_uploader="loop",
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=40,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=f"loop-{uuid.uuid4().hex}",
        )
        session.add(snap)
        await session.commit()

        result = await session.execute(
            select(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
        )
        row = result.scalar_one()
        assert row.source_engine == "loop"
        assert row.default_curve_name == "main"
        assert row.curves_mgdl_json == {
            "main": [120, 122, 125, 128, 130, 131, 130, 128, 125]
        }
        # received_at is server-defaulted -- assert it landed
        assert row.received_at is not None

    @pytest.mark.asyncio
    async def test_aaps_multi_curve_round_trip(self, fc_ctx):
        """AAPS's multi-curve payload (IOB/COB/UAM/ZT) round-trips with
        all four keys preserved and IOB as the source's default."""
        session, user_id, conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _aaps_curves()

        snap = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=conn.id,
            source_engine="aaps",
            source_uploader="aaps",
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=20,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=f"aaps-{uuid.uuid4().hex}",
        )
        session.add(snap)
        await session.commit()

        result = await session.execute(
            select(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
        )
        row = result.scalar_one()
        assert set(row.curves_mgdl_json.keys()) == {"IOB", "COB", "UAM", "ZT"}
        assert row.default_curve_name == "IOB"

    @pytest.mark.asyncio
    async def test_aaps_partial_curves_round_trip(self, fc_ctx):
        """Partial-curve payload: only IOB present. Required: must
        store without breaking on missing COB/UAM/ZT and surface
        IOB as the default."""
        session, user_id, conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _aaps_curves_iob_only()

        snap = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=conn.id,
            source_engine="aaps",
            source_uploader="aaps",
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=15,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=f"aaps-{uuid.uuid4().hex}",
        )
        session.add(snap)
        await session.commit()

        result = await session.execute(
            select(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
        )
        row = result.scalar_one()
        assert row.curves_mgdl_json == {"IOB": [120, 122, 125, 128]}

    @pytest.mark.asyncio
    async def test_engine_source_without_connection(self, fc_ctx):
        """Future-engine path: source_engine = "glycemicgpt", no NS
        connection FK. The column is nullable for exactly this case;
        regression-guard so a future migration doesn't accidentally
        constrain it."""
        session, user_id, _conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _loop_curve()

        snap = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=None,  # <-- key part
            source_engine="glycemicgpt",
            source_uploader=None,
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=40,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=f"gg-{uuid.uuid4().hex}",
        )
        session.add(snap)
        await session.commit()

        # Scope to this test's user -- cross-test leakage (e.g., a
        # prior failing test that didn't clean up) would otherwise
        # produce multiple rows and break scalar_one().
        result = await session.execute(
            select(ForecastSnapshot).where(
                ForecastSnapshot.user_id == user_id,
                ForecastSnapshot.source_engine == "glycemicgpt",
            )
        )
        row = result.scalar_one()
        assert row.nightscout_connection_id is None
        assert row.source_engine == "glycemicgpt"


# ---------------------------------------------------------------------------
# Uniqueness + idempotency
# ---------------------------------------------------------------------------


class TestForecastSnapshotUniqueness:
    """Pins `(source_engine, dedupe_key)` UPSERT semantics:
    same key + same engine rejects (idempotency); same key + different
    engines allowed (cross-source non-collision)."""

    @pytest.mark.asyncio
    async def test_same_source_engine_and_dedupe_key_rejects(self, fc_ctx):
        """Same NS devicestatus _id arriving twice (different sync
        cycles, same upstream row) must NOT create two ForecastSnapshot
        rows. Translator's UPSERT correctness depends on this."""
        session, user_id, conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _loop_curve()
        ns_id = "abc123def456abc123def456"  # 24-char mongo objectid shape

        snap1 = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=conn.id,
            source_engine="loop",
            source_uploader="loop",
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=40,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=ns_id,
        )
        session.add(snap1)
        await session.commit()

        snap2 = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=conn.id,
            source_engine="loop",
            source_uploader="loop",
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=40,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=ns_id,  # same key
        )
        session.add(snap2)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_same_dedupe_key_different_source_engine_allowed(self, fc_ctx):
        """Different engines might both pick `_id = abc123...` by
        coincidence (NS Mongo ObjectIds are 24-hex, the GlycemicGPT
        engine mints UUIDs but the test pins the cross-source
        non-collision contract independent of length). Translator
        UPSERTs by `(source_engine, dedupe_key)`, not dedupe_key
        alone."""
        session, user_id, conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _loop_curve()
        same_key = "abc123def456abc123def456"

        for engine in ("loop", "aaps"):
            snap = ForecastSnapshot(
                user_id=user_id,
                nightscout_connection_id=conn.id,
                source_engine=engine,
                source_uploader=engine,
                issued_at=issued,
                start_at=issued,
                step_minutes=5,
                horizon_minutes=40,
                curves_mgdl_json=curves,
                default_curve_name=default_curve,
                dedupe_key=same_key,
            )
            session.add(snap)
            await session.commit()

        result = await session.execute(
            select(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
        )
        rows = result.scalars().all()
        assert len(rows) == 2
        assert {r.source_engine for r in rows} == {"loop", "aaps"}


# ---------------------------------------------------------------------------
# ForecastEvaluation
# ---------------------------------------------------------------------------


class TestForecastEvaluation:
    """Pins the schema contract for the deferred scoring job: partial
    rows (NULL actual), idempotent UPSERT by (snapshot_id, offset), and
    snapshot-delete cascade."""

    @pytest.mark.asyncio
    async def test_evaluation_partial_row(self, fc_ctx):
        """The future scoring job writes one evaluation row per
        forecast offset. `actual_mgdl` is NULL when no CGM reading
        landed within tolerance -- the schema must accept that."""
        session, user_id, conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _loop_curve()
        snap = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=conn.id,
            source_engine="loop",
            source_uploader="loop",
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=40,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=f"loop-{uuid.uuid4().hex}",
        )
        session.add(snap)
        await session.flush()

        # Scored point: actual reading landed exactly.
        eval_scored = ForecastEvaluation(
            forecast_snapshot_id=snap.id,
            offset_minutes=5,
            predicted_mgdl=122.0,
            actual_mgdl=120.0,
            actual_offset_seconds=0,
        )
        # Unscored point: CGM dropout, no reading in window.
        eval_unscored = ForecastEvaluation(
            forecast_snapshot_id=snap.id,
            offset_minutes=10,
            predicted_mgdl=125.0,
            actual_mgdl=None,
            actual_offset_seconds=None,
        )
        session.add_all([eval_scored, eval_unscored])
        await session.commit()

        result = await session.execute(
            select(ForecastEvaluation)
            .where(ForecastEvaluation.forecast_snapshot_id == snap.id)
            .order_by(ForecastEvaluation.offset_minutes)
        )
        rows = result.scalars().all()
        assert len(rows) == 2
        assert rows[0].actual_mgdl == 120.0
        assert rows[0].actual_offset_seconds == 0
        assert rows[1].actual_mgdl is None
        assert rows[1].actual_offset_seconds is None

    @pytest.mark.asyncio
    async def test_evaluation_same_offset_rejected(self, fc_ctx):
        """Re-running the scoring job on the same snapshot must not
        produce duplicate offset rows. UPSERT relies on the
        `(forecast_snapshot_id, offset_minutes)` unique constraint."""
        session, user_id, conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _loop_curve()
        snap = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=conn.id,
            source_engine="loop",
            source_uploader="loop",
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=40,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=f"loop-{uuid.uuid4().hex}",
        )
        session.add(snap)
        await session.flush()

        session.add(
            ForecastEvaluation(
                forecast_snapshot_id=snap.id,
                offset_minutes=5,
                predicted_mgdl=122.0,
                actual_mgdl=120.0,
            )
        )
        await session.commit()

        session.add(
            ForecastEvaluation(
                forecast_snapshot_id=snap.id,
                offset_minutes=5,  # duplicate
                predicted_mgdl=122.0,
                actual_mgdl=121.0,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_evaluation_cascades_on_snapshot_delete(self, fc_ctx):
        """Drop the parent snapshot; the eval rows go with it."""
        session, user_id, conn = fc_ctx
        issued = datetime.now(UTC)
        curves, default_curve = _loop_curve()
        snap = ForecastSnapshot(
            user_id=user_id,
            nightscout_connection_id=conn.id,
            source_engine="loop",
            source_uploader="loop",
            issued_at=issued,
            start_at=issued,
            step_minutes=5,
            horizon_minutes=40,
            curves_mgdl_json=curves,
            default_curve_name=default_curve,
            dedupe_key=f"loop-{uuid.uuid4().hex}",
        )
        session.add(snap)
        await session.flush()
        session.add(
            ForecastEvaluation(
                forecast_snapshot_id=snap.id,
                offset_minutes=5,
                predicted_mgdl=122.0,
                actual_mgdl=120.0,
            )
        )
        await session.commit()
        snap_id = snap.id

        await session.execute(
            delete(ForecastSnapshot).where(ForecastSnapshot.id == snap_id)
        )
        await session.commit()

        # The evaluation row is gone too.
        result = await session.execute(
            select(ForecastEvaluation).where(
                ForecastEvaluation.forecast_snapshot_id == snap_id
            )
        )
        assert result.scalars().first() is None


# ---------------------------------------------------------------------------
# Time-series query path (latest forecast per source for a user)
# ---------------------------------------------------------------------------


class TestForecastQueryByLatest:
    """Verifies the read path's index ordering for
    `(user_id, source_engine, issued_at DESC)`."""

    @pytest.mark.asyncio
    async def test_latest_per_source_via_issued_at_index(self, fc_ctx):
        """Read endpoint will hit `ix_forecast_user_source_issued` to
        answer 'give me this user's latest Loop forecast'. Verify the
        ordering does what the index claims."""
        session, user_id, conn = fc_ctx
        base = datetime.now(UTC)
        curves, default_curve = _loop_curve()

        # Three Loop forecasts, 5 min apart.
        for i in range(3):
            session.add(
                ForecastSnapshot(
                    user_id=user_id,
                    nightscout_connection_id=conn.id,
                    source_engine="loop",
                    source_uploader="loop",
                    issued_at=base - timedelta(minutes=(2 - i) * 5),
                    start_at=base - timedelta(minutes=(2 - i) * 5),
                    step_minutes=5,
                    horizon_minutes=40,
                    curves_mgdl_json=curves,
                    default_curve_name=default_curve,
                    dedupe_key=f"loop-{i}-{uuid.uuid4().hex}",
                )
            )
        await session.commit()

        # "Latest Loop forecast for this user" query.
        latest = (
            await session.execute(
                select(ForecastSnapshot)
                .where(
                    ForecastSnapshot.user_id == user_id,
                    ForecastSnapshot.source_engine == "loop",
                )
                .order_by(ForecastSnapshot.issued_at.desc())
                .limit(1)
            )
        ).scalar_one()
        assert latest.issued_at == base  # the most-recent one


# ---------------------------------------------------------------------------
# DB-level invariants (CHECK constraints from migration 055)
# ---------------------------------------------------------------------------


class TestForecastDbInvariants:
    """Pins the CHECK constraints the migration declares. Each test
    proves the DB rejects a malformed row that a buggy PR 2 translator
    might otherwise land.
    """

    async def _base_snap_kwargs(self, user_id: uuid.UUID) -> dict:
        issued = datetime.now(UTC)
        curves, default_curve = _loop_curve()
        return {
            "user_id": user_id,
            "nightscout_connection_id": None,
            "source_engine": "loop",
            "source_uploader": "loop",
            "issued_at": issued,
            "start_at": issued,
            "step_minutes": 5,
            "horizon_minutes": 40,
            "curves_mgdl_json": curves,
            "default_curve_name": default_curve,
            "dedupe_key": f"loop-{uuid.uuid4().hex}",
        }

    @pytest.mark.asyncio
    async def test_unknown_source_engine_rejected(self, fc_ctx):
        session, user_id, _conn = fc_ctx
        kwargs = await self._base_snap_kwargs(user_id)
        kwargs["source_engine"] = "AAPS"  # casing typo, NOT in allowed set
        session.add(ForecastSnapshot(**kwargs))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_zero_step_minutes_rejected(self, fc_ctx):
        """`step_minutes=0` would divide by zero on chart render."""
        session, user_id, _conn = fc_ctx
        kwargs = await self._base_snap_kwargs(user_id)
        kwargs["step_minutes"] = 0
        session.add(ForecastSnapshot(**kwargs))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_negative_horizon_minutes_rejected(self, fc_ctx):
        """A negative horizon is physically meaningless."""
        session, user_id, _conn = fc_ctx
        kwargs = await self._base_snap_kwargs(user_id)
        kwargs["horizon_minutes"] = -5
        session.add(ForecastSnapshot(**kwargs))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_default_curve_missing_from_curves_rejected(self, fc_ctx):
        """default_curve_name = "IOB" but curves only has "main".
        Read endpoint would KeyError. DB must reject."""
        session, user_id, _conn = fc_ctx
        kwargs = await self._base_snap_kwargs(user_id)
        kwargs["curves_mgdl_json"] = {"main": [120, 122]}
        kwargs["default_curve_name"] = "IOB"  # not in curves
        session.add(ForecastSnapshot(**kwargs))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_empty_dedupe_key_rejected(self, fc_ctx):
        """Empty dedupe key would defeat UPSERT idempotency."""
        session, user_id, _conn = fc_ctx
        kwargs = await self._base_snap_kwargs(user_id)
        kwargs["dedupe_key"] = ""
        session.add(ForecastSnapshot(**kwargs))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_oversized_dedupe_key_rejected(self, fc_ctx):
        """Bounds against a malformed translator writing huge strings."""
        session, user_id, _conn = fc_ctx
        kwargs = await self._base_snap_kwargs(user_id)
        kwargs["dedupe_key"] = "x" * 200  # over 128
        session.add(ForecastSnapshot(**kwargs))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_evaluation_fk_rejects_bogus_snapshot(self, fc_ctx):
        """Inserting an eval row pointing at a non-existent snapshot
        must fail at the FK boundary, not later."""
        session, _user_id, _conn = fc_ctx
        session.add(
            ForecastEvaluation(
                forecast_snapshot_id=uuid.uuid4(),  # no such snapshot
                offset_minutes=5,
                predicted_mgdl=120.0,
                actual_mgdl=120.0,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_evaluation_negative_offset_rejected(self, fc_ctx):
        """A negative `offset_minutes` would mean a forecast point
        before the forecast was issued -- nonsense, and would corrupt
        MAE / coverage rollups. The DB must reject it."""
        session, user_id, conn = fc_ctx
        kwargs = await self._base_snap_kwargs(user_id)
        kwargs["nightscout_connection_id"] = conn.id
        snap = ForecastSnapshot(**kwargs)
        session.add(snap)
        await session.flush()

        session.add(
            ForecastEvaluation(
                forecast_snapshot_id=snap.id,
                offset_minutes=-5,  # invalid
                predicted_mgdl=120.0,
                actual_mgdl=120.0,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_non_utc_timezone_round_trip(self, fc_ctx):
        """PR 2 translator may receive timestamps in non-UTC offsets
        (NS payloads carry whatever the uploader's clock reports).
        DB stores TIMESTAMPTZ; round-trip must preserve the absolute
        instant regardless of the wire-format tz."""
        session, user_id, _conn = fc_ctx
        # 14:30 in UTC+05:30 == 09:00 UTC
        ist = timezone(timedelta(hours=5, minutes=30))
        issued_local = datetime(2026, 5, 12, 14, 30, 0, tzinfo=ist)
        kwargs = await self._base_snap_kwargs(user_id)
        kwargs["issued_at"] = issued_local
        kwargs["start_at"] = issued_local
        session.add(ForecastSnapshot(**kwargs))
        await session.commit()

        row = (
            await session.execute(
                select(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
            )
        ).scalar_one()
        # Postgres TIMESTAMPTZ normalizes to UTC on storage.
        assert row.issued_at.tzinfo is not None
        assert row.issued_at == issued_local  # same absolute instant
        # Confirm the absolute-instant equivalence explicitly.
        assert row.issued_at.astimezone(UTC) == datetime(
            2026, 5, 12, 9, 0, 0, tzinfo=UTC
        )
