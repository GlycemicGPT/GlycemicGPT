"""Tests for the background Nightscout sync scheduler.

Mocks `sync_nightscout_for_connection` at the module boundary so we
exercise the real discovery query + per-row isolation logic without
hitting an actual Nightscout instance. Live end-to-end coverage --
"the scheduler tick triggers a real fetch + translate" -- is left to
manual verification against the dev synthetic uploader (see
`dev/ns_synthetic_uploader.py`); the unit-tested seam here is the
"who's due, what happens when one fails" decision tree.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.models.nightscout_connection import (
    NightscoutAuthType,
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.models.user import User
from src.services.integrations.nightscout.scheduler import (
    _clamped_interval,
    _is_due,
    run_nightscout_sync_all_users,
)
from src.services.integrations.nightscout.sync import SyncResult

# ---------------------------------------------------------------------------
# _is_due: the discovery predicate
# ---------------------------------------------------------------------------


class TestIsDue:
    def test_never_synced_is_always_due(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        assert _is_due(None, 5, now=now) is True

    def test_within_window_not_due(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        last = now - timedelta(minutes=3)
        assert _is_due(last, 5, now=now) is False

    def test_at_exact_window_is_due(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        last = now - timedelta(minutes=5)
        assert _is_due(last, 5, now=now) is True

    def test_well_past_window_is_due(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        last = now - timedelta(hours=3)
        assert _is_due(last, 5, now=now) is True

    def test_naive_timestamp_is_treated_as_utc(self):
        """Defensive: column is timezone=True so we shouldn't see this,
        but if a naive datetime sneaks in we don't want a TypeError."""
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        last = datetime(2026, 5, 10, 11, 0)  # naive
        assert _is_due(last, 5, now=now) is True


class TestClampedInterval:
    def test_in_range_passes_through(self):
        assert _clamped_interval(60) == 60

    def test_below_min_clamps(self):
        # SYNC_INTERVAL_MIN_MINUTES = 1
        assert _clamped_interval(0) == 1
        assert _clamped_interval(-5) == 1

    def test_above_max_clamps(self):
        # SYNC_INTERVAL_MAX_MINUTES = 1440 (24h)
        assert _clamped_interval(10000) == 1440


# ---------------------------------------------------------------------------
# Discovery + per-row isolation
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def scheduler_ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID], None]:
    """Provide a session + a user that owns several test connections.

    Mirrors the pattern used by other Nightscout test files -- own
    session_maker so cross-loop teardown noise stays cosmetic.
    """
    session_maker = get_session_maker()
    session = session_maker()
    email = f"sched_{uuid.uuid4().hex[:10]}@example.com"
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()
    user_id = user.id
    await session.commit()
    try:
        yield session, user_id
    finally:
        try:
            await session.rollback()
            await session.execute(
                delete(NightscoutConnection).where(
                    NightscoutConnection.user_id == user_id
                )
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        except Exception:
            # Broad catch on cleanup: a SQLAlchemy / asyncpg cross-loop
            # error here would otherwise mask the real test failure.
            # Cosmetic noise during teardown is the price.
            pass
        finally:
            try:
                await session.close()
            except Exception:
                pass


def _mk_connection(
    user_id: uuid.UUID,
    *,
    name: str,
    interval_minutes: int = 5,
    last_synced_at: datetime | None = None,
    last_sync_status: NightscoutSyncStatus = NightscoutSyncStatus.NEVER,
    is_active: bool = True,
) -> NightscoutConnection:
    return NightscoutConnection(
        user_id=user_id,
        name=name,
        base_url="https://example.com",
        auth_type=NightscoutAuthType.SECRET,
        encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
        sync_interval_minutes=interval_minutes,
        is_active=is_active,
        last_synced_at=last_synced_at,
        last_sync_status=last_sync_status,
    )


def _ok_result(connection_id: uuid.UUID) -> SyncResult:
    return SyncResult(
        connection_id=str(connection_id),
        status=NightscoutSyncStatus.OK,
        entries_inserted=1,
        entries_skipped=0,
        entries_failed=0,
        treatments_inserted_pump=0,
        treatments_inserted_glucose=0,
        treatments_failed=0,
        devicestatuses_inserted=0,
        devicestatuses_failed=0,
        profile_synced=False,
        duration_ms=42,
        error=None,
    )


class TestRunNightscoutSyncAllUsers:
    @pytest.mark.asyncio
    async def test_only_due_connections_get_synced(self, scheduler_ctx):
        """Connections whose interval hasn't elapsed are skipped.

        Filters synced IDs to this test's user so leftover rows from
        prior interrupted runs don't pollute the assertion.
        """
        session, user_id = scheduler_ctx
        now = datetime.now(UTC)
        # Due (never synced)
        a = _mk_connection(user_id, name="due-a", interval_minutes=5)
        # Due (last synced 10m ago, interval=5)
        b = _mk_connection(
            user_id,
            name="due-b",
            interval_minutes=5,
            last_synced_at=now - timedelta(minutes=10),
            last_sync_status=NightscoutSyncStatus.OK,
        )
        # Not due (last synced 1m ago, interval=60)
        c = _mk_connection(
            user_id,
            name="not-due",
            interval_minutes=60,
            last_synced_at=now - timedelta(minutes=1),
            last_sync_status=NightscoutSyncStatus.OK,
        )
        session.add_all([a, b, c])
        await session.commit()
        a_id, b_id, c_id = a.id, b.id, c.id

        synced_for_test_user: set[uuid.UUID] = set()

        async def fake_sync(_session, conn):
            if conn.user_id == user_id:
                synced_for_test_user.add(conn.id)
            return _ok_result(conn.id)

        with patch(
            "src.services.integrations.nightscout.scheduler.sync_nightscout_for_connection",
            side_effect=fake_sync,
        ):
            await run_nightscout_sync_all_users()

        assert synced_for_test_user == {a_id, b_id}
        assert c_id not in synced_for_test_user

    @pytest.mark.asyncio
    async def test_inactive_connections_excluded(self, scheduler_ctx):
        """Soft-deleted (is_active=false) rows are ignored."""
        session, user_id = scheduler_ctx
        active = _mk_connection(user_id, name="active")
        inactive = _mk_connection(user_id, name="inactive", is_active=False)
        session.add_all([active, inactive])
        await session.commit()
        active_id = active.id

        synced_for_test_user: list[uuid.UUID] = []

        async def fake_sync(_session, conn):
            if conn.user_id == user_id:
                synced_for_test_user.append(conn.id)
            return _ok_result(conn.id)

        with patch(
            "src.services.integrations.nightscout.scheduler.sync_nightscout_for_connection",
            side_effect=fake_sync,
        ):
            await run_nightscout_sync_all_users()

        assert synced_for_test_user == [active_id]

    @pytest.mark.asyncio
    async def test_auth_failed_connection_excluded(self, scheduler_ctx):
        """AUTH_FAILED is sticky -- requires user re-auth, no auto retry."""
        session, user_id = scheduler_ctx
        ok = _mk_connection(user_id, name="ok-conn")
        broken = _mk_connection(
            user_id,
            name="auth-failed-conn",
            last_sync_status=NightscoutSyncStatus.AUTH_FAILED,
        )
        session.add_all([ok, broken])
        await session.commit()
        ok_id = ok.id

        synced_for_test_user: list[uuid.UUID] = []

        async def fake_sync(_session, conn):
            if conn.user_id == user_id:
                synced_for_test_user.append(conn.id)
            return _ok_result(conn.id)

        with patch(
            "src.services.integrations.nightscout.scheduler.sync_nightscout_for_connection",
            side_effect=fake_sync,
        ):
            await run_nightscout_sync_all_users()

        assert synced_for_test_user == [ok_id]

    @pytest.mark.asyncio
    async def test_paused_statuses_set_is_minimal(self):
        """Pinned set for the discovery filter.

        UNREACHABLE is intentionally NOT in `_PAUSED_STATUSES` yet --
        the model defines it for a future "consecutive-failure circuit
        breaker" that no code path currently writes. Adding it to the
        exclusion now would advertise a circuit breaker that doesn't
        exist. When the breaker is wired in its own PR, expand this
        test alongside the new code.
        """
        from src.services.integrations.nightscout.scheduler import (
            _PAUSED_STATUSES,
        )

        assert frozenset({NightscoutSyncStatus.AUTH_FAILED}) == _PAUSED_STATUSES

    @pytest.mark.asyncio
    async def test_one_connection_failing_does_not_block_others(self, scheduler_ctx):
        """Per-connection isolation: a raise on one row doesn't kill the tick."""
        session, user_id = scheduler_ctx
        a = _mk_connection(user_id, name="a")
        b = _mk_connection(user_id, name="b")
        c = _mk_connection(user_id, name="c")
        session.add_all([a, b, c])
        await session.commit()
        a_id, b_id, c_id = a.id, b.id, c.id

        synced_ok_for_test_user: set[uuid.UUID] = set()

        async def fake_sync(_session, conn):
            if conn.id == b_id:
                raise RuntimeError("simulated upstream blowup on conn-b")
            if conn.user_id == user_id:
                synced_ok_for_test_user.add(conn.id)
            return _ok_result(conn.id)

        with patch(
            "src.services.integrations.nightscout.scheduler.sync_nightscout_for_connection",
            side_effect=fake_sync,
        ):
            # Should NOT raise.
            await run_nightscout_sync_all_users()

        assert synced_ok_for_test_user == {a_id, c_id}

    @pytest.mark.asyncio
    async def test_no_connections_for_test_user_means_no_call(self, scheduler_ctx):
        """Sanity: scheduler does not invoke sync for THIS test's user
        when that user has zero connections.

        We can't assert the global mock was never called -- the dev DB
        may have leftover rows from prior interrupted test runs and the
        scheduler scans all users. Scope the assertion to "no call
        referenced one of OUR connections" to stay isolation-clean.
        """
        _session, user_id = scheduler_ctx

        synced_for_test_user: list[uuid.UUID] = []

        async def fake_sync(_session, conn):
            if conn.user_id == user_id:
                synced_for_test_user.append(conn.id)
            return _ok_result(conn.id)

        with patch(
            "src.services.integrations.nightscout.scheduler.sync_nightscout_for_connection",
            side_effect=fake_sync,
        ):
            await run_nightscout_sync_all_users()

        assert synced_for_test_user == []
