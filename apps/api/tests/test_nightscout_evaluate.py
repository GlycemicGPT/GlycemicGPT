"""Story 43.7a -- tests for the evaluate endpoint + orchestrator.

Mocks the NightscoutClient at the class level so we exercise the real
orchestrator + the real router (cache, persistence, timeout handling)
without depending on a live Nightscout. The orchestrator's profile
parsing, uploader detection, and segment summarization are exercised
directly with Pydantic-validated fixtures so the unit + integration
slices both light up.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.main import app
from src.models.nightscout_connection import (
    NightscoutApiVersion,
    NightscoutAuthType,
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.models.user import User
from src.services.integrations.nightscout.connection_test import (
    ConnectionTestOutcome,
)
from src.services.integrations.nightscout.evaluate import (
    evaluate_nightscout_for_connection,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _unique_email(stem: str) -> str:
    return f"{stem}_{uuid.uuid4().hex[:10]}@example.com"


async def _register_and_login(client, email: str, password: str = "Test1234!"):
    from src.config import settings

    reg = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code in (200, 201), reg.text
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    cookie = resp.cookies.get(settings.jwt_cookie_name)
    assert cookie
    return {settings.jwt_cookie_name: cookie}


async def _cleanup(emails: list[str]) -> None:
    async with get_session_maker()() as db:
        result = await db.execute(User.__table__.select().where(User.email.in_(emails)))
        ids = [row.id for row in result.fetchall()]
        if ids:
            await db.execute(
                delete(NightscoutConnection).where(
                    NightscoutConnection.user_id.in_(ids)
                )
            )
            await db.execute(delete(User).where(User.id.in_(ids)))
            await db.commit()


@pytest_asyncio.fixture
async def http_client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


def _ok_outcome(server_version: str = "15.0.3") -> ConnectionTestOutcome:
    return ConnectionTestOutcome(
        ok=True,
        server_version=server_version,
        api_version_detected=NightscoutApiVersion.V1,
        auth_validated=True,
    )


def _fail_outcome(error: str = "auth rejected") -> ConnectionTestOutcome:
    return ConnectionTestOutcome(ok=False, error=error)


def _mk_client_mock(
    *,
    recent_entries: list[dict] | None = None,
    oldest_entries: list[dict] | None = None,
    treatments: list[dict] | None = None,
    devicestatus: list[dict] | None = None,
    profile: list[dict] | None = None,
    fetch_exception: Exception | None = None,
) -> MagicMock:
    """Build a mock standing in for an opened `NightscoutClient`.

    fetch_entries side-effects: the orchestrator calls it twice -- once
    with `since=` (recent) and once without (oldest sample). We discriminate
    by the kwarg presence to return the right list.
    """
    client_instance = AsyncMock()

    async def _fetch_entries(**kwargs):
        if fetch_exception is not None:
            raise fetch_exception
        if "since" in kwargs and kwargs["since"] is not None:
            return list(recent_entries or [])
        return list(oldest_entries or [])

    client_instance.fetch_entries = AsyncMock(side_effect=_fetch_entries)
    client_instance.fetch_treatments = AsyncMock(
        return_value=treatments or [],
        side_effect=fetch_exception,
    )
    client_instance.fetch_devicestatus = AsyncMock(
        return_value=devicestatus or [],
        side_effect=fetch_exception,
    )
    client_instance.fetch_profile = AsyncMock(
        return_value=profile or [],
        side_effect=fetch_exception,
    )
    if fetch_exception is None:
        # AsyncMock with both return_value AND side_effect ignores
        # return_value. Re-bind without side effect for the no-error
        # case.
        client_instance.fetch_treatments = AsyncMock(return_value=treatments or [])
        client_instance.fetch_devicestatus = AsyncMock(return_value=devicestatus or [])
        client_instance.fetch_profile = AsyncMock(return_value=profile or [])

    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=None)
    return client_instance


def _patch_test(outcome: ConnectionTestOutcome):
    return patch(
        "src.services.integrations.nightscout.evaluate.test_connection",
        new=AsyncMock(return_value=outcome),
    )


def _patch_client(client_mock: MagicMock):
    """Patch the NightscoutClient.create() factory."""
    return patch(
        "src.services.integrations.nightscout.evaluate.NightscoutClient.create",
        new=AsyncMock(return_value=client_mock),
    )


def _loop_profile(units: str = "mg/dl") -> dict:
    """A realistic Loop profile record (single store, single-band target)."""
    return {
        "_id": "abc123",
        "defaultProfile": "Default",
        "startDate": "2026-04-01T00:00:00.000Z",
        "units": units,
        "store": {
            "Default": {
                "dia": 5.0,
                "timezone": "America/Los_Angeles",
                "units": units,
                "carbratio": [{"time": "00:00", "value": 12.0}],
                "sens": [{"time": "00:00", "value": 50.0}],
                "basal": [{"time": "00:00", "value": 0.65}],
                "target_low": [{"time": "00:00", "value": 90.0}],
                "target_high": [{"time": "00:00", "value": 120.0}],
            },
        },
    }


def _aaps_treatment() -> dict:
    return {
        "eventType": "Bolus",
        "insulin": 2.5,
        "created_at": "2026-05-09T12:00:00.000Z",
        "enteredBy": "openaps://AndroidAPS",
    }


def _xdrip_entry(date_string: str = "2026-05-10T11:55:00.000Z") -> dict:
    return {
        "type": "sgv",
        "sgv": 120,
        "date": 1778155500000,
        "dateString": date_string,
        "device": "xDrip-Android",
        "enteredBy": "xdrip-android",
    }


# ---------------------------------------------------------------------------
# Unit: orchestrator (calls evaluate_nightscout_for_connection directly)
# ---------------------------------------------------------------------------


def _mk_conn(
    user_id: uuid.UUID | None = None,
    *,
    last_evaluated_at: datetime | None = None,
    detected_uploaders_json: dict | None = None,
) -> NightscoutConnection:
    """Construct a transient connection (not persisted) for unit tests.

    `user_id=None` -> generate a fresh UUID per call. (Default mutable
    `uuid.uuid4()` would freeze at import time, leaking the same id
    across tests; harmless today but a future test asserting on
    user_id would silently flake.)
    """
    return NightscoutConnection(
        id=uuid.uuid4(),
        user_id=user_id if user_id is not None else uuid.uuid4(),
        name="test",
        base_url="https://example.com",
        auth_type=NightscoutAuthType.SECRET,
        encrypted_credential=encrypt_credential("secret-12chars-min"),
        api_version=NightscoutApiVersion.V1,
        is_active=True,
        last_sync_status=NightscoutSyncStatus.NEVER,
        last_evaluated_at=last_evaluated_at,
        detected_uploaders_json=detected_uploaders_json,
    )


@pytest.mark.asyncio
async def test_orchestrator_happy_path_with_loop_profile():
    conn = _mk_conn()
    client_mock = _mk_client_mock(
        recent_entries=[_xdrip_entry() for _ in range(20)],
        oldest_entries=[_xdrip_entry("2024-08-12T00:00:00.000Z") for _ in range(100)],
        treatments=[_aaps_treatment() for _ in range(5)],
        devicestatus=[{"device": "loop://iPhone/Loop/3.4.5"}],
        profile=[_loop_profile()],
    )
    with _patch_test(_ok_outcome()), _patch_client(client_mock):
        report = await evaluate_nightscout_for_connection(conn)

    assert report.status_ok is True
    assert report.server_version == "15.0.3"
    assert report.recent_entry_count_7d == 20
    # entry_count_estimate is now an extrapolation from the recent-7d
    # rate * (now - earliest) span. With 20 entries/7d and earliest
    # set to 2024-08-12 (~600+ days back), the estimate is well into
    # the thousands -- always >= sample_size (100). The exact value
    # drifts with wall-clock so we assert the bound + magnitude
    # rather than an exact number.
    assert report.entry_count_estimate >= 100  # sample-size floor
    assert report.entry_count_estimate >= 1000  # extrapolated
    assert report.earliest_entry_at is not None
    assert report.has_treatments is True
    assert report.treatment_count_estimate == 5
    assert report.has_devicestatus is True
    # Loop in devicestatus + AAPS in treatments + xdrip+ in entries.
    assert "loop" in report.uploaders_detected
    assert "aaps" in report.uploaders_detected
    assert "xdrip+" in report.uploaders_detected
    # Loop wins the active_pump_loop tiebreak (first in _LOOP_UPLOADERS).
    assert report.active_pump_loop == "loop"
    assert report.has_profile is True
    assert report.profile_summary is not None
    assert report.profile_summary.dia_hours == 5.0
    assert report.profile_summary.target_low == 90
    assert report.profile_summary.target_high == 120
    assert report.profile_summary.units == "mg/dl"
    assert report.profile_summary.timezone == "America/Los_Angeles"
    assert report.profile_summary.carb_ratio_schedule is not None
    assert report.profile_summary.carb_ratio_schedule[0].value == 12.0


@pytest.mark.asyncio
async def test_orchestrator_status_ok_false_when_test_fails():
    conn = _mk_conn()
    with _patch_test(_fail_outcome("auth rejected")):
        report = await evaluate_nightscout_for_connection(conn)

    assert report.status_ok is False
    assert report.error == "auth rejected"
    assert report.recent_entry_count_7d == 0
    assert report.has_profile is False
    assert report.profile_summary is None


@pytest.mark.asyncio
async def test_orchestrator_handles_decrypt_failure_cleanly():
    """Real-world e2e found this: tampered encrypted_credential
    propagated ValueError -> 500 instead of a clean status_ok=False
    report. Production triggers: key rotation, DB corruption, manual
    DB edits.
    """
    conn = _mk_conn()
    # Replace the encrypted_credential with garbage so Fernet's
    # signature verification fails.
    conn.encrypted_credential = "gAAAAABxxxinvalidxxx"

    # No need to patch test_connection -- the orchestrator MUST
    # bail out before reaching it.
    report = await evaluate_nightscout_for_connection(conn)

    assert report.status_ok is False
    assert report.error is not None
    assert "decrypt" in report.error.lower()
    assert report.recent_entry_count_7d == 0
    assert report.has_profile is False


@pytest.mark.asyncio
async def test_orchestrator_no_profile_records():
    """Empty profile collection -> has_profile=False, no malformed flag."""
    conn = _mk_conn()
    client_mock = _mk_client_mock(profile=[])
    with _patch_test(_ok_outcome()), _patch_client(client_mock):
        report = await evaluate_nightscout_for_connection(conn)

    assert report.status_ok is True
    assert report.has_profile is False
    assert report.profile_summary is None


@pytest.mark.asyncio
async def test_orchestrator_profile_with_no_active_store():
    """Profile record exists but defaultProfile points nowhere."""
    conn = _mk_conn()
    bad = {
        "_id": "abc",
        "defaultProfile": "Missing",
        "startDate": "2026-04-01T00:00:00.000Z",
        "store": {"Default": {"dia": 5.0}},  # active points to "Missing", not in store
    }
    client_mock = _mk_client_mock(profile=[bad])
    with _patch_test(_ok_outcome()), _patch_client(client_mock):
        report = await evaluate_nightscout_for_connection(conn)

    assert report.has_profile is False
    assert report.profile_summary is None


@pytest.mark.asyncio
async def test_orchestrator_malformed_profile_flagged_per_ac11():
    """AC11: profile fetch returns garbage -> is_malformed=True, no crash."""
    conn = _mk_conn()
    # Pydantic NightscoutProfile.model_validate raises on this shape
    # (`store` should be a dict, not a string).
    garbage = {"_id": "x", "store": "not-a-dict"}
    client_mock = _mk_client_mock(profile=[garbage])
    with _patch_test(_ok_outcome()), _patch_client(client_mock):
        report = await evaluate_nightscout_for_connection(conn)

    assert report.has_profile is False
    assert report.profile_summary is not None
    assert report.profile_summary.is_malformed is True


@pytest.mark.asyncio
async def test_orchestrator_per_resource_failure_degrades_gracefully():
    """If treatments fetch raises, we still get a report from the rest.

    Also asserts the failed resource shows up on `partial_resources`
    so the wizard can surface "your token might be entries-only"
    (M5 from CR review).
    """
    conn = _mk_conn()

    # Build a client where treatments raises but everything else
    # works. Re-bind manually since _mk_client_mock applies one
    # exception across all four fetches.
    client_instance = AsyncMock()

    async def _fetch_entries(**kwargs):
        if "since" in kwargs and kwargs["since"] is not None:
            return [_xdrip_entry()]
        return [_xdrip_entry("2024-08-12T00:00:00.000Z")]

    client_instance.fetch_entries = AsyncMock(side_effect=_fetch_entries)
    client_instance.fetch_treatments = AsyncMock(
        side_effect=RuntimeError("treatments 500")
    )
    client_instance.fetch_devicestatus = AsyncMock(return_value=[])
    client_instance.fetch_profile = AsyncMock(return_value=[_loop_profile()])
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=None)

    with _patch_test(_ok_outcome()), _patch_client(client_instance):
        report = await evaluate_nightscout_for_connection(conn)

    assert report.status_ok is True
    assert report.has_treatments is False  # graceful degrade
    assert report.recent_entry_count_7d == 1
    assert report.has_profile is True
    # M5: failed resource surfaced so wizard can flag "scope-restricted token".
    assert "treatments" in report.partial_resources
    assert "recent_entries" not in report.partial_resources


def test_estimate_total_entries_extrapolates_from_recent_rate():
    """Direct test for the helper; CR M2 (entry_count_estimate must
    be a real estimate, not just sample size).
    """
    from src.services.integrations.nightscout.evaluate import (
        _estimate_total_entries,
    )

    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)

    # Steady CGM: 2016 entries in last 7 days (~288/day), earliest
    # 365 days back -> expect ~105K total.
    estimate = _estimate_total_entries(
        recent_count_7d=2016,
        earliest_at=now - timedelta(days=365),
        sample_size=1000,
        now=now,
    )
    # 2016/7 = 288/day * 365 = 105,120
    assert 100_000 <= estimate <= 110_000

    # No earliest_at -> fall back to sample size (no extrapolation
    # distance).
    assert (
        _estimate_total_entries(
            recent_count_7d=2016,
            earliest_at=None,
            sample_size=1000,
            now=now,
        )
        == 1000
    )

    # Zero recent activity -> use sample size (rate of 0 would
    # under-report what we actually saw).
    assert (
        _estimate_total_entries(
            recent_count_7d=0,
            earliest_at=now - timedelta(days=365),
            sample_size=500,
            now=now,
        )
        == 500
    )

    # Span < 7 days -> recent count IS effectively the total.
    estimate_short = _estimate_total_entries(
        recent_count_7d=144,
        earliest_at=now - timedelta(days=2),
        sample_size=144,
        now=now,
    )
    assert estimate_short == 144

    # Floor: extrapolation never reports fewer than the directly-
    # observed sample.
    estimate_floor = _estimate_total_entries(
        recent_count_7d=10,  # very sparse uploader
        earliest_at=now - timedelta(days=8),
        sample_size=2000,  # but we observed 2K in our oldest probe
        now=now,
    )
    assert estimate_floor >= 2000

    # Ceiling: degenerate inputs can't blow up the wizard prose.
    estimate_huge = _estimate_total_entries(
        recent_count_7d=10**9,  # absurd
        earliest_at=now - timedelta(days=10000),
        sample_size=1000,
        now=now,
    )
    assert estimate_huge <= 100_000_000


@pytest.mark.asyncio
async def test_orchestrator_target_low_high_preserve_mmol_precision():
    """M3: mmol/L profile values stay as floats (4.4 / 7.8), not rounded."""
    conn = _mk_conn()
    profile = _loop_profile(units="mmol")
    profile["store"]["Default"]["target_low"] = [{"time": "00:00", "value": 4.4}]
    profile["store"]["Default"]["target_high"] = [{"time": "00:00", "value": 7.8}]
    client_mock = _mk_client_mock(profile=[profile])
    with _patch_test(_ok_outcome()), _patch_client(client_mock):
        report = await evaluate_nightscout_for_connection(conn)

    assert report.profile_summary is not None
    # Float precision preserved -- not rounded to int 4 / 8.
    assert report.profile_summary.target_low == 4.4
    assert report.profile_summary.target_high == 7.8
    assert report.profile_summary.units == "mmol"


# ---------------------------------------------------------------------------
# Profile summary edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_summary_takes_min_max_for_segmented_target():
    """Time-varying target reports min(low) / max(high) across segments."""
    conn = _mk_conn()
    profile = _loop_profile()
    profile["store"]["Default"]["target_low"] = [
        {"time": "00:00", "value": 80.0},
        {"time": "08:00", "value": 90.0},
        {"time": "22:00", "value": 100.0},  # higher -- min is 80
    ]
    profile["store"]["Default"]["target_high"] = [
        {"time": "00:00", "value": 130.0},  # lower -- max is 150
        {"time": "08:00", "value": 150.0},
        {"time": "22:00", "value": 110.0},
    ]
    client_mock = _mk_client_mock(profile=[profile])
    with _patch_test(_ok_outcome()), _patch_client(client_mock):
        report = await evaluate_nightscout_for_connection(conn)

    assert report.profile_summary is not None
    assert report.profile_summary.target_low == 80
    assert report.profile_summary.target_high == 150
    # Schedules preserved as DTO list.
    assert len(report.profile_summary.target_low_schedule or []) == 3


# ---------------------------------------------------------------------------
# Endpoint: cache, persistence, RBAC
# ---------------------------------------------------------------------------


async def _create_conn(http_client, cookies, name: str = "Test NS") -> str:
    """Use the real POST endpoint to seed a connection (mocked test)."""
    with patch(
        "src.routers.nightscout.test_connection",
        new=AsyncMock(return_value=_ok_outcome()),
    ):
        resp = await http_client.post(
            "/api/integrations/nightscout",
            cookies=cookies,
            json={
                "name": name,
                "base_url": "https://example.com",
                "auth_type": "secret",
                "credential": "test-secret-12chars",
                "api_version": "v1",
            },
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["connection"]["id"]


@pytest.mark.asyncio
async def test_evaluate_endpoint_persists_report_and_timestamp(http_client):
    email = _unique_email("ns_eval_persist")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)

        client_mock = _mk_client_mock(
            recent_entries=[_xdrip_entry()],
            profile=[_loop_profile()],
        )
        with (
            _patch_test(_ok_outcome()),
            _patch_client(client_mock),
        ):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status_ok"] is True
        assert body["has_profile"] is True
        assert body["profile_summary"]["dia_hours"] == 5.0

        # Persistence: detected_uploaders_json + last_evaluated_at written.
        async with get_session_maker()() as db:
            result = await db.execute(
                NightscoutConnection.__table__.select().where(
                    NightscoutConnection.id == uuid.UUID(connection_id)
                )
            )
            row = result.fetchone()
            assert row.detected_uploaders_json is not None
            assert row.detected_uploaders_json["status_ok"] is True
            assert row.last_evaluated_at is not None
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_evaluate_endpoint_returns_cached_within_5_min(http_client):
    """AC9: second call within cache window does NOT re-evaluate."""
    email = _unique_email("ns_eval_cache")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)

        # First call: actual evaluate.
        client_mock = _mk_client_mock(
            recent_entries=[_xdrip_entry()],
            profile=[_loop_profile()],
        )
        test_mock = AsyncMock(return_value=_ok_outcome())
        with (
            patch(
                "src.services.integrations.nightscout.evaluate.test_connection",
                new=test_mock,
            ),
            _patch_client(client_mock),
        ):
            r1 = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        assert r1.status_code == 200
        assert test_mock.call_count == 1

        # Second call: should hit cache, NOT re-call test_connection.
        with (
            patch(
                "src.services.integrations.nightscout.evaluate.test_connection",
                new=test_mock,
            ),
            _patch_client(client_mock),
        ):
            r2 = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        assert r2.status_code == 200
        # Cache hit -> test_connection NOT called a second time.
        assert test_mock.call_count == 1
        # Same body shape
        assert r2.json()["server_version"] == r1.json()["server_version"]
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_evaluate_endpoint_rejects_cross_tenant_with_404(http_client):
    email_a = _unique_email("ns_eval_a")
    email_b = _unique_email("ns_eval_b")
    cookies_a = await _register_and_login(http_client, email_a)
    cookies_b = await _register_and_login(http_client, email_b)
    try:
        a_conn_id = await _create_conn(http_client, cookies_a, "A's conn")

        # B tries to evaluate A's connection -- 404 (not 403, no leak).
        with (
            _patch_test(_ok_outcome()),
            _patch_client(_mk_client_mock()),
        ):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{a_conn_id}/evaluate",
                cookies=cookies_b,
            )
        assert resp.status_code == 404
    finally:
        await _cleanup([email_a, email_b])


@pytest.mark.asyncio
async def test_evaluate_endpoint_404s_soft_deleted_connection(http_client):
    email = _unique_email("ns_eval_softdel")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)

        # Soft-delete the connection.
        del_resp = await http_client.delete(
            f"/api/integrations/nightscout/{connection_id}",
            cookies=cookies,
        )
        assert del_resp.status_code == 200

        with (
            _patch_test(_ok_outcome()),
            _patch_client(_mk_client_mock()),
        ):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        # require_active=True -> 404 even though row exists.
        assert resp.status_code == 404
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_evaluate_endpoint_unauthenticated_rejected(http_client):
    fake_id = uuid.uuid4()
    resp = await http_client.post(f"/api/integrations/nightscout/{fake_id}/evaluate")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_evaluate_endpoint_504_on_timeout(http_client):
    """Bound by _EVALUATE_TIMEOUT_SECONDS -- a slow upstream returns 504."""
    email = _unique_email("ns_eval_timeout")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)

        # Make evaluate hang past the wait_for window. We patch the
        # orchestrator to await a long sleep (much longer than the
        # router's _EVALUATE_TIMEOUT_SECONDS).
        async def _hang(*args, **kwargs):
            await asyncio.sleep(60)

        with (
            patch(
                "src.routers.nightscout.evaluate_nightscout_for_connection",
                new=_hang,
            ),
            patch("src.routers.nightscout._EVALUATE_TIMEOUT_SECONDS", 0.05),
        ):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        assert resp.status_code == 504
        assert "timeout" in resp.json()["detail"].lower()
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_evaluate_endpoint_does_not_cache_failures(http_client):
    """H2 from CR review: a failed evaluate (status_ok=False) MUST NOT
    cache for 5 min -- a user fixing a typo'd token must be able to
    immediately retry.
    """
    email = _unique_email("ns_eval_failcache")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)

        # First call: evaluate fails (auth rejected by the upstream).
        with _patch_test(_fail_outcome("auth rejected by upstream")):
            r1 = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        assert r1.status_code == 200
        assert r1.json()["status_ok"] is False

        # The failure should NOT have been written to the cache.
        async with get_session_maker()() as db:
            result = await db.execute(
                NightscoutConnection.__table__.select().where(
                    NightscoutConnection.id == uuid.UUID(connection_id)
                )
            )
            row = result.fetchone()
            assert row.detected_uploaders_json is None
            assert row.last_evaluated_at is None

        # Second call: user fixed the token -- should re-attempt
        # (NOT serve a cached failure).
        client_mock = _mk_client_mock(
            recent_entries=[_xdrip_entry()],
            profile=[_loop_profile()],
        )
        with _patch_test(_ok_outcome()), _patch_client(client_mock):
            r2 = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        assert r2.status_code == 200
        assert r2.json()["status_ok"] is True
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_evaluate_endpoint_404s_inactive_via_db_flag(http_client):
    """M6 from CR review: assert require_active=True is wired by setting
    is_active=False directly in DB (not via DELETE), so 404 can't be
    explained by 'row missing'.
    """
    email = _unique_email("ns_eval_inactivedb")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)

        # Directly flip is_active=False without touching the row count.
        async with get_session_maker()() as db:
            await db.execute(
                NightscoutConnection.__table__.update()
                .where(NightscoutConnection.id == uuid.UUID(connection_id))
                .values(is_active=False)
            )
            await db.commit()

        with _patch_test(_ok_outcome()), _patch_client(_mk_client_mock()):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        assert resp.status_code == 404

        # Sanity: the row IS still there.
        async with get_session_maker()() as db:
            result = await db.execute(
                NightscoutConnection.__table__.select().where(
                    NightscoutConnection.id == uuid.UUID(connection_id)
                )
            )
            assert result.fetchone() is not None
    finally:
        await _cleanup([email])


@pytest.mark.asyncio
async def test_evaluate_endpoint_cache_drift_falls_through_to_fresh(http_client):
    """If cached payload has stale schema, we re-evaluate cleanly."""
    email = _unique_email("ns_eval_drift")
    cookies = await _register_and_login(http_client, email)
    try:
        connection_id = await _create_conn(http_client, cookies)

        # Manually plant a cache payload with `status_ok: true` (so it
        # gets past the cache-only-on-success gate) but otherwise
        # malformed (so model_validate fails -> fall through to a
        # fresh evaluate).
        async with get_session_maker()() as db:
            await db.execute(
                NightscoutConnection.__table__.update()
                .where(NightscoutConnection.id == uuid.UUID(connection_id))
                .values(
                    detected_uploaders_json={
                        "status_ok": True,
                        "some_old_field": "drift",
                        # Missing required `evaluated_at` -- triggers
                        # ValidationError on model_validate.
                    },
                    last_evaluated_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
            await db.commit()

        client_mock = _mk_client_mock(
            recent_entries=[_xdrip_entry()],
            profile=[_loop_profile()],
        )
        with (
            _patch_test(_ok_outcome()),
            _patch_client(client_mock),
        ):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{connection_id}/evaluate",
                cookies=cookies,
            )
        assert resp.status_code == 200
        body = resp.json()
        # Fresh evaluate populated the report -- not the stale shape.
        assert body["status_ok"] is True
        assert "some_old_field" not in body
    finally:
        await _cleanup([email])
