"""Output-side carb-citation verification (pure core).

The meal-intelligence feature surfaces the user's logged meals into the AI's
*input* context as carb ranges (``diabetes_context._format_meal_line``) and
scrubs dosing *language* before it reaches the model. This module closes the
complementary gap on the model *output*: any carb figure the model utters in a
chat reply or daily brief is verified against the same set of stored ranges that
were rendered into the context, and a figure that does not trace to a stored
record is removed -- never passed through as the model wrote it.

The failure mode this defends is well-documented (diabettech.com "Five AI
Models, Three Users"): models cite a user's own data with confident, false
specifics -- up to ~70% of cited values were misattributed (wrong value or wrong
timestamp). Because the model only ever *saw* the rendered ranges, every
legitimate carb figure it can cite traces back to one of them; anything else is
an invention.

Design:
  * Deterministic and pure -- ``re`` + numeric comparison over the (<=10) allowed
    ranges. No second LLM call, no semantic NL understanding.
  * Glucose (mg/dL, g/L, g/dL), insulin (u / units) and time (h, HH:MM) figures
    are out of scope *by construction* -- the extractor only matches a number
    anchored to carbohydrates by an adjacent "carb(ohydrate)" word (a grams unit
    alone is NOT sufficient), and rejects a number qualified as another macro or
    a per-volume glucose concentration.
  * Conservative for safety: an unverifiable carb figure is removed or narrowed,
    never rewritten to a guessed new number, and never turned into a dose. Every
    rewrite carries ``MEAL_ESTIMATE_QUALIFIER`` -- the figure is an AI guess that
    must never drive a dose. We never tell a user a carb estimate is safe to
    bolus from (no "verify before dosing"); it is presented like any other AI
    answer: a guess that can be wrong.

Deliberately scoped-out limitations (documented so a reviewer doesn't mistake
them for bugs):
  * When >=2 meals are logged we template an unverifiable figure to a non-numeric
    phrase rather than guess which meal a bad number meant -- binding a free-text
    number to a specific meal referent would need NL coreference that produces
    more false positives than it prevents.
  * Timestamp misattribution is handled only in the unambiguous single-record
    case (an absolute-date meal cited with a contradicting weekday/"today"); the
    "today/yesterday cannot refer to it" rule relies on the context only
    rendering an absolute date for meals at least ``MEAL_RELATIVE_TIME_MAX_HOURS``
    (48h) old. Full natural-language datetime validation is not attempted.
  * A bare grams weight with no carb word (e.g. "200g of water", "a 90g
    serving") and a bare number with no carb word at all (e.g. a multiplier like
    "twice your usual") are intentionally not extracted -- a grams unit alone is
    too ambiguous to treat as carbs, and pulling every number out of prose would
    scrub legitimate text. A carb amount the model writes with no carb word
    anywhere (just "~70g") is therefore also not caught; in practice the rendered
    context always pairs the figure with "carbs", so the model echoes it too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.vision.carb_contract import MEAL_ESTIMATE_QUALIFIER

# ── Tolerance ──
# A cited figure matches a stored range within a tolerance taken from the STORED
# bound (not the cited value): a wrong number must not earn itself more slack by
# being further off. The tolerance is the larger of an absolute floor (so small
# meals still tolerate honest rounding) and a fraction of the stored high bound.
CARB_TOLERANCE_ABS_G = 3.0
CARB_TOLERANCE_PCT = 0.10
# Guard float representation at the comparison boundary so an exactly-on-edge
# value (e.g. 38.5 vs a computed 38.5) is not lost to rounding.
_FLOAT_EPSILON = 1e-9

# ── Replacement strings ──
# A figure with one unambiguous referent (exactly one logged meal) is corrected
# to that meal's stored range; otherwise the figure is templated to a non-numeric
# phrase. Every form carries ``MEAL_ESTIMATE_QUALIFIER`` -- the figure is an AI
# guess that must never drive a dose. We deliberately do NOT say "verify before
# dosing": telling a user a carb guess is safe to bolus from once checked is the
# exact failure this feature must avoid (see ``_verify_templates_carry_qualifier``).
# The scrub ``*_DET`` variant drops the leading article for a span already
# preceded by a determiner ("a", "your", "that"...) so the rewrite reads
# grammatically; "carb amount" (consonant onset) keeps "a"/"an" agreement.
SCRUB_TEMPLATE = f"a carb amount I can't verify ({MEAL_ESTIMATE_QUALIFIER})"
SCRUB_TEMPLATE_DET = f"carb amount I can't verify ({MEAL_ESTIMATE_QUALIFIER})"
CORRECT_TEMPLATE = f"~{{low:g}}-{{high:g}}g carbs ({MEAL_ESTIMATE_QUALIFIER})"


@dataclass(frozen=True)
class AllowedCarb:
    """One stored carb range the model was allowed to cite.

    ``low``/``high`` are exactly what ``diabetes_context._meal_carb_range``
    returned for the record, so the user's corrected values are preferred by
    construction (AC3). ``when`` is the same ``[when]`` token the context
    rendered ("3h ago" / "Mon 19:30") and is used only by the single-record
    timestamp guard.
    """

    low: float
    high: float
    when: str


@dataclass(frozen=True)
class CitationOutcome:
    """PHI-free aggregate result of verifying one model response.

    Only counts and the rewritten text -- never the user's figures or food
    descriptions -- so the choke-point can log it for observability (AC6)
    without leaking protected health information.

    Every cited figure lands in exactly one outcome bucket, so
    ``citations_seen == citations_matched + citations_corrected +
    citations_scrubbed``. ``timestamp_mismatches`` is a *reason* sub-tag, not a
    fourth bucket: it counts how many of the scrubbed figures were removed
    because a stated day contradicted the meal's date.
    """

    text: str
    citations_seen: int
    citations_matched: int
    citations_corrected: int
    citations_scrubbed: int
    timestamp_mismatches: int

    @property
    def changed(self) -> bool:
        return bool(
            self.citations_corrected
            or self.citations_scrubbed
            or self.timestamp_mismatches
        )


@dataclass(frozen=True)
class _Citation:
    """One extracted carb-figure span (``low == high`` for a single value)."""

    start: int
    end: int
    low: float
    high: float
    is_range: bool


# ── Extraction regexes ──
# A carb figure is a number (single value or range) ANCHORED to carbohydrates by
# a carb word -- either after it ("200g carbs", "60-80g carbs") or before it
# ("Carbs: 200", "net carbs around 200"). A grams unit ALONE is not sufficient: a
# bare "200g" with no carb word is an ambiguous weight (water, a serving size,
# body weight) and is left untouched, so the verifier never corrupts legitimate
# non-carb text. Requiring the carb word also covers every form in which a model
# attributes a carb amount to a meal, including the leading-label phrasings the
# trailing-only anchor used to miss.

# A number: 1-9 leading digits (BOUNDED so a pathological all-digits run cannot
# drive super-linear backtracking), optional comma-grouped thousands, optional
# decimal. Commas are stripped before ``float`` so "1,025" parses as 1025 -- not
# silently split into a passing "025".
_NUM = r"\d{1,9}(?:,\d{3})*(?:\.\d+)?"
# Range separator: hyphen, en/em dash, or the word "to". Spaces only (not \s) so
# it cannot span newlines; a flat literal alternation -- no nested quantifier, no
# catastrophic backtracking.
_SEP = r"[ \t]*(?:-|–|—|to)[ \t]*"
# Optional approximator, consumed into the span so a rewrite leaves no dangling
# "about"/"~". The trailing whitespace is INSIDE the optional group so that, when
# no approximator is present, the match starts at the digit -- otherwise a bare
# "Ng" would swallow the space that separates it from the preceding word and a
# rewrite would fuse them ("a 70g" -> "arecorded ...").
_APPROX = r"(?:(?:~|about|approximately|around|roughly|≈)[ \t]*)?"
# Grams unit, optional on each numeric bound. The look-behind rejects the g in
# mg/kg/mcg/a word; the trailing \b rejects "gm"/"gh"; the look-ahead rejects
# "g/L"/"g/dL" (a glucose concentration, not a carb mass).
_GRAMS = r"(?<![A-Za-z])g(?:ram(?:s)?)?\b(?!\s*/\s*[A-Za-z])"
_OPT_GRAMS = rf"(?:[ \t]*{_GRAMS})?"
# Carb word as a standalone noun.
_CARBWORD = r"carb(?:ohydrate)?s?\b"
# Number(s) with a grams unit optional on EITHER bound, so a unit repeated on
# both ends of a range ("200g-210g") collapses to one span instead of two. The
# low bound may also carry its own carb word ("200 carbs to 210 carbs") -- the
# range separator excludes "and", so two distinct citations ("40g carbs and 90g
# carbs") are still parsed separately, not fused into one range.
_NUMBER_GROUP = (
    rf"(?P<low>{_NUM}){_OPT_GRAMS}(?:[ \t]+{_CARBWORD})?"
    rf"(?:{_SEP}(?P<high>{_NUM}){_OPT_GRAMS})?"
)
# Separator between a number and a trailing carb word: whitespace (optionally
# "of"), or a hyphen ("120-carb"). An optional trailing "grams" is consumed too
# so "200 carbohydrate grams" leaves no dangling unit after the rewrite.
_TRAIL_SEP = r"(?:[ \t]+(?:of[ \t]+)?|[ \t]*-[ \t]*)"
_OPT_TRAILING_GRAMS = r"(?:[ \t]+g(?:ram(?:s)?)?\b)?"

# Carb word AFTER the number ("200 carbs", "60-80g carbs", "70 g of carbs").
_TRAILING_RE = re.compile(
    rf"{_APPROX}{_NUMBER_GROUP}{_TRAIL_SEP}{_CARBWORD}{_OPT_TRAILING_GRAMS}",
    re.IGNORECASE,
)
# Carb word BEFORE the number, linked by a short in-clause run of non-digit text
# ("Carbs: 200", "net carbs around 200", "carbohydrate count: 200"). The
# look-behind keeps it off the tail of a hyphenated adjective ("low-carb") or a
# longer word; the bounded ``filler`` window keeps it from reaching across a
# clause to an unrelated number.
_LEADING_RE = re.compile(
    rf"(?<![A-Za-z-]){_CARBWORD}(?P<filler>[^\d\n.;!?]{{0,14}}?){_APPROX}{_NUMBER_GROUP}",
    re.IGNORECASE,
)

# Right after the matched number, these mark it as a NON-carb quantity (another
# macro, a glucose/insulin reading, a per-volume concentration). Used to reject a
# carb word that "reaches over" a real carb figure onto an adjacent non-carb
# number ("...of carbs, 25g protein"; "carbs ok, bg 120 mg/dL").
_NONCARB_AFTER = re.compile(
    r"[ \t]*(?:"
    r"(?:of[ \t]+)?(?:protein|fats?|fib(?:er|re)|sugars?|sodium|potassium|"
    r"cholesterol|calories|kcal|glucose|sugar)\b"
    r"|/?[ \t]*d?l\b|mg\b|mmol\b|%|units?\b|u\b"
    r")",
    re.IGNORECASE,
)
# A non-carb quantity word INSIDE a leading anchor's filler gap means the carb
# word and the number aren't actually about each other ("carbs fine, bg 120").
_NONCARB_IN_FILLER = re.compile(
    r"\b(?:bg|glucose|sugar|protein|fats?|fib(?:er|re)|sodium|insulin|iob|"
    r"mg|mmol)\b",
    re.IGNORECASE,
)

# Weekday / relative-day tokens for the single-record timestamp guard.
_DAY_TOKEN_RE = re.compile(
    r"\b(today|yesterday|mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|"
    r"thu(?:rs?|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)
_WEEKDAY_PREFIXES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_TOKEN_WINDOW = 24

# A span already preceded by a determiner gets the article-free replacement form.
_DET_BEFORE_RE = re.compile(r"\b(?:a|an|the|your|that|this)\s+$", re.IGNORECASE)
_DET_LOOKBACK = 8


def _to_float(num_text: str) -> float:
    return float(num_text.replace(",", ""))


def _tolerance(stored_high: float) -> float:
    return max(CARB_TOLERANCE_ABS_G, CARB_TOLERANCE_PCT * stored_high)


def _value_matches(value: float, allowed: AllowedCarb) -> bool:
    tol = _tolerance(allowed.high) + _FLOAT_EPSILON
    return allowed.low - tol <= value <= allowed.high + tol


def _range_matches(low: float, high: float, allowed: AllowedCarb) -> bool:
    # Endpoint proximity in BOTH directions, which also bounds width: a widened
    # ("40-120" vs 60-80) or narrowed ("70-75" vs 60-80) range fails because at
    # least one endpoint drifts past tolerance.
    tol = _tolerance(allowed.high) + _FLOAT_EPSILON
    return abs(low - allowed.low) <= tol and abs(high - allowed.high) <= tol


def _matched_record(
    citation: _Citation, allowed: list[AllowedCarb]
) -> AllowedCarb | None:
    for record in allowed:
        if citation.is_range:
            if _range_matches(citation.low, citation.high, record):
                return record
        elif _value_matches(citation.low, record):
            return record
    return None


def _extract(text: str) -> list[_Citation]:
    """Return non-overlapping carb-figure spans, sorted by position.

    Collects carb-anchored figures (trailing- and leading-anchored), drops any
    whose number is qualified as a non-carb quantity, then resolves overlaps
    left-to-right so each figure is verified exactly once.
    """
    candidates: list[_Citation] = []
    for pattern in (_TRAILING_RE, _LEADING_RE):
        for match in pattern.finditer(text):
            # A macro/unit immediately after the number means it isn't carbs.
            if _NONCARB_AFTER.match(text, match.end()):
                continue
            # A leading anchor whose gap to the number names another quantity
            # ("carbs fine, bg 120") isn't actually a carb citation.
            filler = match.groupdict().get("filler")
            if filler and _NONCARB_IN_FILLER.search(filler):
                continue
            high = match.group("high")
            low_value = _to_float(match.group("low"))
            candidates.append(
                _Citation(
                    start=match.start(),
                    end=match.end(),
                    low=low_value,
                    high=_to_float(high) if high is not None else low_value,
                    is_range=high is not None,
                )
            )

    # Resolve overlaps left-to-right: earliest start wins, and on a tie the
    # longer span wins. A trailing-anchored "70g of carbs" thus claims its carb
    # word before a leading match could reuse it to reach the next number.
    # Candidates are sorted by start, so a span overlaps the kept set iff its
    # start falls before the furthest end kept so far -- an O(n) running-max
    # check rather than scanning every kept span (keeps the pass linear in the
    # citation count for adversarially long output).
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
    return SCRUB_TEMPLATE_DET if _det_before(text, start) else SCRUB_TEMPLATE


def _correct_replacement(text: str, start: int, allowed: AllowedCarb) -> str:
    # The corrected form opens with the range ("~60-80g carbs"), which reads fine
    # after a determiner ("a ~60-80g carbs ..."), so it needs no article-drop
    # variant -- unlike the scrub form, which opens with its own article.
    return CORRECT_TEMPLATE.format(low=allowed.low, high=allowed.high)


def _timestamp_contradicts(
    citation: _Citation, text: str, allowed: AllowedCarb
) -> bool:
    """Whether a value-matched citation names a day the stored meal isn't.

    Only fires for an absolute-dated meal ("Mon 19:30"): a relative token
    ("3h ago") structurally cannot disagree with a weekday/"today" the model
    might mention, so the guard is skipped there to avoid false positives on a
    legitimate "today" near a recent meal.
    """
    when = allowed.when.lower()
    if "ago" in when:  # relative token -> nothing to contradict
        return False
    record_day = when[:3]
    if record_day not in _WEEKDAY_PREFIXES:
        return False
    lo = max(0, citation.start - _DAY_TOKEN_WINDOW)
    hi = min(len(text), citation.end + _DAY_TOKEN_WINDOW)
    match = _DAY_TOKEN_RE.search(text[lo:hi])
    if match is None:
        return False
    token = match.group(1).lower()
    if token in ("today", "yesterday"):
        # An absolute-dated meal is rendered only when it is >= ~2 days old, so
        # "today"/"yesterday" cannot refer to it.
        return True
    return token[:3] != record_day


def verify_carb_citations(text: str, allowed: list[AllowedCarb]) -> CitationOutcome:
    """Verify and rewrite every carb figure in ``text`` against ``allowed``.

    Matched figures are left byte-for-byte unchanged. An unverifiable figure is
    corrected to the stored range when exactly one meal is logged (a single
    unambiguous referent), otherwise templated to a non-numeric phrase. An empty
    ``allowed`` (no meals, or a fail-closed allow-set) scrubs every figure --
    nothing is verifiable, so nothing specific is asserted. Pure; never raises on
    ``str`` input.
    """
    if not text:
        return CitationOutcome(text or "", 0, 0, 0, 0, 0)

    citations = _extract(text)
    if not citations:
        return CitationOutcome(text, 0, 0, 0, 0, 0)

    single_referent = len(allowed) == 1
    seen = matched = corrected = scrubbed = timestamp_mismatches = 0
    pieces: list[str] = []
    cursor = 0

    for citation in citations:
        seen += 1
        pieces.append(text[cursor : citation.start])
        record = _matched_record(citation, allowed)

        if record is not None:
            if single_referent and _timestamp_contradicts(citation, text, allowed[0]):
                # Removed via the scrub template, so it counts as scrubbed; the
                # timestamp counter is the *reason* sub-tag, not a separate
                # outcome, keeping seen == matched + corrected + scrubbed.
                pieces.append(_scrub_replacement(text, citation.start))
                scrubbed += 1
                timestamp_mismatches += 1
            else:
                pieces.append(text[citation.start : citation.end])
                matched += 1
        elif single_referent:
            pieces.append(_correct_replacement(text, citation.start, allowed[0]))
            corrected += 1
        else:
            pieces.append(_scrub_replacement(text, citation.start))
            scrubbed += 1

        cursor = citation.end

    pieces.append(text[cursor:])
    return CitationOutcome(
        "".join(pieces), seen, matched, corrected, scrubbed, timestamp_mismatches
    )


def _verify_templates_carry_qualifier() -> None:
    """Fail fast at import if a replacement template loses its safety framing.

    These strings are emitted verbatim to users in place of an unverified carb
    figure, so a future edit must not (a) drop the "never dose or bolus"
    qualifier or (b) reintroduce the permissive "verify before dosing" phrasing
    that implies it is OK to bolus from a carb guess. ``RuntimeError`` (not
    ``assert``) so the guard survives ``python -O``.
    """
    samples = (
        SCRUB_TEMPLATE,
        SCRUB_TEMPLATE_DET,
        CORRECT_TEMPLATE.format(low=60, high=80),
    )
    for sample in samples:
        if MEAL_ESTIMATE_QUALIFIER not in sample:
            msg = f"citation replacement template missing safety qualifier: {sample!r}"
            raise RuntimeError(msg)
        if "verify before dosing" in sample.lower():
            msg = f"citation replacement template uses permissive dosing language: {sample!r}"
            raise RuntimeError(msg)


_verify_templates_carry_qualifier()
