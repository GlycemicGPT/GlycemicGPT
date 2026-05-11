"""Tests for the per-connection Nightscout sync service.

Mocks the NightscoutClient at the class level so we exercise the real
translator + DB write paths but don't depend on a running Nightscout
instance. Live end-to-end coverage lives in `test_nightscout_translator.py`
gated by the NIGHTSCOUT_TEST_URL / NIGHTSCOUT_TEST_SECRET env vars.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.models.glucose import GlucoseReading
from src.models.nightscout_connection import (
    NightscoutAuthType,
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.models.user import User
from src.services.integrations.nightscout.errors import (
    NightscoutAuthError,
    NightscoutNetworkError,
    NightscoutRateLimitError,
)
from src.services.integrations.nightscout.sync import (
    _resolve_since,
    sync_nightscout_for_connection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sync_ctx() -> AsyncGenerator[tuple[AsyncSession, NightscoutConnection], None]:
    """Provide a session + a fresh user + connection.

    Mirrors the pattern in test_nightscout_translator.py -- own
    session_maker so cross-loop teardown doesn't crash.
    """
    session_maker = get_session_maker()
    session = session_maker()
    email = f"sync_{uuid.uuid4().hex[:10]}@example.com"
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()
    user_id = user.id

    conn = NightscoutConnection(
        user_id=user_id,
        name="test-sync",
        base_url="https://example.com",
        auth_type=NightscoutAuthType.SECRET,
        encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
        initial_sync_window_days=7,
    )
    session.add(conn)
    await session.flush()
    await session.commit()

    try:
        yield session, conn
    finally:
        try:
            await session.rollback()
            await session.execute(
                delete(GlucoseReading).where(GlucoseReading.user_id == user_id)
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


def _mk_client_mock(
    *,
    entries: list[dict] | None = None,
    treatments: list[dict] | None = None,
    devicestatus: list[dict] | None = None,
    profile: list[dict] | None = None,
    fetch_exception: Exception | None = None,
) -> MagicMock:
    """Build a mock standing in for an opened `NightscoutClient`.

    Exposes the four `fetch_*` coroutines plus `__aenter__`/`__aexit__`
    so the `async with await NightscoutClient.create(...)` in sync.py
    works against the mock.
    """
    client_instance = AsyncMock()
    if fetch_exception is not None:
        client_instance.fetch_entries = AsyncMock(side_effect=fetch_exception)
        client_instance.fetch_treatments = AsyncMock(side_effect=fetch_exception)
        client_instance.fetch_devicestatus = AsyncMock(side_effect=fetch_exception)
        client_instance.fetch_profile = AsyncMock(side_effect=fetch_exception)
    else:
        client_instance.fetch_entries = AsyncMock(return_value=entries or [])
        client_instance.fetch_treatments = AsyncMock(return_value=treatments or [])
        client_instance.fetch_devicestatus = AsyncMock(return_value=devicestatus or [])
        client_instance.fetch_profile = AsyncMock(return_value=profile or [])

    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=None)
    return client_instance


# ---------------------------------------------------------------------------
# _resolve_since: cursor logic
# ---------------------------------------------------------------------------


class TestResolveSince:
    def test_first_sync_uses_initial_window(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        since = _resolve_since(None, 7, now)
        assert since == now - timedelta(days=7)

    def test_subsequent_sync_uses_last_synced_at(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        last = datetime(2026, 5, 10, 11, 0, tzinfo=UTC)
        assert _resolve_since(last, 7, now) == last

    def test_zero_window_means_unbounded_for_uncapped_call(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        assert _resolve_since(None, 0, now) is None

    def test_zero_window_with_cap_uses_cap(self):
        """devicestatus path: 0 means 'all available' but cap_days bounds it."""
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        since = _resolve_since(None, 0, now, cap_days=30)
        assert since == now - timedelta(days=30)

    def test_window_larger_than_cap_clamps_to_cap(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        since = _resolve_since(None, 90, now, cap_days=30)
        assert since == now - timedelta(days=30)


# ---------------------------------------------------------------------------
# sync_nightscout_for_connection: outcome paths
# ---------------------------------------------------------------------------


class TestSyncOutcome:
    @pytest.mark.asyncio
    async def test_successful_sync_advances_cursor(self, sync_ctx):
        session, conn = sync_ctx

        client_mock = _mk_client_mock(
            entries=[
                {
                    "_id": "fixture-entry-1",
                    "type": "sgv",
                    "sgv": 120,
                    "dateString": "2026-05-10T12:00:00.000Z",
                    "device": "xdrip",
                }
            ],
        )
        before = datetime.now(UTC)
        with patch(
            "src.services.integrations.nightscout.sync.NightscoutClient.create",
            new=AsyncMock(return_value=client_mock),
        ):
            result = await sync_nightscout_for_connection(session, conn)
        after = datetime.now(UTC)

        assert result.status == NightscoutSyncStatus.OK
        assert result.entries_inserted == 1
        # Cursor advanced
        assert conn.last_synced_at is not None
        assert before <= conn.last_synced_at <= after
        # Status persisted
        assert conn.last_sync_status == NightscoutSyncStatus.OK
        assert conn.last_sync_error is None

    @pytest.mark.asyncio
    async def test_auth_error_maps_to_auth_failed_and_keeps_cursor(self, sync_ctx):
        """Cursor MUST NOT advance on failure."""
        session, conn = sync_ctx
        original_cursor = conn.last_synced_at  # None on first run

        client_mock = _mk_client_mock(
            fetch_exception=NightscoutAuthError("401 unauthorized", status_code=401),
        )
        with patch(
            "src.services.integrations.nightscout.sync.NightscoutClient.create",
            new=AsyncMock(return_value=client_mock),
        ):
            result = await sync_nightscout_for_connection(session, conn)

        assert result.status == NightscoutSyncStatus.AUTH_FAILED
        assert result.error == "401 unauthorized"
        assert conn.last_synced_at is original_cursor  # unchanged
        assert conn.last_sync_status == NightscoutSyncStatus.AUTH_FAILED
        assert conn.last_sync_error == "401 unauthorized"

    @pytest.mark.asyncio
    async def test_rate_limit_maps_to_rate_limited(self, sync_ctx):
        session, conn = sync_ctx
        client_mock = _mk_client_mock(
            fetch_exception=NightscoutRateLimitError("429 too many requests")
        )
        with patch(
            "src.services.integrations.nightscout.sync.NightscoutClient.create",
            new=AsyncMock(return_value=client_mock),
        ):
            result = await sync_nightscout_for_connection(session, conn)
        assert result.status == NightscoutSyncStatus.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_network_error_maps_to_network(self, sync_ctx):
        session, conn = sync_ctx
        client_mock = _mk_client_mock(
            fetch_exception=NightscoutNetworkError("connection reset")
        )
        with patch(
            "src.services.integrations.nightscout.sync.NightscoutClient.create",
            new=AsyncMock(return_value=client_mock),
        ):
            result = await sync_nightscout_for_connection(session, conn)
        assert result.status == NightscoutSyncStatus.NETWORK

    @pytest.mark.asyncio
    async def test_idempotent_resync(self, sync_ctx):
        """Running the same sync twice -- second call inserts nothing."""
        session, conn = sync_ctx

        # Fixed data; same payload both calls.
        entries = [
            {
                "_id": f"idem-entry-{i}",
                "type": "sgv",
                "sgv": 110 + i,
                "dateString": f"2026-05-10T12:0{i}:00.000Z",
                "device": "xdrip",
            }
            for i in range(3)
        ]
        client_mock = _mk_client_mock(entries=entries)

        with patch(
            "src.services.integrations.nightscout.sync.NightscoutClient.create",
            new=AsyncMock(return_value=client_mock),
        ):
            first = await sync_nightscout_for_connection(session, conn)
            second = await sync_nightscout_for_connection(session, conn)

        assert first.entries_inserted == 3
        assert second.entries_inserted == 0
        # Both passes still landed on OK (i.e., dedupe is a skip, not an error).
        assert first.status == NightscoutSyncStatus.OK
        assert second.status == NightscoutSyncStatus.OK

        rows = (
            (
                await session.execute(
                    select(GlucoseReading).where(GlucoseReading.user_id == conn.user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 3
