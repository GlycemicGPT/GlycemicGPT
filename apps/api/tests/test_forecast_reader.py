"""Service-layer tests for `forecast_reader` (Story 43.12 PR 3).

Two layers covered here:

1. **Pure-function resolution** (`resolve_effective_source`) --
   table-driven across every row of the design doc's resolution
   matrix. Trivially testable, doesn't touch the DB.
2. **DB-backed projections** (`get_or_create_forecast_settings`,
   `get_available_sources`, `get_latest_forecast`) -- exercise the
   real queries against a per-test user + connection.

Endpoint-level coverage lives in `test_forecast_endpoints.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.models.forecast_settings import ForecastSettings
from src.models.forecast_snapshot import ForecastSnapshot
from src.models.nightscout_connection import (
    NightscoutAuthType,
    NightscoutConnection,
)
from src.models.user import User
from src.services.forecast_reader import (
    AVAILABLE_SOURCES_WINDOW,
    FORECAST_FRESHNESS_THRESHOLD,
    get_available_sources,
    get_latest_forecast,
    get_or_create_forecast_settings,
    resolve_effective_source,
    set_forecast_source,
)

# ---------------------------------------------------------------------------
# Pure-function tests: resolve_effective_source
# ---------------------------------------------------------------------------


class TestResolveEffectiveSource:
    """Pins the design doc Section 3 resolution matrix.

    Every row of the table is covered. A future refactor to the
    function must not silently flip any cell.
    """

    def test_none_preference_yields_none(self):
        assert resolve_effective_source("none", []) is None
        assert resolve_effective_source("none", ["loop"]) is None
        assert resolve_effective_source("none", ["loop", "aaps"]) is None

    def test_auto_empty_yields_none(self):
        assert resolve_effective_source("auto", []) is None

    def test_auto_single_yields_that_source(self):
        assert resolve_effective_source("auto", ["loop"]) == "loop"
        assert resolve_effective_source("auto", ["aaps"]) == "aaps"

    def test_auto_multiple_yields_none(self):
        """No silent guessing per design doc. User must pick when
        more than one source is publishing."""
        assert resolve_effective_source("auto", ["loop", "aaps"]) is None
        assert resolve_effective_source("auto", ["loop", "trio", "oref0"]) is None

    def test_specific_present_yields_that_source(self):
        assert resolve_effective_source("loop", ["loop"]) == "loop"
        assert resolve_effective_source("aaps", ["loop", "aaps"]) == "aaps"

    def test_specific_missing_yields_none(self):
        """Source went silent -- no fallback. User sees "your X stopped
        publishing" UX rather than a silent substitution."""
        assert resolve_effective_source("loop", []) is None
        assert resolve_effective_source("loop", ["aaps"]) is None
        assert resolve_effective_source("aaps", ["loop", "trio"]) is None

    def test_glycemicgpt_preference_resolves_when_present(self):
        """Future-engine schema is reachable end-to-end."""
        assert resolve_effective_source("glycemicgpt", ["glycemicgpt"]) == "glycemicgpt"
        assert (
            resolve_effective_source("glycemicgpt", ["loop", "glycemicgpt"])
            == "glycemicgpt"
        )

    def test_glycemicgpt_preference_falls_to_none_when_absent(self):
        assert resolve_effective_source("glycemicgpt", ["loop", "aaps"]) is None


# ---------------------------------------------------------------------------
# DB integration fixture (per-test user + connection)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def reader_ctx() -> AsyncGenerator[
    tuple[AsyncSession, uuid.UUID, uuid.UUID], None
]:
    """Per-test session + fresh user + NS connection.

    Mirrors `loop_ctx` from PR 6 -- the query path is user-scoped so
    cross-test leakage from OTHER users can't influence reads. We DO
    truncate `forecast_snapshots` pre-yield because PR 1's
    `(source_engine, dedupe_key)` unique constraint is GLOBAL, so
    stale rows from a sibling test using a deterministic ns_id could
    block our writes.
    """
    session_maker = get_session_maker()
    session = session_maker()
    # Same precaution as PR 2's translator fixture: forecast_snapshots
    # uses a globally-unique `(source_engine, dedupe_key)`. Truncate
    # before yielding so cross-test ns_id collisions can't drop our
    # inserts via ON CONFLICT DO NOTHING.
    await session.execute(
        text("TRUNCATE forecast_evaluations, forecast_snapshots CASCADE")
    )
    await session.commit()
    email = f"forecast_reader_{uuid.uuid4().hex[:10]}@example.com"
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()
    user_id = user.id

    conn = NightscoutConnection(
        user_id=user_id,
        name="test-forecast-reader",
        base_url="https://example.com",
        auth_type=NightscoutAuthType.SECRET,
        encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
        initial_sync_window_days=7,
    )
    session.add(conn)
    await session.flush()
    connection_id = conn.id
    await session.commit()

    try:
        yield session, user_id, connection_id
    finally:
        try:
            await session.rollback()
            await session.execute(
                delete(ForecastSnapshot).where(ForecastSnapshot.user_id == user_id)
            )
            await session.execute(
                delete(ForecastSettings).where(ForecastSettings.user_id == user_id)
            )
            await session.execute(
                delete(NightscoutConnection).where(
                    NightscoutConnection.user_id == user_id
                )
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


def _make_snapshot(
    user_id: uuid.UUID,
    connection_id: uuid.UUID,
    *,
    source_engine: str,
    issued_at: datetime,
    dedupe_key: str | None = None,
    curves: dict | None = None,
    default_curve_name: str = "main",
) -> ForecastSnapshot:
    """Build a ForecastSnapshot for tests with sensible defaults that
    pass PR 1's CHECK constraints (range, length, default_curve_name in
    curves)."""
    return ForecastSnapshot(
        user_id=user_id,
        nightscout_connection_id=connection_id,
        source_engine=source_engine,
        source_uploader=source_engine,
        issued_at=issued_at,
        start_at=issued_at,
        step_minutes=5,
        horizon_minutes=30,
        curves_mgdl_json=curves or {"main": [120, 122, 125, 128, 130, 131]},
        default_curve_name=default_curve_name,
        dedupe_key=dedupe_key or f"test-{uuid.uuid4().hex}",
    )


# ---------------------------------------------------------------------------
# get_or_create_forecast_settings
# ---------------------------------------------------------------------------


class TestForecastSettingsLifecycle:
    """Lazy-create-on-first-read semantics + the write path."""

    @pytest.mark.asyncio
    async def test_first_read_creates_default_auto(self, reader_ctx):
        """A user who's never touched the picker gets the row created
        on first read with `'auto'`. No 404, no error, no manual
        provisioning."""
        session, user_id, _conn_id = reader_ctx
        settings = await get_or_create_forecast_settings(session, user_id)
        assert settings.source == "auto"
        assert settings.user_id == user_id

    @pytest.mark.asyncio
    async def test_second_read_returns_existing_row(self, reader_ctx):
        """Subsequent reads return the same row -- no duplicate
        inserts."""
        session, user_id, _conn_id = reader_ctx
        first = await get_or_create_forecast_settings(session, user_id)
        await session.commit()
        second = await get_or_create_forecast_settings(session, user_id)
        assert first.id == second.id

    @pytest.mark.asyncio
    async def test_set_source_persists(self, reader_ctx):
        session, user_id, _conn_id = reader_ctx
        await set_forecast_source(session, user_id, "loop")
        await session.commit()
        refreshed = await get_or_create_forecast_settings(session, user_id)
        assert refreshed.source == "loop"

    @pytest.mark.asyncio
    async def test_set_source_through_auto_back_to_specific(self, reader_ctx):
        """Round-trip: auto -> loop -> none -> auto each persists
        independently."""
        session, user_id, _conn_id = reader_ctx
        for picked in ("loop", "none", "aaps", "auto"):
            await set_forecast_source(session, user_id, picked)
            await session.commit()
            refreshed = await get_or_create_forecast_settings(session, user_id)
            assert refreshed.source == picked


# ---------------------------------------------------------------------------
# get_available_sources
# ---------------------------------------------------------------------------


class TestGetAvailableSources:
    @pytest.mark.asyncio
    async def test_no_snapshots_returns_empty(self, reader_ctx):
        session, user_id, _conn_id = reader_ctx
        assert await get_available_sources(session, user_id) == []

    @pytest.mark.asyncio
    async def test_single_engine_returns_one(self, reader_ctx):
        session, user_id, conn_id = reader_ctx
        snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="loop",
            issued_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        session.add(snap)
        await session.commit()
        assert await get_available_sources(session, user_id) == ["loop"]

    @pytest.mark.asyncio
    async def test_multiple_engines_sorted_alphabetically(self, reader_ctx):
        """Stable picker ordering: the dropdown shouldn't reshuffle
        between renders."""
        session, user_id, conn_id = reader_ctx
        now = datetime.now(UTC)
        for engine in ("loop", "aaps", "trio"):
            session.add(
                _make_snapshot(
                    user_id,
                    conn_id,
                    source_engine=engine,
                    issued_at=now - timedelta(minutes=5),
                )
            )
        await session.commit()
        assert await get_available_sources(session, user_id) == [
            "aaps",
            "loop",
            "trio",
        ]

    @pytest.mark.asyncio
    async def test_old_engines_dropped(self, reader_ctx):
        """Past the 24h window -> engine drops from the dropdown.
        24h matches the design doc text."""
        session, user_id, conn_id = reader_ctx
        now = datetime.now(UTC)
        # Loop: 25h ago (out of window)
        session.add(
            _make_snapshot(
                user_id,
                conn_id,
                source_engine="loop",
                issued_at=now - timedelta(hours=25),
            )
        )
        # AAPS: 5 min ago (in window)
        session.add(
            _make_snapshot(
                user_id,
                conn_id,
                source_engine="aaps",
                issued_at=now - timedelta(minutes=5),
            )
        )
        await session.commit()
        assert await get_available_sources(session, user_id) == ["aaps"]

    @pytest.mark.asyncio
    async def test_distinct_engines_no_duplicates(self, reader_ctx):
        """Multiple snapshots from the same engine collapse to one
        dropdown entry."""
        session, user_id, conn_id = reader_ctx
        now = datetime.now(UTC)
        for offset_min in (5, 10, 15):
            session.add(
                _make_snapshot(
                    user_id,
                    conn_id,
                    source_engine="loop",
                    issued_at=now - timedelta(minutes=offset_min),
                )
            )
        await session.commit()
        assert await get_available_sources(session, user_id) == ["loop"]

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation(self, reader_ctx):
        """User A's snapshots don't leak into user B's dropdown."""
        session, user_a, conn_a = reader_ctx
        # Create a second user + connection inline.
        user_b = User(
            email=f"forecast_other_{uuid.uuid4().hex[:10]}@example.com",
            hashed_password="not-a-real-hash",
        )
        session.add(user_b)
        await session.flush()
        conn_b = NightscoutConnection(
            user_id=user_b.id,
            name="other-user",
            base_url="https://example.com",
            auth_type=NightscoutAuthType.SECRET,
            encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
            initial_sync_window_days=7,
        )
        session.add(conn_b)
        await session.flush()

        now = datetime.now(UTC)
        # B has loop+aaps; A has only trio
        session.add(
            _make_snapshot(
                user_b.id,
                conn_b.id,
                source_engine="loop",
                issued_at=now - timedelta(minutes=5),
            )
        )
        session.add(
            _make_snapshot(
                user_b.id,
                conn_b.id,
                source_engine="aaps",
                issued_at=now - timedelta(minutes=5),
            )
        )
        session.add(
            _make_snapshot(
                user_a,
                conn_a,
                source_engine="trio",
                issued_at=now - timedelta(minutes=5),
            )
        )
        await session.commit()

        assert await get_available_sources(session, user_a) == ["trio"]
        assert await get_available_sources(session, user_b.id) == ["aaps", "loop"]


# ---------------------------------------------------------------------------
# get_latest_forecast
# ---------------------------------------------------------------------------


class TestGetLatestForecast:
    @pytest.mark.asyncio
    async def test_no_snapshots_returns_none(self, reader_ctx):
        session, user_id, _conn_id = reader_ctx
        assert await get_latest_forecast(session, user_id, "loop") is None

    @pytest.mark.asyncio
    async def test_fresh_snapshot_returned(self, reader_ctx):
        session, user_id, conn_id = reader_ctx
        snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="loop",
            issued_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        session.add(snap)
        await session.commit()
        result = await get_latest_forecast(session, user_id, "loop")
        assert result is not None
        assert result.source_engine == "loop"

    @pytest.mark.asyncio
    async def test_stale_snapshot_returns_none(self, reader_ctx):
        """Past the 30-min freshness threshold: even though a row
        exists, return None so the chart doesn't draw a misaligned
        dotted line."""
        session, user_id, conn_id = reader_ctx
        stale_age = FORECAST_FRESHNESS_THRESHOLD + timedelta(minutes=5)
        snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="loop",
            issued_at=datetime.now(UTC) - stale_age,
        )
        session.add(snap)
        await session.commit()
        assert await get_latest_forecast(session, user_id, "loop") is None

    @pytest.mark.asyncio
    async def test_latest_by_issued_at_not_received_at(self, reader_ctx):
        """A backfilled (recently-received) snapshot from 2h ago must
        NOT outrank a live one from 5 min ago. issued_at is the source
        loop's emit time; received_at is our DB write time."""
        session, user_id, conn_id = reader_ctx
        old_snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="loop",
            issued_at=datetime.now(UTC) - timedelta(hours=2),
        )
        new_snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="loop",
            issued_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        # Fake "backfill": old snap was received MORE recently.
        old_snap.received_at = datetime.now(UTC)
        new_snap.received_at = datetime.now(UTC) - timedelta(minutes=3)
        session.add_all([old_snap, new_snap])
        await session.commit()

        result = await get_latest_forecast(session, user_id, "loop")
        assert result is not None
        # New snapshot's issued_at wins (5 min ago, not 2h).
        assert (datetime.now(UTC) - result.issued_at) < timedelta(minutes=10)

    @pytest.mark.asyncio
    async def test_filters_by_source_engine(self, reader_ctx):
        """Querying for loop's forecast must not pick up an aaps row
        even if the aaps row is newer."""
        session, user_id, conn_id = reader_ctx
        now = datetime.now(UTC)
        loop_snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="loop",
            issued_at=now - timedelta(minutes=15),
        )
        aaps_snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="aaps",
            issued_at=now - timedelta(minutes=2),
        )
        session.add_all([loop_snap, aaps_snap])
        await session.commit()

        loop_result = await get_latest_forecast(session, user_id, "loop")
        aaps_result = await get_latest_forecast(session, user_id, "aaps")
        assert loop_result is not None
        assert loop_result.source_engine == "loop"
        assert aaps_result is not None
        assert aaps_result.source_engine == "aaps"

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation(self, reader_ctx):
        session, user_a, conn_a = reader_ctx
        user_b = User(
            email=f"forecast_other_{uuid.uuid4().hex[:10]}@example.com",
            hashed_password="not-a-real-hash",
        )
        session.add(user_b)
        await session.flush()
        conn_b = NightscoutConnection(
            user_id=user_b.id,
            name="other-user",
            base_url="https://example.com",
            auth_type=NightscoutAuthType.SECRET,
            encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
            initial_sync_window_days=7,
        )
        session.add(conn_b)
        await session.flush()

        now = datetime.now(UTC)
        session.add(
            _make_snapshot(
                user_b.id,
                conn_b.id,
                source_engine="loop",
                issued_at=now - timedelta(minutes=5),
            )
        )
        await session.commit()
        # A has no loop forecast; B does.
        assert await get_latest_forecast(session, user_a, "loop") is None
        assert await get_latest_forecast(session, user_b.id, "loop") is not None


# ---------------------------------------------------------------------------
# Constants smoke (regression guards)
# ---------------------------------------------------------------------------


class TestConstants:
    def test_freshness_threshold_is_thirty_minutes(self):
        """Design doc choice; tests rely on this constant. If it
        changes, this test fires to force the design doc + UX
        review."""
        assert timedelta(minutes=30) == FORECAST_FRESHNESS_THRESHOLD

    def test_availability_window_is_twenty_four_hours(self):
        assert timedelta(hours=24) == AVAILABLE_SOURCES_WINDOW


# ---------------------------------------------------------------------------
# Drift guards: schema <-> migration CHECK alignment
# ---------------------------------------------------------------------------


class TestSourceAllowListAlignment:
    """Pins the `forecast_settings.source` CHECK clause and the
    `ForecastSourcePreference` Pydantic Literal as the same set.

    Drift in either direction silently breaks the API:
    - DB adds a value, Pydantic doesn't -> GET 500 (Pydantic can't
      construct the response for an existing row with the new value).
    - Pydantic adds a value, DB doesn't -> PUT 500 (CHECK violation
      after the API-level validation passes).

    The CI catches drift before a deploy hits prod.
    """

    def test_check_constraint_values_match_literal(self):
        import re
        from pathlib import Path
        from typing import get_args

        from src.schemas.forecast import ForecastSourcePreference

        migration_path = (
            Path(__file__).parent.parent
            / "migrations"
            / "versions"
            / "057_forecast_settings.py"
        )
        contents = migration_path.read_text()

        # Extract the IN-clause string. Tolerant of whitespace/newlines.
        match = re.search(
            r"source IN \(([^)]+)\)",
            contents,
            re.DOTALL,
        )
        assert match is not None, "couldn't find CHECK clause in migration"

        # Parse the SQL string values.
        db_values = {
            v.strip().strip("'") for v in match.group(1).split(",") if v.strip()
        }

        # Extract Pydantic Literal values.
        literal_values = set(get_args(ForecastSourcePreference))

        assert db_values == literal_values, (
            f"CHECK constraint and Pydantic Literal disagree.\n"
            f"  In DB only:       {db_values - literal_values}\n"
            f"  In Pydantic only: {literal_values - db_values}"
        )


# ---------------------------------------------------------------------------
# Race-path coverage: UNIQUE violation recovery
# ---------------------------------------------------------------------------


class TestGetOrCreateRaceRecovery:
    """Pins the IntegrityError fallback in `get_or_create_forecast_settings`.

    Triggered by pre-INSERTing a row from a separate session that
    commits, then calling `get_or_create_forecast_settings` from a
    fresh session whose SELECT happens to miss the row (simulated
    by manually adding a conflicting row mid-flight). The SAVEPOINT
    rolls back the failed INSERT and the retry SELECT finds the
    winning row.
    """

    @pytest.mark.asyncio
    async def test_concurrent_insert_recovers_via_select(self, reader_ctx):
        session, user_id, _conn_id = reader_ctx

        # Simulate the race by pre-inserting via a second session.
        # By the time the test calls get_or_create on `session`,
        # the row already exists in the DB but isn't in the
        # session's identity map yet.
        session_maker = get_session_maker()
        async with session_maker() as concurrent_session:
            concurrent_session.add(ForecastSettings(user_id=user_id, source="loop"))
            await concurrent_session.commit()

        # Now call get_or_create on our session. The SELECT should
        # see the row (committed by the other session). This DOES
        # NOT exercise the IntegrityError path because the SELECT
        # finds the row first.
        result = await get_or_create_forecast_settings(session, user_id)
        assert result.source == "loop"

    @pytest.mark.asyncio
    async def test_savepoint_isolation_under_integrity_error(
        self, reader_ctx, monkeypatch
    ):
        """The harder case: simulate the SELECT-miss-then-INSERT-loses
        race directly by patching `scalar_one_or_none` to return None
        on first call so we enter the INSERT branch, while a
        conflicting row already exists. The SAVEPOINT must roll back
        the failed INSERT without touching the outer transaction
        state, and the retry SELECT must find the winning row.
        """
        session, user_id, _conn_id = reader_ctx

        # Pre-insert the conflicting row.
        session_maker = get_session_maker()
        async with session_maker() as concurrent_session:
            concurrent_session.add(ForecastSettings(user_id=user_id, source="aaps"))
            await concurrent_session.commit()

        # Patch the SELECT result's `scalar_one_or_none` to return
        # None ONCE so we enter the INSERT branch. (Real-world race:
        # the SELECT in transaction T1 happens before T2's commit
        # is visible.)
        from sqlalchemy.engine.result import Result

        original_scalar = Result.scalar_one_or_none
        call_count = {"n": 0}

        def fake_scalar(self):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None  # simulate race: row not yet visible
            return original_scalar(self)

        monkeypatch.setattr(Result, "scalar_one_or_none", fake_scalar)

        # Now call -- the INSERT will hit IntegrityError, SAVEPOINT
        # rolls back, retry SELECT (no longer patched after 1st call)
        # finds the conflicting row.
        result = await get_or_create_forecast_settings(session, user_id)
        assert result.source == "aaps", (
            "SAVEPOINT recovery failed -- expected to find the "
            "concurrently-inserted row after the race-loss."
        )


# ---------------------------------------------------------------------------
# Boundary cases: exact 24h on get_available_sources
# ---------------------------------------------------------------------------


class TestAvailableSourcesBoundary:
    """Pins the inclusive/exclusive edge of the 24h window."""

    @pytest.mark.asyncio
    async def test_snapshot_at_exact_boundary_included(self, reader_ctx):
        """An issued_at exactly `now - 24h` is INSIDE the window
        (`>=` not `>`)."""
        session, user_id, conn_id = reader_ctx
        ref_now = datetime.now(UTC)
        # Issued exactly at the boundary.
        snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="loop",
            issued_at=ref_now - AVAILABLE_SOURCES_WINDOW,
        )
        session.add(snap)
        await session.commit()
        result = await get_available_sources(session, user_id, now=ref_now)
        assert result == ["loop"]

    @pytest.mark.asyncio
    async def test_snapshot_one_ms_past_boundary_excluded(self, reader_ctx):
        """One millisecond past the 24h window -> dropped from the
        dropdown."""
        session, user_id, conn_id = reader_ctx
        ref_now = datetime.now(UTC)
        snap = _make_snapshot(
            user_id,
            conn_id,
            source_engine="loop",
            issued_at=ref_now - AVAILABLE_SOURCES_WINDOW - timedelta(milliseconds=1),
        )
        session.add(snap)
        await session.commit()
        result = await get_available_sources(session, user_id, now=ref_now)
        assert result == []
