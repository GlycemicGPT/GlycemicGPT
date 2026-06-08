"""CareLink Personal HTTP client -- data methods (clean-room).

Built from our own observation of the CareLink Personal web API. Covers the
read/download surface this feature needs:

- ``get_patient_id()``  -> GET /patient/users/me
- ``get_availability()`` -> GET /patient/reports/snapshotTimelinesRange
- ``export_csv(...)``    -> the async CSV-export job:
      POST /patient/reports/generateReport  (returns a job uuid)
   -> GET  /patient/reports/reportStatus?uuid=...  (poll until ready)
   -> GET  /patient/reports/reportCsv?uuid=...      (download the CSV text)

**Auth is injected** as an async ``bearer_provider`` callable, so these data
methods are independent of (and testable without) the session-capture flow,
which is the genuinely uncertain part of this integration. The provider
returns a valid bearer for each call; refreshing it is the provider's job.

Confirmed against a live US account: the auth model, the availability shape
``{"start", "end"}``, the generateReport request body, and the
generateReport->reportStatus->reportCsv sequence. NOT yet confirmed live (so
parsed tolerantly here, to be pinned during the integration spike): the exact
field names in the /users/me and generateReport *responses* and the
reportStatus *response* body. These are marked inline.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import httpx

#: Max retries on HTTP 429 (rate limit) before giving up.
_MAX_RETRIES_429 = 3

#: Reject an absurdly large report rather than parsing it into memory. A real
#: 31-day CGM-dense CSV is well under 1 MB; this is a generous safety net.
_MAX_CSV_BYTES = 25 * 1024 * 1024

#: US CareLink host (confirmed). EU uses a different regional host; pass
#: base_url explicitly for it rather than guessing here.
US_BASE_URL = "https://carelink.minimed.com"

#: Allowed base-url host suffixes. base_url is otherwise injectable, so without
#: this an attacker-influenced region/url could make the client POST the
#: bearer to an arbitrary host (SSRF / credential exfiltration). Medtronic
#: CareLink hosts live under minimed.com (US) / minimed.eu (EU regional).
_ALLOWED_HOST_SUFFIXES = ("minimed.com", "minimed.eu")

BearerProvider = Callable[[], Awaitable[str]]

# reportStatus "ready" signals. We observed the generateReport ->
# reportStatus -> reportCsv sequence but not the status response body, so we
# accept a tolerant set of completion markers; to be confirmed live.
_READY_TOKENS = {
    "COMPLETE",
    "COMPLETED",
    "READY",
    "DONE",
    "SUCCESS",
    "SUCCEEDED",
    "FINISHED",
}


class CareLinkError(Exception):
    """Base error for CareLink client calls."""


class CareLinkAuthError(CareLinkError):
    """401/403 from CareLink -- the session/bearer is invalid or expired."""


class CareLinkReportTimeoutError(CareLinkError):
    """The CSV-export job did not become ready within the poll budget."""


@dataclass
class CareLinkAvailability:
    """Date range of pump data available in the user's CareLink cloud."""

    start: datetime
    end: datetime


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _first(d: dict, *keys: str) -> object | None:
    """First present, truthy value among ``keys`` (tolerant response parsing)."""
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None


class CareLinkClient:
    def __init__(
        self,
        *,
        bearer_provider: BearerProvider,
        base_url: str = US_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 2.0,
        poll_max_attempts: int = 30,
    ) -> None:
        host = (urlparse(base_url).hostname or "").lower()
        if not any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES):
            raise ValueError(
                f"Refusing CareLink base_url with untrusted host {host!r}; "
                f"allowed: {_ALLOWED_HOST_SUFFIXES}"
            )
        self._bearer_provider = bearer_provider
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval_seconds
        self._poll_max_attempts = poll_max_attempts
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=min(5.0, timeout_seconds),
                read=timeout_seconds,
                write=min(5.0, timeout_seconds),
                pool=min(2.0, timeout_seconds),
            )
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> CareLinkClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def _headers(self) -> dict[str, str]:
        bearer = await self._bearer_provider()
        return {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json, text/plain, */*",
        }

    def _check(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise CareLinkAuthError(
                f"CareLink auth failed ({resp.status_code}); session invalid/expired"
            )
        if resp.status_code >= 400:
            raise CareLinkError(
                f"CareLink request to {resp.request.url.path} failed: "
                f"{resp.status_code}"
            )

    async def _request(
        self, method: str, path: str, *, json: dict | None = None, **kwargs: object
    ) -> httpx.Response:
        """Issue a request with retry on 429 (backoff, honoring Retry-After)
        and a single retry on 5xx. 401/403 and other 4xx are not retried."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES_429 + 1):
            try:
                resp = await self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=await self._headers(),
                    json=json,
                    **kwargs,
                )
            except httpx.HTTPError as e:
                raise CareLinkError(
                    f"CareLink network error on {method} {path}: {e}"
                ) from e

            if resp.status_code == 429 and attempt < _MAX_RETRIES_429:
                await asyncio.sleep(self._retry_after_seconds(resp, attempt))
                continue
            if 500 <= resp.status_code < 600 and attempt == 0:
                await asyncio.sleep(0.5 + random.random() * 0.5)
                last_exc = CareLinkError(
                    f"CareLink {resp.status_code} on {method} {path}"
                )
                continue
            self._check(resp)
            return resp
        # Exhausted retries on a retryable status.
        raise last_exc or CareLinkError(f"CareLink request to {path} kept failing")

    def _retry_after_seconds(self, resp: httpx.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header and header.isdigit():
            return min(float(header), 30.0)
        return min(self._poll_interval * (2**attempt), 30.0) + random.random()

    async def _get(self, path: str, **kwargs: object) -> httpx.Response:
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, *, json: dict) -> httpx.Response:
        return await self._request("POST", path, json=json)

    async def get_patient_id(self) -> str:
        """Fetch the patient/account id required by generateReport."""
        data = self._json(await self._get("/patient/users/me"))
        # Response field name unconfirmed live -- accept the likely candidates.
        pid = _first(data, "patientId", "accountId", "loginId", "id")
        if pid is None:
            raise CareLinkError("Could not find patient id in /patient/users/me")
        return str(pid)

    async def get_availability(self) -> CareLinkAvailability:
        """Date range of data available in the CareLink cloud."""
        data = self._json(await self._get("/patient/reports/snapshotTimelinesRange"))
        start, end = data.get("start"), data.get("end")
        if not start or not end:
            raise CareLinkError("snapshotTimelinesRange missing start/end")
        try:
            return CareLinkAvailability(start=_parse_iso(start), end=_parse_iso(end))
        except (ValueError, TypeError) as e:
            raise CareLinkError(
                f"Could not parse snapshotTimelinesRange dates ({start!r}, {end!r})"
            ) from e

    async def export_csv(
        self,
        *,
        patient_id: str,
        start_date: date,
        end_date: date,
        client_time: datetime | None = None,
    ) -> str:
        """Run the CSV-export job for [start_date, end_date] and return the CSV.

        ``client_time`` should be the user's *local* time (CareLink may use it
        to resolve the start/end dates to instants; sending UTC could shift the
        range by a day at the edges). Defaults to now() in UTC.

        Raises CareLinkReportTimeoutError if the job doesn't finish in the poll
        budget, CareLinkAuthError on 401/403, CareLinkError otherwise.
        """
        body = self._build_generate_report_body(
            patient_id, start_date, end_date, client_time
        )
        gen = self._json(await self._post("/patient/reports/generateReport", json=body))
        uuid = _first(gen, "uuid", "reportUuid", "id")
        if uuid is None:
            raise CareLinkError("generateReport did not return a report uuid")
        uuid = str(uuid)

        for _ in range(self._poll_max_attempts):
            status_resp = await self._get(
                "/patient/reports/reportStatus", params={"uuid": uuid}
            )
            if self._is_report_ready(status_resp):
                break
            await asyncio.sleep(self._poll_interval)
        else:
            raise CareLinkReportTimeoutError(
                f"CSV export job {uuid} not ready after {self._poll_max_attempts} polls"
            )

        csv_resp = await self._get(
            "/patient/reports/reportCsv",
            params={"uuid": uuid, "dMInFileName": "false"},
        )
        if len(csv_resp.content) > _MAX_CSV_BYTES:
            raise CareLinkError(
                f"CareLink reportCsv for job {uuid} is too large "
                f"({len(csv_resp.content)} bytes > {_MAX_CSV_BYTES} cap)"
            )
        text = csv_resp.text
        # Validate it actually looks like a CareLink export. Because the
        # reportStatus "ready" shape is unconfirmed, a too-early/partial fetch
        # would otherwise parse to zero rows and silently under-import.
        # Accept both comma and semicolon (EU-locale) delimited exports -- the
        # parser handles either; this guard must not reject a valid one.
        if "Index," not in text and "Index;" not in text:
            raise CareLinkError(
                f"CareLink reportCsv for job {uuid} did not return a CSV "
                "with an 'Index' header (job may not have been ready)"
            )
        return text

    @staticmethod
    def _build_generate_report_body(
        patient_id: str,
        start_date: date,
        end_date: date,
        client_time: datetime | None = None,
    ) -> dict:
        """Mirror the observed generateReport body: CSV only, all PDF report
        sections off, aggregated CSV enabled."""
        return {
            "clientTime": (client_time or datetime.now(UTC)).isoformat(),
            "dailyDetailReportDays": [],
            "patientId": patient_id,
            "reportFileFormat": "CSV",
            "aggregatedCsvEnabled": True,
            "reportShowAdherence": False,
            "reportShowAssessmentAndProgress": False,
            "reportShowBolusWizardFoodBolus": False,
            "reportShowDashBoard": False,
            "reportShowDataTable": False,
            "reportShowDeviceSettings": False,
            "reportShowEpisodeSummary": False,
            "reportShowLogbook": False,
            "reportShowOverview": False,
            "reportShowWeeklyReview": False,
            "reportShowSettingsHistory": False,
            "reportShowInsulinAssessment": False,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
        }

    @staticmethod
    def _is_report_ready(resp: httpx.Response) -> bool:
        """Tolerant readiness check (exact reportStatus body unconfirmed live).

        Treats as ready: an explicit ``status``/``state`` token in the ready
        set, a truthy ``ready``/``completed``/``done`` flag, or an empty 204.
        """
        if resp.status_code == 204:
            return True
        try:
            data = resp.json()
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        for key in ("status", "state", "reportStatus"):
            token = data.get(key)
            if isinstance(token, str) and token.strip().upper() in _READY_TOKENS:
                return True
        return any(bool(data.get(k)) for k in ("ready", "completed", "done"))

    @staticmethod
    def _json(resp: httpx.Response) -> dict:
        try:
            data = resp.json()
        except ValueError as e:
            raise CareLinkError(
                f"CareLink returned non-JSON on {resp.request.url.path}"
            ) from e
        if not isinstance(data, dict):
            raise CareLinkError(
                f"CareLink returned unexpected JSON shape on {resp.request.url.path}"
            )
        return data
