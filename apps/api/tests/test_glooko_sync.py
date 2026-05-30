"""Tests for the Glooko sync orchestrator (state transitions + cursor handling).

The auth + client + mapper + storage layers have their own unit tests
(``test_glooko_client.py`` / ``test_glooko_mapper.py``); here we drive
``sync_glooko_for_user`` / ``import_glooko_history_for_user`` with those
collaborators patched to exercise the ``GlookoSyncState`` row updates: success +
per-stream cursor advance + CGM high-water mark, the first-sync recent-window
cursor, the decrypt-flood guard, auth-expiry -> disconnect, transient error ->
error, and the import path's "don't bump last_sync_at / don't touch the cursor"
contract. Hermetic: no DB, no network (mirrors ``test_connect_sync.py``).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.core.encryption import encrypt_credential
from src.models.glooko_sync_state import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    GlookoSyncState,
)
from src.services.integrations.glooko import sync as gs
from src.services.integrations.glooko.auth import GlookoSession
from src.services.integrations.glooko.client import CursorPage
from src.services.integrations.glooko.errors import (
    GlookoAuthError,
    GlookoNetworkError,
)
from src.services.integrations.glooko.storage import GlookoStoreResult
from src.services.integrations.glooko.sync import (
    GlookoSyncRunError,
    import_glooko_history_for_user,
    sync_glooko_for_user,
)

_NOW = datetime(2025, 2, 1, tzinfo=UTC)


def _state(**overrides) -> GlookoSyncState:
    base = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "region": "US",
        "encrypted_email": encrypt_credential("user@example.com"),
        "encrypted_password": encrypt_credential("hunter2"),
        "enabled": True,
        "sync_interval_minutes": 30,
        "status": "pending",
        "readings_synced_total": 0,
    }
    base.update(overrides)
    return GlookoSyncState(**base)


class _FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def patched(monkeypatch):
    """Patch login/client/storage; capture what the orchestrator passed them."""
    captured: dict = {"fetch_calls": [], "cgm_windows": []}

    async def _fake_login(email, password, region="US", **kwargs):
        captured["login"] = {"email": email, "password": password, "region": region}
        return GlookoSession(
            region=region,
            cookies={"_logbook-web_session": "cookie"},
            patient_slug="adjective-noun-1234",
            patient_oid="64233d92cd75e20c8d86edd4",
        )

    monkeypatch.setattr(gs, "glooko_login", _fake_login)

    class _FakeClient:
        def __init__(self, session, *, reauth=None, **kwargs):
            self.session = session

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def fetch_stream(
            self,
            stream,
            *,
            last_updated_at=None,
            last_guid=None,
            limit=None,
            max_pages=None,
        ):
            captured["fetch_calls"].append(
                {
                    "stream": stream,
                    "last_updated_at": last_updated_at,
                    "last_guid": last_guid,
                    "max_pages": max_pages,
                }
            )
            return CursorPage(
                stream=stream,
                records=[{"stream": stream}],
                last_updated_at=f"{stream}-next",
                last_guid=f"{stream}-guid",
                last_page=True,
                pages_fetched=1,
            )

        async def fetch_cgm_points(self, start_date, end_date):
            captured["cgm_windows"].append((start_date, end_date))
            return [{"y": 120, "timestamp": "2025-01-31T12:00:00Z"}]

    monkeypatch.setattr(gs, "GlookoClient", _FakeClient)

    def _fake_map(**kwargs):
        captured["map_kwargs"] = kwargs
        return object()  # storage is stubbed -> the mapped value is opaque here

    monkeypatch.setattr(gs, "map_glooko", _fake_map)

    async def _fake_store(db, user_id, records, *, now=None, commit=True):
        captured["store"] = {"commit": commit, "user_id": user_id}
        return GlookoStoreResult(
            glucose_fetched=2, glucose_stored=2, events_fetched=3, events_stored=3
        )

    monkeypatch.setattr(gs, "store_glooko_records", _fake_store)
    return captured


# --- incremental sync ------------------------------------------------------
async def test_success_updates_state_and_advances_cursor(patched):
    state = _state()
    db = _FakeDB()

    result = await sync_glooko_for_user(db, state, now=_NOW)

    assert result.glucose_stored == 2
    assert result.events_stored == 3
    assert state.status == STATUS_CONNECTED
    assert state.last_sync_at == _NOW
    assert state.last_attempt_at == _NOW
    assert state.last_error is None
    assert state.readings_synced_total == 2
    # Patient identifiers discovered at login are persisted.
    assert state.patient_slug == "adjective-noun-1234"
    assert state.patient_oid == "64233d92cd75e20c8d86edd4"
    # Per-stream cursor advanced for every synced pump stream.
    assert set(state.stream_cursors) == set(gs.SYNC_PUMP_STREAMS)
    assert state.stream_cursors["normal_boluses"] == {
        "last_updated_at": "normal_boluses-next",
        "last_guid": "normal_boluses-guid",
    }
    # CGM high-water mark moved to "now".
    assert state.last_cgm_window_end == _NOW
    # Credentials were decrypted and threaded into login.
    assert patched["login"]["email"] == "user@example.com"
    assert patched["login"]["password"] == "hunter2"
    # Records + state committed together (storage deferred to the final commit).
    assert patched["store"]["commit"] is False
    # Each stream's records must land in its OWN mapper kwarg (a swapped
    # basals/boluses wiring bug would otherwise slip past every other assert).
    map_kwargs = patched["map_kwargs"]
    assert map_kwargs["scheduled_basals"] == [{"stream": "scheduled_basals"}]
    assert map_kwargs["normal_boluses"] == [{"stream": "normal_boluses"}]
    assert map_kwargs["events"] == [{"stream": "events"}]
    assert map_kwargs["cgm_points"] == [{"y": 120, "timestamp": "2025-01-31T12:00:00Z"}]


async def test_first_sync_uses_recent_window_not_epoch(patched):
    # No stored cursor -> the first incremental tick must start from a recent
    # point, NOT the epoch (that full backfill is the explicit import's job).
    state = _state(stream_cursors=None, last_cgm_window_end=None)
    db = _FakeDB()

    await sync_glooko_for_user(db, state, now=_NOW)

    expected = gs._iso_z(_NOW - timedelta(days=gs._INITIAL_PUMP_LOOKBACK_DAYS))
    for call in patched["fetch_calls"]:
        assert call["last_updated_at"] == expected
        assert call["last_guid"] == "00000000-0000-0000-0000-000000000000"


async def test_resume_uses_stored_cursor(patched):
    stored = {
        "scheduled_basals": {
            "last_updated_at": "2025-01-30T00:00:00Z",
            "last_guid": "g1",
        },
        "normal_boluses": {
            "last_updated_at": "2025-01-29T00:00:00Z",
            "last_guid": "g2",
        },
        "events": {"last_updated_at": "2025-01-28T00:00:00Z", "last_guid": "g3"},
    }
    state = _state(stream_cursors=stored)
    db = _FakeDB()

    await sync_glooko_for_user(db, state, now=_NOW)

    by_stream = {c["stream"]: c for c in patched["fetch_calls"]}
    assert by_stream["normal_boluses"]["last_updated_at"] == "2025-01-29T00:00:00Z"
    assert by_stream["normal_boluses"]["last_guid"] == "g2"


async def test_cgm_window_resumes_with_overlap(patched):
    prior_end = datetime(2025, 1, 31, 12, 0, tzinfo=UTC)
    state = _state(last_cgm_window_end=prior_end)
    db = _FakeDB()

    await sync_glooko_for_user(db, state, now=_NOW)

    start, end = patched["cgm_windows"][0]
    assert start == gs._iso_z(prior_end - timedelta(minutes=gs._CGM_OVERLAP_MINUTES))
    assert end == gs._iso_z(_NOW)


async def test_undecryptable_credential_marks_disconnected():
    # A row whose credentials can't be decrypted (key rotated out / corrupted)
    # must self-disconnect and commit, NOT escape uncaught -- otherwise the
    # scheduler retries it every tick and floods logs/Sentry.
    state = _state(encrypted_password="not-a-valid-fernet-token", status="connected")
    db = _FakeDB()

    with pytest.raises(GlookoSyncRunError, match="stored data invalid"):
        await sync_glooko_for_user(db, state, now=_NOW)

    assert state.status == STATUS_DISCONNECTED
    assert state.last_attempt_at == _NOW
    assert db.commits == 1


async def test_unknown_region_marks_disconnected():
    state = _state(region="ZZ", status="connected")
    db = _FakeDB()

    with pytest.raises(GlookoSyncRunError, match="stored data invalid"):
        await sync_glooko_for_user(db, state, now=_NOW)

    assert state.status == STATUS_DISCONNECTED
    assert "region" in state.last_error.lower()
    assert db.commits == 1


async def test_auth_error_marks_disconnected(patched, monkeypatch):
    async def _bad_login(*a, **k):
        raise GlookoAuthError("Glooko login rejected -- check email/password")

    monkeypatch.setattr(gs, "glooko_login", _bad_login)

    state = _state(status="connected")
    db = _FakeDB()
    with pytest.raises(GlookoSyncRunError, match="auth failed"):
        await sync_glooko_for_user(db, state, now=_NOW)

    assert state.status == STATUS_DISCONNECTED
    assert state.last_attempt_at == _NOW


async def test_transient_network_error_marks_error(patched, monkeypatch):
    async def _flaky_login(*a, **k):
        raise GlookoNetworkError("Glooko session check server error (503)")

    monkeypatch.setattr(gs, "glooko_login", _flaky_login)

    state = _state(status="connected")
    db = _FakeDB()
    with pytest.raises(GlookoSyncRunError, match="transient"):
        await sync_glooko_for_user(db, state, now=_NOW)

    # ERROR (not disconnected) -> the scheduler retries next interval.
    assert state.status == STATUS_ERROR
    assert "503" in state.last_error


async def test_midstream_failure_does_not_persist_cursor(patched, monkeypatch):
    # A stream failing PART-WAY through the fetch loop must leave the prior
    # connected state's cursor/CGM high-water mark untouched (we never commit a
    # half-advanced cursor) and flip the row to error -- not silently advance.
    prior_cursors = {
        "scheduled_basals": {
            "last_updated_at": "2025-01-30T00:00:00Z",
            "last_guid": "g1",
        }
    }
    prior_cgm_end = datetime(2025, 1, 31, tzinfo=UTC)
    state = _state(
        status="connected",
        stream_cursors=prior_cursors,
        last_cgm_window_end=prior_cgm_end,
    )

    # The `patched` fixture stubbed login/map/store; override just the client so
    # stream 1 succeeds and stream 2 raises mid-loop.
    class _PartialClient:
        def __init__(self, session, *, reauth=None, **kwargs):
            self._calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def fetch_stream(self, stream, **kwargs):
            self._calls += 1
            if self._calls >= 2:  # succeed on stream 1, blow up on stream 2
                raise GlookoNetworkError("Glooko GET transient failure: 503")
            return CursorPage(
                stream=stream,
                records=[],
                last_updated_at="advanced",
                last_guid="advanced-guid",
                last_page=True,
                pages_fetched=1,
            )

        async def fetch_cgm_points(self, *a):
            return []

    monkeypatch.setattr(gs, "GlookoClient", _PartialClient)

    db = _FakeDB()
    with pytest.raises(GlookoSyncRunError, match="transient"):
        await sync_glooko_for_user(db, state, now=_NOW)

    assert state.status == STATUS_ERROR
    # Untouched: the half-advanced cursor and CGM mark were never committed.
    assert state.stream_cursors == prior_cursors
    assert state.last_cgm_window_end == prior_cgm_end
    assert state.last_sync_at is None


async def test_lock_released_after_sync(patched):
    state = _state()
    db = _FakeDB()
    await sync_glooko_for_user(db, state, now=_NOW)
    # The in-flight lock is dropped once no one is waiting (the dict tracks
    # "currently syncing", not every user ever seen).
    assert state.user_id not in gs._in_flight_locks


# --- one-time historical import --------------------------------------------
async def test_import_does_not_bump_sync_or_cursor(patched):
    state = _state(status="error", last_error="stale", stream_cursors={"events": {}})
    db = _FakeDB()

    result = await import_glooko_history_for_user(db, state, now=_NOW)

    assert result.glucose_stored == 2
    # Import proves creds work -> connected + cleared error...
    assert state.status == STATUS_CONNECTED
    assert state.last_error is None
    assert state.readings_synced_total == 2
    # ...but it backfills the past: it must NOT advance the live-sync state.
    assert state.last_sync_at is None
    assert state.last_attempt_at is None
    assert state.stream_cursors == {"events": {}}
    assert state.last_cgm_window_end is None


async def test_import_paginates_from_epoch(patched):
    # The import must walk full history -> it passes NO cursor (client defaults
    # to the epoch + zero-UUID sentinel), unlike the incremental recent-window.
    state = _state()
    db = _FakeDB()

    await import_glooko_history_for_user(db, state, now=_NOW)

    pump_calls = [
        c for c in patched["fetch_calls"] if c["stream"] in gs.SYNC_PUMP_STREAMS
    ]
    assert pump_calls  # all three streams fetched
    for call in pump_calls:
        assert call["last_updated_at"] is None
        assert call["last_guid"] is None
        assert call["max_pages"] == gs._IMPORT_MAX_PAGES
    # CGM backfill walks multiple windows that together span the configured
    # lookback: newest window ends at "now", oldest reaches back _IMPORT_CGM_DAYS.
    windows = patched["cgm_windows"]
    assert len(windows) > 1
    assert windows[0][1] == gs._iso_z(_NOW)
    assert windows[-1][0] == gs._iso_z(_NOW - timedelta(days=gs._IMPORT_CGM_DAYS))


# --- availability probe (read-only) ----------------------------------------
async def test_probe_availability_is_read_only_and_lightweight(patched):
    # A `connected` row with prior freshness; the probe must leave EVERY field
    # untouched (the persist_status=False contract) -- it takes no db and must
    # not mutate the row object either.
    state = _state(
        status=STATUS_CONNECTED,
        last_sync_at=_NOW,
        last_attempt_at=_NOW,
        last_error="stale error",
        readings_synced_total=42,
        stream_cursors={"normal_boluses": {"last_updated_at": "x", "last_guid": "y"}},
        last_cgm_window_end=_NOW,
    )
    snapshot = {
        "status": state.status,
        "last_sync_at": state.last_sync_at,
        "last_attempt_at": state.last_attempt_at,
        "last_error": state.last_error,
        "readings_synced_total": state.readings_synced_total,
        "stream_cursors": dict(state.stream_cursors),
        "last_cgm_window_end": state.last_cgm_window_end,
    }

    result = await gs.probe_glooko_availability(state, now=_NOW)

    # Nothing on the row changed.
    assert state.status == snapshot["status"]
    assert state.last_sync_at == snapshot["last_sync_at"]
    assert state.last_attempt_at == snapshot["last_attempt_at"]
    assert state.last_error == snapshot["last_error"]
    assert state.readings_synced_total == snapshot["readings_synced_total"]
    assert state.stream_cursors == snapshot["stream_cursors"]
    assert state.last_cgm_window_end == snapshot["last_cgm_window_end"]

    # The mapped fixture CGM point surfaces as available.
    assert isinstance(result, gs.GlookoAvailability)
    assert result.cgm_available is True
    # Lightweight: a SINGLE recent window (one graph request), not the import walk.
    assert len(patched["cgm_windows"]) == 1
    assert patched["cgm_windows"][0] == (
        gs._iso_z(_NOW - timedelta(days=gs._AVAILABILITY_LOOKBACK_DAYS)),
        gs._iso_z(_NOW),
    )
