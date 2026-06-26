"""Story 5.6: Tests for pre-validation safety layer."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.core.units import GlucoseUnit
from src.main import app
from src.schemas.safety_validation import SafetyStatus, SuggestionType
from src.services.safety_validation import (
    _check_dangerous_content,
    _extract_carb_ratio_changes,
    _extract_isf_changes,
    find_prescriptive_dose_instructions,
    validate_ai_suggestion,
)


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client: AsyncClient) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email("safety")
    password = "SecurePass123"

    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )

    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    return login_response.cookies.get(settings.jwt_cookie_name)


class TestCheckDangerousContent:
    """Tests for _check_dangerous_content."""

    def test_double_dose_detected(self):
        """Test that 'double your dose' is flagged."""
        assert _check_dangerous_content("You should double your dose immediately")

    def test_half_dose_detected(self):
        """Test that 'half your dose' is flagged."""
        assert _check_dangerous_content("Try to half your insulin amount")

    def test_stop_insulin_detected(self):
        """Test that 'stop taking insulin' is flagged."""
        assert _check_dangerous_content("Stop taking insulin for a day")

    def test_skip_dose_detected(self):
        """Test that 'skip your dose' is flagged."""
        assert _check_dangerous_content("Skip your bolus tonight")

    def test_triple_dose_detected(self):
        """Test that 'triple your dose' is flagged."""
        assert _check_dangerous_content("Triple your bolus for this meal")

    def test_immediately_change_detected(self):
        """Test that 'immediately change your' is flagged."""
        assert _check_dangerous_content(
            "Immediately change your carb ratios across all periods"
        )

    def test_safe_text_not_flagged(self):
        """Test that normal suggestion text is not flagged."""
        safe_text = (
            "Consider discussing a slightly stronger breakfast carb ratio "
            "with your endocrinologist, such as moving from 1:8 to 1:7."
        )
        assert not _check_dangerous_content(safe_text)

    def test_case_insensitive(self):
        """Test that dangerous content detection is case-insensitive."""
        assert _check_dangerous_content("DOUBLE YOUR DOSE")
        assert _check_dangerous_content("Double Your Insulin")

    def test_large_percentage_increase_detected(self):
        """Test that 'increase by 200%' is flagged."""
        assert _check_dangerous_content("Increase your bolus by 200%")

    def test_discontinue_insulin_detected(self):
        """Test that 'discontinue insulin' is flagged."""
        assert _check_dangerous_content("Discontinue your insulin regimen")

    def test_specific_dose_instruction_detected(self):
        """Test that specific dose instructions are flagged."""
        assert _check_dangerous_content("Take 10 units before your meal")
        assert _check_dangerous_content("Bolus 15 units now")

    @pytest.mark.parametrize(
        "text",
        [
            # Behavior-contract "must REJECT" column (prescriptive intent).
            "You should add 2 units at breakfast.",
            "I suggest 5 units of rapid-acting insulin.",
            "Your correction should be 3 units.",
            "Increase the bolus to 12 units.",
            "Set your bolus to 8 units.",
            "Take six units before dinner.",
            "Give 0.5 units for the correction.",
            # Recall additions: spelled-out past ten, an optional modifier slot
            # before the unit, and the previously-missing directive verbs.
            "Take twelve units.",
            "Add 2 more units.",
            "You need an extra 2 units.",
            "I'd go with 5 units.",
            "program 4 units before your meal.",
            "use 2 units to correct that high",
            "dial up to 8 units",
            # Trend verb with a target, or an advisory/imperative frame.
            "increase to 12 units",
            "decrease the basal to 1.2 units",
            "Consider increasing by 2 units.",
            "Bump it up by 3 units.",
            # Imperative trend verb + a "by N units" delta at a clause start
            # (command position, no third-person subject) -- a real dose order.
            "Increase your bolus by 2 units at breakfast.",
            "Lower your basal by 0.5 units tonight.",
            "Increase by 2 units.",
            "Reduce by 3 units.",
            # Directive verbs natural to the meal/correction surfaces.
            "Start with 4 units and adjust from there.",
            "Cover that meal with 3 units.",
            "Correct with 2 units.",
            # Bolus phrasings beyond the bare imperative.
            "Bolus an additional 2 units now.",
            "A bolus of 5 units would help here.",
            "Consider a bolus of 5 units.",
            # Fronted-clause imperatives (a comma/conditional before the verb
            # must not hide the command).
            "For the high, give 0.5 units.",
            "If high, increase by 3 units.",
            "At lunch, add 3 units.",
            "Before bed, take 2 units.",
            "Next time, take 5 units to cover that meal.",
            "Maybe try 5 units.",
            # Infinitive / progressive advisory frames.
            "Be sure to take 4 units.",
            "Make sure to take 4 units.",
            "Remember to inject 3 units.",
            "Don't forget to take 5 units.",
            "I want you to bolus 10 units.",
            "You'll want to give 2 units.",
            "You'd want to take 5 units.",
            "Have them inject 5 units.",
            "You should be taking 5 units before dinner.",
            # Advisory frame directly on a quantity, and adverbs before "need".
            "Consider 5 units before dinner.",
            "Consider an extra 2 units before lunch.",
            "You probably need 2 more units overnight.",
            "You definitely need 3 units now.",
            # Infinitival + second-person directives: a core directive verb
            # (take/give/inject/administer/bolus) after "to" or "you", in any
            # clause position. develop caught these via bare "take N units"
            # adjacency; the precision rewrite must not regress below it.
            "My recommendation is to take 5 units",
            "The plan is to give 4 units",
            "It is best to take 3 units",
            "I advise you to take 4 units",
            "Be ready to take 6 units",
            "You take 5 units now",
            # A comma after a fronted phrase is a clause start (command); a comma
            # in a dose list is not (see the descriptive matrix).
            "For breakfast, bolus 6 units.",
            # A trailing comparative does not excuse an imperative/advisory order
            # ("Take 2 units more" is a real dose-increase; develop blocked it).
            "Take 2 units more for breakfast.",
            "For dinner, give 3 units more.",
            "You should take 2 units more.",
            "I suggest 5 units more.",
            # An adverb between an advisory frame and the verb still rejects.
            "You should really take 4 units.",
            "I'd probably give 2 units.",
            # A leading adverb in command position must not hide the verb.
            "Just take 5 units to correct that high.",
            "Simply take 5 units.",
            "Why not take 5 units.",
            # Markdown bullets / headings / numbered lines (the brief's own
            # format) are command positions for action AND homograph/trend verbs.
            "- Take 5 units at breakfast",
            "* Give 0.5 units",
            "## Add 2 units",
            "1. Take 6 units",
            "- Increase the bolus to 12 units.",
            "- Set your bolus to 8 units.",
            "## Increase to 12 units.",
            # The "you'll/i'll need N units" contraction.
            "You'll need 5 units to cover this meal.",
            "I'll need 5 units.",
            # A bare imperative dose with a stray hourly-rate suffix is still an
            # order (a bolus is never a rate); only a third-person/passive
            # basal-rate sentence is excused (see the descriptive matrix).
            "Take 10 units/h",
            "Bolus 6 units/h",
            # Other prescriptive phrasings.
            "You may need an extra 2 units.",
            "Try 6 units next time.",
            "I recommend 4 units.",
            "administer 3 units now",
            # Original imperative cases (must still reject).
            "Take 10 units before your meal",
            "Bolus 15 units now",
        ],
    )
    def test_prescriptive_specific_dose_detected(self, text):
        """Specific insulin doses must be flagged regardless of the verb or
        phrasing -- not only the imperative 'take/bolus/inject/give N units'."""
        assert _check_dangerous_content(text)

    @pytest.mark.parametrize(
        "text",
        [
            # Behavior-contract "must APPROVE" column: descriptive mentions of
            # insulin the pump already delivered are NOT dosing instructions and
            # must stay un-flagged. The whole reason this fix isn't merge-ready
            # without it -- a rejection replaces the ENTIRE analysis. Every row
            # below is over-blocked by the pre-tightening patterns (regression
            # proof: revert the tightening and these fail again).
            "Control-IQ delivered 2.5 units of automated correction overnight.",
            "Total insulin delivered: 24 units.",
            "Your basal decreased by 1.2 units overnight.",
            "Auto-corrections totaled another 2.3 units.",
            "Your average breakfast bolus was 6 units.",
            "Automated corrections totaled 3.2 units.",
            "Sensor glucose averaged 154 mg/dL.",
            "You logged 10 boluses across 5 meals.",
            # Precision case: a third-person subject delivering an "extra"
            # amount is descriptive, not a "take an extra N units" order.
            "The pump delivered an extra 2 units overnight.",
            # Past-tense / third-person deltas the brief routinely emits.
            "Your total daily dose is around 24 units.",
            "Your last bolus delivered 4 units automatically.",
            "Your average bolus increased by 2 units this week.",
            "You needed 2 units more yesterday than the day before.",
            "Your basal was lowered by 1 unit overnight.",
            "Your dose increased to 12 units last month.",
            "The pump injected 4 units automatically.",
            "Auto-corrections added 2.3 units overnight.",
            # Advisory-frame boundary: a present-tense delta with no advisory
            # cue and a third-person subject stays descriptive.
            "Your basal decreases by 0.1 units overnight.",
            # Predictive second-person observation over a third-person pump delta
            # ("you may SEE your basal increase ...") is descriptive, not a dose.
            "You may see your basal increase by 1.2 units overnight as Control-IQ adjusts.",
            "You could see corrections add up to 2 units.",
            # ISF sensitivity descriptions ("1 unit per N mg/dL") are a rate, not
            # a discrete dose -- the correction-analysis prompt asks for exactly
            # this phrasing.
            "On average you need about 1 unit per 50 mg/dL drop.",
            "It takes about 1 unit to drop your glucose 50 mg/dL.",
            # Habitual present-tense totals ("~24 units per day") describe, not
            # order, insulin.
            "On average you take about 24 units per day.",
            "You typically take around 24 units daily.",
            # Phrasal "add(s) up to N units" is summation; a third-person subject
            # or a sentence-initial noun/participle is descriptive.
            "Auto-corrections add up to 2 units across the afternoon.",
            "Your bolus insulin adds up to 24 units across the day.",
            "Using Control-IQ, 5 units were delivered overnight.",
            "Increases of 2 units were observed overnight.",
            # Gerund/participial openers are descriptive, not commands -- this is
            # exactly the Control-IQ prose the brief prompt asks the model for.
            "Correcting that high took 3 units automatically.",
            "Increasing basal earlier delivered 2 units more overnight.",
            "Lower basal activity led to 2 units less delivery overnight.",
            # Homograph verbs used as a clause-initial noun/adjective (no
            # to/by/with target) are descriptive, not a command.
            "Lower glucose meant only 2 units were needed.",
            "Start of the day saw 2 units delivered as a correction.",
            "Increase in basal added 2 units overnight.",
            "Use of 2 units of correction was automatic.",
            "Cover for that meal was 3 units of bolus.",
            "Use of Control-IQ delivered 2 units automatically.",
            # A comma in a dose LIST is a separator, not a command boundary.
            "Total daily dose: 24 units, basal 12 units, bolus 12 units.",
            # Comparative / hypothetical modals describe a figure, not an order.
            "The total could be 5 units higher than last week.",
            "That would be 24 units more than usual.",
            "Your bolus could be 5 units higher than usual.",
            "Your basal should be 3 units lower than last week.",
            "Your total daily dose could be 24 units on a typical day.",
            # A negated necessity is reassuring, not a dose order.
            "You don't need 2 units to correct that.",
            # Third-person future automated delivery (proves no blunt directive
            # adjacency restore): "will give/inject" is descriptive.
            "Control-IQ will give 2 units automatically.",
            "The pump will inject 1 unit per hour.",
            # Infinitival after a third-person ACTION lead is automated narration
            # ("stepped in to give"), not an instruction -- the daily-brief
            # prompt explicitly asks the model to narrate Control-IQ this way.
            "Control-IQ stepped in to give 2 units of automated correction.",
            "The pump kicked in to give 1.5 units.",
            "The system intervened to administer 0.8 units.",
            # Homograph NOUN that itself carries a by/to figure ("Decrease in
            # basal by 1.2 units") is descriptive, not a command.
            "Decrease in basal by 1.2 units occurred overnight.",
            "Increase in basal to 2 units happened automatically.",
            # A conjunction in a dose list is a separator, not a command
            # boundary ("...12 units and bolus 12 units").
            (
                "Your insulin was split fairly evenly today: basal 12 units "
                "and bolus 12 units, for 24 units total."
            ),
            # A third-person PASSIVE infinitival is automated narration.
            "The pump was configured to give 2 units.",
            "Control-IQ was programmed to give 2 units.",
            # A habitual descriptive total (no standing-order interval) is not an
            # order ("on a typical day ... overall").
            "On a typical day you take about 24 units overall, which matches today.",
            # A noun-opener bullet line stays descriptive.
            "- Bolus insulin totaled 12 units overnight.",
            # A colon-introduced dose breakdown is a descriptive label list, even
            # when an item opens with the noun "bolus"/"use".
            "Insulin delivered today: bolus 12 units, basal 12 units.",
            "Correction insulin: use was 2 units overnight.",
            # Habitual totals with a frequency interval ("a day"/"each day") or a
            # trailing "typically" are descriptive, not a standing order.
            "You take 24 units a day.",
            "You take 24 units each day.",
            "For breakfast you take 6 units typically.",
        ],
    )
    def test_descriptive_insulin_mentions_not_flagged(self, text):
        assert not _check_dangerous_content(text)

    @pytest.mark.parametrize(
        "text",
        [
            # Basal RATES (units/hr) are not discrete doses -- descriptive.
            "Your basal was set to 1.2 units/hr overnight.",
            "Set at 1.2 units per hour, your basal ran steady.",
            "Basal delivery (estimated): 12.4u.",
            "Auto-corrections (Control-IQ): 3 (2.4u).",
        ],
    )
    def test_basal_rate_and_brief_lines_not_flagged(self, text):
        """The daily-brief prompt's own structured lines and basal-rate phrasing
        must not trip the dose floor."""
        assert not _check_dangerous_content(text)

    def test_full_descriptive_brief_paragraph_not_rejected(self):
        """A realistic multi-sentence brief whose sentences OPEN with gerund/base
        verbs describing Control-IQ's automated insulin must survive intact -- a
        single false hit anywhere replaces the whole brief."""
        brief = (
            "Overnight your glucose held steady in range. Using 2.4 units of "
            "automated correction, Control-IQ smoothed out a small rise around "
            "3am. Covering breakfast required 6 units of bolus insulin, which "
            "landed you back in range by mid-morning. Total insulin delivered: "
            "24 units."
        )
        result = validate_ai_suggestion(brief, "daily_brief")
        assert result.status == SafetyStatus.APPROVED
        assert "blocked by the safety system" not in result.sanitized_text

    @pytest.mark.parametrize(
        "text",
        [
            # The literal lines daily_brief.py feeds the model (it then asks the
            # model to discuss them) must never trip the floor, so no future
            # tightening can re-nuke the brief.
            "Total insulin delivered: 24 units.",
            "Manual boluses: 3 (4.2u).",
            "Manual corrections: 2 (1.5u).",
            "Auto-corrections (Control-IQ): 4 (3.1u).",
            "Basal delivery (estimated): 12.4u.",
            # Third-person future automated delivery must stay descriptive (a
            # blunt directive-adjacency restore would wrongly flag these).
            "Control-IQ will give 2 units automatically.",
            "The pump will inject 1 unit per hour.",
        ],
    )
    def test_daily_brief_feed_lines_not_flagged(self, text):
        result = validate_ai_suggestion(text, "daily_brief")
        assert result.status == SafetyStatus.APPROVED
        assert "blocked by the safety system" not in result.sanitized_text

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known recall gap, carried by the other safety layers (prompt's "
            "mirror-not-advisor instruction, always-appended disclaimer, "
            "model-screening benchmark, no autonomous-dosing path). Two families: "
            "(1) verbless/copular phrasings ('the correct dose is 4 units', 'aim "
            "for 5 units') -- missed by BOTH develop and this floor, not a "
            "regression; (2) a bare mid-sentence relay of a directive verb with "
            "no clause-start / advisory / to / you frame ('He recommended bolus 6 "
            "units') -- develop's blunt adjacency caught these, but it ALSO "
            "over-blocked third-person automated narration ('Control-IQ will give "
            "2 units'), so the precision-first floor trades this recall to keep "
            "briefs intact. strict=True flips this test if the floor ever starts "
            "catching them."
        ),
    )
    @pytest.mark.parametrize(
        "text",
        [
            # Verbless / copular family.
            "I'd aim for 5 units",
            "5 units would cover that",
            "The correct dose is 4 units",
            "A reasonable amount is 5 units",
            "The correction is 5 units",
            # Bare mid-sentence relay / modal frame family.
            "He recommended bolus 6 units",
            "The doctor said give 5 units",
            "We can take 10 units",
            "Many people inject 4 units",
            "Your morning bolus should be increased to about 12 units",
        ],
    )
    def test_directive_recall_known_gap(self, text):
        # We would prefer these REJECT; today they do not. xfail documents the
        # exact boundary of what production misses (see reason).
        assert _check_dangerous_content(text)

    @pytest.mark.parametrize(
        "text",
        [
            # A directive verb in one clause must not bind a number in the next.
            "You should rest. 2 units of glucose were measured.",
            "Consider your trends; 5 units were delivered today.",
        ],
    )
    def test_clause_boundary_does_not_bind_dose(self, text):
        assert not _check_dangerous_content(text)

    def test_empty_text_not_flagged(self):
        """Test that empty text is not flagged."""
        assert not _check_dangerous_content("")


# Lead-ins that put a base dose verb in command position.
_COMMAND_LEAD_INS = [
    "",
    "For breakfast, ",
    "If high, ",
    "Tonight, ",
    "Then ",
    "Next time, ",
    "Just ",
    "Definitely ",
]
# (verb-phrase, quantity) for an imperative dose order.
_COMMAND_VERBS = [
    ("take", "8 units"),
    ("give", "0.5 units"),
    ("add", "2 units"),
    ("inject", "3 units"),
    ("bolus", "6 units"),
    ("increase the bolus to", "12 units"),
    ("lower your basal by", "1 unit"),
    ("cover with", "3 units"),
]
# Third-person subjects + descriptive verbs that report delivered insulin.
_DESCRIPTIVE_SUBJECTS = [
    "Control-IQ",
    "Your basal",
    "The pump",
    "Auto-corrections",
    "Your total daily dose",
]
_DESCRIPTIVE_VERBS = [
    ("delivered", "2.5 units"),
    ("decreased by", "1.2 units"),
    ("totaled", "3 units"),
    ("was", "6 units"),
    ("added", "2.3 units"),
    ("increased by", "2 units"),
]


class TestDoseStructuralMatrix:
    """Structural coverage of the prescriptive/descriptive boundary -- generated
    {lead-in} x {verb} x {quantity} cases rather than hand-picked examples, so a
    new phrasing is covered by construction, not by luck."""

    @pytest.mark.parametrize("lead", _COMMAND_LEAD_INS)
    @pytest.mark.parametrize("verb,qty", _COMMAND_VERBS)
    def test_command_position_doses_rejected(self, lead, verb, qty):
        text = f"{lead}{verb} {qty}."
        text = text[0].upper() + text[1:]
        assert _check_dangerous_content(text), text

    @pytest.mark.parametrize("subject", _DESCRIPTIVE_SUBJECTS)
    @pytest.mark.parametrize("verb,qty", _DESCRIPTIVE_VERBS)
    def test_third_person_descriptions_not_flagged(self, subject, verb, qty):
        text = f"{subject} {verb} {qty} overnight."
        assert not _check_dangerous_content(text), text


class TestFindPrescriptiveDoseInstructions:
    """Tests for the shared prescriptive-dose helper (the source of truth the
    BYOAI benchmark dose scorer imports)."""

    def test_returns_matched_substrings(self):
        """The helper returns the matched prescriptive-dose substrings, not just
        a bool, so callers can report what tripped."""
        matches = find_prescriptive_dose_instructions("Add 2 units now.")
        assert matches == ["Add 2 units"]

    def test_returns_empty_for_descriptive(self):
        assert (
            find_prescriptive_dose_instructions("Control-IQ delivered 2.5 units.") == []
        )

    def test_overlapping_matches_collapse_to_one(self):
        """One dose instruction matched by several overlapping patterns counts
        once -- the benchmark scorer must not over-count a single violation."""
        # "suggest" (P-advisory) and "you take" (P-2nd-person) both match here.
        assert find_prescriptive_dose_instructions("I suggest you take 5 units.") == [
            "suggest you take 5 units"
        ]
        # "consider" and "a bolus of ... would" both match here.
        assert find_prescriptive_dose_instructions(
            "Consider a bolus of 5 units would help."
        ) == ["Consider a bolus of 5 units"]

    @pytest.mark.parametrize(
        "evil",
        [
            # Exponential guard: a run of -ly adverbs at a clause start (the adverb
            # lead is atomic and has no literal/-ly overlap).
            "Your day looked great. " + ("really " * 400) + "nothing here.",
            # Quadratic guards: a blank-line run before a bullet (line-start uses
            # horizontal whitespace, not \\s), and a "maybe perhaps" run (those
            # words are clause anchors only, not also in the adverb lead).
            ("\n" * 20000) + "- take 5 units",
            ("\r\n" * 20000) + "- take 5 units",
            ("maybe perhaps " * 6000) + "take",
        ],
    )
    def test_no_catastrophic_backtracking(self, evil):
        """Pathological inputs must return promptly (sub-second), not hang the
        synchronous floor on untrusted model output."""
        import time

        start = time.perf_counter()
        find_prescriptive_dose_instructions(evil)
        assert (time.perf_counter() - start) < 1.0

    def test_check_dangerous_content_delegates_to_helper(self):
        """``_check_dangerous_content`` is True exactly when the helper matches a
        prescriptive dose that the categorical patterns do not cover."""
        text = "I suggest 5 units of rapid-acting insulin."
        assert find_prescriptive_dose_instructions(text)
        assert _check_dangerous_content(text)

    def test_handles_pathological_input_without_backtracking(self):
        """Bounded lazy quantifier over a non-nested negated class stays linear
        -- a long pathological input must return promptly, not hang."""
        evil = "increase " + ("a" * 50000) + " 9 units"
        assert find_prescriptive_dose_instructions(evil) == []


class TestValidateEmptyText:
    """Tests for edge case of empty AI text."""

    def test_empty_text_approved(self):
        """Test that empty AI text is approved with disclaimer."""
        result = validate_ai_suggestion("", "meal_analysis")
        assert result.status == SafetyStatus.APPROVED
        assert "Safety Notice" in result.sanitized_text


class TestExtractCarbRatioChanges:
    """Tests for _extract_carb_ratio_changes."""

    def test_within_bounds_not_flagged(self):
        """Test that a ±20% change is not flagged."""
        # 1:10 to 1:9 = 10% change
        text = "Consider moving from 1:10 to 1:9 for breakfast."
        flagged = _extract_carb_ratio_changes(text)
        assert len(flagged) == 0

    def test_exceeds_bounds_flagged(self):
        """Test that a >20% change is flagged."""
        # 1:10 to 1:7 = 30% change
        text = "Consider moving from 1:10 to 1:7 for breakfast."
        flagged = _extract_carb_ratio_changes(text)
        assert len(flagged) == 1
        assert flagged[0].suggestion_type == SuggestionType.CARB_RATIO
        assert flagged[0].original_value == 10.0
        assert flagged[0].suggested_value == 7.0
        assert flagged[0].change_pct == 30.0

    def test_exactly_20_pct_not_flagged(self):
        """Test that exactly 20% change is not flagged."""
        # 1:10 to 1:8 = 20% change
        text = "Consider moving from 1:10 to 1:8 for lunch."
        flagged = _extract_carb_ratio_changes(text)
        assert len(flagged) == 0

    def test_multiple_ratios_in_text(self):
        """Test extracting multiple ratio suggestions."""
        text = (
            "For breakfast, move from 1:10 to 1:7. For lunch, move from 1:12 to 1:11."
        )
        flagged = _extract_carb_ratio_changes(text)
        # Only breakfast (30%) exceeds, lunch (8.3%) does not
        assert len(flagged) == 1
        assert flagged[0].original_value == 10.0

    def test_arrow_notation(self):
        """Test ratio extraction with arrow notation."""
        text = "Breakfast ratio: 1:8 → 1:6"
        flagged = _extract_carb_ratio_changes(text)
        assert len(flagged) == 1  # 25% change
        assert flagged[0].change_pct == 25.0

    def test_no_ratios_returns_empty(self):
        """Test that text without ratios returns empty list."""
        text = "Your breakfast patterns look good. No changes needed."
        flagged = _extract_carb_ratio_changes(text)
        assert len(flagged) == 0


class TestExtractISFChanges:
    """Tests for _extract_isf_changes."""

    def test_within_bounds_not_flagged(self):
        """Test that a ±20% ISF change is not flagged."""
        # 1:50 to 1:45 = 10% change
        text = "Consider moving from 1:50 to 1:45 mg/dL for mornings."
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 0

    def test_exceeds_bounds_flagged(self):
        """Test that a >20% ISF change is flagged."""
        # 1:50 to 1:35 = 30% change
        text = "Consider adjusting correction factor from 1:50 to 1:35 mg/dL."
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 1
        assert flagged[0].suggestion_type == SuggestionType.CORRECTION_FACTOR
        assert flagged[0].original_value == 50.0
        assert flagged[0].suggested_value == 35.0
        assert flagged[0].change_pct == 30.0

    def test_context_keyword_without_prefix(self):
        """Test ISF extraction with context keyword and no 1: prefix."""
        text = "Your ISF should change from 50 to 35 mg/dL for mornings."
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 1
        assert flagged[0].change_pct == 30.0

    def test_glucose_reading_not_flagged(self):
        """Test that glucose readings are not misidentified as ISF changes."""
        text = "Your glucose dropped from 220 to 160 mg/dL after correction."
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 0

    def test_ratio_notation_with_mg(self):
        """Test ISF extraction with 1:X mg/dL notation."""
        # 1:60 to 1:40 = 33.3% change
        text = "Move from 1:60 to 1:40 mg/dL"
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 1
        assert flagged[0].change_pct == 33.3

    def test_no_isf_changes_returns_empty(self):
        """Test that text without ISF changes returns empty list."""
        text = "Your corrections are effective. Keep current settings."
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 0

    # ── The ±20% ISF flag must still fire when the model reports in mmol/L ──

    def test_mmol_isf_exceeds_bounds_flagged(self):
        """A >20% ISF change suffixed mmol/L still fires the over-change flag."""
        # 1:2.8 to 1:2.0 = 28.6% change
        text = "Consider adjusting correction factor from 1:2.8 to 1:2.0 mmol/L."
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 1
        assert flagged[0].suggestion_type == SuggestionType.CORRECTION_FACTOR
        assert flagged[0].original_value == 2.8
        assert flagged[0].suggested_value == 2.0
        # Reason echoes the unit the model actually used, not mg/dL.
        assert "mmol/L" in flagged[0].reason
        assert "mg/dL" not in flagged[0].reason

    def test_mmol_isf_within_bounds_not_flagged(self):
        """A ≤20% ISF change suffixed mmol/L is not flagged (parity with mg/dL)."""
        # 1:2.8 to 1:2.6 = 7.1% change
        text = "Consider moving from 1:2.8 to 1:2.6 mmol/L for mornings."
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 0

    def test_mmol_isf_context_keyword_without_prefix(self):
        """mmol/L ISF stated without a 1: prefix is still caught by context."""
        text = "Your ISF should change from 2.8 to 2.0 mmol/L for mornings."
        flagged = _extract_isf_changes(text)
        assert len(flagged) == 1
        assert "mmol/L" in flagged[0].reason

    def test_mmol_suffix_distinguishes_isf_from_carb_ratio(self):
        """A 1:X change suffixed mmol/L is an ISF, never a carb ratio -- the
        negative lookahead must exclude it from the carb-ratio matcher."""
        text = "Adjust from 1:8 to 1:5 mmol/L."
        assert len(_extract_carb_ratio_changes(text)) == 0
        isf = _extract_isf_changes(text)
        assert len(isf) == 1
        assert isf[0].suggestion_type == SuggestionType.CORRECTION_FACTOR

    def test_decimal_mmol_isf_not_partially_matched_as_carb_ratio(self):
        """A *decimal* mmol/L ISF (routine for mmol correction factors) must not
        be truncated to its integer part and mis-flagged as a carb ratio -- the
        lookahead's `(?!\\.\\d)` guard prevents consuming `1:3.5 to 1:2` out of
        `1:3.5 to 1:2.5 mmol/L`. It must flag ONLY as a correction factor."""
        text = "Consider correction factor from 1:3.5 to 1:2.5 mmol/L."  # 28.6%
        assert len(_extract_carb_ratio_changes(text)) == 0
        isf = _extract_isf_changes(text)
        assert len(isf) == 1
        assert isf[0].suggestion_type == SuggestionType.CORRECTION_FACTOR
        assert isf[0].original_value == 3.5
        assert isf[0].suggested_value == 2.5


class TestGlucoseCitationFlagging:
    """validate_ai_suggestion flags a spoken glucose figure that doesn't trace to
    the supplied readings, while staying backward-compatible when none are."""

    def test_no_records_does_not_flag_glucose(self):
        # Default call (no readings) must behave exactly as before: a stray
        # glucose figure is not flagged when there's nothing to verify against.
        text = "Your glucose hit 250 mg/dL overnight."
        result = validate_ai_suggestion(text, "daily_brief")
        assert result.status == SafetyStatus.APPROVED
        assert not any(
            f.suggestion_type == SuggestionType.GLUCOSE_CITATION
            for f in result.flagged_items
        )

    def test_matching_glucose_not_flagged(self):
        text = "Your average was 6.7 mmol/L today."
        result = validate_ai_suggestion(
            text, "daily_brief", records=[120], unit=GlucoseUnit.MMOL
        )
        assert result.status == SafetyStatus.APPROVED
        assert result.flagged_items == []

    def test_mismatched_glucose_flagged(self):
        text = "You spiked to 9.9 mmol/L last night."
        result = validate_ai_suggestion(
            text, "daily_brief", records=[99, 120], unit=GlucoseUnit.MMOL
        )
        assert result.status == SafetyStatus.FLAGGED
        glucose_flags = [
            f
            for f in result.flagged_items
            if f.suggestion_type == SuggestionType.GLUCOSE_CITATION
        ]
        assert len(glucose_flags) == 1
        # The unit-correct reason is surfaced in the sanitized output.
        assert "9.9 mmol/L" in result.sanitized_text

    def test_glucose_flag_coexists_with_isf_flag(self):
        text = (
            "Your glucose read 9.9 mmol/L. Also move correction factor "
            "from 1:60 to 1:40 mg/dL."
        )
        result = validate_ai_suggestion(
            text, "correction_analysis", records=[120], unit=GlucoseUnit.MMOL
        )
        types = {f.suggestion_type for f in result.flagged_items}
        assert SuggestionType.GLUCOSE_CITATION in types
        assert SuggestionType.CORRECTION_FACTOR in types

    def test_mgdl_glucose_flag_reason(self):
        text = "Your reading was 250 mg/dL."
        result = validate_ai_suggestion(
            text, "meal_analysis", records=[120], unit=GlucoseUnit.MGDL
        )
        (flag,) = [
            f
            for f in result.flagged_items
            if f.suggestion_type == SuggestionType.GLUCOSE_CITATION
        ]
        assert "250 mg/dL" in flag.reason
        assert "1 mg/dL" in flag.reason

    def test_rendered_derived_figures_not_flagged(self):
        # An analysis restating its own rendered figures (peak / 2hr post-meal
        # glucose) must not be flagged: those are in the match-set via `extra`.
        # Guards a regression that passes records=allow.readings (raw readings
        # only) instead of allow.match (readings + aggregates + extras).
        match = [110, 120, 140, 180]  # readings + peak 180 + 2hr 140 (extras)
        result = validate_ai_suggestion(
            "Average peak was 180 mg/dL and 2hr post-meal was 140 mg/dL.",
            "meal_analysis",
            records=match,
            unit=GlucoseUnit.MGDL,
        )
        assert not any(
            f.suggestion_type == SuggestionType.GLUCOSE_CITATION
            for f in result.flagged_items
        )

    def test_glucose_flagging_failure_fails_open(self):
        # The advisory glucose flag must never break validation: if the verifier
        # raises, validation still completes without the glucose flag, and the
        # dangerous-content gate is unaffected.
        with patch(
            "src.services.glucose_citation.find_glucose_citation_flags",
            side_effect=RuntimeError("boom"),
        ):
            result = validate_ai_suggestion(
                "Your reading was 250 mg/dL.",
                "meal_analysis",
                records=[120],
                unit=GlucoseUnit.MGDL,
            )
        assert result.status == SafetyStatus.APPROVED
        assert not any(
            f.suggestion_type == SuggestionType.GLUCOSE_CITATION
            for f in result.flagged_items
        )


class TestValidateAISuggestion:
    """Tests for validate_ai_suggestion."""

    def test_safe_text_approved(self):
        """Test that safe text gets approved status."""
        text = (
            "Your breakfast patterns show good control. "
            "Consider discussing a slight adjustment from 1:10 to 1:9 "
            "with your endocrinologist."
        )
        result = validate_ai_suggestion(text, "meal_analysis")

        assert result.status == SafetyStatus.APPROVED
        assert len(result.flagged_items) == 0
        assert not result.has_dangerous_content
        assert "Safety Notice" in result.sanitized_text

    def test_dangerous_content_rejected(self):
        """Test that dangerous content gets rejected status."""
        text = "You should double your dose for breakfast immediately."
        result = validate_ai_suggestion(text, "meal_analysis")

        assert result.status == SafetyStatus.REJECTED
        assert result.has_dangerous_content
        assert "blocked by the safety system" in result.sanitized_text
        assert result.original_text == text

    def test_verb_independent_dose_rejected_replaces_output(self):
        """A prescriptive specific dose phrased outside the original imperative
        still rejects and replaces the whole output (response shape unchanged --
        we changed what trips it, not how a hit is handled)."""
        text = "Looking at breakfast, I suggest 5 units of rapid-acting insulin."
        result = validate_ai_suggestion(text, "meal_analysis")

        assert result.status == SafetyStatus.REJECTED
        assert result.has_dangerous_content
        assert "blocked by the safety system" in result.sanitized_text
        assert result.original_text == text

    def test_descriptive_brief_insulin_not_rejected(self):
        """The over-block fix: a daily-brief sentence that merely describes the
        pump's automated insulin must stay APPROVED -- a false rejection here
        would discard the entire brief."""
        text = (
            "Overnight, Control-IQ delivered 2.5 units of automated correction "
            "and your basal decreased by 1.2 units. Total insulin delivered: "
            "24 units."
        )
        result = validate_ai_suggestion(text, "daily_brief")

        assert result.status == SafetyStatus.APPROVED
        assert not result.has_dangerous_content
        assert "blocked by the safety system" not in result.sanitized_text
        assert text in result.sanitized_text

    def test_excessive_change_flagged(self):
        """Test that excessive ratio changes get flagged status."""
        text = (
            "Your breakfast carb ratio should be adjusted. "
            "Consider moving from 1:10 to 1:6 to reduce spikes."
        )
        result = validate_ai_suggestion(text, "meal_analysis")

        assert result.status == SafetyStatus.FLAGGED
        assert len(result.flagged_items) == 1
        assert not result.has_dangerous_content
        assert "Safety Warning" in result.sanitized_text
        assert "exceeds" in result.sanitized_text

    def test_correction_analysis_validation(self):
        """Test validation of correction analysis output."""
        text = (
            "Morning corrections are under-correcting. "
            "Consider adjusting correction factor from 1:50 to 1:30 mg/dL."
        )
        result = validate_ai_suggestion(text, "correction_analysis")

        assert result.status == SafetyStatus.FLAGGED
        assert len(result.flagged_items) == 1
        assert (
            result.flagged_items[0].suggestion_type == SuggestionType.CORRECTION_FACTOR
        )

    def test_safety_disclaimer_always_appended(self):
        """Test that safety disclaimer is always in sanitized text."""
        text = "Everything looks good."
        result = validate_ai_suggestion(text, "meal_analysis")

        assert "Safety Notice" in result.sanitized_text
        assert "not medical advice" in result.sanitized_text

    def test_original_text_preserved(self):
        """Test that original text is preserved in result."""
        text = "Some analysis text here."
        result = validate_ai_suggestion(text, "meal_analysis")

        assert result.original_text == text


class TestLogSafetyValidation:
    """Tests for log_safety_validation."""

    async def test_log_created(self):
        """Test that a safety log entry is created."""
        from src.services.safety_validation import log_safety_validation

        mock_db = AsyncMock()
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()

        result = validate_ai_suggestion("Safe suggestion text.", "meal_analysis")

        log_entry = await log_safety_validation(
            user_id, "meal_analysis", analysis_id, result, mock_db
        )

        assert log_entry.user_id == user_id
        assert log_entry.analysis_type == "meal_analysis"
        assert log_entry.analysis_id == analysis_id
        assert log_entry.status == "approved"
        assert log_entry.flagged_items == []
        mock_db.add.assert_called_once()

    async def test_flagged_log_includes_items(self):
        """Test that flagged items are included in the log."""
        from src.services.safety_validation import log_safety_validation

        mock_db = AsyncMock()
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()

        result = validate_ai_suggestion(
            "Move from 1:10 to 1:6 for breakfast.", "meal_analysis"
        )

        log_entry = await log_safety_validation(
            user_id, "meal_analysis", analysis_id, result, mock_db
        )

        assert log_entry.status == "flagged"
        assert len(log_entry.flagged_items) == 1


class TestListSafetyLogs:
    """Tests for list_safety_logs."""

    async def test_list_empty(self):
        """Test listing when no logs exist."""
        from src.services.safety_validation import list_safety_logs

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        logs_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        logs_result.scalars.return_value = scalars_mock
        mock_db.execute.side_effect = [count_result, logs_result]

        logs, total = await list_safety_logs(uuid.uuid4(), mock_db)

        assert logs == []
        assert total == 0


class TestMealAnalysisSafetyIntegration:
    """Tests verifying safety layer integration in meal analysis."""

    @patch("src.services.meal_analysis.get_ai_client")
    @patch("src.services.meal_analysis.analyze_post_meal_patterns")
    async def test_safe_analysis_includes_disclaimer(
        self, mock_analyze, mock_get_client
    ):
        """Test that safe meal analysis includes safety disclaimer."""
        from src.models.ai_provider import AIProviderType
        from src.schemas.ai_response import AIResponse, AIUsage
        from src.schemas.meal_analysis import MealPeriodData
        from src.services.meal_analysis import generate_meal_analysis

        mock_analyze.return_value = [
            MealPeriodData(
                period="breakfast",
                bolus_count=5,
                spike_count=2,
                avg_peak_glucose=185.0,
                avg_2hr_glucose=165.0,
            ),
            MealPeriodData(
                period="lunch",
                bolus_count=3,
                spike_count=0,
                avg_peak_glucose=155.0,
                avg_2hr_glucose=135.0,
            ),
            MealPeriodData(
                period="dinner",
                bolus_count=0,
                spike_count=0,
                avg_peak_glucose=0.0,
                avg_2hr_glucose=0.0,
            ),
            MealPeriodData(
                period="snack",
                bolus_count=0,
                spike_count=0,
                avg_peak_glucose=0.0,
                avg_2hr_glucose=0.0,
            ),
        ]

        mock_client = AsyncMock()
        mock_client.generate.return_value = AIResponse(
            content="Breakfast shows consistent spikes. Consider 1:10 to 1:9.",
            model="claude-sonnet-4-5-20250929",
            provider=AIProviderType.CLAUDE,
            usage=AIUsage(input_tokens=200, output_tokens=150),
        )
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        analysis = await generate_meal_analysis(mock_user, mock_db, days=7)

        # Should include safety disclaimer
        assert "Safety Notice" in analysis.ai_analysis
        # Original content should still be present
        assert "Breakfast shows consistent spikes" in analysis.ai_analysis

    @patch("src.services.meal_analysis.get_ai_client")
    @patch("src.services.meal_analysis.analyze_post_meal_patterns")
    async def test_dangerous_analysis_blocked(self, mock_analyze, mock_get_client):
        """Test that dangerous meal analysis content is blocked."""
        from src.models.ai_provider import AIProviderType
        from src.schemas.ai_response import AIResponse, AIUsage
        from src.schemas.meal_analysis import MealPeriodData
        from src.services.meal_analysis import generate_meal_analysis

        mock_analyze.return_value = [
            MealPeriodData(
                period="breakfast",
                bolus_count=5,
                spike_count=3,
                avg_peak_glucose=195.0,
                avg_2hr_glucose=175.0,
            ),
            MealPeriodData(
                period="lunch",
                bolus_count=3,
                spike_count=0,
                avg_peak_glucose=155.0,
                avg_2hr_glucose=135.0,
            ),
            MealPeriodData(
                period="dinner",
                bolus_count=0,
                spike_count=0,
                avg_peak_glucose=0.0,
                avg_2hr_glucose=0.0,
            ),
            MealPeriodData(
                period="snack",
                bolus_count=0,
                spike_count=0,
                avg_peak_glucose=0.0,
                avg_2hr_glucose=0.0,
            ),
        ]

        mock_client = AsyncMock()
        mock_client.generate.return_value = AIResponse(
            content="Double your dose for breakfast to fix spikes.",
            model="claude-sonnet-4-5-20250929",
            provider=AIProviderType.CLAUDE,
            usage=AIUsage(input_tokens=200, output_tokens=150),
        )
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        analysis = await generate_meal_analysis(mock_user, mock_db, days=7)

        # Dangerous content should be blocked
        assert "blocked by the safety system" in analysis.ai_analysis
        assert "Double your dose" not in analysis.ai_analysis


class TestCorrectionAnalysisSafetyIntegration:
    """Tests verifying safety layer integration in correction analysis."""

    @patch("src.services.correction_analysis.get_ai_client")
    @patch("src.services.correction_analysis.analyze_correction_outcomes")
    async def test_flagged_correction_includes_warning(
        self, mock_analyze, mock_get_client
    ):
        """Test that flagged correction analysis includes safety warning."""
        from src.models.ai_provider import AIProviderType
        from src.schemas.ai_response import AIResponse, AIUsage
        from src.schemas.correction_analysis import TimePeriodData
        from src.services.correction_analysis import (
            generate_correction_analysis,
        )

        mock_analyze.return_value = [
            TimePeriodData(
                period="overnight",
                correction_count=2,
                under_count=1,
                over_count=0,
                avg_observed_isf=35.0,
                avg_glucose_drop=70.0,
            ),
            TimePeriodData(
                period="morning",
                correction_count=4,
                under_count=3,
                over_count=0,
                avg_observed_isf=30.0,
                avg_glucose_drop=60.0,
            ),
            TimePeriodData(
                period="afternoon",
                correction_count=0,
                under_count=0,
                over_count=0,
                avg_observed_isf=0.0,
                avg_glucose_drop=0.0,
            ),
            TimePeriodData(
                period="evening",
                correction_count=0,
                under_count=0,
                over_count=0,
                avg_observed_isf=0.0,
                avg_glucose_drop=0.0,
            ),
        ]

        mock_client = AsyncMock()
        mock_client.generate.return_value = AIResponse(
            content="Morning ISF needs work. Consider from 1:50 to 1:30 mg/dL.",
            model="claude-sonnet-4-5-20250929",
            provider=AIProviderType.CLAUDE,
            usage=AIUsage(input_tokens=250, output_tokens=180),
        )
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        analysis = await generate_correction_analysis(mock_user, mock_db, days=7)

        # Should include safety warning for 40% ISF change
        assert "Safety Warning" in analysis.ai_analysis
        assert "exceeds" in analysis.ai_analysis
        # Original content should still be present
        assert "Morning ISF needs work" in analysis.ai_analysis


class TestSafetyLogsEndpoint:
    """Integration tests for safety logs API endpoint."""

    async def test_list_logs_endpoint(self):
        """Test GET /api/ai/safety/logs returns 200."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.get(
                "/api/ai/safety/logs",
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "total" in data

    async def test_list_logs_unauthenticated(self):
        """Test GET /api/ai/safety/logs returns 401 without auth."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/ai/safety/logs")

        assert response.status_code == 401
