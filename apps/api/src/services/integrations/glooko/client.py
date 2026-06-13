"""Glooko data client -- keyset-cursor pump fetch + v3-graph CGM (clean-room).

Two retrieval paths, because the live capture proved the integrated
CGM is NOT in the v2 cursor for an Omnipod-5 account:

  * **Pump data** -- ``/api/v2/*`` keyset-cursor endpoints (basal/bolus/events/
    modes/alarms). Each requires BOTH ``lastUpdatedAt`` and ``lastGuid``; the
    first page uses the zero-UUID sentinel, and the response echoes the next
    page's cursor plus a ``lastPage`` flag. Cursor is on ``updatedAt`` (server
    write time), so it captures late uploads/edits -- good for incremental sync,
    and a full backfill just walks from the epoch.
  * **CGM glucose** -- ``/api/v3/graph/statistics/overall`` (date-windowed). The
    raw per-reading series (``graph/data?series[]=...``) is deferred to a follow-up.

The ``_logbook-web_session`` cookie from ``auth.glooko_login`` is replayed on the
cluster API host. A data-call 401/403 means the session expired and a 421 means
the account was re-homed to another cluster; if a ``reauth`` callback is supplied
the client re-logs-in once (re-deriving the cluster host) and retries, else it
raises ``GlookoAuthError`` so the orchestrator can mark the connection for re-auth.

Clean-room: endpoints/params observed first-hand (live capture), not copied from
the AGPL-3.0 nightscout-connect / jpollock Glooko sources.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from .auth import GlookoSession, resolve_region, validate_glooko_api_host
from .errors import GlookoAuthError, GlookoNetworkError, GlookoSyncError

#: First-page sentinel for the keyset cursor. The literal "0" yields a 500; an
#: empty value 422s. The zero-UUID is the accepted first-page value.
ZERO_GUID = "00000000-0000-0000-0000-000000000000"
#: A cursor instant safely before any Glooko data -- walks the full history.
EPOCH_CURSOR = "2015-01-01T00:00:00.000Z"

#: Cursor streams: name -> (path, response array key). All keyset-cursor endpoints
#: confirmed live. (``alarms`` records are snake_case while the rest are
#: camelCase, but the envelope keys are consistent -- the mapper handles record
#: casing; the cursor mechanics here are identical.)
#: ``insulins`` is NOT under the ``/pumps`` namespace -- it carries smart-pen
#: doses (NovoPen 6 / Echo Plus, confirmed live) and manually logged insulin,
#: but uses the exact same cursor envelope as the pump streams.
PUMP_STREAMS: dict[str, tuple[str, str]] = {
    "scheduled_basals": ("/api/v2/pumps/scheduled_basals", "scheduledBasals"),
    "normal_boluses": ("/api/v2/pumps/normal_boluses", "normalBoluses"),
    "extended_boluses": ("/api/v2/pumps/extended_boluses", "extendedBoluses"),
    "events": ("/api/v2/pumps/events", "events"),
    "modes": ("/api/v2/pumps/modes", "modes"),
    "alarms": ("/api/v2/pumps/alarms", "alarms"),
    "cgm_readings": ("/api/v2/cgm/readings", "readings"),
    "cgm_egvs": ("/api/v2/cgm/egvs", "egvs"),
    "insulins": ("/api/v2/insulins", "insulins"),
}

_GRAPH_STATS_PATH = "/api/v3/graph/statistics/overall"
_GRAPH_DATA_PATH = "/api/v3/graph/data"
#: The three range-bucketed CGM series whose union is the full per-reading CGM
#: trace (observed in the live capture). Each datum: {y: mg/dL, value: mg/dL*100, timestamp: UTC, ...}.
CGM_SERIES = ("cgmHigh", "cgmNormal", "cgmLow")

_DEFAULT_LIMIT = 500
#: Safety bound on pages drained in one ``fetch_stream`` call. Incremental fetches
#: terminate well before this; a full backfill should pass an explicit budget.
_DEFAULT_MAX_PAGES = 50
_MAX_RETRIES_429 = 3
_DEFAULT_TIMEOUT = 40.0

ReauthProvider = Callable[[], Awaitable[GlookoSession]]
# httpx accepts either a dict or a list of (key, value) pairs; the list form lets
# us send the repeated ``series[]`` params graph/data requires.
Params = dict[str, object] | list[tuple[str, str]]


@dataclass
class CursorPage:
    """Accumulated records for one stream plus the advanced cursor."""

    stream: str
    records: list[dict]
    last_updated_at: str
    last_guid: str
    last_page: bool
    pages_fetched: int


class GlookoClient:
    """Replays a ``GlookoSession`` against the cluster API host.

    ``reauth`` (optional) returns a fresh authenticated session; the client uses
    it to recover from a single auth-recoverable response (401/403/421 -- the
    sync orchestrator supplies it from stored creds).
    """

    def __init__(
        self,
        session: GlookoSession,
        *,
        reauth: ReauthProvider | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._region = resolve_region(session.region)  # also SSRF-validates the host
        self._session = session
        self._api_host = self._resolve_api_host(session)
        self._reauth = reauth
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )
        self._apply_cookies()

    def _resolve_api_host(self, session: GlookoSession) -> str:
        """Prefer the sub-cluster host discovered at login over the region default.

        EU accounts are re-homed to country sub-clusters (e.g.
        ``de-fr.api.glooko.com``); the ``eu.*`` hosts 421 every data call. The
        session value must be a TLS API host (``https://<cluster>.api.glooko.com``)
        -- the authenticated cookie is never replayed against a web host.
        """
        if session.api_host:
            return validate_glooko_api_host(session.api_host)
        return self._region.api_host

    def _apply_cookies(self) -> None:
        # The session is stored as ``{_logbook-web_session: value}``; its real domain
        # is ``.glooko.com``, which is what makes one cookie serve both the web and
        # API hosts -- so we pin it there explicitly when replaying onto our client.
        for name, value in self._session.cookies.items():
            self._client.cookies.set(name, value, domain="glooko.com")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> GlookoClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    @property
    def patient(self) -> str:
        slug = self._session.patient_slug
        if not slug:
            raise GlookoSyncError(
                "GlookoSession has no patient slug; cannot fetch data"
            )
        return slug

    # ---- HTTP plumbing --------------------------------------------------------
    async def _send(self, path: str, params: Params) -> httpx.Response:
        """One GET with retry on 429 (Retry-After) and a single 5xx retry.

        The final attempt is never "retriable" (429 needs ``attempt < max``; the 5xx
        retry only fires on ``attempt == 0``), so the loop always returns; the trailing
        raise is an explicit unreachable guard rather than a fall-through ``return``.
        """
        url = self._api_host + path
        for attempt in range(_MAX_RETRIES_429 + 1):
            try:
                resp = await self._client.get(
                    url, params=params, headers={"Accept": "application/json"}
                )
            except httpx.HTTPError as exc:
                raise GlookoNetworkError(
                    f"Glooko network error on GET {path}: {type(exc).__name__}: {exc or '<no message>'}"
                ) from exc
            retriable = (resp.status_code == 429 and attempt < _MAX_RETRIES_429) or (
                500 <= resp.status_code < 600 and attempt == 0
            )
            if retriable:
                await asyncio.sleep(self._retry_after(resp, attempt))
                continue
            return resp
        raise GlookoNetworkError(f"Glooko GET {path} exhausted retries")  # unreachable

    @staticmethod
    def _retry_after(resp: httpx.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header and header.isdigit():
            return min(float(header), 30.0)
        return min(2.0 * (2**attempt), 30.0) + random.random()

    async def _get_json(self, path: str, params: Params) -> dict:
        """GET returning parsed JSON, recovering from a single 401/403/421 via ``reauth``.

        421 (Misdirected Request) joins the re-auth triggers because it means the
        account was re-homed to a different cluster mid-session (the EU sub-cluster
        live finding): a fresh login re-derives the cluster host from the redirect,
        so the recovery path is identical to an expired session.
        """
        resp = await self._send(path, params)
        if resp.status_code in (401, 403, 421):
            resp = await self._reauth_and_retry(path, params, trigger=resp.status_code)
        # A 5xx (or a 429 that survived the retry budget) is transient -> the typed
        # GlookoNetworkError tells the orchestrator to retry with backoff, not to mark
        # the connection for re-auth. Genuine 4xx/shape problems are GlookoSyncError.
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            raise GlookoNetworkError(
                f"Glooko GET {path} transient failure: {resp.status_code}"
            )
        if resp.status_code >= 400:
            raise GlookoSyncError(f"Glooko GET {path} failed: {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise GlookoSyncError(f"Glooko GET {path} returned non-JSON") from exc
        if not isinstance(body, dict):
            raise GlookoSyncError(
                f"Glooko GET {path} returned unexpected shape {type(body).__name__}"
            )
        return body

    async def _reauth_and_retry(
        self, path: str, params: Params, *, trigger: int
    ) -> httpx.Response:
        if self._reauth is None:
            raise GlookoAuthError(
                f"Glooko auth-recoverable response ({trigger}) on {path} and no "
                "reauth provider is configured"
            )
        self._session = await self._reauth()
        self._api_host = self._resolve_api_host(self._session)
        self._apply_cookies()
        resp = await self._send(path, params)
        if resp.status_code in (401, 403):
            raise GlookoAuthError(
                f"Glooko re-auth did not recover the session on {path}"
            )
        if resp.status_code == 421:
            # Still misdirected after re-deriving the host: transient posture
            # (see the 421 rationale in auth.glooko_login).
            raise GlookoNetworkError(
                f"Glooko GET {path} still misdirected (421) after re-auth on "
                f"{self._api_host}"
            )
        return resp

    # ---- AC4: keyset-cursor pump fetch ---------------------------------------
    async def fetch_stream(
        self,
        stream: str,
        *,
        last_updated_at: str = EPOCH_CURSOR,
        last_guid: str = ZERO_GUID,
        limit: int = _DEFAULT_LIMIT,
        max_pages: int = _DEFAULT_MAX_PAGES,
    ) -> CursorPage:
        """Drain a pump stream from the given cursor until ``lastPage`` (or ``max_pages``).

        Pass the stored ``(last_updated_at, last_guid)`` for an incremental sync, or
        the defaults (epoch + zero-UUID) for a full historical backfill. Returns the
        accumulated records and the advanced cursor for the next call.

        Note: all pages are buffered in memory before returning. Incremental syncs are
        small, but a backfill should bound ``max_pages`` per call (the orchestrator in
        chunks it and persists the cursor between calls) rather than draining
        years of history in one go.
        """
        try:
            path, array_key = PUMP_STREAMS[stream]
        except KeyError:
            raise GlookoSyncError(
                f"Unknown Glooko stream {stream!r}; known: {sorted(PUMP_STREAMS)}"
            ) from None

        records: list[dict] = []
        cursor_updated, cursor_guid = last_updated_at, last_guid
        last_page = True
        pages = 0
        for _ in range(max(1, max_pages)):
            body = await self._get_json(
                path,
                {
                    "patient": self.patient,
                    "lastUpdatedAt": cursor_updated,
                    "lastGuid": cursor_guid,
                    "limit": limit,
                },
            )
            page_records = body.get(array_key)
            if isinstance(page_records, list):
                # Silently skip any non-dict entries (defensive; the schema is all
                # objects -- a stray scalar would be a server quirk, not our data).
                records.extend(r for r in page_records if isinstance(r, dict))
            pages += 1
            last_page = bool(body.get("lastPage", True))
            next_updated = str(body.get("lastUpdatedAt", cursor_updated))
            next_guid = str(body.get("lastGuid", cursor_guid))
            # `lastPage` is the authoritative terminator (reverse-engineering §6.1).
            if last_page:
                cursor_updated, cursor_guid = next_updated, next_guid
                break
            # Anti-infinite-loop guard: if the server echoes the same cursor back
            # (non-advancing), stop rather than re-fetch the identical page until the
            # max_pages budget is burned (which would also duplicate records).
            if (next_updated, next_guid) == (cursor_updated, cursor_guid):
                break
            cursor_updated, cursor_guid = next_updated, next_guid
        return CursorPage(
            stream=stream,
            records=records,
            last_updated_at=cursor_updated,
            last_guid=cursor_guid,
            last_page=last_page,
            pages_fetched=pages,
        )

    # ---- CGM glucose (v3 graph) ----------------------------------------------
    async def fetch_cgm_stats(self, start_date: str, end_date: str) -> dict:
        """Fetch date-windowed CGM/insulin aggregates from ``graph/statistics/overall``.

        Returns ``averageBg``, ``min``, ``max``, ``readingsPerDay``,
        ``activeCgmTimePercentage``, ... -- useful for an availability/summary check.
        For the per-reading trace use ``fetch_cgm_points``.
        """
        return await self._get_json(
            _GRAPH_STATS_PATH,
            {
                "patient": self.patient,
                "startDate": start_date,
                "endDate": end_date,
                "egv": "true",
                "includeInsulin": "true",
            },
        )

    async def fetch_cgm_points(self, start_date: str, end_date: str) -> list[dict]:
        """Fetch the raw per-reading CGM trace for a window.

        Merges the three range-bucketed ``cgm*`` series from ``graph/data`` into a
        single list of points (``{y: mg/dL, value, timestamp: UTC, ...}``), which
        ``mapper.map_cgm_points`` turns into glucose rows. The response's ``series``
        is an OBJECT keyed by series name (an unknown name is silently dropped).
        """
        params: list[tuple[str, str]] = [
            ("patient", self.patient),
            ("startDate", start_date),
            ("endDate", end_date),
            *[("series[]", name) for name in CGM_SERIES],
            ("locale", "en"),
            ("insulinTooltips", "false"),
            ("filterBgReadings", "false"),
            ("splitByDay", "false"),
        ]
        body = await self._get_json(_GRAPH_DATA_PATH, params)
        series = body.get("series")
        points: list[dict] = []
        if isinstance(series, dict):
            for name in CGM_SERIES:
                bucket = series.get(name)
                if isinstance(bucket, list):
                    points.extend(p for p in bucket if isinstance(p, dict))
        return points
