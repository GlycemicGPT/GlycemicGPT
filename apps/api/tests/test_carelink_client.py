"""Tests for the CareLink HTTP client data methods (mocked, no network)."""

import json
from datetime import date, datetime

import httpx
import pytest

from src.services.integrations.medtronic.client import (
    US_BASE_URL,
    CareLinkAuthError,
    CareLinkClient,
    CareLinkReportTimeoutError,
)


async def _bearer() -> str:
    return "test-bearer-123"


def _make_client(handler, **kwargs) -> CareLinkClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return CareLinkClient(
        bearer_provider=_bearer,
        client=http,
        poll_interval_seconds=0,  # don't actually sleep in tests
        **kwargs,
    )


async def test_get_availability_parses_range():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/patient/reports/snapshotTimelinesRange"
        assert request.headers["authorization"] == "Bearer test-bearer-123"
        return httpx.Response(
            200,
            json={
                "start": "2012-01-01T00:02:34.000Z",
                "end": "2025-01-31T15:05:47.000Z",
            },
        )

    async with _make_client(handler) as client:
        avail = await client.get_availability()
    assert avail.start == datetime.fromisoformat("2012-01-01T00:02:34+00:00")
    assert avail.end == datetime.fromisoformat("2025-01-31T15:05:47+00:00")


async def test_get_patient_id_tolerant_field():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/patient/users/me"
        return httpx.Response(200, json={"patientId": "50497203", "firstName": "X"})

    async with _make_client(handler) as client:
        assert await client.get_patient_id() == "50497203"


async def test_export_csv_full_job_flow():
    """generateReport -> reportStatus (pending then ready) -> reportCsv."""
    captured = {}
    status_calls = {"n": 0}
    csv_payload = "Index,Date,Time\n0,2025/01/31,12:00:00\n"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/patient/reports/generateReport":
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"uuid": "abc-123"})
        if path == "/patient/reports/reportStatus":
            assert request.url.params["uuid"] == "abc-123"
            status_calls["n"] += 1
            # pending on the first poll, ready on the second
            ready = status_calls["n"] >= 2
            return httpx.Response(
                200, json={"status": "COMPLETE" if ready else "GENERATING"}
            )
        if path == "/patient/reports/reportCsv":
            assert request.url.params["uuid"] == "abc-123"
            return httpx.Response(200, text=csv_payload)
        return httpx.Response(404)

    async with _make_client(handler) as client:
        csv_text = await client.export_csv(
            patient_id="50497203",
            start_date=date(2025, 1, 18),
            end_date=date(2025, 1, 31),
        )

    assert csv_text == csv_payload
    assert status_calls["n"] == 2  # polled until ready
    # generateReport body mirrors the observed shape
    body = captured["body"]
    assert body["patientId"] == "50497203"
    assert body["reportFileFormat"] == "CSV"
    assert body["aggregatedCsvEnabled"] is True
    assert body["startDate"] == "2025-01-18"
    assert body["endDate"] == "2025-01-31"
    assert body["reportShowLogbook"] is False


async def test_export_csv_times_out_if_never_ready():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/patient/reports/generateReport":
            return httpx.Response(200, json={"uuid": "abc-123"})
        if request.url.path == "/patient/reports/reportStatus":
            return httpx.Response(200, json={"status": "GENERATING"})
        return httpx.Response(404)

    async with _make_client(handler, poll_max_attempts=3) as client:
        with pytest.raises(CareLinkReportTimeoutError):
            await client.export_csv(
                patient_id="1", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)
            )


async def test_auth_error_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    async with _make_client(handler) as client:
        with pytest.raises(CareLinkAuthError):
            await client.get_availability()


async def test_status_204_is_treated_ready():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/patient/reports/generateReport":
            return httpx.Response(200, json={"reportUuid": "u9"})  # alt uuid field
        if request.url.path == "/patient/reports/reportStatus":
            return httpx.Response(204)
        if request.url.path == "/patient/reports/reportCsv":
            return httpx.Response(200, text="Index,Date,Time\n")
        return httpx.Response(404)

    async with _make_client(handler) as client:
        out = await client.export_csv(
            patient_id="1", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)
        )
    assert out.startswith("Index,")


def test_default_base_url_is_us():
    assert US_BASE_URL == "https://carelink.minimed.com"
