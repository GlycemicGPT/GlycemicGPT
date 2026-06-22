"""Output-side glucose-citation verification (pure core).

The AI-text layer renders the user's glucose data into the prompt in their
preferred unit (``diabetes_context.build_glucose_section`` and the analysis
prompt builders) and instructs the model to answer in that unit. This module
closes the complementary gap on the model *output*: any glucose figure the model
utters in a chat reply, daily brief, or analysis is verified against the user's
real readings, and a figure that does not trace to one is corrected to the right
value or removed -- never passed through as the model wrote it.

The failure mode this defends is the same one the carb verifier
(``meal_citation``) guards (diabettech.com "Five AI Models, Three Users"): models
cite a user's own data with confident, false specifics. For glucose the stakes
are higher -- a wrong glucose number is something a user might act on -- so the
comparison is unit-aware and rounding-tolerant: turning on mmol/L display must
never let a converted-and-rounded figure read as a mismatch (99 mg/dL -> "5.5",
100 mg/dL -> "5.6"), nor let a genuinely wrong number slip through.

Design (mirrors ``meal_citation``):
  * Deterministic and pure -- ``re`` extraction + the shared rounding-tolerant
    band (``core.units.glucose_display_matches``: +/-1 mg/dL or +/-0.1 mmol/L,
    never equality). No second LLM call.
  * The extractor matches a number anchored to glucose by a per-volume unit
    suffix (``mg/dL`` / ``mmol/L``) and excludes the ``1:X`` ISF / carb-ratio
    forms and ISF *rates* ("50 mg/dL per unit"), so a correction-factor figure is
    never mis-flagged as a glucose reading (those are the safety layer's job).
  * Two consumption models share one extraction + match core:
      - rewrite (``verify_glucose_citations``): correct-or-scrub the reply text,
        for the chat handlers and the daily brief -- consistent with the carb
        verifier at the same call sites.
      - flag (``find_glucose_citation_flags``): emit ``FlaggedSuggestion`` records
        for the ``validate_ai_suggestion`` / ``ValidationResult`` path used by the
        correction and meal analyses.
  * Read-only: input is the model text + the canonical mg/dL records, output is a
    rewritten string or a list of flags. A converted value is never persisted;
    the stored record stays integer mg/dL.

The allowed records are the user's real ``GlucoseReading`` values (canonical
mg/dL) for the surface's window plus the rendered aggregates (average, target
bounds) -- the set the model was shown. A cited figure that matches any of them
within the display band traces to real data; anything else is an invention.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from src.core.units import (
    MGDL_PER_MMOL,
    GlucoseUnit,
    format_glucose,
    glucose_display_matches,
    glucose_unit_label,
)
from src.schemas.safety_validation import FlaggedSuggestion, SuggestionType
from src.services.safety_validation import (
    CARB_RATIO_PATTERN,
    ISF_CONTEXT_PATTERN,
    ISF_PATTERN,
)

# ── Extraction regexes ──
# A glucose citation is a number (single value or low-to-high range) immediately
# carrying a per-volume glucose unit. Requiring the ``/dL`` // ``/L`` denominator
# excludes a bare "mg"/"mmol" (the abbreviated ISF suffix) and a carb "g/dL"
# concentration. 1-4 integer digits so a hallucinated out-of-range value
# (e.g. "1200 mg/dL") is still caught and flagged rather than silently skipped;
# optional comma-grouped thousands and an optional decimal written with a dot OR
# a comma -- mmol/L users (and European-locale model output) routinely write
# "6,7 mmol/L", and the whole token must be captured, never half-read as "7".
# ``_to_float`` normalizes the separators.
_NUM = r"\d{1,4}(?:,\d{3})*(?:[.,]\d+)?"
# Range separator: hyphen, en/em dash, or "to". Spaces/tabs only (not ``\s``) so
# it cannot span newlines; a flat alternation with no nested quantifier.
_SEP = r"[ \t]*(?:-|–|—|to)[ \t]*"
# The two display labels, tolerant of incidental spaces around the slash.
_READING_SUFFIX = r"mg\s*/\s*dl|mmol\s*/\s*l"
# ``(?<![\d.])`` keeps the match from starting mid-number; the optional range
# group captures a second endpoint sharing the trailing suffix.
GLUCOSE_VALUE_PATTERN = re.compile(
    rf"(?<![\d.])(?P<low>{_NUM})(?:{_SEP}(?P<high>{_NUM}))?"
    rf"\s*(?P<unit>{_READING_SUFFIX})\b",
    re.IGNORECASE,
)

# An ISF / correction-factor *rate* ("50 mg/dL per unit", "50 mg/dL drop per
# unit", "2.8 mmol/L / u") right after the suffix means the figure is a rate, not
# a reading -- leave it to the correction-factor checks in ``safety_validation``.
# The optional "drop" matches the phrasing the correction-analysis prompt teaches.
_RATE_AFTER = re.compile(
    r"[ \t]*(?:drop[ \t]+)?(?:per[ \t]+unit|/[ \t]*u(?:nit)?\b)", re.IGNORECASE
)

# Any ``1:X`` form (ISF or carb ratio), regardless of a trailing unit, so the
# value after the colon is never treated as a glucose reading.
_ONE_TO_X = re.compile(r"1\s*:\s*\d+(?:\.\d+)?")


@dataclass(frozen=True)
class _Citation:
    """One extracted glucose-figure span (``values`` holds 1 value, or 2 for a
    range), tagged with the unit its suffix named."""

    start: int
    end: int
    values: tuple[float, ...]
    unit: GlucoseUnit
    is_range: bool


@dataclass(frozen=True)
class GlucoseCitationOutcome:
    """PHI-free aggregate result of verifying one model response.

    Only counts and the rewritten text -- never the user's glucose figures -- so
    the choke-point can log it for observability without leaking protected health
    information. Every cited figure lands in exactly one bucket, so
    ``citations_seen == citations_matched + citations_corrected +
    citations_scrubbed``.
    """

    text: str
    citations_seen: int
    citations_matched: int
    citations_corrected: int
    citations_scrubbed: int

    @property
    def changed(self) -> bool:
        return bool(self.citations_corrected or self.citations_scrubbed)


# ── Replacement strings (rewrite model) ──
# A figure with one unambiguous referent (the user's readings collapse to a
# single value) is corrected to that value in the user's unit; otherwise it is
# templated to a non-numeric phrase. The ``*_DET`` variant drops the leading
# article for a span already preceded by a determiner so the rewrite reads
# grammatically.
_SCRUB_TEMPLATE = "a glucose value I can't verify against your readings"
_SCRUB_TEMPLATE_DET = "glucose value I can't verify against your readings"
_DET_BEFORE_RE = re.compile(r"\b(?:a|an|the|your|that|this)\s+$", re.IGNORECASE)
_DET_LOOKBACK = 8


def _unit_from_suffix(matched: str) -> GlucoseUnit:
    """Map a matched suffix or unit token (``"mmol/L"``/``"mmol"``/``"mgdl"``...)
    to its ``GlucoseUnit``."""
    return (
        GlucoseUnit.MMOL
        if matched.strip().lower().startswith("mmol")
        else GlucoseUnit.MGDL
    )


def _to_float(token: str) -> float:
    """Parse a matched number token, treating a comma as either a thousands
    separator (``"1,025"`` -> 1025) or a European decimal point (``"6,7"`` ->
    6.7).

    A comma followed by exactly three digits is a thousands group; a comma
    followed by one or two digits (and no dot present) is a decimal separator.
    Without this, ``"6,7 mmol/L"`` would half-extract as ``7`` and a correct
    citation would read as a mismatch.
    """
    if "." in token:
        return float(token.replace(",", ""))  # commas can only be thousands here
    if re.fullmatch(r"\d{1,4}(?:,\d{3})+", token):
        return float(token.replace(",", ""))  # 1,025 -> 1025
    return float(token.replace(",", "."))  # 6,7 -> 6.7


def verify_glucose_citation(
    spoken_value: float, spoken_unit: str, record_mgdl: int
) -> bool:
    """Whether a single AI-spoken glucose figure matches a stored mg/dL reading.

    The spoken value is in ``spoken_unit`` (``"mgdl"``/``"mmol"`` or a display
    label); the record is canonical mg/dL. Thin wrapper over
    ``core.units.glucose_display_matches`` with the argument order normalized.
    """
    return glucose_display_matches(
        record_mgdl, spoken_value, _unit_from_suffix(spoken_unit)
    )


def _value_matches_any(value: float, unit: GlucoseUnit, records: Sequence[int]) -> bool:
    return any(glucose_display_matches(record, value, unit) for record in records)


def _citation_matches(citation: _Citation, records: Sequence[int]) -> bool:
    """A citation verifies iff every endpoint traces to some allowed reading."""
    return all(
        _value_matches_any(value, citation.unit, records) for value in citation.values
    )


def _excluded_spans(text: str) -> list[tuple[int, int]]:
    """Character spans covering ISF / carb-ratio *figures* (the numeric tokens,
    not the surrounding prose), so a glucose candidate overlapping one (e.g.
    "45 mg/dL" in "correction factor from 50 to 45 mg/dL") is not mis-extracted
    as a reading -- while a genuine reading sharing the sentence ("BG 250 mg/dL,
    move from 50 to 45 mg/dL") is still extracted and verified.

    Bounding each ISF span to its captured number groups (not the whole match) is
    what prevents ``ISF_CONTEXT_PATTERN``'s lazy ``.*?`` from stretching the
    exclusion back over an unrelated reading between the keyword and the clause.
    """
    spans: list[tuple[int, int]] = []
    # ISF patterns capture original (1), suggested (2) and unit (3); exclude only
    # that "N to N unit" figure span.
    for pattern in (ISF_PATTERN, ISF_CONTEXT_PATTERN):
        spans.extend((m.start(1), m.end(3)) for m in pattern.finditer(text))
    # Carb ratio captures the two ratio numbers (no unit group).
    spans.extend((m.start(1), m.end(2)) for m in CARB_RATIO_PATTERN.finditer(text))
    # Any bare ``1:X`` token.
    spans.extend((m.start(), m.end()) for m in _ONE_TO_X.finditer(text))
    return spans


def _is_excluded(start: int, end: int, excluded: list[tuple[int, int]]) -> bool:
    return any(s_start <= start < s_end for s_start, s_end in excluded)


def _extract(text: str) -> list[_Citation]:
    """Return non-overlapping glucose-figure spans, sorted by position.

    Drops candidates that are ISF/carb-ratio figures or ISF rates, then resolves
    overlaps left-to-right so each figure is verified exactly once.
    """
    excluded = _excluded_spans(text)
    candidates: list[_Citation] = []
    for match in GLUCOSE_VALUE_PATTERN.finditer(text):
        if _is_excluded(match.start(), match.end(), excluded):
            continue
        if _RATE_AFTER.match(text, match.end()):
            continue
        unit = _unit_from_suffix(match.group("unit"))
        low = _to_float(match.group("low"))
        high = match.group("high")
        values = (low,) if high is None else (low, _to_float(high))
        candidates.append(
            _Citation(
                start=match.start(),
                end=match.end(),
                values=values,
                unit=unit,
                is_range=high is not None,
            )
        )

    # Resolve overlaps left-to-right: earliest start wins, longer span on a tie.
    candidates.sort(key=lambda c: (c.start, -(c.end - c.start)))
    kept: list[_Citation] = []
    max_end = 0
    for cand in candidates:
        if cand.start < max_end:
            continue
        kept.append(cand)
        max_end = cand.end
    return kept


def _det_before(text: str, start: int) -> bool:
    return bool(_DET_BEFORE_RE.search(text[max(0, start - _DET_LOOKBACK) : start]))


def _scrub_replacement(text: str, start: int) -> str:
    return _SCRUB_TEMPLATE_DET if _det_before(text, start) else _SCRUB_TEMPLATE


def verify_glucose_citations(
    text: str,
    records: Sequence[int],
    unit: GlucoseUnit,
    *,
    referents: Sequence[int] | None = None,
) -> GlucoseCitationOutcome:
    """Verify and rewrite every glucose figure in ``text``.

    A figure is *matched* against ``records`` -- the full set the model was shown
    (the user's readings plus the rendered aggregates: average, target bounds).
    An unverifiable single figure is *corrected* only when there is one
    unambiguous reading to point at: ``referents`` (the user's distinct real
    readings, excluding the padded aggregates so a flat-line user is still a
    single referent; defaults to ``records``) collapses to one value. Otherwise
    it is templated to a non-numeric phrase. The corrected value renders in
    ``unit`` (the user's configured display unit). An empty ``records`` (no data,
    or a fail-closed allow-set) scrubs every figure. Pure; never raises on
    ``str`` input.
    """
    if not text:
        return GlucoseCitationOutcome(text or "", 0, 0, 0, 0)

    citations = _extract(text)
    if not citations:
        return GlucoseCitationOutcome(text, 0, 0, 0, 0)

    referent_pool = set(records if referents is None else referents)
    single_referent = len(referent_pool) == 1
    seen = matched = corrected = scrubbed = 0
    pieces: list[str] = []
    cursor = 0

    for citation in citations:
        seen += 1
        pieces.append(text[cursor : citation.start])

        if _citation_matches(citation, records):
            pieces.append(text[citation.start : citation.end])
            matched += 1
        elif single_referent and not citation.is_range:
            # One reading to point at: correct the misquote rather than blank it.
            pieces.append(format_glucose(next(iter(referent_pool)), unit))
            corrected += 1
        else:
            pieces.append(_scrub_replacement(text, citation.start))
            scrubbed += 1

        cursor = citation.end

    pieces.append(text[cursor:])
    return GlucoseCitationOutcome("".join(pieces), seen, matched, corrected, scrubbed)


def _band_label(unit: GlucoseUnit) -> str:
    return "0.1 mmol/L" if unit == GlucoseUnit.MMOL else "1 mg/dL"


def _display(value: float, unit: GlucoseUnit) -> str:
    """Render a value already expressed in ``unit`` (mmol to one decimal, mg/dL
    as a whole number) -- distinct from ``format_glucose_value``, which converts
    from stored mg/dL."""
    return f"{value:.1f}" if unit == GlucoseUnit.MMOL else f"{value:.0f}"


def _nearest_record(value_mgdl: float, records: Sequence[int]) -> int:
    return min(records, key=lambda record: abs(record - value_mgdl))


def find_glucose_citation_flags(
    text: str, records: Sequence[int], unit: GlucoseUnit
) -> list[FlaggedSuggestion]:
    """Flag every glucose figure in ``text`` that does not trace to ``records``.

    For the ``validate_ai_suggestion`` / ``ValidationResult`` path. Each mismatch
    becomes one ``FlaggedSuggestion`` whose reason is unit-correct: it states the
    spoken value, the nearest reading rendered in the *same* (spoken) unit, and
    the tolerance band. The numeric ``original_value``/``suggested_value`` carry
    the spoken value and the nearest reading, both in canonical mg/dL (matching
    how the ratio/factor flags keep a single unit); ``change_pct`` has no glucose
    meaning and is left at 0 so it is never read as a factor change.
    """
    if not text or not records:
        return []

    flags: list[FlaggedSuggestion] = []
    for citation in _extract(text):
        if _citation_matches(citation, records):
            continue

        spoken = citation.values[0]
        spoken_unit = citation.unit
        spoken_mgdl = (
            spoken * MGDL_PER_MMOL if spoken_unit == GlucoseUnit.MMOL else spoken
        )
        nearest = _nearest_record(spoken_mgdl, records)
        nearest_display = format_glucose(nearest, spoken_unit)
        spoken_text = (
            f"{_display(citation.values[0], spoken_unit)}-"
            f"{_display(citation.values[1], spoken_unit)} {glucose_unit_label(spoken_unit)}"
            if citation.is_range
            else f"{_display(spoken, spoken_unit)} {glucose_unit_label(spoken_unit)}"
        )
        flags.append(
            FlaggedSuggestion(
                suggestion_type=SuggestionType.GLUCOSE_CITATION,
                original_value=float(spoken_mgdl),
                suggested_value=float(nearest),
                change_pct=0.0,
                max_allowed_pct=0.0,
                reason=(
                    f"AI-stated glucose {spoken_text} does not match any logged "
                    f"reading (closest: {nearest_display}; tolerance "
                    f"+/-{_band_label(spoken_unit)})"
                ),
            )
        )
    return flags
