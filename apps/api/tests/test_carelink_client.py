"""Tests for the CareLink HTTP client data methods (mocked, no network)."""

import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from src.services.integrations.medtronic.client import (
    US_BASE_URL,
    CareLinkAuthError,
    CareLinkClient,
    CareLinkError,
    CareLinkReportTimeoutError,
    CareLinkTransportError,
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


async def test_get_patient_id_eu_accountid_fallback():
    """EU/OUS /users/me has no patientId; the id lives in accountId (role
    PATIENT_OUS). _first must resolve accountId -- not the unrelated 'id' -- as
    the generateReport patientId (#811)."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/patient/users/me"
        return httpx.Response(
            200,
            json={"id": "auth0|abc", "accountId": "52266805", "role": "PATIENT_OUS"},
        )

    async with _make_client(handler) as client:
        assert await client.get_patient_id() == "52266805"


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
    # clientTime must be seconds-precision: the EU host 400s ("Malformed JSON in
    # request body") on a fractional-second clientTime (#811).
    assert "." not in body["clientTime"]
    # No PeriodB comparison window: the EU CSV-export endpoint rejects it with
    # 400 {"field":"startDatePeriodB","message":"not.required"} (#811).
    assert "startDatePeriodB" not in body
    assert "endDatePeriodB" not in body


def test_generate_report_body_omits_period_b():
    """The body must not carry the ``*PeriodB`` comparison window: the EU
    CSV-export endpoint rejects it with ``message: not.required`` (#811). It was
    added from a PDF-comparison-report capture that doesn't apply to CSV export."""
    body = CareLinkClient._build_generate_report_body(
        patient_id="1", start_date=date(2025, 3, 1), end_date=date(2025, 3, 1)
    )
    assert body["startDate"] == "2025-03-01"
    assert body["endDate"] == "2025-03-01"
    assert "startDatePeriodB" not in body
    assert "endDatePeriodB" not in body


def test_generate_report_body_client_time_drops_microseconds():
    """clientTime is serialized at seconds precision, preserving the local
    offset. The EU report host 400s on fractional seconds (#811); the working
    browser request sends ``...:ss+02:00`` with no microseconds."""
    local = timezone(timedelta(hours=2))
    client_time = datetime(2025, 3, 1, 8, 12, 54, 21383, tzinfo=local)
    body = CareLinkClient._build_generate_report_body(
        patient_id="1",
        start_date=date(2025, 3, 1),
        end_date=date(2025, 3, 1),
        client_time=client_time,
    )
    assert body["clientTime"] == "2025-03-01T08:12:54+02:00"


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


async def test_403_surfaces_response_body_snippet():
    """A 403 (authenticated but forbidden, e.g. generateReport refusing an
    action/format on a live session) raises CareLinkAuthError carrying the
    upstream body, so the reason is visible and a forbidden-action 403 can be
    told apart from an expired-token 401 (#811)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "operation not permitted"})

    async with _make_client(handler) as client:
        with pytest.raises(CareLinkAuthError) as exc_info:
            await client.get_patient_id()
    msg = str(exc_info.value)
    assert "403" in msg
    assert "operation not permitted" in msg


async def test_transport_error_is_typed():
    """A true transport failure (DNS/TLS/connection) is wrapped as
    CareLinkTransportError -- the subtype the router maps to 'Unable to reach
    CareLink'. Assert the exact type so a revert to the base CareLinkError (which
    would silently fall through to the 'unexpected response' branch) is caught."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with _make_client(handler) as client:
        with pytest.raises(CareLinkTransportError) as exc_info:
            await client.get_availability()
    assert exc_info.type is CareLinkTransportError


async def test_malformed_compressed_body_is_handled_not_500():
    """A reachable host returning an undecodable body (bad Content-Encoding) is
    always wrapped as a CareLinkError, never an unhandled exception/500. Depending
    on the exact bytes the decode fails either during the response read (-> the
    CareLinkTransportError subclass) or at JSON parse (-> the base CareLinkError);
    both subclass CareLinkError and both map to a 503 at the router, so assert the
    superclass rather than a brittle byte-dependent subtype."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            content=b"\x1f\x8b\x08\x00not-valid-gzip",
        )

    async with _make_client(handler) as client:
        with pytest.raises(CareLinkError):
            await client.get_patient_id()


async def test_reachable_4xx_is_base_error_not_transport():
    """A reachable host returning a non-auth 4xx raises the BASE CareLinkError
    (router -> 'unexpected response'), NOT the transport subtype -- pinning the
    other direction of the split so neither branch can absorb the other."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    async with _make_client(handler) as client:
        with pytest.raises(CareLinkError) as exc_info:
            await client.get_patient_id()
    assert exc_info.type is CareLinkError


async def test_4xx_error_surfaces_response_body_snippet():
    """A reachable 4xx must carry the upstream body in the error message so the
    actual rejection reason (e.g. which generateReport field CareLink rejected)
    reaches the router WARNING log instead of being hidden behind a bare status.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"message": "Validation failed", "field": "clientTime"}
        )

    async with _make_client(handler) as client:
        with pytest.raises(CareLinkError) as exc_info:
            await client.get_patient_id()
    msg = str(exc_info.value)
    assert "400" in msg
    assert "clientTime" in msg


async def test_4xx_error_body_snippet_is_truncated():
    """An oversized error body is length-capped so the surfaced message and log
    line stay bounded."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="x" * 5000)

    async with _make_client(handler) as client:
        with pytest.raises(CareLinkError) as exc_info:
            await client.get_patient_id()
    assert "[truncated]" in str(exc_info.value)


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


async def test_rejects_untrusted_base_url():
    with pytest.raises(ValueError, match="untrusted host"):
        CareLinkClient(bearer_provider=_bearer, base_url="https://evil.example.com")


async def test_eu_host_is_allowed():
    # Should not raise (regional EU host under minimed.eu).
    c = CareLinkClient(bearer_provider=_bearer, base_url="https://carelink.minimed.eu")
    await c.aclose()


async def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(
            200, json={"start": "2012-01-01T00:00:00Z", "end": "2025-01-31T00:00:00Z"}
        )

    async with _make_client(handler) as client:
        avail = await client.get_availability()
    assert calls["n"] == 2  # retried once after the 429
    assert avail.end.year == 2025


async def test_export_rejects_csv_without_index_header():
    """A too-early/partial reportCsv (no 'Index,' header) must not be accepted
    as a successful (but empty) import."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/patient/reports/generateReport":
            return httpx.Response(200, json={"uuid": "u1"})
        if request.url.path == "/patient/reports/reportStatus":
            return httpx.Response(200, json={"status": "COMPLETE"})
        if request.url.path == "/patient/reports/reportCsv":
            return httpx.Response(200, text="<html>not ready</html>")
        return httpx.Response(404)

    async with _make_client(handler) as client:
        with pytest.raises(CareLinkError, match="Index"):
            await client.export_csv(
                patient_id="1", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)
            )
