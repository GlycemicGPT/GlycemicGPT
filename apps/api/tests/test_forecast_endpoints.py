"""Endpoint-level tests for the forecast read/write endpoints
(Story 43.12 PR 3).

Service-layer unit tests live in `test_forecast_reader.py`. This file
covers the HTTP boundary: auth gating, response shape per scenario,
cross-tenant safety, and the picker write path's validation.

Tests use the standard `register_and_login` pattern (cookie auth via
the `/api/auth/login` route) consistent with `test_aggregate_stats.py`
and `test_emergency_contacts.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.encryption import encrypt_credential
from src.database import get_db, get_session_maker
from src.main import app
from src.models.forecast_settings import ForecastSettings
from src.models.forecast_snapshot import ForecastSnapshot
from src.models.nightscout_connection import (
    NightscoutAuthType,
    NightscoutConnection,
)
from src.schemas.forecast import ForecastSourcePreference


def _unique_email() -> str:
    return f"forecast_ep_{uuid.uuid4().hex[:10]}@example.com"


async def register_and_login(client: AsyncClient) -> tuple[str, str]:
    """Register a fresh test user and return `(session_cookie, user_id)`."""
    email = _unique_email()
    password = "SecurePass123"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    cookie = login.cookies.get(settings.jwt_cookie_name)
    assert cookie is not None
    me = await client.get("/api/auth/me", cookies={settings.jwt_cookie_name: cookie})
    assert me.status_code == 200
    return cookie, me.json()["id"]


async def _seed_snapshot(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    source_engine: str,
    issued_minutes_ago: int,
) -> NightscoutConnection:
    """Insert one forecast snapshot for the user. Creates a connection
    on first call if needed."""
    uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    # Reuse connection if one exists for the user; otherwise create.
    from sqlalchemy import select

    existing = await db.execute(
        select(NightscoutConnection).where(NightscoutConnection.user_id == uid)
    )
    conn = existing.scalar_one_or_none()
    if conn is None:
        conn = NightscoutConnection(
            user_id=uid,
            name="test-forecast-ep",
            base_url="https://example.com",
            auth_type=NightscoutAuthType.SECRET,
            encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
            initial_sync_window_days=7,
        )
        db.add(conn)
        await db.flush()

    issued = datetime.now(UTC) - timedelta(minutes=issued_minutes_ago)
    snap = ForecastSnapshot(
        user_id=uid,
        nightscout_connection_id=conn.id,
        source_engine=source_engine,
        source_uploader=source_engine,
        issued_at=issued,
        start_at=issued,
        step_minutes=5,
        horizon_minutes=30,
        curves_mgdl_json={"main": [120, 122, 125, 128, 130, 131]},
        default_curve_name="main",
        dedupe_key=f"test-{uuid.uuid4().hex}",
    )
    db.add(snap)
    await db.commit()
    return conn


@pytest.fixture(autouse=True)
async def _truncate_forecasts():
    """Forecast snapshots use a globally-unique
    `(source_engine, dedupe_key)`. Truncate between tests so cross-
    test ns_id collisions can't drop our seeds via ON CONFLICT
    DO NOTHING."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            await session.execute(
                text("TRUNCATE forecast_evaluations, forecast_snapshots CASCADE")
            )
            await session.commit()
        except RuntimeError:
            pass
    yield


@pytest.fixture(autouse=True)
async def _cleanup_forecast_settings():
    """`forecast_settings` is one-to-one with users. The user
    fixture cascade-deletes via FK, but this is a belt-and-braces
    sweep so a partially-failed test can't leak rows that confuse
    a subsequent test on the same user."""
    yield
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            await session.execute(delete(ForecastSettings))
            await session.commit()
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# GET /api/integrations/forecast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_get_returns_401():
    """Authentication is required."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/integrations/forecast")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_no_integration_returns_clean_empty_shape():
    """A user with no NS-imported forecasts gets auto preference,
    empty sources, and a null forecast -- the picker UI hides itself
    cleanly in that state. Reason: `no_sources` so frontend can
    render "Connect Nightscout to see forecasts" copy."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, _user_id = await register_and_login(client)
        resp = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_preference"] == "auto"
    assert data["effective_source"] is None
    assert data["available_sources"] == []
    assert data["forecast"] is None
    assert data["forecast_unavailable_reason"] == "no_sources"


@pytest.mark.asyncio
async def test_get_no_integration_does_not_persist_settings_row():
    """REST GET must not write. A first-time-reader doesn't get a
    `forecast_settings` row INSERTed -- the synthesized default flows
    through the response without DB side effects. Persisted only on
    first PUT."""
    from sqlalchemy import func, select

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, _ = await register_and_login(client)
        # Two GETs in a row -- no rows should appear.
        await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )
        await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )

    session_maker = get_session_maker()
    async with session_maker() as session:
        count = await session.scalar(select(func.count(ForecastSettings.id)))
    assert count == 0, (
        "GET must not INSERT a forecast_settings row -- this is a"
        " side-effect-free read; persistence happens on PUT."
    )


@pytest.mark.asyncio
async def test_get_auto_single_source_resolves_and_returns_forecast():
    """Single-source `auto`: picker resolves to that engine and the
    forecast payload comes through end-to-end."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, user_id = await register_and_login(client)
        async for db in get_db():
            await _seed_snapshot(
                db,
                user_id,
                source_engine="loop",
                issued_minutes_ago=5,
            )
            break

        resp = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_preference"] == "auto"
    assert data["effective_source"] == "loop"
    assert data["available_sources"] == ["loop"]
    assert data["forecast"] is not None
    assert data["forecast"]["source_engine"] == "loop"
    assert data["forecast"]["default_curve_name"] == "main"
    assert data["forecast"]["curves_mgdl"]["main"] == [120, 122, 125, 128, 130, 131]
    # Happy path -> reason omitted (null).
    assert data["forecast_unavailable_reason"] is None


@pytest.mark.asyncio
async def test_get_auto_multi_source_returns_null_effective():
    """Multiple sources under `auto` -> no silent guess. The picker
    UI surfaces but no forecast renders until the user picks."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, user_id = await register_and_login(client)
        async for db in get_db():
            await _seed_snapshot(
                db, user_id, source_engine="loop", issued_minutes_ago=5
            )
            await _seed_snapshot(
                db, user_id, source_engine="aaps", issued_minutes_ago=5
            )
            break

        resp = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )
    data = resp.json()
    assert data["effective_source"] is None
    assert data["available_sources"] == ["aaps", "loop"]  # sorted
    assert data["forecast"] is None
    assert data["forecast_unavailable_reason"] == "needs_pick"


@pytest.mark.asyncio
async def test_get_specific_source_picks_only_that_engine():
    """User picked loop but aaps is also publishing -> resolves to
    loop and only loop's forecast comes through."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, user_id = await register_and_login(client)
        async for db in get_db():
            await _seed_snapshot(
                db, user_id, source_engine="loop", issued_minutes_ago=5
            )
            await _seed_snapshot(
                db, user_id, source_engine="aaps", issued_minutes_ago=5
            )
            break

        # Set preference to loop
        put = await client.put(
            "/api/integrations/forecast/source",
            json={"source": "loop"},
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert put.status_code == 200

        resp = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )
    data = resp.json()
    assert data["source_preference"] == "loop"
    assert data["effective_source"] == "loop"
    assert data["forecast"]["source_engine"] == "loop"
    assert data["forecast_unavailable_reason"] is None


@pytest.mark.asyncio
async def test_get_specific_source_went_silent_returns_null_no_fallback():
    """User picked aaps but aaps stopped publishing -- only loop is
    online. No fallback: `effective_source=None`. Honest "your AAPS
    stopped publishing" UX rather than a silent substitution to loop."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, user_id = await register_and_login(client)
        async for db in get_db():
            await _seed_snapshot(
                db, user_id, source_engine="loop", issued_minutes_ago=5
            )
            break

        await client.put(
            "/api/integrations/forecast/source",
            json={"source": "aaps"},
            cookies={settings.jwt_cookie_name: cookie},
        )

        resp = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )
    data = resp.json()
    assert data["source_preference"] == "aaps"
    assert data["effective_source"] is None
    assert data["forecast"] is None
    assert data["forecast_unavailable_reason"] == "source_silent"
    # But the dropdown still surfaces loop as available, so the user
    # can switch.
    assert data["available_sources"] == ["loop"]


@pytest.mark.asyncio
async def test_get_none_preference_suppresses_forecast():
    """`none` opts out entirely -- forecast and effective_source both
    null even when sources are publishing."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, user_id = await register_and_login(client)
        async for db in get_db():
            await _seed_snapshot(
                db, user_id, source_engine="loop", issued_minutes_ago=5
            )
            break

        await client.put(
            "/api/integrations/forecast/source",
            json={"source": "none"},
            cookies={settings.jwt_cookie_name: cookie},
        )

        resp = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )
    data = resp.json()
    assert data["source_preference"] == "none"
    assert data["effective_source"] is None
    assert data["forecast"] is None
    assert data["forecast_unavailable_reason"] == "opted_out"
    # available_sources still populated so the UI knows the data
    # exists even when the user opted out.
    assert data["available_sources"] == ["loop"]


@pytest.mark.asyncio
async def test_get_stale_forecast_suppresses_payload_only():
    """A forecast older than the 30-min freshness threshold is
    suppressed from the `forecast` field, but the engine still
    appears in `available_sources` (24h window) and is the effective
    source. Mirrors PR 6's "stale loop status hidden but COB
    preserved" pattern."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, user_id = await register_and_login(client)
        async for db in get_db():
            # 1h old -- past 30-min freshness, within 24h availability.
            await _seed_snapshot(
                db, user_id, source_engine="loop", issued_minutes_ago=60
            )
            break

        resp = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie},
        )
    data = resp.json()
    assert data["effective_source"] == "loop"
    assert data["available_sources"] == ["loop"]
    assert data["forecast"] is None  # too stale to draw the dotted line
    assert data["forecast_unavailable_reason"] == "stale"


# ---------------------------------------------------------------------------
# PUT /api/integrations/forecast/source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_put_returns_401():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.put(
            "/api/integrations/forecast/source", json={"source": "loop"}
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_put_invalid_source_returns_422():
    """Pydantic Literal rejects unknown values before the DB ever
    sees them. Catches frontend bugs at the API boundary."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, _ = await register_and_login(client)
        resp = await client.put(
            "/api/integrations/forecast/source",
            json={"source": "FUTURE_ENGINE"},
            cookies={settings.jwt_cookie_name: cookie},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_each_allowed_value_persists():
    """Every allowed enum value round-trips through PUT then GET.

    Sources `allowed` from the canonical `ForecastSourcePreference`
    Literal so a future schema extension automatically gains test
    coverage. A hardcoded list would silently miss new values.
    """
    allowed = list(get_args(ForecastSourcePreference))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, _ = await register_and_login(client)
        for value in allowed:
            put = await client.put(
                "/api/integrations/forecast/source",
                json={"source": value},
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert put.status_code == 200, f"PUT failed for {value!r}: {put.text}"
            assert put.json() == {"source_preference": value}

            get = await client.get(
                "/api/integrations/forecast",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert get.json()["source_preference"] == value


@pytest.mark.asyncio
async def test_put_extra_fields_rejected():
    """`extra='forbid'` on the body schema rejects sneaky extras."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie, _ = await register_and_login(client)
        resp = await client.put(
            "/api/integrations/forecast/source",
            json={"source": "loop", "rogue_field": "x"},
            cookies={settings.jwt_cookie_name: cookie},
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_isolates_per_user():
    """User A's forecast preference and snapshots don't leak into
    user B's response."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie_a, user_a_id = await register_and_login(client)
        cookie_b, user_b_id = await register_and_login(client)
        async for db in get_db():
            await _seed_snapshot(
                db, user_a_id, source_engine="loop", issued_minutes_ago=5
            )
            await _seed_snapshot(
                db, user_b_id, source_engine="aaps", issued_minutes_ago=5
            )
            break
        # A picks loop; B picks none.
        await client.put(
            "/api/integrations/forecast/source",
            json={"source": "loop"},
            cookies={settings.jwt_cookie_name: cookie_a},
        )
        await client.put(
            "/api/integrations/forecast/source",
            json={"source": "none"},
            cookies={settings.jwt_cookie_name: cookie_b},
        )

        resp_a = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie_a},
        )
        resp_b = await client.get(
            "/api/integrations/forecast",
            cookies={settings.jwt_cookie_name: cookie_b},
        )

    data_a = resp_a.json()
    data_b = resp_b.json()
    assert data_a["source_preference"] == "loop"
    assert data_a["effective_source"] == "loop"
    assert data_a["available_sources"] == ["loop"]
    assert data_b["source_preference"] == "none"
    assert data_b["effective_source"] is None
    assert data_b["available_sources"] == ["aaps"]
