"""Sentry error monitoring: initialization and PII scrubbing.

Sentry is OFF unless ``GLYCEMICGPT_SENTRY_DSN`` is set. The DSN is supplied only
in the project's own development, CI, and staging environments via a runtime
environment variable and is never baked into a distributed build. A self-hoster
may set their own DSN to send errors to their own Sentry account.

Error and transaction events are scrubbed of health data, secrets, request
bodies, stack locals, and span detail before they leave the process; the
project's hosted Sentry applies server-side Advanced Data Scrubbing as a second
layer, and contributor guidelines forbid putting health data or identifiers in
exception messages. See PRIVACY.md and docs/concepts/privacy.md.
"""

from __future__ import annotations

import re
from typing import Any

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)

# Best-effort, readability-preserving redaction of high-risk patterns that can
# appear in free text (exception messages, breadcrumbs, span descriptions,
# URLs). This is the in-process layer; the project's hosted Sentry adds
# server-side scrubbing as a backstop. Short numbers (e.g. glucose values) are
# intentionally left readable -- the server-side scrubber and the
# no-PHI-in-messages guideline cover those; here we target the unambiguous
# secret/identifier shapes.
_SCRUB_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"://[^/@\s]+@"), "://[redacted]@"),  # inline url credentials
    # Length-bounded quantifiers (RFC-ish caps) keep this linear-time -- an
    # unbounded local part backtracks quadratically on a long no-dot domain.
    (re.compile(r"\b[\w.+-]{1,64}@[\w-]{1,255}\.[\w.-]{1,255}\b"), "[email]"),
    (re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+\b"), "[jwt]"),  # JWTs
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "bearer [token]"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9]{16,}\b"), "[token]"),  # api keys
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[token]"),  # github tokens
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[token]"),  # aws access key id
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[token]"),  # slack tokens
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "[hex]"),  # long hex blobs / hashes
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "[blob]"),  # long base64-ish
    (re.compile(r"\b\d{9,}\b"), "[number]"),  # phone / device / record ids
)

# Request sub-fields that are never needed for triage and are the highest PHI
# risk; dropped wholesale before the event leaves the process.
_REQUEST_DROP_FIELDS = ("data", "cookies", "headers", "env")
# User identity fields dropped defensively (send_default_pii=False already
# avoids auto-populating them); an opaque id is left for the server-side Safe
# Field.
_USER_DROP_FIELDS = ("email", "username", "ip_address", "name")
# Clamp free text before regex scrubbing: bounds worst-case work (defense vs
# ReDoS-style input) and matches Sentry's own field truncation. The dropped tail
# is never sent. Messages/URLs are normally far shorter than this.
_MAX_SCRUB_LEN = 8192


def scrub_text(text: str) -> str:
    """Redact high-risk secret/identifier patterns from a free-text string."""
    if len(text) > _MAX_SCRUB_LEN:
        text = text[:_MAX_SCRUB_LEN]
    for pattern, replacement in _SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _drop_frame_vars(stacktrace: Any) -> None:
    """Remove captured local variables from every frame of a stacktrace."""
    if isinstance(stacktrace, dict):
        for frame in stacktrace.get("frames", []):
            if isinstance(frame, dict):
                frame.pop("vars", None)


def _scrub_logentry(entry: dict[str, Any]) -> None:
    """Scrub a logentry-shaped dict's formatted/message strings in place."""
    for key in ("formatted", "message"):
        if isinstance(entry.get(key), str):
            entry[key] = scrub_text(entry[key])


def _scrub_message(event: dict[str, Any]) -> None:
    message = event.get("message")
    if isinstance(message, str):
        event["message"] = scrub_text(message)
    elif isinstance(message, dict):
        _scrub_logentry(message)
    # Sentry's event serializer prefers logentry.formatted as the effective
    # displayed message, so it can carry text that bypasses event["message"].
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        _scrub_logentry(logentry)


def _scrub_common(event: dict[str, Any]) -> None:
    """Scrub fields shared by error and transaction events (in place)."""
    # Host name and the ad-hoc "extra" dump are not in the documented send-list.
    event.pop("server_name", None)
    event.pop("extra", None)

    user = event.get("user")
    if isinstance(user, dict):
        for field in _USER_DROP_FIELDS:
            user.pop(field, None)

    # Defensively scrub tag values. No scope API sets PHI today, but a future
    # set_tag() with an identifier must not leak. (contexts/modules/sdk are
    # version metadata -- the intentionally-sent "OS/runtime versions".)
    tags = event.get("tags")
    if isinstance(tags, dict):
        for key, value in tags.items():
            if isinstance(value, str):
                tags[key] = scrub_text(value)

    # Transaction name -- a route pattern under transaction_style="endpoint",
    # but scrub defensively in case a raw path ever slips through.
    if isinstance(event.get("transaction"), str):
        event["transaction"] = scrub_text(event["transaction"])

    breadcrumbs = event.get("breadcrumbs")
    crumbs = breadcrumbs.get("values", []) if isinstance(breadcrumbs, dict) else []
    for crumb in crumbs:
        if isinstance(crumb, dict):
            if isinstance(crumb.get("message"), str):
                crumb["message"] = scrub_text(crumb["message"])
            crumb.pop("data", None)  # breadcrumb data can carry arbitrary fields

    request = event.get("request")
    if isinstance(request, dict):
        for field in _REQUEST_DROP_FIELDS:
            request.pop(field, None)
        if "query_string" in request:
            request["query_string"] = ""
        if isinstance(request.get("url"), str):
            request["url"] = scrub_text(request["url"])


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Scrub an error event in-process before it is sent to Sentry.

    Defense in depth on top of the init flags: drop stack-frame locals (incl.
    thread stacks), strip request bodies/cookies/headers/query, drop the
    ``extra`` dump and user identity, and pattern-scrub free text. Returning
    ``None`` would drop the event entirely.
    """
    for exc in event.get("exception", {}).get("values", []):
        _drop_frame_vars(exc.get("stacktrace"))
        if isinstance(exc.get("value"), str):
            exc["value"] = scrub_text(exc["value"])
    for thread in event.get("threads", {}).get("values", []):
        _drop_frame_vars(thread.get("stacktrace"))
    _scrub_message(event)
    _scrub_common(event)
    return event


def _before_send_transaction(
    event: dict[str, Any], hint: dict[str, Any]
) -> dict[str, Any] | None:
    """Scrub a transaction (tracing) event before it is sent to Sentry.

    Tracing is off by default, but if enabled the SDK attaches query strings to
    HTTP spans and statement text to DB spans -- both potential PHI -- so spans
    are scrubbed here. ``before_send`` does NOT run for transaction events, so
    this hook is required to cover them.
    """
    for span in event.get("spans", []):
        if isinstance(span, dict):
            if isinstance(span.get("description"), str):
                span["description"] = scrub_text(span["description"])
            span.pop("data", None)  # span data carries query params / SQL binds
            span_tags = span.get("tags")
            if isinstance(span_tags, dict):
                for key, value in span_tags.items():
                    if isinstance(value, str):
                        span_tags[key] = scrub_text(value)
    _scrub_common(event)
    return event


def init_sentry() -> None:
    """Initialize Sentry if a DSN is configured; otherwise a no-op.

    Safe to call once at startup. Without ``GLYCEMICGPT_SENTRY_DSN`` the SDK is
    never initialized, so the running platform sends nothing.
    """
    dsn = settings.glycemicgpt_sentry_dsn.strip()
    if not dsn:
        logger.info("Sentry disabled (GLYCEMICGPT_SENTRY_DSN not set)")
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    release = settings.glycemicgpt_sentry_release.strip()
    if release in ("", "unknown"):
        release = None

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.glycemicgpt_sentry_environment,
        release=release,
        # --- PII / data lockdown (see PRIVACY.md) ---
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        before_send=_before_send,
        before_send_transaction=_before_send_transaction,
        # Route patterns (not raw paths) in transaction names, so path-param
        # values (potential PHI) don't land in transaction names / issue titles.
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        # --- products we deliberately never enable ---
        enable_logs=False,
        # --- tracing off by default (errors only); raise via env to sample ---
        traces_sample_rate=settings.glycemicgpt_sentry_traces_sample_rate,
    )
    logger.info(
        "Sentry enabled",
        environment=settings.glycemicgpt_sentry_environment,
        release=release or "unset",
        traces_sample_rate=settings.glycemicgpt_sentry_traces_sample_rate,
    )
