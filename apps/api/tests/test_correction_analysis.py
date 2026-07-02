"""Story 5.5: Tests for correction factor analysis and ISF suggestions."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.core.units import GlucoseUnit
from src.main import app
from src.models.ai_provider import AIProviderType
from src.schemas.ai_response import AIResponse, AIUsage
from src.schemas.correction_analysis import TimePeriodData
from src.services.correction_analysis import (
    _build_correction_prompt,
    _build_system_prompt,
    _classify_time_period,
    analyze_correction_outcomes,
)


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client: AsyncClient) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email("correction")
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


def _mock_ai_response(
    content: str = "Morning corrections consistently under-correct.",
) -> AIResponse:
    """Create a mock AI response for testing."""
    return AIResponse(
        content=content,
        model="claude-sonnet-4-5-20250929",
        provider=AIProviderType.CLAUDE,
        usage=AIUsage(input_tokens=250, output_tokens=180),
    )


class TestClassifyTimePeriod:
    """Tests for _classify_time_period."""

    def test_morning_hours(self):
        """Test hours 6-11 classify as morning."""
        for hour in [6, 7, 8, 9, 10, 11]:
            assert _classify_time_period(hour) == "morning"

    def test_afternoon_hours(self):
        """Test hours 12-16 classify as afternoon."""
        for hour in [12, 13, 14, 15, 16]:
            assert _classify_time_period(hour) == "afternoon"

    def test_evening_hours(self):
        """Test hours 17-21 classify as evening."""
        for hour in [17, 18, 19, 20, 21]:
            assert _classify_time_period(hour) == "evening"

    def test_overnight_hours(self):
        """Test hours 22-5 classify as overnight (wraps midnight)."""
        for hour in [22, 23, 0, 1, 2, 3, 4, 5]:
            assert _classify_time_period(hour) == "overnight"

    def test_boundary_morning_start(self):
        """Test hour 6 is morning, hour 5 is overnight."""
        assert _classify_time_period(6) == "morning"
        assert _classify_time_period(5) == "overnight"

    def test_boundary_evening_end(self):
        """Test hour 21 is evening, hour 22 is overnight."""
        assert _classify_time_period(21) == "evening"
        assert _classify_time_period(22) == "overnight"

    def test_boundary_afternoon(self):
        """Test hour 11 is morning, hour 12 is afternoon, hour 17 is evening."""
        assert _classify_time_period(11) == "morning"
        assert _classify_time_period(12) == "afternoon"
        assert _classify_time_period(17) == "evening"


class TestBuildCorrectionPrompt:
    """Tests for _build_correction_prompt."""

    def test_prompt_includes_all_periods(self):
        """Test that the prompt includes data for all time periods."""
        periods = [
            TimePeriodData(
                period="morning",
                correction_count=5,
                under_count=3,
                over_count=0,
                avg_observed_isf=40.0,
                avg_glucose_drop=80.0,
            ),
            TimePeriodData(
                period="evening",
                correction_count=4,
                under_count=0,
                over_count=2,
                avg_observed_isf=60.0,
                avg_glucose_drop=120.0,
            ),
        ]

        prompt = _build_correction_prompt(periods, 9, 7)

        assert "7-day" in prompt
        assert "9" in prompt  # total corrections
        assert "Morning" in prompt
        assert "Evening" in prompt
        assert "40.0" in prompt  # ISF
        assert "60.0" in prompt
        assert "Effective correction rate: 40%" in prompt  # (5-3-0)/5
        assert "Effective correction rate: 50%" in prompt  # (4-0-2)/4

    def test_prompt_with_zero_corrections_period(self):
        """Test that zero-correction periods don't produce effectiveness rate."""
        periods = [
            TimePeriodData(
                period="overnight",
                correction_count=0,
                under_count=0,
                over_count=0,
                avg_observed_isf=0.0,
                avg_glucose_drop=0.0,
            ),
        ]

        prompt = _build_correction_prompt(periods, 0, 7)

        assert "Overnight" in prompt
        assert "Effective correction rate" not in prompt

    def _periods(self) -> list[TimePeriodData]:
        return [
            TimePeriodData(
                period="morning",
                correction_count=5,
                under_count=3,
                over_count=0,
                avg_observed_isf=40.0,
                avg_glucose_drop=80.0,
            ),
        ]

    def test_prompt_mgdl_unchanged_from_legacy(self):
        """mg/dL output is byte-identical to the pre-unit format (default unit)."""
        prompt = _build_correction_prompt(self._periods(), 5, 7, unit=GlucoseUnit.MGDL)

        assert "glucose stayed >120 mg/dL" in prompt
        assert "glucose dropped <70 mg/dL" in prompt
        assert "Average observed ISF: 40.0 mg/dL per unit" in prompt
        assert "Average glucose drop: 80 mg/dL" in prompt

    def test_prompt_renders_mmol_unit(self):
        """Anchors (120->6.7, 70->3.9), the ISF rate, and the drop convert;
        the ISF rate converts as a rate (40 mg/dL/U -> 2.2 mmol/L/U)."""
        prompt = _build_correction_prompt(self._periods(), 5, 7, unit=GlucoseUnit.MMOL)

        assert "glucose stayed >6.7 mmol/L" in prompt
        assert "glucose dropped <3.9 mmol/L" in prompt
        assert "Average observed ISF: 2.2 mmol/L per unit" in prompt
        assert "Average glucose drop: 4.4 mmol/L" in prompt
        assert "mg/dL" not in prompt

    def test_mmol_prompt_keeps_cf_and_observed_isf_same_scale(self):
        """The configured correction factor and the observed ISF the prompt asks
        the model to compare must be on the same scale for an mmol/L user (both
        mmol/L per unit), not a mg/dL CF against a mmol observed ISF."""
        from src.services.diabetes_context import ProfileSegment, PumpProfileSummary

        summary = PumpProfileSummary(
            profile_name="Default",
            segments=[
                ProfileSegment(
                    time="00:00",
                    start_minutes=0,
                    basal_rate=0.5,
                    correction_factor=50,
                    carb_ratio=8,
                    target_bg=120,
                ),
            ],
        )
        prompt = _build_correction_prompt(
            self._periods(), 5, 7, summary, GlucoseUnit.MMOL
        )
        assert "CF 1:2.8" in prompt  # configured CF on the mmol scale
        assert "2.2 mmol/L per unit" in prompt  # observed ISF on the same scale
        assert "CF 1:50" not in prompt

    def test_system_prompt_states_user_unit(self):
        """Each system prompt names the report unit and the ISF rate unit."""
        mgdl = _build_system_prompt(GlucoseUnit.MGDL)
        assert "mg/dL drop per unit of insulin" in mgdl
        assert "Report all glucose values in mg/dL" in mgdl
        assert "dropped below 70 mg/dL" in mgdl

        # The ISF example renders on the user's scale so observed ISF and the
        # configured correction factor stay same-unit (1:50 mg/dL -> 1:2.8 mmol).
        assert "currently 1:50" in mgdl

        mmol = _build_system_prompt(GlucoseUnit.MMOL)
        assert "mmol/L drop per unit of insulin" in mmol
        assert "Report all glucose values in mmol/L" in mmol
        assert "dropped below 3.9 mmol/L" in mmol
        assert "currently 1:2.8" in mmol
        assert "currently 1:50" not in mmol


class TestAnalyzeCorrectionOutcomes:
    """Tests for analyze_correction_outcomes."""

    @pytest.fixture(autouse=True)
    def _stub_empty_cgm_exclusion(self):
        # These unit tests mock the DB and configure no CGM sources, so the
        # user's primary-source exclusion is empty. Stub it (GLY-123) so the
        # shared glucose-read funnel doesn't issue its list_cgm_sources queries
        # against the rigid execute mocks.
        with patch(
            "src.services.cgm_source.get_excluded_cgm_sources",
            new=AsyncMock(return_value=[]),
        ):
            yield

    async def test_no_corrections_returns_empty_periods(self):
        """Test that no corrections returns zeroed time periods."""
        mock_db = AsyncMock()

        # First query: corrections (empty)
        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        bolus_result.scalars.return_value = scalars_mock

        # Second query: all glucose readings
        glucose_result = MagicMock()
        glucose_result.all.return_value = []

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_correction_outcomes(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        assert len(periods) == 4
        for p in periods:
            assert p.correction_count == 0
            assert p.under_count == 0
            assert p.over_count == 0

    async def test_under_correction_detected(self):
        """Test that a correction leaving glucose high is detected."""
        mock_db = AsyncMock()

        # Morning correction at 8 AM, BG 220, 2 units
        correction_time = datetime(2026, 2, 7, 8, 0, tzinfo=UTC)
        mock_correction = SimpleNamespace(
            event_timestamp=correction_time,
            event_type="bolus",
            is_automated=False,
            bg_at_event=220,
            units=2.0,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_correction]
        bolus_result.scalars.return_value = scalars_mock

        # Glucose only drops to 160 (above target 120) = under-correction
        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            (correction_time + timedelta(minutes=30), 200),
            (correction_time + timedelta(minutes=60), 185),
            (correction_time + timedelta(minutes=120), 170),
            (correction_time + timedelta(minutes=180), 160),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_correction_outcomes(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        morning = next(p for p in periods if p.period == "morning")
        assert morning.correction_count == 1
        assert morning.under_count == 1  # final 160 > 120 target
        assert morning.over_count == 0
        # ISF = (220 - 160) / 2.0 = 30.0
        assert morning.avg_observed_isf == 30.0
        assert morning.avg_glucose_drop == 60.0

    async def test_over_correction_detected(self):
        """Test that a correction dropping glucose too low is detected."""
        mock_db = AsyncMock()

        # Evening correction at 7 PM, BG 200, 3 units
        correction_time = datetime(2026, 2, 7, 19, 0, tzinfo=UTC)
        mock_correction = SimpleNamespace(
            event_timestamp=correction_time,
            event_type="bolus",
            is_automated=False,
            bg_at_event=200,
            units=3.0,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_correction]
        bolus_result.scalars.return_value = scalars_mock

        # Glucose drops to 60 (below 70 low threshold) = over-correction
        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            (correction_time + timedelta(minutes=30), 170),
            (correction_time + timedelta(minutes=60), 130),
            (correction_time + timedelta(minutes=120), 85),
            (correction_time + timedelta(minutes=180), 60),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_correction_outcomes(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        evening = next(p for p in periods if p.period == "evening")
        assert evening.correction_count == 1
        assert evening.under_count == 0
        assert evening.over_count == 1  # final 60 < 70
        # ISF = (200 - 60) / 3.0 = 46.7
        assert evening.avg_observed_isf == 46.7
        assert evening.avg_glucose_drop == 140.0

    async def test_effective_correction(self):
        """Test that a correction reaching target is counted as effective."""
        mock_db = AsyncMock()

        # Afternoon correction at 2 PM, BG 180, 2 units
        correction_time = datetime(2026, 2, 7, 14, 0, tzinfo=UTC)
        mock_correction = SimpleNamespace(
            event_timestamp=correction_time,
            event_type="bolus",
            is_automated=False,
            bg_at_event=180,
            units=2.0,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_correction]
        bolus_result.scalars.return_value = scalars_mock

        # Glucose drops to 100 (between 70 and 120) = effective
        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            (correction_time + timedelta(minutes=60), 150),
            (correction_time + timedelta(minutes=120), 120),
            (correction_time + timedelta(minutes=180), 100),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_correction_outcomes(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        afternoon = next(p for p in periods if p.period == "afternoon")
        assert afternoon.correction_count == 1
        assert afternoon.under_count == 0
        assert afternoon.over_count == 0
        # ISF = (180 - 100) / 2.0 = 40.0
        assert afternoon.avg_observed_isf == 40.0

    async def test_correction_with_no_readings_skipped(self):
        """Test that corrections with no subsequent readings are skipped."""
        mock_db = AsyncMock()

        correction_time = datetime(2026, 2, 7, 23, 0, tzinfo=UTC)
        mock_correction = SimpleNamespace(
            event_timestamp=correction_time,
            event_type="bolus",
            is_automated=False,
            bg_at_event=200,
            units=2.0,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_correction]
        bolus_result.scalars.return_value = scalars_mock

        # No glucose readings in the window
        glucose_result = MagicMock()
        glucose_result.all.return_value = []

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_correction_outcomes(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        overnight = next(p for p in periods if p.period == "overnight")
        assert overnight.correction_count == 0  # skipped

    async def test_correction_with_zero_units_skipped(self):
        """Test that corrections with zero units are skipped."""
        mock_db = AsyncMock()

        correction_time = datetime(2026, 2, 7, 8, 0, tzinfo=UTC)
        mock_correction = SimpleNamespace(
            event_timestamp=correction_time,
            event_type="bolus",
            is_automated=False,
            bg_at_event=200,
            units=0.0,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_correction]
        bolus_result.scalars.return_value = scalars_mock

        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            (correction_time + timedelta(minutes=60), 180),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_correction_outcomes(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        morning = next(p for p in periods if p.period == "morning")
        assert morning.correction_count == 0  # skipped due to zero units

    async def test_glucose_rise_after_correction_skipped(self):
        """Test that corrections where glucose rose (concurrent meal) are skipped."""
        mock_db = AsyncMock()

        # Morning correction at 8 AM, BG 180, 2 units
        correction_time = datetime(2026, 2, 7, 8, 0, tzinfo=UTC)
        mock_correction = SimpleNamespace(
            event_timestamp=correction_time,
            event_type="bolus",
            is_automated=False,
            bg_at_event=180,
            units=2.0,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_correction]
        bolus_result.scalars.return_value = scalars_mock

        # Glucose rises to 220 (likely concurrent meal) — negative drop
        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            (correction_time + timedelta(minutes=30), 190),
            (correction_time + timedelta(minutes=60), 210),
            (correction_time + timedelta(minutes=120), 220),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_correction_outcomes(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        morning = next(p for p in periods if p.period == "morning")
        assert morning.correction_count == 0  # skipped due to glucose rise

    async def test_multiple_corrections_same_period(self):
        """Test averaging across multiple corrections in the same period."""
        mock_db = AsyncMock()

        corr1_time = datetime(2026, 2, 6, 8, 0, tzinfo=UTC)
        corr2_time = datetime(2026, 2, 7, 9, 0, tzinfo=UTC)
        corr1 = SimpleNamespace(
            event_timestamp=corr1_time,
            event_type="bolus",
            is_automated=False,
            bg_at_event=200,
            units=2.0,
        )
        corr2 = SimpleNamespace(
            event_timestamp=corr2_time,
            event_type="bolus",
            is_automated=False,
            bg_at_event=220,
            units=3.0,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [corr1, corr2]
        bolus_result.scalars.return_value = scalars_mock

        # All readings sorted by timestamp
        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            # Corr 1 window: BG 200 -> 140 (drop 60, ISF = 60/2 = 30)
            (corr1_time + timedelta(minutes=60), 170),
            (corr1_time + timedelta(minutes=180), 140),
            # Corr 2 window: BG 220 -> 130 (drop 90, ISF = 90/3 = 30)
            (corr2_time + timedelta(minutes=60), 175),
            (corr2_time + timedelta(minutes=180), 130),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_correction_outcomes(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        morning = next(p for p in periods if p.period == "morning")
        assert morning.correction_count == 2
        assert morning.under_count == 2  # both final > 120
        assert morning.over_count == 0
        # ISF: avg of 30 and 30 = 30.0
        assert morning.avg_observed_isf == 30.0
        # Avg drop: (60 + 90) / 2 = 75.0
        assert morning.avg_glucose_drop == 75.0


class TestGenerateCorrectionAnalysis:
    """Tests for generate_correction_analysis service function."""

    @patch("src.services.correction_analysis.get_ai_client")
    @patch("src.services.correction_analysis.analyze_correction_outcomes")
    async def test_generate_analysis_success(self, mock_analyze, mock_get_client):
        """Test successful correction analysis generation."""
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
                correction_count=3,
                under_count=0,
                over_count=1,
                avg_observed_isf=50.0,
                avg_glucose_drop=100.0,
            ),
            TimePeriodData(
                period="evening",
                correction_count=1,
                under_count=0,
                over_count=0,
                avg_observed_isf=45.0,
                avg_glucose_drop=90.0,
            ),
        ]

        mock_client = AsyncMock()
        mock_client.generate.return_value = _mock_ai_response()
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        analysis = await generate_correction_analysis(mock_user, mock_db, days=7)

        assert analysis.total_corrections == 10
        assert analysis.under_corrections == 4
        assert analysis.over_corrections == 1
        # Weighted avg ISF: (35*2 + 30*4 + 50*3 + 45*1) / 10 = 385/10 = 38.5
        assert analysis.avg_observed_isf == 38.5
        assert "Morning corrections consistently under-correct." in analysis.ai_analysis
        assert "Safety Notice" in analysis.ai_analysis
        assert len(analysis.time_periods_data) == 4
        # db.add called twice: once for analysis, once for safety log
        assert mock_db.add.call_count == 2
        mock_db.commit.assert_called_once()

    @patch("src.services.correction_analysis.analyze_correction_outcomes")
    async def test_generate_analysis_insufficient_data(self, mock_analyze):
        """Test that insufficient corrections raises 400."""
        from fastapi import HTTPException

        from src.services.correction_analysis import (
            generate_correction_analysis,
        )

        mock_analyze.return_value = [
            TimePeriodData(
                period="overnight",
                correction_count=1,
                under_count=0,
                over_count=0,
                avg_observed_isf=40.0,
                avg_glucose_drop=80.0,
            ),
            TimePeriodData(
                period="morning",
                correction_count=2,
                under_count=1,
                over_count=0,
                avg_observed_isf=35.0,
                avg_glucose_drop=70.0,
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

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await generate_correction_analysis(mock_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Insufficient correction data" in exc_info.value.detail

    @patch("src.services.correction_analysis.get_ai_client")
    @patch("src.services.correction_analysis.analyze_correction_outcomes")
    async def test_generate_analysis_ai_error_propagates(
        self, mock_analyze, mock_get_client
    ):
        """Test that AI provider errors propagate."""
        from src.services.correction_analysis import (
            generate_correction_analysis,
        )

        mock_analyze.return_value = [
            TimePeriodData(
                period="overnight",
                correction_count=3,
                under_count=1,
                over_count=0,
                avg_observed_isf=40.0,
                avg_glucose_drop=80.0,
            ),
            TimePeriodData(
                period="morning",
                correction_count=3,
                under_count=2,
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
        mock_client.generate.side_effect = RuntimeError("AI failed")
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        with pytest.raises(RuntimeError, match="AI failed"):
            await generate_correction_analysis(mock_user, mock_db)


class TestListCorrectionAnalyses:
    """Tests for list_correction_analyses."""

    async def test_list_empty(self):
        """Test listing when no analyses exist."""
        from src.services.correction_analysis import list_correction_analyses

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        analyses_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        analyses_result.scalars.return_value = scalars_mock
        mock_db.execute.side_effect = [count_result, analyses_result]

        analyses, total = await list_correction_analyses(uuid.uuid4(), mock_db)

        assert analyses == []
        assert total == 0


class TestGetCorrectionAnalysisById:
    """Tests for get_correction_analysis_by_id."""

    async def test_not_found(self):
        """Test that missing analysis raises 404."""
        from fastapi import HTTPException

        from src.services.correction_analysis import (
            get_correction_analysis_by_id,
        )

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await get_correction_analysis_by_id(uuid.uuid4(), uuid.uuid4(), mock_db)

        assert exc_info.value.status_code == 404

    async def test_found(self):
        """Test successful retrieval."""
        from src.services.correction_analysis import (
            get_correction_analysis_by_id,
        )

        mock_analysis = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_analysis
        mock_db.execute.return_value = result

        analysis = await get_correction_analysis_by_id(
            mock_analysis.id, mock_analysis.user_id, mock_db
        )

        assert analysis.id == mock_analysis.id


class TestCorrectionAnalysisEndpoints:
    """Integration tests for correction analysis API endpoints."""

    @patch("src.services.correction_analysis.get_ai_client")
    @patch("src.services.correction_analysis.analyze_correction_outcomes")
    async def test_analyze_endpoint(self, mock_analyze, mock_get_client):
        """Test POST /api/ai/corrections/analyze returns 201."""
        mock_analyze.return_value = [
            TimePeriodData(
                period="overnight",
                correction_count=3,
                under_count=1,
                over_count=0,
                avg_observed_isf=35.0,
                avg_glucose_drop=70.0,
            ),
            TimePeriodData(
                period="morning",
                correction_count=5,
                under_count=4,
                over_count=0,
                avg_observed_isf=28.0,
                avg_glucose_drop=56.0,
            ),
            TimePeriodData(
                period="afternoon",
                correction_count=3,
                under_count=0,
                over_count=1,
                avg_observed_isf=55.0,
                avg_glucose_drop=110.0,
            ),
            TimePeriodData(
                period="evening",
                correction_count=2,
                under_count=0,
                over_count=0,
                avg_observed_isf=45.0,
                avg_glucose_drop=90.0,
            ),
        ]

        mock_client = AsyncMock()
        mock_client.generate.return_value = _mock_ai_response(
            "Your morning correction factor may need strengthening."
        )
        mock_get_client.return_value = mock_client

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/corrections/analyze",
                json={"days": 7},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["total_corrections"] == 13
        assert data["under_corrections"] == 5
        assert data["over_corrections"] == 1
        assert (
            "Your morning correction factor may need strengthening."
            in data["ai_analysis"]
        )
        assert "Safety Notice" in data["ai_analysis"]
        assert len(data["time_periods_data"]) == 4
        assert "id" in data
        assert "created_at" in data

    @patch("src.services.correction_analysis.analyze_correction_outcomes")
    async def test_analyze_insufficient_data_endpoint(self, mock_analyze):
        """Test POST /api/ai/corrections/analyze returns 400."""
        mock_analyze.return_value = [
            TimePeriodData(
                period=p,
                correction_count=1 if p == "morning" else 0,
                under_count=0,
                over_count=0,
                avg_observed_isf=40.0 if p == "morning" else 0.0,
                avg_glucose_drop=80.0 if p == "morning" else 0.0,
            )
            for p in ["overnight", "morning", "afternoon", "evening"]
        ]

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/corrections/analyze",
                json={"days": 7},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 400
        assert "Insufficient correction data" in response.json()["detail"]

    async def test_analyze_unauthenticated(self):
        """Test POST /api/ai/corrections/analyze returns 401 without auth."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/ai/corrections/analyze",
                json={"days": 7},
            )

        assert response.status_code == 401

    async def test_list_analyses_endpoint(self):
        """Test GET /api/ai/corrections returns 200."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.get(
                "/api/ai/corrections",
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert "analyses" in data
        assert "total" in data

    async def test_list_analyses_unauthenticated(self):
        """Test GET /api/ai/corrections returns 401 without auth."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/ai/corrections")

        assert response.status_code == 401

    async def test_get_analysis_not_found(self):
        """Test GET /api/ai/corrections/{id} returns 404."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            fake_id = uuid.uuid4()
            response = await client.get(
                f"/api/ai/corrections/{fake_id}",
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 404

    @patch("src.services.correction_analysis.get_ai_client")
    @patch("src.services.correction_analysis.analyze_correction_outcomes")
    async def test_analyze_then_list_and_get(self, mock_analyze, mock_get_client):
        """Test generating an analysis, then listing and getting it."""
        mock_analyze.return_value = [
            TimePeriodData(
                period="overnight",
                correction_count=2,
                under_count=0,
                over_count=0,
                avg_observed_isf=45.0,
                avg_glucose_drop=90.0,
            ),
            TimePeriodData(
                period="morning",
                correction_count=4,
                under_count=2,
                over_count=0,
                avg_observed_isf=32.0,
                avg_glucose_drop=64.0,
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
        mock_client.generate.return_value = _mock_ai_response()
        mock_get_client.return_value = mock_client

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)
            cookies = {settings.jwt_cookie_name: cookie}

            # Generate analysis
            gen_response = await client.post(
                "/api/ai/corrections/analyze",
                json={"days": 7},
                cookies=cookies,
            )
            assert gen_response.status_code == 201
            analysis_id = gen_response.json()["id"]

            # List analyses
            list_response = await client.get(
                "/api/ai/corrections",
                cookies=cookies,
            )
            assert list_response.status_code == 200
            assert list_response.json()["total"] >= 1

            # Get specific analysis
            get_response = await client.get(
                f"/api/ai/corrections/{analysis_id}",
                cookies=cookies,
            )
            assert get_response.status_code == 200
            assert get_response.json()["id"] == analysis_id

    async def test_analyze_invalid_days(self):
        """Test POST /api/ai/corrections/analyze rejects days < 3."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/corrections/analyze",
                json={"days": 1},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 422

    async def test_analyze_days_too_large(self):
        """Test POST /api/ai/corrections/analyze rejects days > 30."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/corrections/analyze",
                json={"days": 60},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 422
