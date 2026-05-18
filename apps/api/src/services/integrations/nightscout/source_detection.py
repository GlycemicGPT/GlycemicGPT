"""Closed-loop source-engine detection -- shared between PR 2 (forecast
mapper) and PR 6 (loop state extractor).

Story 43.12 PR 6. Both extractors classify the OpenAPS-family source
(`aaps` / `trio` / `oref0` / `iaps`) from the same signals -- the
NS `device` string + a determination-block fallback for older Trio
builds. They MUST agree, or the chart legend and hero card will
attribute the same row to different engines.

This module owns the canonical chain. Both call sites import from
here so a future heuristic change can't drift between the two.

`detect_uploader()` in `models.py` (PR 43.3) is the shared base layer;
this module adds the OpenAPS-specific refinements (iAPS substring
fallback, Trio determination-block fallback) needed by both
forecast-row and hero-card-row code paths.
"""

from __future__ import annotations

from typing import Any, Literal

from src.services.integrations.nightscout.models import detect_uploader

# OpenAPS-family engines this module can classify. Loop is NOT in this
# set: Loop has its own subtree presence check (`ds.loop.predicted`
# for forecasts; `ds.loop.{enacted,suggested}` for runtime state) and
# doesn't need an OpenAPS-style fallback chain.
_OPENAPS_ENGINES = frozenset({"aaps", "trio", "oref0", "iaps"})

OpenapsEngine = Literal["aaps", "trio", "oref0", "iaps"]


def detect_openaps_engine(
    device: str | None, openaps_subtree: dict[str, Any] | None
) -> OpenapsEngine | None:
    """Classify an OpenAPS-family devicestatus as AAPS / Trio / oref0 / iAPS.

    Detection chain (most-specific first):

    1. **`detect_uploader()` shared heuristic** for canonical device
       strings. Returns the lowercase tag for AAPS / Trio / oref0.
       Hybrids like `openaps://AndroidAPS-iAPS-bridge` correctly
       classify as `aaps` here (the URI scheme + AAPS prefix win
       through `parse_openaps_uri`).
    2. **iAPS substring fallback** when `detect_uploader()` returns
       "unknown" but the device string contains `iaps`. The shared
       helper has no iAPS branch yet; checking inline avoids touching
       PR 1's shared file. The `"aaps" not in device_lower` guard is
       belt-and-braces local protection -- today the canonical AAPS
       device strings (`androidaps`) don't contain `iaps`, but the
       guard makes the local logic self-evident.
    3. **Trio determination-block fallback** when neither path
       classifies but the payload carries `openaps.determination`
       (a Trio-specific subtree). Older Trio builds occasionally
       ship without a recognizable device string; the determination
       block is the next-best signal.

    Returns None for indeterminate payloads -- the caller's UI should
    hide the attribution rather than guess.

    NOTE: `detect_uploader()` reads `device` only -- `enteredBy` is
    discarded for devicestatus. Real-world devicestatus rarely carries
    enteredBy; documented limitation, not a current correctness issue.
    """
    uploader = detect_uploader(None, device)
    if uploader in _OPENAPS_ENGINES:
        return uploader  # type: ignore[return-value]

    device_lower = (device or "").lower()
    if "iaps" in device_lower and "aaps" not in device_lower:
        return "iaps"

    if openaps_subtree is not None and isinstance(
        openaps_subtree.get("determination"), dict
    ):
        return "trio"

    return None
