"""Tests for Sentry initialization and PII scrubbing (src/observability.py).

These lock in the load-bearing privacy guarantees: the SDK is a no-op without a
DSN, init applies the data-lockdown flags and endpoint-style transaction names,
and the before_send / before_send_transaction hooks strip health data / secrets
/ request data / stack locals before anything leaves the process.

NOTE: the secret-shaped fixtures below are ASSEMBLED AT RUNTIME from parts so
that secret scanners (e.g. GitGuardian) don't flag literal credentials in this
test file. The assembled runtime values still exercise the scrubber's patterns.
"""

import time
from unittest.mock import patch

from src.config import settings
from src.observability import (
    _before_send,
    _before_send_transaction,
    init_sentry,
    scrub_text,
)

# Assembled-at-runtime, non-literal secret-shaped fixtures (see module docstring).
_FAKE_DSN = "https://" + "examplekey" + "@o0.ingest.sentry.invalid/0"
_GH_TOKEN = "ghp_" + "0" * 36  # GitHub-PAT shape
_API_KEY = "sk-" + "A" * 24  # generic api-key shape
_JWT = "eyJ" + "a" * 8 + "." + "b" * 8 + "." + "c" * 8  # JWT shape
_BEARER = "Bearer " + "token" + "1234567890"  # bearer-token shape
_URL_PW = "examplepw" + "1234"  # password inside a URL


def test_init_is_noop_without_dsn(monkeypatch):
    """No DSN -> the SDK is never initialized (the platform sends nothing)."""
    monkeypatch.setattr(settings, "glycemicgpt_sentry_dsn", "")
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
    mock_init.assert_not_called()


def test_init_is_noop_with_whitespace_dsn(monkeypatch):
    """A whitespace-only DSN is treated as unset."""
    monkeypatch.setattr(settings, "glycemicgpt_sentry_dsn", "   ")
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
    mock_init.assert_not_called()


def test_init_applies_privacy_lockdown(monkeypatch):
    """When enabled, init must pass the PII/data-lockdown flags + both hooks."""
    monkeypatch.setattr(settings, "glycemicgpt_sentry_dsn", _FAKE_DSN)
    monkeypatch.setattr(settings, "glycemicgpt_sentry_environment", "staging")
    monkeypatch.setattr(settings, "glycemicgpt_sentry_traces_sample_rate", 0.0)
    monkeypatch.setattr(settings, "glycemicgpt_sentry_release", "abc1234")
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()

    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["max_request_body_size"] == "never"
    assert kwargs["include_local_variables"] is False
    assert kwargs["enable_logs"] is False
    assert kwargs["environment"] == "staging"
    assert kwargs["release"] == "abc1234"
    assert kwargs["traces_sample_rate"] == 0.0
    assert callable(kwargs["before_send"])
    assert callable(kwargs["before_send_transaction"])
    # Endpoint-style transaction names keep path-param VALUES (PHI) out of
    # transaction names and issue titles.
    styles = {getattr(i, "transaction_style", None) for i in kwargs["integrations"]}
    assert styles == {"endpoint"}


def test_init_treats_unknown_release_as_none(monkeypatch):
    """A placeholder release ("unknown" from an un-tagged build) is dropped."""
    monkeypatch.setattr(settings, "glycemicgpt_sentry_dsn", _FAKE_DSN)
    monkeypatch.setattr(settings, "glycemicgpt_sentry_release", "unknown")
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
    assert mock_init.call_args.kwargs["release"] is None


def test_init_excludes_503_from_error_reporting(monkeypatch):
    """503 is a deliberate retryable degradation response (e.g. token refresh
    during a Redis outage), so it must not be reported as a Sentry error event
    -- but other 5xx must still be captured."""
    monkeypatch.setattr(settings, "glycemicgpt_sentry_dsn", _FAKE_DSN)
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()

    integrations = mock_init.call_args.kwargs["integrations"]
    codes_per_integration = [
        i.failed_request_status_codes
        for i in integrations
        if hasattr(i, "failed_request_status_codes")
    ]
    assert codes_per_integration, "expected request integrations to be configured"
    for codes in codes_per_integration:
        assert 503 not in codes
        assert 500 in codes
        assert 504 in codes


def test_scrub_text_redacts_secrets_and_identifiers():
    # Assert BOTH that the marker appears AND that the original secret is gone,
    # so a buggy scrubber that only appends a marker (without removing the
    # value) would fail.
    assert scrub_text("contact jane.doe@example.com") == "contact [email]"

    result = scrub_text("key " + _API_KEY)
    assert "[token]" in result and _API_KEY not in result

    result = scrub_text(_GH_TOKEN)
    assert "[token]" in result and _GH_TOKEN not in result

    result = scrub_text("auth " + _JWT)
    assert "[jwt]" in result and _JWT not in result

    result = scrub_text("phone 15551234567")
    assert "[number]" in result and "15551234567" not in result

    result = scrub_text(_BEARER)
    assert "bearer [token]" in result and _BEARER not in result


def test_scrub_text_redacts_inline_url_credentials():
    out = scrub_text("conn https://user:" + _URL_PW + "@db.host/path")
    assert _URL_PW not in out
    assert "[redacted]@" in out


def test_scrub_text_keeps_short_numbers_readable():
    # Glucose-magnitude values (2-3 digits) are intentionally preserved; the
    # server-side scrubber + no-PHI-in-messages guideline cover those.
    assert scrub_text("glucose reading 180 mg/dL") == "glucose reading 180 mg/dL"


def test_before_send_strips_phi():
    event = {
        "server_name": "internal-host-01",
        "user": {
            "id": "u-1",
            "email": "jane@example.com",
            "username": "jane",
            "ip_address": "1.2.3.4",
        },
        "transaction": "/api/u/123456789",
        "exception": {
            "values": [
                {
                    "value": "lookup failed for jane@example.com",
                    "stacktrace": {
                        "frames": [
                            {"function": "f", "vars": {"glucose": 350, "pwd": "x"}}
                        ]
                    },
                }
            ]
        },
        "threads": {"values": [{"stacktrace": {"frames": [{"vars": {"s": "y"}}]}}]},
        "message": "request from 15551234567 failed",
        "request": {
            "url": "https://user:" + _URL_PW + "@host/api/glucose",
            "data": {"glucose": 350},
            "cookies": {"session": "x"},
            "headers": {"Authorization": "x"},
            "env": {"REMOTE_ADDR": "1.2.3.4"},
            "query_string": "user_id=42&glucose=350",
        },
        "breadcrumbs": {
            "values": [{"message": "logged jane@example.com", "data": {"bg": 350}}]
        },
        "extra": {"raw_payload": {"glucose": 350}},
    }

    out = _before_send(event, {})
    assert out is not None

    assert "server_name" not in out
    assert out["user"] == {"id": "u-1"}  # only opaque id kept
    assert "123456789" not in out["transaction"]

    frame = out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame  # stack locals dropped
    assert "@example.com" not in out["exception"]["values"][0]["value"]
    thread_frame = out["threads"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in thread_frame  # thread-stack locals dropped too
    assert "15551234567" not in out["message"]

    req = out["request"]
    assert "data" not in req
    assert "cookies" not in req
    assert "headers" not in req
    assert "env" not in req
    assert req["query_string"] == ""  # query string cleared
    assert _URL_PW not in req["url"]
    assert "[redacted]@" in req["url"]  # inline url credentials scrubbed

    crumb = out["breadcrumbs"]["values"][0]
    assert "data" not in crumb  # breadcrumb data dropped
    assert "@example.com" not in crumb["message"]

    assert "extra" not in out  # additional-data dump dropped


def test_before_send_strips_query_and_fragment_from_url():
    """A secret in the URL query or fragment must not survive: both are dropped
    wholesale, not merely pattern-scrubbed. The values below match NO scrub
    pattern, so this fails unless the query/fragment is actually stripped."""
    event = {
        "request": {
            "url": "https://host/api/glucose?session=keepoutofreports#tok=alsosecret",
        }
    }
    out = _before_send(event, {})
    url = out["request"]["url"]
    assert url == "https://host/api/glucose"
    assert "keepoutofreports" not in url and "alsosecret" not in url
    assert "?" not in url and "#" not in url


def test_before_send_scrubs_logentry():
    """Sentry's serializer prefers logentry.formatted as the displayed message."""
    event = {
        "logentry": {
            "formatted": "failed for jane@example.com",
            "message": "failed for %s",
        }
    }
    out = _before_send(event, {})
    assert "@example.com" not in out["logentry"]["formatted"]


def test_before_send_scrubs_event_tags():
    """Defensive: a tag value carrying an identifier must be scrubbed."""
    event = {"tags": {"endpoint": "ok", "actor_email": "jane@example.com"}}
    out = _before_send(event, {})
    assert out["tags"]["endpoint"] == "ok"
    assert "@example.com" not in out["tags"]["actor_email"]


def test_before_send_transaction_scrubs_spans():
    """Transaction events bypass before_send; spans must be scrubbed here."""
    txn = {
        "type": "transaction",
        "transaction": "/api/u/123456789",
        "server_name": "internal-host-01",
        "spans": [
            {
                "description": "SELECT * FROM glucose WHERE email = 'jane@example.com'",
                "data": {"db.params": {"email": "jane@example.com"}},
                "tags": {"who": "jane@example.com"},
            }
        ],
        "request": {
            "url": "https://user:" + _URL_PW + "@host/api",
            "query_string": "user_id=42",
            "headers": {"X": "y"},
        },
    }

    out = _before_send_transaction(txn, {})
    assert out is not None

    span = out["spans"][0]
    assert "@example.com" not in span["description"]
    assert "data" not in span  # span data (query params / SQL binds) dropped
    assert "@example.com" not in span["tags"]["who"]  # span tags scrubbed
    assert "server_name" not in out
    assert "123456789" not in out["transaction"]
    assert out["request"]["query_string"] == ""
    assert "headers" not in out["request"]
    assert "[redacted]@" in out["request"]["url"]


def test_scrub_text_bounded_on_large_pathological_input():
    # Regression guard against ReDoS: a long local-part run with no domain dot
    # used to backtrack quadratically. Clamp + bounded quantifiers keep it fast.
    # Generous threshold so normal CI load can't make it flaky.
    pathological = ("a." * 8000) + "@" + ("b" * 8000)  # ~24 KB, no domain dot
    start = time.perf_counter()
    result = scrub_text(pathological)
    assert isinstance(result, str)
    assert time.perf_counter() - start < 2.0
