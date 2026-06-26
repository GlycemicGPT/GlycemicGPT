"""Tests for the autonomous Connect sync orchestrator (state transitions).

The auth + client + storage layers have their own unit tests; here we drive
``sync_connect_for_user`` with those collaborators patched to exercise the
state-row updates: success, rotated-token persistence, auth-expiry -> disconnect,
and transient error -> error status.
"""

import uuid
from datetime import UTC, datetime

import pytest

from src.core.encryption import decrypt_credential, encrypt_credential
from src.core.units import GlucoseUnit
from src.models.medtronic_connect_state import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    MedtronicConnectState,
)
from src.services.integrations.medtronic import connect_sync as cs
from src.services.integrations.medtronic.connect_client import ConnectError
from src.services.integrations.medtronic.connect_sync import (
    ConnectSyncError,
    sync_connect_for_user,
)
from src.services.integrations.medtronic.storage import CareLinkStoreResult


def _state(**overrides) -> MedtronicConnectState:
    base = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "region": "US",
        "encrypted_username": encrypt_credential("user@example.com"),
        "encrypted_refresh_token": encrypt_credential("refresh-orig"),
        "role": "patient",
        "encrypted_patient_id": None,
        "enabled": True,
        "sync_interval_minutes": 30,
        "status": "pending",
        "readings_synced_total": 0,
    }
    base.update(overrides)
    return MedtronicConnectState(**base)


class _FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def patched(monkeypatch):
    """Patch the network/storage collaborators; capture what was used."""
    captured = {}

    class _FakeProvider:
        # Default provider: returns a token, never rotates. Tests that exercise
        # rotation / auth-expiry override ConnectTokenProvider themselves.
        def __init__(self, *, region, refresh_token, on_rotate=None):
            self._on_rotate = on_rotate

        async def __call__(self):
            return "access-token"

    monkeypatch.setattr(cs, "ConnectTokenProvider", _FakeProvider)

    class _FakeClient:
        def __init__(self, *, bearer_provider, **kwargs):
            captured["client_kwargs"] = {"bearer_provider": bearer_provider, **kwargs}
            self._bearer = bearer_provider

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get_recent_data(self):
            # The real client fetches the bearer here, which is what triggers
            # token rotation / auth-expiry in the provider.
            await self._bearer()
            return {"sgs": [{"sg": 120, "datetime": "2025-01-31T12:00:00-05:00"}]}

    monkeypatch.setattr(cs, "CareLinkConnectClient", _FakeClient)

    def _fake_map(recent, *, glucose_unit):
        captured["recent"] = recent
        captured["glucose_unit"] = glucose_unit
        return recent

    monkeypatch.setattr(cs, "map_recent_data", _fake_map)

    # resolve_glucose_unit hits the DB; the fake DB has no execute(). Patch it to
    # return a configurable unit (default mg/dL) and capture which user it asked
    # for, so we can assert the data owner's preference is threaded into the mapper.
    async def _fake_resolve(db, user_id):
        captured["resolve_user_id"] = user_id
        return captured.get("unit", GlucoseUnit.MGDL)

    monkeypatch.setattr(cs, "resolve_glucose_unit", _fake_resolve)

    async def _fake_store(db, user_id, records, *, now=None, commit=True):
        return CareLinkStoreResult(
            glucose_fetched=1, glucose_stored=1, events_fetched=0, events_stored=0
        )

    monkeypatch.setattr(cs, "store_carelink_records", _fake_store)
    return captured


async def test_success_updates_state(patched):
    state = _state()
    db = _FakeDB()
    now = datetime(2025, 2, 1, tzinfo=UTC)

    result = await sync_connect_for_user(db, state, now=now)

    assert result.glucose_stored == 1
    assert state.status == STATUS_CONNECTED
    assert state.last_sync_at == now
    assert state.last_attempt_at == now
    assert state.last_error is None
    assert state.readings_synced_total == 1
    # username + cloud host threaded into the client.
    assert patched["client_kwargs"]["username"] == "user@example.com"
    assert "clcloud.minimed.com" in patched["client_kwargs"]["base_url"]


async def test_data_owner_unit_preference_is_threaded_into_mapper(patched):
    # GLY-59: the orchestrator resolves the data owner's glucose-unit preference
    # and passes it to the mapper so the mmol/L follower-feed guard can fire.
    state = _state()
    db = _FakeDB()

    await sync_connect_for_user(db, state, now=datetime(2025, 2, 1, tzinfo=UTC))

    assert patched["resolve_user_id"] == state.user_id
    assert patched["glucose_unit"] == GlucoseUnit.MGDL


async def test_mmol_preference_is_threaded_into_mapper(patched):
    # When the owner prefers mmol/L, that unit reaches the mapper unchanged so the
    # fail-safe drop applies on this sync path.
    patched["unit"] = GlucoseUnit.MMOL
    state = _state()
    db = _FakeDB()

    await sync_connect_for_user(db, state, now=datetime(2025, 2, 1, tzinfo=UTC))

    assert patched["glucose_unit"] == GlucoseUnit.MMOL


async def test_rotated_refresh_token_is_persisted(patched, monkeypatch):
    # Force the token provider to "rotate" by invoking on_rotate immediately.
    class _RotatingProvider:
        def __init__(self, *, region, refresh_token, on_rotate=None):
            self._on_rotate = on_rotate

        async def __call__(self):
            if self._on_rotate:
                await self._on_rotate("refresh-rotated")
            return "access-token"

    monkeypatch.setattr(cs, "ConnectTokenProvider", _RotatingProvider)

    state = _state()
    db = _FakeDB()
    await sync_connect_for_user(db, state, now=datetime(2025, 2, 1, tzinfo=UTC))

    assert decrypt_credential(state.encrypted_refresh_token) == "refresh-rotated"


async def test_auth_expiry_marks_disconnected(patched, monkeypatch):
    class _DeadProvider:
        def __init__(self, **kwargs):
            pass

        async def __call__(self):
            raise cs.ConnectTokenError("Refresh token rejected; re-login required")

    monkeypatch.setattr(cs, "ConnectTokenProvider", _DeadProvider)

    state = _state()
    db = _FakeDB()
    with pytest.raises(ConnectSyncError, match="auth expired"):
        await sync_connect_for_user(db, state, now=datetime(2025, 2, 1, tzinfo=UTC))

    assert state.status == STATUS_DISCONNECTED
    assert "re-login" in state.last_error
    assert state.last_attempt_at is not None


async def test_undecryptable_credential_marks_disconnected(patched):
    # A row whose credentials can't be decrypted (key rotated out / corrupted)
    # must self-disconnect and commit, NOT escape as an unhandled exception --
    # otherwise the scheduler retries it every tick and floods logs/Sentry.
    state = _state(
        encrypted_refresh_token="not-a-valid-fernet-token",
        status="connected",
    )
    db = _FakeDB()

    with pytest.raises(ConnectSyncError, match="stored data invalid"):
        await sync_connect_for_user(db, state, now=datetime(2025, 2, 1, tzinfo=UTC))

    assert state.status == STATUS_DISCONNECTED
    assert "decrypt" in state.last_error.lower()
    # last_attempt_at stamped + row committed so the disconnect persists.
    assert state.last_attempt_at == datetime(2025, 2, 1, tzinfo=UTC)
    assert db.commits == 1


async def test_unknown_region_marks_disconnected(patched):
    # A corrupted/legacy region column is just as permanent as a bad credential:
    # it must self-disconnect rather than escape uncaught and flood every tick.
    state = _state(region="ZZ", status="connected")
    db = _FakeDB()

    with pytest.raises(ConnectSyncError, match="stored data invalid"):
        await sync_connect_for_user(db, state, now=datetime(2025, 2, 1, tzinfo=UTC))

    assert state.status == STATUS_DISCONNECTED
    assert "region" in state.last_error.lower()
    assert state.last_attempt_at == datetime(2025, 2, 1, tzinfo=UTC)
    assert db.commits == 1


async def test_transient_error_marks_error(patched, monkeypatch):
    class _FailingClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get_recent_data(self):
            raise ConnectError("CarePartner 503")

    monkeypatch.setattr(cs, "CareLinkConnectClient", _FailingClient)

    state = _state()
    db = _FakeDB()
    with pytest.raises(ConnectSyncError, match="sync failed"):
        await sync_connect_for_user(db, state, now=datetime(2025, 2, 1, tzinfo=UTC))

    assert state.status == STATUS_ERROR
    assert "503" in state.last_error
