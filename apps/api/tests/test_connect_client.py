"""Tests for the CarePartner (Connect) recent-data client (mocked, no network)."""

import json

import httpx
import pytest

from src.services.integrations.medtronic.connect_client import (
    APP_VERSION,
    CLOUD_HOST_US,
    CareLinkConnectClient,
    ConnectAuthError,
    ConnectError,
)


async def _bearer() -> str:
    return "access-token-abc"


def _make_client(handler, **kwargs) -> CareLinkConnectClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    kwargs.setdefault("username", "user@example.com")
    return CareLinkConnectClient(bearer_provider=_bearer, client=http, **kwargs)


async def test_patient_role_posts_expected_body_and_returns_patient_data():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/connect/carepartner/v13/display/message"
        assert request.headers["authorization"] == "Bearer access-token-abc"
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"patientData": {"sgs": [{"sg": 120}], "markers": []}}
        )

    async with _make_client(handler) as client:
        data = await client.get_recent_data()

    assert captured["body"] == {
        "username": "user@example.com",
        "role": "patient",
        "appVersion": APP_VERSION,
    }
    assert data == {"sgs": [{"sg": 120}], "markers": []}


async def test_carepartner_role_includes_patient_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"patientData": {"sgs": []}})

    async with _make_client(handler, role="carepartner", patient_id="pat-77") as client:
        await client.get_recent_data()

    assert captured["body"]["role"] == "carepartner"
    assert captured["body"]["patientId"] == "pat-77"


async def test_accepts_bare_recent_data_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sgs": [{"sg": 99}], "markers": []})

    async with _make_client(handler) as client:
        data = await client.get_recent_data()
    assert data == {"sgs": [{"sg": 99}], "markers": []}


async def test_missing_patient_data_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    async with _make_client(handler) as client:
        with pytest.raises(ConnectError, match="missing patientData"):
            await client.get_recent_data()


async def test_401_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "expired"})

    async with _make_client(handler) as client:
        with pytest.raises(ConnectAuthError):
            await client.get_recent_data()


async def test_non_json_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    async with _make_client(handler) as client:
        with pytest.raises(ConnectError, match="non-JSON"):
            await client.get_recent_data()


async def test_retries_then_succeeds_on_5xx():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"patientData": {"sgs": []}})

    async with _make_client(handler) as client:
        data = await client.get_recent_data()
    assert calls["n"] == 2
    assert data == {"sgs": []}


def test_untrusted_host_rejected():
    with pytest.raises(ValueError, match="untrusted host"):
        CareLinkConnectClient(
            bearer_provider=_bearer,
            username="u@example.com",
            base_url="https://evil.example.com",
        )


def test_default_base_url_is_us_cloud():
    client = CareLinkConnectClient(bearer_provider=_bearer, username="u@example.com")
    assert client._base_url == CLOUD_HOST_US


def test_carepartner_role_requires_patient_id():
    with pytest.raises(ValueError, match="requires a patient_id"):
        CareLinkConnectClient(
            bearer_provider=_bearer, username="u@example.com", role="carepartner"
        )


def test_unknown_role_rejected():
    with pytest.raises(ValueError, match="Unknown CarePartner role"):
        CareLinkConnectClient(
            bearer_provider=_bearer, username="u@example.com", role="bogus"
        )


def test_empty_username_rejected():
    with pytest.raises(ValueError, match="username is required"):
        CareLinkConnectClient(bearer_provider=_bearer, username="")
