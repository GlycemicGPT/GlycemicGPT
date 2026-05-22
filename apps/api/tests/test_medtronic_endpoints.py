"""Tests for the Medtronic CareLink manual-import endpoints (feature B).

Stateless endpoints: the request carries the captured auth_tmp_token; the
backend builds a cookie-less client and never stores the token. We patch the
client builder + the sync orchestrator so these stay pure unit/HTTP tests.
"""

import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.core.medtronic_regions import resolve_region_base_url
from src.main import app
from src.services.integrations.medtronic.client import (
    CareLinkAuthError,
    CareLinkAvailability,
    CareLinkError,
    CareLinkReportTimeoutError,
)
from src.services.integrations.medtronic.sync import CareLinkSyncResult

AVAIL_PATH = "/api/integrations/medtronic/availability"
IMPORT_PATH = "/api/integrations/medtronic/import"

# The captured token rides in a header (never the body) so it can't land in a
# body-validation 422 echo or request-body logging.
_HDR = {"X-CareLink-Token": "tok-abc"}

_AVAIL = CareLinkAvailability(
    start=datetime(2012, 1, 1, tzinfo=UTC), end=datetime(2025, 1, 31, tzinfo=UTC)
)


def unique_email(prefix: str = "medtronic") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _login(client: AsyncClient) -> dict:
    email = unique_email()
    pw = "SecurePass123"
    await client.post("/api/auth/register", json={"email": email, "password": pw})
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    return {settings.jwt_cookie_name: r.cookies.get(settings.jwt_cookie_name)}


class _FakeClient:
    """Stand-in for CareLinkClient with canned async methods."""

    def __init__(self, *, availability=None, raise_exc=None):
        self._avail = availability
        self._raise = raise_exc

    async def get_patient_id(self):
        if self._raise:
            raise self._raise
        return "patient-123"

    async def get_availability(self):
        if self._raise:
            raise self._raise
        return self._avail

    async def aclose(self):
        return None


def _import_body(**over) -> dict:
    body = {
        "region": "US",
        "start_date": "2025-01-15",
        "end_date": "2025-01-20",
        "tz": "America/New_York",
    }
    body.update(over)
    return body


def _result() -> CareLinkSyncResult:
    return CareLinkSyncResult(
        patient_id="patient-123",
        start_date=date(2025, 1, 15),
        end_date=date(2025, 1, 20),
        glucose_fetched=500,
        glucose_stored=480,
        events_fetched=120,
        events_stored=110,
    )


# --- unit: region resolver -------------------------------------------------


def test_resolve_region_base_url():
    assert resolve_region_base_url("us") == "https://carelink.minimed.com"
    assert resolve_region_base_url("EU") == "https://carelink.minimed.eu"
    with pytest.raises(ValueError, match="Unsupported"):
        resolve_region_base_url("ZZ")


# --- availability ----------------------------------------------------------


async def test_availability_requires_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(AVAIL_PATH, json={"region": "US"}, headers=_HDR)
    assert resp.status_code == 401


@patch("src.routers.integrations._build_carelink_client")
async def test_availability_success(mock_build):
    mock_build.return_value = _FakeClient(availability=_AVAIL)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            AVAIL_PATH, json={"region": "US"}, headers=_HDR, cookies=cookies
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["start"].startswith("2012-01-01")
    assert data["end"].startswith("2025-01-31")


@patch("src.routers.integrations._build_carelink_client")
async def test_availability_expired_token_401(mock_build):
    mock_build.return_value = _FakeClient(raise_exc=CareLinkAuthError("401"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            AVAIL_PATH, json={"region": "US"}, headers=_HDR, cookies=cookies
        )
    assert resp.status_code == 401, resp.text


@patch("src.routers.integrations._build_carelink_client")
async def test_availability_service_error_503(mock_build):
    mock_build.return_value = _FakeClient(raise_exc=CareLinkError("boom"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            AVAIL_PATH, json={"region": "US"}, headers=_HDR, cookies=cookies
        )
    assert resp.status_code == 503, resp.text


async def test_availability_bad_region_422():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            AVAIL_PATH, json={"region": "ZZ"}, headers=_HDR, cookies=cookies
        )
    assert resp.status_code == 422, resp.text


# --- import ----------------------------------------------------------------


@patch("src.routers.integrations.sync_carelink_for_user", new_callable=AsyncMock)
@patch("src.routers.integrations._build_carelink_client")
async def test_import_success(mock_build, mock_sync):
    mock_build.return_value = _FakeClient()
    mock_sync.return_value = _result()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            IMPORT_PATH, json=_import_body(), headers=_HDR, cookies=cookies
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["glucose_stored"] == 480
    assert data["events_stored"] == 110
    # tz string reached the orchestrator as a ZoneInfo
    assert mock_sync.await_args.kwargs["tz"].key == "America/New_York"


@pytest.mark.parametrize(
    "start,end",
    [
        ("2025-01-20", "2025-01-15"),  # end before start
        ("2025-01-01", "2099-01-01"),  # future
        ("2025-01-01", "2025-03-01"),  # span > 31-day cap
    ],
)
async def test_import_rejects_bad_range_422(start, end):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            IMPORT_PATH,
            json=_import_body(start_date=start, end_date=end),
            headers=_HDR,
            cookies=cookies,
        )
    assert resp.status_code == 422, resp.text


async def test_import_bad_region_422():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            IMPORT_PATH, json=_import_body(region="ZZ"), headers=_HDR, cookies=cookies
        )
    assert resp.status_code == 422, resp.text


async def test_import_invalid_tz_422():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            IMPORT_PATH,
            json=_import_body(tz="Not/AZone"),
            headers=_HDR,
            cookies=cookies,
        )
    assert resp.status_code == 422, resp.text


@patch("src.routers.integrations.sync_carelink_for_user", new_callable=AsyncMock)
@patch("src.routers.integrations._build_carelink_client")
async def test_import_expired_token_401(mock_build, mock_sync):
    mock_build.return_value = _FakeClient()
    mock_sync.side_effect = CareLinkAuthError("401")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            IMPORT_PATH, json=_import_body(), headers=_HDR, cookies=cookies
        )
    assert resp.status_code == 401, resp.text


@patch("src.routers.integrations.sync_carelink_for_user", new_callable=AsyncMock)
@patch("src.routers.integrations._build_carelink_client")
async def test_import_timeout_504(mock_build, mock_sync):
    mock_build.return_value = _FakeClient()
    mock_sync.side_effect = CareLinkReportTimeoutError("slow")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            IMPORT_PATH, json=_import_body(), headers=_HDR, cookies=cookies
        )
    assert resp.status_code == 504, resp.text


async def test_token_not_leaked_in_validation_error():
    """A body-validation 422 (e.g. bad date range) must NOT echo the captured
    token. The token rides in the X-CareLink-Token header, never the body, so a
    body-validation error can't include it."""
    secret = "SUPERSECRETtok_abc_should_never_appear"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookies = await _login(client)
        resp = await client.post(
            IMPORT_PATH,
            json=_import_body(start_date="2025-01-01", end_date="2099-01-01"),
            headers={"X-CareLink-Token": secret},
            cookies=cookies,
        )
    assert resp.status_code == 422, resp.text
    assert secret not in resp.text
