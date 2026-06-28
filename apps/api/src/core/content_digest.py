"""Canonical content hashing for the trust-kernel version modules.

The text harness (``benchmarks.core.version``) and the standalone vision harness
(``evals/vision_carb/harness_version``) both content-hash their per-surface
inputs. They hash *disjoint* component sets, but they must canonicalize and digest
the same way, so the one canonicalization lives here — a single source both import
(the vision harness through the same lightweight ``apps/api`` path shim it already
uses for the carb contract). Pure stdlib, so it stays importable in the lean
environment the vision harness runs in.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Stable JSON for hashing: sorted keys, no incidental whitespace, ASCII-escaped
    so a non-ASCII prompt character hashes identically on every platform."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(text: str) -> str:
    """Raw hex digest of a string — used for the per-component source hashes that
    are themselves embedded in a larger component dict."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_digest(obj: Any) -> str:
    """The algorithm-tagged version string (``sha256:<hex>``) for a component dict.

    The ``sha256:`` prefix self-documents the algorithm so the format can evolve
    (a future scheme would carry a different tag) without ambiguity.
    """
    return "sha256:" + sha256_hex(canonical_json(obj))
