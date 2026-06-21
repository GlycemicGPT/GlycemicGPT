"""Story 5.6: Tests for pre-validation safety layer."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.core.units import GlucoseUnit
from src.main import app
from src.schemas.safety_validation import SafetyStatus, SuggestionType
from src.services.safety_validation import (
    _check_dangerous_content,
    _extract_carb_ratio_changes,
    _extract_isf_changes,
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

    def test_empty_text_not_flagged(self):
        """Test that empty text is not flagged."""
        assert not _check_dangerous_content("")


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
