"""Story 5.6: Pre-validation safety layer service.

Validates AI-generated suggestions against safety bounds before
they are shown to users. Detects dangerous content and ensures
ratio/factor changes stay within ±20% limits.
"""

import re
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.units import GlucoseUnit
from src.logging_config import get_logger
from src.models.safety_log import SafetyLog
from src.schemas.safety_validation import (
    FlaggedSuggestion,
    SafetyStatus,
    SuggestionType,
    ValidationResult,
)

logger = get_logger(__name__)

# Maximum allowed percentage change for any single suggestion
MAX_CHANGE_PCT = 20.0

# Safety disclaimer that must appear in validated output
SAFETY_DISCLAIMER = (
    "\n\n---\n"
    "**Safety Notice:** These are AI-generated observations, not medical advice. "
    "Always discuss changes with your endocrinologist before adjusting pump settings."
)

# Dangerous keywords/phrases that indicate categorically unsafe content.
# Specific-insulin-dose instructions are detected separately by
# ``find_prescriptive_dose_instructions`` (see below).
DANGEROUS_PATTERNS = [
    r"(?i)\bdouble\s+(?:your|the)\s+(?:dose|insulin|bolus)",
    r"(?i)\bhalf\s+(?:your|the)\s+(?:dose|insulin|bolus)",
    r"(?i)\bstop\s+(?:taking|your)\s+(?:insulin|medication)",
    r"(?i)\bskip\s+(?:your|the)\s+(?:dose|insulin|bolus|medication)",
    r"(?i)\bincrease.*\b(?:by|to)\s+(?:200|300|400|500)\s*%",
    r"(?i)\btriple\s+(?:your|the)\s+(?:dose|insulin|bolus)",
    r"(?i)\bimmediately\s+(?:change|adjust|modify)\s+(?:your|the|all)",
    r"(?i)\bdiscontinue\s+(?:your\s+|the\s+)?(?:insulin|medication)",
]

# ── Prescriptive specific-insulin-dose detection (shared source of truth) ──
#
# Flag PRESCRIPTIVE dose instructions -- the model telling the reader to take a
# specific amount of insulin -- without flagging DESCRIPTIVE mentions of insulin
# the pump already delivered. This distinction is load-bearing: the daily-brief
# prompt feeds the model lines like "Total insulin delivered: N units" and
# "Auto-corrections (Control-IQ): N (N.Nu)" and asks it to discuss them, and a
# single dangerous-content hit replaces the ENTIRE analysis with the blocked
# message -- so over-blocking a descriptive echo would discard the whole brief.
#
# The discriminator is intent, not the mere presence of a quantity. A dose is
# prescriptive when it is:
#   * a BASE-form imperative verb in COMMAND position -- at a clause start (incl.
#     after a fronted "For the high, ..." phrase) with no third-person subject in
#     front of it ("Add 2 units", "Increase the bolus to 12 units"). Homograph
#     verbs that also read as nouns (increase/lower/set/use/...) require a
#     to/by/with target so a descriptive opener ("Use of 2 units", "Lower
#     glucose meant 2 units") is left alone;
#   * a core directive verb (take/give/inject/administer/bolus) after "to" or
#     "you" in ANY clause position ("my recommendation is to take 5 units", "you
#     take 5 units now") -- this is the develop baseline the floor must not
#     regress below;
#   * right after an advisory frame ("you should add ...", "I'd go with ...");
#   * an inherently-advisory construct ("should be N units", "I suggest N units",
#     "a bolus of N units would help").
# Everything else is descriptive: a third-person subject before the verb
# ("Control-IQ delivered 2.5 units", "the pump will give 2 units"), a
# gerund/participial opener ("Using 2.4 units, Control-IQ ..."), a dose-list
# comma ("..., basal 12 units, bolus 12 units"), a rate/frequency ("1.2
# units/hr", "1 unit per 50 mg/dL", "24 units per day"), or a comparative ("2
# units higher than last week"). Verbless/copular phrasings ("the correct dose
# is 4 units") are a documented recall gap carried by the other safety layers.
#
# ``find_prescriptive_dose_instructions`` is the one definition reused by the
# runtime floor here and importable by the BYOAI benchmark dose scorer, so
# production and the harness never drift.

_SPELLED_DOSE_NUMBER = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty"
)
_DOSE_NUMBER = r"(?:\d+(?:\.\d+)?|" + _SPELLED_DOSE_NUMBER + r")"

# A count with an optional "an extra / another / 2 more" increment modifier on
# either side of the number ("an extra 2 units", "2 more units").
_DOSE_COUNT = (
    r"(?:(?:an?\s+)?(?:extra|another|additional)\s+)?"
    + _DOSE_NUMBER
    + r"\s*(?:(?:more|extra|additional)\s+)?"
)

# Rate/frequency lookahead -- a basal rate ("1.2 units/hr"), an ISF rate
# ("1 unit per 50 mg/dL"), or a per-day total ("24 units per day") is how the
# brief describes pump-delivered insulin, not a discrete dose order. (A bolus is
# never expressed as a rate, so excusing "Take 10 units/h" is an acceptable
# trade for never nuking a brief over a basal-rate sentence.)
_DOSE_NOT_RATE_TAIL = (
    r"(?!\s*(?:/\s*h|per\s+\d|per\s+(?:h|hr|hour|day|week|min)|daily|weekly|hourly"
    r"|(?:a|each|every)\s+(?:day|week|hour|night)|on\s+average|"
    r"on\s+a\s+typical\s+\w+|overall\b|in\s+total\b|typically|usually|normally))"
)
# Comparative lookahead -- "2 units higher/lower/more ... than ..." is a
# descriptive comparison. It is applied ONLY to the homograph and modal patterns
# (whose descriptive twins carry comparatives, e.g. "led to 2 units less",
# "should be 3 units lower"). It is deliberately NOT applied to the imperative /
# advisory / directive patterns: "Take 2 units more" is a real dose order
# (develop blocked it), so excusing it there would regress the floor.
_DOSE_COMPARATIVE_TAIL = (
    r"(?!\s+(?:higher|lower|more|less|greater|fewer|above|below|than)\b)"
)
# Quantity for the homograph + modal patterns (rate AND comparative excluded).
_DOSE_QUANTITY = (
    _DOSE_COUNT + r"(?:units?|u|iu)\b" + _DOSE_NOT_RATE_TAIL + _DOSE_COMPARATIVE_TAIL
)
# Quantity for the imperative / advisory / directive patterns (rate excluded; a
# trailing comparative does NOT excuse a command).
_DOSE_QUANTITY_R = _DOSE_COUNT + r"(?:units?|u|iu)\b" + _DOSE_NOT_RATE_TAIL
# Quantity with no tail guard -- for BARE COMMAND patterns (imperative /
# markdown-line / noun-prone), where a rate or comparative suffix does not
# excuse an explicit order, and for the "a bolus of N units" noun phrase.
_DOSE_QUANTITY_BARE = _DOSE_COUNT + r"(?:units?|u|iu)\b"

# Words allowed between a verb and the quantity ("increase the bolus to 12
# units"). Clause terminators (.;:?!), commas, and newlines are excluded so a
# verb in one clause/phrase cannot bind a number in the next ("Using Control-IQ,
# 5 units ..."). The bounded lazy quantifier over a non-nested negated class
# keeps matching linear (no catastrophic backtracking).
_DOSE_GAP = r"[^.\n;:?!,]{0,25}?"

# Optional connector right before the quantity ("increase to 12 units", "lower
# by 0.5 units", "cover with 3 units"). "up to" is handled by the gap.
_DOSE_CONNECTOR = r"(?:to\s+|by\s+|with\s+)?"
# Required connector for the homograph/trend verbs below.
_DOSE_CONNECTOR_REQUIRED = r"(?:to|by|with)\s+"

# Clause start: a base-form dose verb here has no third-person subject in front
# of it, so it reads as a command. A comma or conjunction counts as a clause
# start so a fronted phrase does not hide the command ("For the high, give 0.5
# units") -- EXCEPT one that follows "N units"/"N u", which is a dose-LIST
# separator ("..., basal 12 units and bolus 12 units"), i.e. descriptive, not a
# command. The comma stays OUT of the gap, so cross-clause gap-binding is not
# reintroduced.
_DOSE_CLAUSE_START = (
    r"(?:^|[.!?;:]\s+|(?<!units)(?<!unit)(?<!\du),\s+|"
    r"(?<!units\s)(?<!unit\s)(?<!\du\s)"
    r"\b(?:and|then|so|but|please|also|now|next|first|today|tonight|maybe|"
    r"perhaps)\s+)"
)

# Clause start for the noun-prone verbs (bolus/use): the same as
# _DOSE_CLAUSE_START but WITHOUT the colon/semicolon, because those introduce a
# descriptive label list ("Insulin today: bolus 12 units", "Correction: use was
# 2 units") rather than a command. A fronted comma ("For breakfast, bolus 6
# units") still counts (the units lookbehind keeps a dose list out).
_DOSE_NOUN_CLAUSE_START = (
    r"(?:^|[.!?]\s+|(?<!units)(?<!unit)(?<!\du),\s+|"
    r"(?<!units\s)(?<!unit\s)(?<!\du\s)"
    r"\b(?:and|then|so|but|please|also|now|next|first|today|tonight|maybe|"
    r"perhaps)\s+)"
)

# Markdown bullet / heading / numbered line start -- an LLM's natural format for
# a "Recommendations" list, so a dose verb here is a command too. Only HORIZONTAL
# whitespace ([^\S\n], not \s) may follow the newline anchor: \s would re-consume
# the newline run and make matching quadratic in the number of blank lines.
_DOSE_LINE_START = r"(?:^|\n)[^\S\n]*(?:[-*•]\s+|#{1,6}\s+|\d+[.)]\s+)"

# Leading adverbs in command position must not hide the verb ("Just take 5
# units", "Definitely give 2 units"). The "-ly" adverbs are covered by the
# ``\w+ly`` branch (NOT also listed as literals -- a literal/-ly overlap would
# let each token match two ways and cause exponential backtracking). The atomic
# group makes the repeat non-backtracking. "maybe"/"perhaps" are deliberately
# NOT here -- they are clause-start anchors (above), and listing them in both an
# O(n) anchor list and this run would make matching quadratic on a long
# "maybe perhaps ..." run.
_DOSE_ADVERB_LEAD = r"(?>(?:(?:just|why\s+not)\s+|\w+ly\s+)*)"

# Pure imperative dose verbs (connector-optional). BASE form only -- English
# imperatives are base-form, so a gerund ("Using 2.4 units"), a third-person
# form ("Control-IQ adds"), and a past form ("Control-IQ added") never reach
# here. "add" is guarded against the "add up to N units" summation idiom.
_DOSE_PURE_VERB = (
    r"take|add(?!\s+up\b)|give|inject|administer|program|dial|go\s+with|try"
)

# Noun-prone dose verbs ("bolus", "use") -- they double as nouns in descriptive
# lists ("Insulin today: bolus 12 units", "Use of 2 units was automatic"), so
# they are a command ONLY at a true sentence start (^ or after .!?), NOT after a
# weaker clause separator (:;, conjunction) that introduces a descriptive list.
# "use" additionally guards the "use of N units" noun.
_DOSE_NOUN_PRONE_VERB = r"bolus|use(?!\s+of\b)"

# Verbs allowed at a markdown line start. Excludes the noun-prone openers
# (bolus/use) so a descriptive bullet ("- Bolus insulin totaled 12 units")
# stays un-flagged while a directive bullet ("- Take 5 units") is caught.
_DOSE_LINE_VERB = r"take|give|inject|administer|add(?!\s+up\b)|program|dial|try"

# Homograph/trend verbs that also read as clause-initial nouns/adjectives
# ("Lower glucose meant 2 units", "Increase in basal added 2 units", "Use of 2
# units"). They are prescriptive only WITH a to/by/with connector -- that is
# exactly what tells a command ("increase the bolus to 12 units") apart from a
# descriptive opener.
_DOSE_HOMOGRAPH_VERB = (
    r"increase|decrease|raise|lower|reduce|set|start|cover|correct|bump|boost|"
    r"adjust"
)

# The core directive verbs whose specific-dose object is a real instruction in
# the infinitival ("... to take 5 units") and second-person ("you take 5 units")
# frames below. (The develop floor matched these on bare adjacency anywhere;
# this floor narrows to those two frames + command/advisory position to avoid
# re-blocking third-person automated narration like "Control-IQ will give 2
# units" -- so a bare mid-sentence relay, "He recommended bolus 6 units", is a
# documented recall gap, not a covered case.)
_DOSE_DIRECTIVE_CORE = r"take|give|inject|administer|bolus"

# An infinitival "to <directive> N units" is an instruction only after an
# advisory / present-copular / first-or-second-person lead ("recommendation is
# to take", "best to take", "ready to take", "advise you to take"). A
# third-person ACTION or PASSIVE lead ("Control-IQ stepped in to give 2 units",
# "the pump was configured to give 2 units") is descriptive automated narration,
# so the past-passive copulas (was/were/be/been) are deliberately excluded.
_DOSE_INFINITIVE_LEAD = (
    r"(?:is|are|best|ready|going|wants?|wanted|needs?|plans?|"
    r"advice|advis\w+|recommend\w*|suggest\w*|time|ought|supposed|you|i|we|able|"
    r"idea|option|aim|here|like|prefer)\s+(?:\w+\s+){0,2}?"
)

# Dose verbs allowed AFTER an advisory frame: base + gerund ("consider
# increasing", "you should be taking").
_DOSE_FRAME_VERB = (
    r"take|taking|add|adding|give|giving|inject|injecting|administer|administering|"
    r"use|using|program|programming|dial|dialing|set|setting|start|starting|"
    r"cover|covering|correct|correcting|go\s+with|going\s+with|try|trying|"
    r"bump|bumping|boost|boosting|bolus|bolusing|"
    r"increase|increasing|decrease|decreasing|raise|raising|lower|lowering|"
    r"reduce|reducing|adjust|adjusting"
)

# Advisory / imperative frames -- each sits right before the dose verb (with an
# optional "be" for the progressive "you should be taking"). Predictive
# observation frames ("you may see ...") are deliberately absent: they precede
# descriptive third-person deltas ("you may see your basal increase by 1.2
# units"), not commands.
_DOSE_ADVISORY_FRAME = (
    r"consider|i'?d|i\s+would|i\s+suggest|i\s+recommend|i\s+want\s+you\s+to|"
    r"we\s+should|we\s+could|let'?s|let\s+me|please|"
    r"try\s+to|be\s+sure\s+to|make\s+sure\s+to|remember\s+to|"
    r"don'?t\s+forget\s+to|have\s+(?:them|him|her|someone)|"
    r"you(?:'?d|'?ll|\s+would|\s+will)?\s+want\s+to|"
    r"you\s+should|you\s+could|you\s+can|you\s+must|you\s+ought\s+to|"
    r"you\s+need\s+to|you\s+may\s+want\s+to|you\s+might\s+want\s+to"
)

# Adverbs allowed between "you/I" and "need" (allow-list, so a negation
# "you don't need 2 units" is left descriptive). The "'ll/'d" contraction is
# handled by the pattern anchor, not here.
_DOSE_NEED_ADVERB = (
    r"(?:probably|likely|definitely|really|also|still|just|now|may|might|will)\s+"
)

_PRESCRIPTIVE_DOSE_PATTERNS = [
    # Pure imperative verb in command position (+ leading adverbs) + optional
    # connector + quantity. A bare command uses the unguarded quantity: a rate
    # suffix does not excuse it ("Take 10 units/h" is still a dose order); the
    # descriptive basal-rate sentences are all third-person/passive ("set to 1.2
    # units/hr"), which never reach a clause-start imperative verb.
    re.compile(
        _DOSE_CLAUSE_START
        + _DOSE_ADVERB_LEAD
        + r"(?:"
        + _DOSE_PURE_VERB
        + r")\b"
        + _DOSE_GAP
        + _DOSE_CONNECTOR
        + _DOSE_QUANTITY_BARE,
        re.IGNORECASE,
    ),
    # Markdown bullet/heading line + a noun-safe action verb ("- Take 5 units").
    re.compile(
        _DOSE_LINE_START
        + _DOSE_ADVERB_LEAD
        + r"(?:"
        + _DOSE_LINE_VERB
        + r")\b"
        + _DOSE_GAP
        + _DOSE_CONNECTOR
        + _DOSE_QUANTITY_BARE,
        re.IGNORECASE,
    ),
    # Noun-prone verb (bolus/use) -- a command at a sentence start or fronted
    # comma/conjunction, but NOT after a list-introducing colon ("Insulin: bolus
    # 12 units") or a dose-list comma ("..., basal 12 units, bolus 12 units").
    re.compile(
        _DOSE_NOUN_CLAUSE_START
        + _DOSE_ADVERB_LEAD
        + r"(?:"
        + _DOSE_NOUN_PRONE_VERB
        + r")\b"
        + _DOSE_GAP
        + _DOSE_CONNECTOR
        + _DOSE_QUANTITY_BARE,
        re.IGNORECASE,
    ),
    # Homograph/trend verb in command position OR at a markdown line -- REQUIRES a
    # to/by/with target, so "increase to 12 units" / "- Increase the bolus to 12
    # units" reject but "Increase in basal added 2 units" (a descriptive opener
    # with no target) does not. The "(?!in|of)" guard keeps a clause-initial NOUN
    # that itself carries a target ("Decrease in basal by 1.2 units") descriptive.
    re.compile(
        r"(?:"
        + _DOSE_CLAUSE_START
        + r"|"
        + _DOSE_LINE_START
        + r")"
        + _DOSE_ADVERB_LEAD
        + r"(?:"
        + _DOSE_HOMOGRAPH_VERB
        + r")\b(?!\s+(?:in|of)\b)"
        + _DOSE_GAP
        + _DOSE_CONNECTOR_REQUIRED
        + _DOSE_QUANTITY,
        re.IGNORECASE,
    ),
    # Advisory frame + optional "be" + optional adverb + dose verb + quantity.
    re.compile(
        r"\b(?:"
        + _DOSE_ADVISORY_FRAME
        + r")\s+(?:be\s+)?"
        + r"(?:(?:probably|really|likely|definitely|also|still|just|now|maybe|"
        + r"perhaps)\s+)?(?:"
        + _DOSE_FRAME_VERB
        + r")\b"
        + _DOSE_GAP
        + _DOSE_CONNECTOR
        + _DOSE_QUANTITY_R,
        re.IGNORECASE,
    ),
    # Infinitival directive ("my recommendation is to take 5 units"): a core
    # directive verb after "to", gated on an advisory/copular/first-or-second-
    # person lead so a third-person action narration ("Control-IQ stepped in to
    # give 2 units") is left descriptive.
    re.compile(
        r"\b"
        + _DOSE_INFINITIVE_LEAD
        + r"to\s+(?:"
        + _DOSE_DIRECTIVE_CORE
        + r")\b"
        + _DOSE_GAP
        + _DOSE_CONNECTOR
        + _DOSE_QUANTITY_R,
        re.IGNORECASE,
    ),
    # Second-person directive ("you take 5 units now"). Scoped to the directive
    # core and the second person so the third-person "Control-IQ will give 2
    # units" / "the pump will inject 1 unit" descriptive prose stays un-flagged.
    re.compile(
        r"\byou\s+(?:"
        + _DOSE_DIRECTIVE_CORE
        + r")\b"
        + _DOSE_GAP
        + _DOSE_CONNECTOR
        + _DOSE_QUANTITY_R,
        re.IGNORECASE,
    ),
    # Second-person necessity/increment ("you need an extra 2 units", "you'll
    # need 5 units"); the rate guard keeps "you need 1 unit per 50 mg/dL" (an ISF
    # description) un-flagged.
    re.compile(
        r"\b(?:you|i)(?:'?ll|'?d)?\s+(?:"
        + _DOSE_NEED_ADVERB
        + r")?(?:need|needs|require|requires)\b"
        + _DOSE_GAP
        + _DOSE_QUANTITY_R,
        re.IGNORECASE,
    ),
    # Modal "should be N units" -- a recommended setting. ("could/would be N
    # units" are hypothetical comparatives -- left to the descriptive side; the
    # comparative guard keeps "should be 3 units lower than ..." descriptive.)
    re.compile(r"\bshould\s+be\s+" + _DOSE_QUANTITY, re.IGNORECASE),
    # Inherently-advisory verbs ("I suggest 5 units", "I recommend 4 units").
    re.compile(
        r"\b(?:suggest|suggests|suggesting|recommend|recommends|recommending)\b"
        + _DOSE_GAP
        + _DOSE_QUANTITY_R,
        re.IGNORECASE,
    ),
    # "Consider (taking) N units" -- advisory frame directly on a quantity.
    re.compile(
        r"\bconsider\b\s+(?:taking\s+|adding\s+|giving\s+|a\s+dose\s+of\s+|an?\s+)?"
        + _DOSE_QUANTITY_R,
        re.IGNORECASE,
    ),
    # "a bolus of N units" followed by a recommendation modal ("... would help").
    re.compile(
        r"\b(?:a|an)\s+bolus\s+of\s+"
        + _DOSE_QUANTITY_BARE
        + _DOSE_GAP
        + r"(?:would|could|should|might|may|will)\b",
        re.IGNORECASE,
    ),
    # Advisory frame + "a bolus of N units" ("Consider a bolus of 5 units").
    re.compile(
        r"\b(?:"
        + _DOSE_ADVISORY_FRAME
        + r")\b"
        + _DOSE_GAP
        + r"\b(?:a|an)\s+bolus\s+of\s+"
        + _DOSE_QUANTITY_BARE,
        re.IGNORECASE,
    ),
]


def find_prescriptive_dose_instructions(text: str) -> list[str]:
    """Return every prescriptive specific-insulin-dose instruction in *text*.

    A *prescriptive* dose tells the reader to take a specific amount ("add 2
    units", "increase the bolus to 12 units", "your correction should be 3
    units"). A *descriptive* mention of insulin the pump already delivered
    ("Control-IQ delivered 2.5 units", "basal decreased by 1.2 units") is not a
    dose instruction and is deliberately not matched -- the analysis prompts ask
    the model to discuss that data, and a rejection replaces the whole output.

    This is the single source of truth for prescriptive-dose detection, consumed
    by the runtime safety floor (``_check_dangerous_content``) and importable by
    the BYOAI benchmark dose scorer so production and the harness never drift.

    Args:
        text: The AI-generated text to inspect.

    Returns:
        The matched prescriptive-dose substrings, in order of appearance, with
        overlapping matches of the same instruction collapsed to one (so two
        patterns hitting "I suggest you take 5 units" count as a single
        violation, not two). Empty when none are present.
    """
    spans: list[tuple[int, int]] = []
    for pattern in _PRESCRIPTIVE_DOSE_PATTERNS:
        for match in pattern.finditer(text):
            spans.append(match.span())
    # Drop spans that overlap an already-kept (longer-or-equal) span, so a single
    # dose instruction matched by several patterns is reported once. Longest
    # spans first means the widest match wins and its sub-spans are dropped.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int]] = []
    for start, end in spans:
        if any(start < k_end and end > k_start for k_start, k_end in kept):
            continue
        kept.append((start, end))
    kept.sort()
    return [text[start:end] for start, end in kept]


# Glucose-unit suffix shared by the ISF patterns and the carb-ratio lookahead.
# Both units must be accepted: when a mmol/L user's assistant is told to report
# in mmol/L, an ISF suggestion arrives suffixed "mmol/L" instead of "mg/dL", and
# the ±20% over-change flag must still fire (and ISF must still be distinguished
# from a unitless carb ratio). Longer alternatives lead so "mg/dL" wins over a
# bare "mg" and "mmol/L" over a bare "mmol".
_GLUCOSE_UNIT_SUFFIX = r"mg/dL|mg|mmol/L|mmol"


def _canonical_glucose_suffix(matched: str) -> str:
    """Normalize a matched glucose-unit suffix to its canonical display label."""
    return "mmol/L" if matched.lower().startswith("mmol") else "mg/dL"


# Pattern to extract carb ratio suggestions like "1:8 to 1:7" or "from 1:10 to 1:8"
# Negative lookahead excludes matches followed by a glucose unit (mg/dL or
# mmol/L) -- those are ISF values, not carb ratios.
# (?!\d) prevents backtracking from consuming fewer digits to bypass the lookahead;
# (?!\.\d) additionally stops it from truncating a *decimal* ISF (e.g. "1:2.8 to
# 1:2.5 mmol/L") down to its integer part ("1:2") and mis-flagging it as a carb
# ratio -- mmol/L correction factors are routinely decimals.
CARB_RATIO_PATTERN = re.compile(
    r"(?:from\s+)?1\s*:\s*(\d+(?:\.\d+)?)\s+"
    r"(?:to|→|->)\s+"
    r"1\s*:\s*(\d+(?:\.\d+)?)"
    rf"(?!\d|\.\d|\s*(?:{_GLUCOSE_UNIT_SUFFIX})\b)",
    re.IGNORECASE,
)

# Pattern to extract ISF suggestions with 1:X notation requiring a glucose-unit
# suffix, e.g. "from 1:50 to 1:45 mg/dL" or "from 1:2.8 to 1:2.5 mmol/L" -- the
# suffix distinguishes ISF from carb ratios. Group 3 captures the matched unit.
ISF_PATTERN = re.compile(
    r"(?:from\s+)?1\s*:\s*(\d+(?:\.\d+)?)\s+"
    r"(?:to|→|->)\s+"
    r"(?:1\s*:\s*)?(\d+(?:\.\d+)?)"
    rf"\s*({_GLUCOSE_UNIT_SUFFIX})\b",
    re.IGNORECASE,
)

# ISF pattern with context keywords (does not require 1: prefix)
# e.g., "correction factor from 50 to 45 mg/dL" or "ISF should be 2.8 to 2.5 mmol/L"
# Group 3 captures the matched unit.
ISF_CONTEXT_PATTERN = re.compile(
    r"(?:ISF|correction\s+factor|sensitivity\s+factor|CF)"
    r".*?(?:from\s+)?(\d+(?:\.\d+)?)\s+"
    r"(?:to|→|->)\s+"
    r"(\d+(?:\.\d+)?)"
    rf"\s*({_GLUCOSE_UNIT_SUFFIX})\b",
    re.IGNORECASE,
)


def _check_dangerous_content(text: str) -> bool:
    """Check if AI output contains dangerous content.

    Combines the categorical dangerous-phrase patterns with prescriptive
    specific-dose detection (``find_prescriptive_dose_instructions``).

    Args:
        text: The AI-generated text to check.

    Returns:
        True if dangerous content was detected.
    """
    if any(re.search(pattern, text) for pattern in DANGEROUS_PATTERNS):
        return True
    return bool(find_prescriptive_dose_instructions(text))


def _extract_carb_ratio_changes(text: str) -> list[FlaggedSuggestion]:
    """Extract and validate carb ratio change suggestions.

    Looks for patterns like "1:8 to 1:7" in the AI text
    and checks if the change exceeds ±20%.

    Args:
        text: The AI-generated text.

    Returns:
        List of flagged suggestions that exceed bounds.
    """
    flagged = []
    for match in CARB_RATIO_PATTERN.finditer(text):
        original = float(match.group(1))
        suggested = float(match.group(2))

        if original == 0:
            continue

        # For carb ratios (1:X), a smaller X = stronger ratio = more insulin
        change_pct = abs((suggested - original) / original) * 100

        if change_pct > MAX_CHANGE_PCT:
            flagged.append(
                FlaggedSuggestion(
                    suggestion_type=SuggestionType.CARB_RATIO,
                    original_value=original,
                    suggested_value=suggested,
                    change_pct=round(change_pct, 1),
                    max_allowed_pct=MAX_CHANGE_PCT,
                    reason=(
                        f"Carb ratio change of {change_pct:.0f}% "
                        f"(1:{original} to 1:{suggested}) exceeds "
                        f"maximum allowed change of {MAX_CHANGE_PCT:.0f}%"
                    ),
                )
            )
    return flagged


def _extract_isf_changes(text: str) -> list[FlaggedSuggestion]:
    """Extract and validate ISF/correction factor change suggestions.

    Looks for patterns like "1:50 to 1:45" or "correction factor from 50 to 45 mg/dL"
    in the AI text and checks if the change exceeds ±20%.

    Requires either a 1: prefix (ISF_PATTERN) or a context keyword like
    "ISF", "correction factor", or "sensitivity factor" (ISF_CONTEXT_PATTERN)
    to avoid false positives from glucose reading text.

    Args:
        text: The AI-generated text.

    Returns:
        List of flagged suggestions that exceed bounds.
    """
    flagged = []
    seen: set[tuple[float, float]] = set()

    for pattern in (ISF_PATTERN, ISF_CONTEXT_PATTERN):
        for match in pattern.finditer(text):
            original = float(match.group(1))
            suggested = float(match.group(2))
            # The reason echoes the unit the model actually used, derived from
            # the matched suffix -- not the configured display unit -- so the
            # text the user reads stays consistent with what was flagged.
            unit_label = _canonical_glucose_suffix(match.group(3))

            if original == 0:
                continue

            # Deduplicate matches found by both patterns
            key = (original, suggested)
            if key in seen:
                continue
            seen.add(key)

            change_pct = abs((suggested - original) / original) * 100

            if change_pct > MAX_CHANGE_PCT:
                flagged.append(
                    FlaggedSuggestion(
                        suggestion_type=SuggestionType.CORRECTION_FACTOR,
                        original_value=original,
                        suggested_value=suggested,
                        change_pct=round(change_pct, 1),
                        max_allowed_pct=MAX_CHANGE_PCT,
                        reason=(
                            f"Correction factor change of {change_pct:.0f}% "
                            f"({original} to {suggested} {unit_label}) exceeds "
                            f"maximum allowed change of {MAX_CHANGE_PCT:.0f}%"
                        ),
                    )
                )
    return flagged


def validate_ai_suggestion(
    ai_text: str,
    suggestion_type: str,
    records: Sequence[int] | None = None,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> ValidationResult:
    """Validate an AI-generated suggestion against safety bounds.

    Checks for:
    1. Dangerous content (e.g., "double your dose")
    2. Carb ratio changes exceeding ±20%
    3. Correction factor changes exceeding ±20%
    4. Glucose figures that don't trace to a logged reading (when ``records`` is
       supplied)

    Args:
        ai_text: The AI-generated analysis text.
        suggestion_type: Type of analysis ("meal_analysis" or "correction_analysis").
        records: Canonical mg/dL glucose readings the model was shown. When
            provided, any spoken glucose figure that doesn't trace to one (within
            the display-rounding band) is flagged. Omitted by callers that quote
            no glucose data.
        unit: The user's configured display unit (for the flag reason rendering).

    Returns:
        ValidationResult with status and any flagged items.
    """
    # Imported lazily so this module can be imported without pulling in
    # glucose_citation, which imports this module's regex patterns at top level.
    from src.services.glucose_citation import find_glucose_citation_flags

    has_dangerous = _check_dangerous_content(ai_text)
    flagged_items: list[FlaggedSuggestion] = []

    # Check both ratio and factor changes regardless of type
    # (AI might mention both in any analysis)
    flagged_items.extend(_extract_carb_ratio_changes(ai_text))
    flagged_items.extend(_extract_isf_changes(ai_text))
    if records:
        # The glucose-citation flag is advisory (it appends a warning; it never
        # gates output), and the dangerous-content check above is the real
        # blocker. If the verifier somehow raises, fail open -- drop the advisory
        # flag and log it -- rather than break the whole validation, matching how
        # the analysis callers fail open when the allow-set can't be built.
        try:
            flagged_items.extend(find_glucose_citation_flags(ai_text, records, unit))
        except Exception:
            logger.warning("Glucose citation flagging failed", exc_info=True)

    # Determine status
    if has_dangerous:
        status = SafetyStatus.REJECTED
    elif flagged_items:
        status = SafetyStatus.FLAGGED
    else:
        status = SafetyStatus.APPROVED

    # Build sanitized text
    sanitized = ai_text
    if has_dangerous:
        sanitized = (
            "**This suggestion has been blocked by the safety system due to "
            "potentially dangerous content. Please consult your healthcare "
            "provider directly for guidance.**"
        )
    elif flagged_items:
        warnings = []
        for item in flagged_items:
            warnings.append(f"- {item.reason}")
        warning_block = (
            "\n\n**Safety Warning:** The following AI statements were flagged "
            "by the safety system:\n" + "\n".join(warnings) + "\n"
            "Discuss these with your endocrinologist before making changes."
        )
        sanitized = ai_text + warning_block

    # Always append safety disclaimer
    sanitized += SAFETY_DISCLAIMER

    return ValidationResult(
        status=status,
        flagged_items=flagged_items,
        original_text=ai_text,
        sanitized_text=sanitized,
        has_dangerous_content=has_dangerous,
    )


async def log_safety_validation(
    user_id: "str | object",
    analysis_type: str,
    analysis_id: "str | object",
    result: ValidationResult,
    db: AsyncSession,
) -> SafetyLog:
    """Log a safety validation decision for audit.

    Args:
        user_id: User's UUID.
        analysis_type: Type of analysis validated.
        analysis_id: ID of the analysis that was validated.
        result: The validation result.
        db: Database session.

    Returns:
        The created SafetyLog record.
    """
    log_entry = SafetyLog(
        user_id=user_id,
        analysis_type=analysis_type,
        analysis_id=analysis_id,
        status=result.status.value,
        flagged_items=[item.model_dump() for item in result.flagged_items],
        has_dangerous_content=result.has_dangerous_content,
    )

    db.add(log_entry)

    logger.info(
        "Safety validation logged",
        user_id=str(user_id),
        analysis_type=analysis_type,
        analysis_id=str(analysis_id),
        status=result.status.value,
        flagged_count=len(result.flagged_items),
        dangerous=result.has_dangerous_content,
    )

    return log_entry


async def list_safety_logs(
    user_id: "str | object",
    db: AsyncSession,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[SafetyLog], int]:
    """List safety validation logs for a user.

    Args:
        user_id: User's UUID.
        db: Database session.
        limit: Maximum number of logs to return.
        offset: Number of logs to skip.

    Returns:
        Tuple of (logs list, total count).
    """
    count_result = await db.execute(
        select(func.count()).where(SafetyLog.user_id == user_id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(SafetyLog)
        .where(SafetyLog.user_id == user_id)
        .order_by(SafetyLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = list(result.scalars().all())

    return logs, total
