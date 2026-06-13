"""Tests for the Glooko auth + data client (mocked HTTP, no network).

Covers the web Devise login flow, patient discovery, cookie replay, keyset-cursor
pagination (zero-UUID first page, lastPage termination, cursor advance), single
re-auth on 401, region host resolution, and typed errors. HTTP is faked with
``httpx.MockTransport`` (the repo pattern -- see ``test_connect_client.py``).
"""

import httpx
import pytest

from src.services.integrations.glooko.auth import (
    SESSION_COOKIE_NAME,
    GlookoSession,
    glooko_login,
)
from src.services.integrations.glooko.client import (
    EPOCH_CURSOR,
    ZERO_GUID,
    GlookoClient,
)
from src.services.integrations.glooko.errors import (
    GlookoAuthError,
    GlookoNetworkError,
    GlookoSyncError,
)

# --- a real-ish session/users payload carrying the patient slug ----------------
_SESSION_USERS_BODY = {
    "currentPatient": {
        "glookoCode": "adjective-noun-1234",
        "id": "64233d92cd75e20c8d86edd4",
    },
}


def _mock_client(handler, *, follow_redirects: bool = True) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=follow_redirects,
    )


async def _instant_sleep(_seconds: float) -> None:
    """No-op replacement for asyncio.sleep so retry-backoff tests don't actually wait."""
    return None


def _session(**overrides) -> GlookoSession:
    base = {
        "region": "US",
        "cookies": {SESSION_COOKIE_NAME: "authed-cookie"},
        "patient_slug": "adjective-noun-1234",
    }
    base.update(overrides)
    return GlookoSession(**base)


# =============================== auth =========================================


async def test_glooko_login_runs_full_devise_flow_and_discovers_patient():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/users/sign_in":
            assert request.url.host == "us.my.glooko.com"
            return httpx.Response(
                200,
                html='<meta name="csrf-token" content="csrf-tok-xyz" />',
            )
        if request.method == "POST" and path == "/users/sign_in":
            seen["form"] = dict(httpx.QueryParams(request.content.decode()))
            return httpx.Response(
                200,
                headers={
                    "set-cookie": f"{SESSION_COOKIE_NAME}=authed; Domain=glooko.com; Path=/"
                },
            )
        if request.method == "GET" and path == "/api/v3/session/users":
            assert request.url.host == "us.api.glooko.com"
            return httpx.Response(200, json=_SESSION_USERS_BODY)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    async with _mock_client(handler) as http:
        session = await glooko_login("user@example.com", "pw", "US", client=http)

    # form carried the CSRF token + Devise field names
    assert seen["form"]["authenticity_token"] == "csrf-tok-xyz"
    assert seen["form"]["user[email]"] == "user@example.com"
    assert seen["form"]["user[password]"] == "pw"
    assert session.is_authenticated
    assert session.patient_slug == "adjective-noun-1234"
    assert session.patient_oid == "64233d92cd75e20c8d86edd4"
    assert session.region == "US"


async def test_glooko_login_post_sends_html_accept_header():
    # US live finding (2026-06-12): Glooko's edge content-negotiates the login POST
    # by Accept. Without an HTML-admitting Accept it routes to the JSON API tier and
    # 421s before checking credentials, so the login can never succeed. Pin that the
    # POST advertises text/html (the GET already does).
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/users/sign_in":
            seen["accept"] = request.headers.get("accept")
            return httpx.Response(
                200,
                headers={
                    "set-cookie": f"{SESSION_COOKIE_NAME}=authed; Domain=glooko.com; Path=/"
                },
            )
        if path == "/api/v3/session/users":
            return httpx.Response(200, json=_SESSION_USERS_BODY)
        return httpx.Response(200, html='<meta name="csrf-token" content="t" />')

    async with _mock_client(handler) as http:
        await glooko_login("user@example.com", "pw", "US", client=http)

    assert seen["accept"] is not None
    assert "text/html" in seen["accept"].lower()


async def test_glooko_login_bad_credentials_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/session/users":
            return httpx.Response(401, json={"error": "unauthorized"})
        if request.method == "POST":
            return httpx.Response(200)
        return httpx.Response(200, html='<meta name="csrf-token" content="t" />')

    async with _mock_client(handler) as http:
        with pytest.raises(GlookoAuthError):
            await glooko_login("user@example.com", "wrong", "US", client=http)


async def test_glooko_login_421_is_network_error_not_auth_error():
    # 421 = wrong host (account re-homed), not bad creds -- must stay retryable,
    # never a permanent disconnect with a "check email/password" message.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/session/users":
            return httpx.Response(421)
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "set-cookie": f"{SESSION_COOKIE_NAME}=authed; Domain=glooko.com; Path=/"
                },
            )
        return httpx.Response(200, html='<meta name="csrf-token" content="t" />')

    async with _mock_client(handler) as http:
        with pytest.raises(GlookoNetworkError):
            await glooko_login("user@example.com", "pw", "EU", client=http)


async def test_glooko_login_missing_session_cookie_raises_auth_error():
    # session/users says 200 but no _logbook-web_session cookie was ever set.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/session/users":
            return httpx.Response(200, json=_SESSION_USERS_BODY)
        if request.method == "POST":
            return httpx.Response(200)
        return httpx.Response(200, html='<meta name="csrf-token" content="t" />')

    async with _mock_client(handler) as http:
        with pytest.raises(GlookoAuthError):
            await glooko_login("user@example.com", "pw", "US", client=http)


async def test_glooko_login_network_error_is_typed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async with _mock_client(handler) as http:
        with pytest.raises(GlookoNetworkError):
            await glooko_login("user@example.com", "pw", "US", client=http)


async def test_glooko_login_unknown_region_raises_value_error():
    # An unknown region is a config/programming error, not a runtime auth failure.
    with pytest.raises(ValueError):
        await glooko_login("user@example.com", "pw", "ZZ")


async def test_glooko_login_requires_credentials():
    with pytest.raises(GlookoAuthError):
        await glooko_login("", "", "US")


# ====================== auth: EU sub-cluster redirect =========================
# Live finding: the EU login 302s to a country sub-cluster web host
# (eu.my -> de-fr.my), and only the matching sub-cluster API host accepts
# session/data calls -- the eu.* hosts answer 421 Misdirected Request.


async def test_glooko_login_eu_follows_sub_cluster_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if request.method == "GET" and path == "/users/sign_in":
            assert host == "eu.my.glooko.com"
            return httpx.Response(
                200, html='<meta name="csrf-token" content="csrf-tok-eu" />'
            )
        if request.method == "POST" and path == "/users/sign_in":
            assert host == "eu.my.glooko.com"
            return httpx.Response(
                302,
                headers={
                    "location": "https://de-fr.my.glooko.com",
                    "set-cookie": f"{SESSION_COOKIE_NAME}=authed; Domain=glooko.com; Path=/",
                },
            )
        if request.method == "GET" and host == "de-fr.my.glooko.com" and path == "/":
            return httpx.Response(200, html="<html>landing</html>")
        if path == "/api/v3/session/users":
            # Reality check: only the sub-cluster API host works; eu.* 421s.
            if host == "de-fr.api.glooko.com":
                return httpx.Response(200, json=_SESSION_USERS_BODY)
            return httpx.Response(421)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    async with _mock_client(handler) as http:
        session = await glooko_login("user@example.com", "pw", "EU", client=http)

    assert session.is_authenticated
    assert session.api_host == "https://de-fr.api.glooko.com"
    assert session.patient_slug == "adjective-noun-1234"
    assert session.region == "EU"


async def test_glooko_login_without_redirect_derives_region_host():
    # US flow: no sub-cluster redirect; the derived host equals the region host.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/session/users":
            return httpx.Response(200, json=_SESSION_USERS_BODY)
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "set-cookie": f"{SESSION_COOKIE_NAME}=authed; Domain=glooko.com; Path=/"
                },
            )
        return httpx.Response(200, html='<meta name="csrf-token" content="t" />')

    async with _mock_client(handler) as http:
        session = await glooko_login("user@example.com", "pw", "US", client=http)

    assert session.api_host == "https://us.api.glooko.com"


async def test_glooko_login_redirect_to_foreign_host_falls_back_to_region():
    # A redirect outside *.my.glooko.com must NOT steer data calls there: the
    # derivation returns None and the verify call uses the region default.
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if request.method == "POST" and path == "/users/sign_in":
            return httpx.Response(
                302,
                headers={
                    "location": "https://attacker.example.com",
                    "set-cookie": f"{SESSION_COOKIE_NAME}=authed; Domain=glooko.com; Path=/",
                },
            )
        if host == "attacker.example.com":
            # The redirect-following GET itself is browser-equivalent and
            # unavoidable with follow_redirects -- what must NEVER happen is the
            # .glooko.com-scoped session cookie travelling along with it.
            foreign_cookie_headers.append(request.headers.get("cookie"))
            return httpx.Response(200, html="<html>not glooko</html>")
        if path == "/api/v3/session/users":
            assert host == "eu.api.glooko.com"
            return httpx.Response(200, json=_SESSION_USERS_BODY)
        return httpx.Response(200, html='<meta name="csrf-token" content="t" />')

    foreign_cookie_headers: list[str | None] = []
    async with _mock_client(handler) as http:
        session = await glooko_login("user@example.com", "pw", "EU", client=http)

    # No session cookie ever reached the foreign host, and data calls fell back
    # to the region API host instead of following the rogue redirect.
    assert foreign_cookie_headers == [None]
    assert session.api_host == "https://eu.api.glooko.com"


def test_derive_api_host_shapes():
    from src.services.integrations.glooko.auth import derive_api_host

    assert (
        derive_api_host("https://de-fr.my.glooko.com/dashboard")
        == "https://de-fr.api.glooko.com"
    )
    assert derive_api_host("https://us.my.glooko.com") == "https://us.api.glooko.com"
    assert derive_api_host("https://api.glooko.com") is None
    assert derive_api_host("https://evil.example.com") is None
    assert derive_api_host("/relative/path") is None


# =============================== client: cursor ===============================


def _page(
    array_key,
    records,
    *,
    last_page,
    last_updated="2024-01-01T00:00:00.000Z",
    last_guid="11111111-1111-1111-1111-111111111111",
):
    return {
        array_key: records,
        "lastPage": last_page,
        "lastUpdatedAt": last_updated,
        "lastGuid": last_guid,
    }


async def test_fetch_stream_single_page_returns_records_and_cursor():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "us.api.glooko.com"
        assert request.url.path == "/api/v2/pumps/normal_boluses"
        # the session cookie is replayed on the data call
        assert request.headers.get("cookie") == "_logbook-web_session=authed-cookie"
        params = request.url.params
        # the (only) request uses the epoch + zero-UUID first-page sentinel
        assert params["lastGuid"] == ZERO_GUID
        assert params["lastUpdatedAt"] == EPOCH_CURSOR
        assert params["patient"] == "adjective-noun-1234"
        return httpx.Response(
            200,
            json=_page("normalBoluses", [{"insulinDelivered": 1.0}], last_page=True),
        )

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        page = await client.fetch_stream("normal_boluses")

    assert page.pages_fetched == 1
    assert page.last_page is True
    assert page.records == [{"insulinDelivered": 1.0}]


async def test_client_replays_on_session_sub_cluster_host():
    # A session carrying a sub-cluster api_host (EU live finding) must steer
    # every data call there, not to the static region host.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "de-fr.api.glooko.com"
        return httpx.Response(
            200,
            json=_page("normalBoluses", [{"insulinDelivered": 2.0}], last_page=True),
        )

    async with _mock_client(handler) as http:
        client = GlookoClient(
            _session(region="EU", api_host="https://de-fr.api.glooko.com"),
            client=http,
        )
        page = await client.fetch_stream("normal_boluses")

    assert page.records == [{"insulinDelivered": 2.0}]


def test_client_rejects_session_host_outside_allowlist():
    # Defense in depth: the session data host must be exactly
    # https://<cluster>.api.glooko.com -- anything else (foreign host, a
    # *.my.* WEB host, plain http) is a config/programming error and must
    # fail closed at construction (same posture as resolve_region).
    for bad in (
        "https://evil.example.com",
        "https://us.my.glooko.com",  # legit web host, but NOT a data host
        "https://api.glooko.com",  # apex, not a per-cluster host
        "http://us.api.glooko.com",  # right host, no TLS
        # A bare origin is required: the client builds URLs as api_host + path,
        # so userinfo/port/path/query/fragment would corrupt every data call.
        "https://user:pass@us.api.glooko.com",
        "https://us.api.glooko.com:9999",
        "https://us.api.glooko.com/",
        "https://us.api.glooko.com/some/path",
        "https://us.api.glooko.com?q=1",
        "https://us.api.glooko.com#frag",
    ):
        with pytest.raises(ValueError):
            GlookoClient(_session(api_host=bad))


async def test_fetch_stream_paginates_until_last_page_and_advances_cursor():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        calls.append((params["lastUpdatedAt"], params["lastGuid"]))
        if len(calls) == 1:
            return httpx.Response(
                200,
                json=_page(
                    "events",
                    [{"type": "pod_activating"}],
                    last_page=False,
                    last_updated="2023-06-01T00:00:00.000Z",
                    last_guid="guid-page2",
                ),
            )
        return httpx.Response(
            200,
            json=_page(
                "events",
                [{"type": "reservoir_change"}],
                last_page=True,
                last_updated="2023-09-01T00:00:00.000Z",
                last_guid="guid-final",
            ),
        )

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        page = await client.fetch_stream("events", max_pages=10)

    # page 2 was requested with page 1's advanced cursor
    assert calls[0] == (EPOCH_CURSOR, ZERO_GUID)
    assert calls[1] == ("2023-06-01T00:00:00.000Z", "guid-page2")
    assert page.pages_fetched == 2
    assert [r["type"] for r in page.records] == ["pod_activating", "reservoir_change"]
    assert page.last_updated_at == "2023-09-01T00:00:00.000Z"
    assert page.last_guid == "guid-final"


async def test_fetch_stream_respects_max_pages_budget():
    n = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["i"] += 1
        # advance the cursor each page so the non-advance guard does NOT fire -- this
        # isolates the max_pages budget as the reason the drain stops.
        return httpx.Response(
            200,
            json=_page(
                "modes",
                [{"type": "automatic"}],
                last_page=False,
                last_updated=f"2023-0{n['i']}-01T00:00:00.000Z",
                last_guid=f"guid-{n['i']}",
            ),
        )

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        page = await client.fetch_stream("modes", max_pages=3)

    assert page.pages_fetched == 3  # stopped at the budget despite lastPage=false
    assert page.last_page is False


async def test_fetch_stream_stops_when_cursor_does_not_advance():
    # Server bug / boundary: lastPage=false forever but the echoed cursor never moves.
    # The client must stop after one page rather than burn the whole max_pages budget
    # re-fetching (and duplicating) the identical page.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json=_page(
                "modes",
                [{"type": "automatic"}],
                last_page=False,
                last_updated=EPOCH_CURSOR,
                last_guid=ZERO_GUID,
            ),
        )

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        page = await client.fetch_stream("modes", max_pages=10)

    assert calls["n"] == 1
    assert page.pages_fetched == 1


async def test_fetch_stream_unknown_stream_raises():
    async with _mock_client(lambda r: httpx.Response(200, json={})) as http:
        client = GlookoClient(_session(), client=http)
        with pytest.raises(GlookoSyncError):
            await client.fetch_stream("not_a_stream")


async def test_fetch_stream_without_patient_slug_raises():
    async with _mock_client(lambda r: httpx.Response(200, json={})) as http:
        client = GlookoClient(_session(patient_slug=None), client=http)
        with pytest.raises(GlookoSyncError):
            await client.fetch_stream("normal_boluses")


# =============================== client: re-auth ==============================


async def test_reauth_on_401_retries_once_and_recovers():
    state = {"calls": 0, "reauths": 0, "cookies": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        state["cookies"].append(request.headers.get("cookie"))
        if state["calls"] == 1:
            return httpx.Response(401, json={"error": "session expired"})
        return httpx.Response(
            200, json=_page("scheduledBasals", [{"rate": 0.5}], last_page=True)
        )

    async def reauth() -> GlookoSession:
        state["reauths"] += 1
        return _session(cookies={SESSION_COOKIE_NAME: "fresh-cookie"})

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), reauth=reauth, client=http)
        page = await client.fetch_stream("scheduled_basals")

    assert state["reauths"] == 1
    assert page.records == [{"rate": 0.5}]
    # the first call carried the stale cookie; the retry carried the re-applied fresh one
    assert state["cookies"][0] == "_logbook-web_session=authed-cookie"
    assert state["cookies"][1] == "_logbook-web_session=fresh-cookie"


async def test_401_without_reauth_provider_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "expired"})

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)  # no reauth
        with pytest.raises(GlookoAuthError):
            await client.fetch_stream("normal_boluses")


async def test_second_401_after_reauth_raises_auth_error():
    async def reauth() -> GlookoSession:
        return _session()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "still expired"})

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), reauth=reauth, client=http)
        with pytest.raises(GlookoAuthError):
            await client.fetch_stream("normal_boluses")


async def test_reauth_on_421_re_derives_cluster_host_and_recovers():
    # Mid-session cluster re-home: re-auth re-derives the host and the SAME
    # data call succeeds there in-cycle -- no failed sync tick.
    state = {"reauths": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "eu.api.glooko.com":
            return httpx.Response(421)
        assert request.url.host == "de-fr.api.glooko.com"
        return httpx.Response(
            200,
            json=_page("normalBoluses", [{"insulinDelivered": 1.5}], last_page=True),
        )

    async def reauth() -> GlookoSession:
        state["reauths"] += 1
        return _session(region="EU", api_host="https://de-fr.api.glooko.com")

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(region="EU"), reauth=reauth, client=http)
        page = await client.fetch_stream("normal_boluses")

    assert state["reauths"] == 1
    assert page.records == [{"insulinDelivered": 1.5}]


async def test_persistent_421_after_reauth_is_network_error_not_auth_error():
    # 421 surviving re-auth = Glooko routing problem -- retryable, not a
    # disconnect.
    async def reauth() -> GlookoSession:
        return _session(region="EU")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(421)

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(region="EU"), reauth=reauth, client=http)
        with pytest.raises(GlookoNetworkError):
            await client.fetch_stream("normal_boluses")


# =============================== client: misc =================================


async def test_fetch_cgm_stats_hits_graph_with_egv_true():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/graph/statistics/overall"
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200, json={"averageBg": 142, "min": 40, "max": 320, "readingsPerDay": 130}
        )

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        stats = await client.fetch_cgm_stats(
            "2024-01-01T00:00:00.000Z", "2024-02-01T00:00:00.000Z"
        )

    assert seen["params"]["egv"] == "true"
    assert seen["params"]["startDate"] == "2024-01-01T00:00:00.000Z"
    assert stats["averageBg"] == 142


@pytest.mark.parametrize(
    ("region", "expected_host"),
    [("US", "us.api.glooko.com"), ("EU", "eu.api.glooko.com")],
)
async def test_region_host_resolution(region, expected_host):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        return httpx.Response(200, json=_page("normalBoluses", [], last_page=True))

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(region=region), client=http)
        await client.fetch_stream("normal_boluses")

    assert seen["host"] == expected_host


async def test_network_error_is_typed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        with pytest.raises(GlookoNetworkError):
            await client.fetch_stream("normal_boluses")


async def test_5xx_is_retried_once_then_succeeds(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _instant_sleep)
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(503, json={"error": "upstream"})
        return httpx.Response(
            200,
            json=_page("normalBoluses", [{"insulinDelivered": 2.0}], last_page=True),
        )

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        page = await client.fetch_stream("normal_boluses")

    assert state["n"] == 2  # one retry
    assert page.records == [{"insulinDelivered": 2.0}]


async def test_persistent_5xx_raises_network_error_not_sync_error(monkeypatch):
    # 5xx is transient -> GlookoNetworkError (retry), NOT GlookoSyncError/GlookoAuthError.
    monkeypatch.setattr("asyncio.sleep", _instant_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        with pytest.raises(GlookoNetworkError):
            await client.fetch_stream("normal_boluses")


async def test_4xx_raises_sync_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "nope"})

    async with _mock_client(handler) as http:
        client = GlookoClient(_session(), client=http)
        with pytest.raises(GlookoSyncError):
            await client.fetch_stream("normal_boluses")
