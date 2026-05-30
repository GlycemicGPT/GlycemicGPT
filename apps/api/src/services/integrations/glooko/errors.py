"""Typed errors for the Glooko integration.

The sync orchestrator (Milestone C) must distinguish an **auth failure** (mark
the connection ``disconnected`` and prompt re-auth -- do NOT retry every tick)
from a **transient network error** (retry with backoff). Keep them separate.
"""

from __future__ import annotations


class GlookoSyncError(Exception):
    """Base error for the Glooko integration."""


class GlookoAuthError(GlookoSyncError):
    """Login failed or the session is invalid/expired and re-auth did not recover.

    The caller should mark the connection for re-auth rather than retrying.
    """


class GlookoNetworkError(GlookoSyncError):
    """A transient transport-level failure (timeout, connection error, 5xx).

    The caller may retry with backoff.
    """
