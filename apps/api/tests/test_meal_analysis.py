"""Story 5.4: Tests for meal pattern analysis and carb ratio suggestions."""

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
from src.schemas.meal_analysis import MealPeriodData
from src.services.meal_analysis import (
    _build_meal_prompt,
    _build_system_prompt,
    _classify_meal_period,
    analyze_post_meal_patterns,
)


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client: AsyncClient) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email("meal")
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
    content: str = "Breakfast shows consistent spikes.",
) -> AIResponse:
    """Create a mock AI response for testing."""
    return AIResponse(
        content=content,
        model="claude-sonnet-4-5-20250929",
        provider=AIProviderType.CLAUDE,
        usage=AIUsage(input_tokens=200, output_tokens=150),
    )


class TestClassifyMealPeriod:
    """Tests for _classify_meal_period."""

    def test_breakfast_hours(self):
        """Test hours 5-9 classify as breakfast."""
        for hour in [5, 6, 7, 8, 9]:
            assert _classify_meal_period(hour) == "breakfast"

    def test_lunch_hours(self):
        """Test hours 10-13 classify as lunch."""
        for hour in [10, 11, 12, 13]:
            assert _classify_meal_period(hour) == "lunch"

    def test_dinner_hours(self):
        """Test hours 17-20 classify as dinner."""
        for hour in [17, 18, 19, 20]:
            assert _classify_meal_period(hour) == "dinner"

    def test_snack_hours(self):
        """Test all other hours classify as snack."""
        for hour in [0, 1, 2, 3, 4, 14, 15, 16, 21, 22, 23]:
            assert _classify_meal_period(hour) == "snack"

    def test_boundary_breakfast_start(self):
        """Test hour 5 is breakfast, hour 4 is snack."""
        assert _classify_meal_period(5) == "breakfast"
        assert _classify_meal_period(4) == "snack"

    def test_boundary_breakfast_end(self):
        """Test hour 9 is breakfast, hour 10 is lunch."""
        assert _classify_meal_period(9) == "breakfast"
        assert _classify_meal_period(10) == "lunch"

    def test_boundary_dinner(self):
        """Test dinner boundaries: 16 is snack, 17 is dinner, 21 is snack."""
        assert _classify_meal_period(16) == "snack"
        assert _classify_meal_period(17) == "dinner"
        assert _classify_meal_period(21) == "snack"


class TestBuildMealPrompt:
    """Tests for _build_meal_prompt."""

    def test_prompt_includes_all_periods(self):
        """Test that the prompt includes data for all meal periods."""
        periods = [
            MealPeriodData(
                period="breakfast",
                bolus_count=5,
                spike_count=3,
                avg_peak_glucose=195.0,
                avg_2hr_glucose=175.0,
            ),
            MealPeriodData(
                period="lunch",
                bolus_count=4,
                spike_count=1,
                avg_peak_glucose=160.0,
                avg_2hr_glucose=140.0,
            ),
        ]

        prompt = _build_meal_prompt(periods, 9, 7)

        assert "7-day" in prompt
        assert "9" in prompt  # total boluses
        assert "Breakfast" in prompt
        assert "Lunch" in prompt
        assert "195" in prompt
        assert "160" in prompt
        assert "Spike rate: 60%" in prompt  # 3/5

    def _periods(self) -> list[MealPeriodData]:
        return [
            MealPeriodData(
                period="breakfast",
                bolus_count=5,
                spike_count=3,
                avg_peak_glucose=195.0,
                avg_2hr_glucose=140.0,
            ),
        ]

    def test_prompt_mgdl_unchanged_from_legacy(self):
        """mg/dL output is byte-identical to the pre-unit format (default unit)."""
        prompt = _build_meal_prompt(self._periods(), 5, 7, unit=GlucoseUnit.MGDL)

        assert "Post-meal spikes (>180 mg/dL): 3" in prompt
        assert "Average peak glucose: 195 mg/dL" in prompt
        assert "Average 2hr post-meal glucose: 140 mg/dL" in prompt

    def test_prompt_renders_mmol_unit(self):
        """Spike threshold (180->10.0), peak (195->10.8) and 2hr (140->7.8)
        convert; mg/dL never leaks."""
        prompt = _build_meal_prompt(self._periods(), 5, 7, unit=GlucoseUnit.MMOL)

        assert "Post-meal spikes (>10.0 mmol/L): 3" in prompt
        assert "Average peak glucose: 10.8 mmol/L" in prompt
        assert "Average 2hr post-meal glucose: 7.8 mmol/L" in prompt
        assert "mg/dL" not in prompt

    def test_system_prompt_states_user_unit(self):
        """Each system prompt names its report unit and spike threshold."""
        mgdl = _build_system_prompt(GlucoseUnit.MGDL)
        assert "(>180 mg/dL within 2 hours)" in mgdl
        assert "Report all glucose values in mg/dL" in mgdl

        mmol = _build_system_prompt(GlucoseUnit.MMOL)
        assert "(>10.0 mmol/L within 2 hours)" in mmol
        assert "Report all glucose values in mmol/L" in mmol

    def test_prompt_with_zero_bolus_period(self):
        """Test that zero-bolus periods don't produce spike rate."""
        periods = [
            MealPeriodData(
                period="snack",
                bolus_count=0,
                spike_count=0,
                avg_peak_glucose=0.0,
                avg_2hr_glucose=0.0,
            ),
        ]

        prompt = _build_meal_prompt(periods, 0, 7)

        assert "Snack" in prompt
        assert "Spike rate" not in prompt


class TestAnalyzePostMealPatterns:
    """Tests for analyze_post_meal_patterns."""

    async def test_no_boluses_returns_empty_periods(self):
        """Test that no boluses returns zeroed meal periods."""
        mock_db = AsyncMock()

        # First query: boluses (empty)
        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        bolus_result.scalars.return_value = scalars_mock

        # Second query: all glucose readings
        glucose_result = MagicMock()
        glucose_result.all.return_value = []

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_post_meal_patterns(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        assert len(periods) == 4
        for p in periods:
            assert p.bolus_count == 0
            assert p.spike_count == 0

    async def test_bolus_with_spike(self):
        """Test that a bolus followed by high readings detects a spike."""
        mock_db = AsyncMock()

        # Create a breakfast bolus at 7 AM
        bolus_time = datetime(2026, 2, 7, 7, 0, tzinfo=UTC)
        mock_bolus = SimpleNamespace(
            event_timestamp=bolus_time,
            event_type="bolus",
            is_automated=False,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_bolus]
        bolus_result.scalars.return_value = scalars_mock

        # All glucose readings (timestamp, value) sorted chronologically
        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            (bolus_time + timedelta(minutes=10), 150),
            (bolus_time + timedelta(minutes=30), 180),
            (bolus_time + timedelta(minutes=60), 200),
            (bolus_time + timedelta(minutes=90), 190),
            (bolus_time + timedelta(minutes=120), 170),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_post_meal_patterns(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        breakfast = next(p for p in periods if p.period == "breakfast")
        assert breakfast.bolus_count == 1
        assert breakfast.spike_count == 1  # peak 200 > 180
        assert breakfast.avg_peak_glucose == 200.0
        assert breakfast.avg_2hr_glucose == 170.0  # last reading

    async def test_bolus_without_spike(self):
        """Test that a bolus with good readings shows no spike."""
        mock_db = AsyncMock()

        # Lunch bolus at noon
        bolus_time = datetime(2026, 2, 7, 12, 0, tzinfo=UTC)
        mock_bolus = SimpleNamespace(
            event_timestamp=bolus_time,
            event_type="bolus",
            is_automated=False,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_bolus]
        bolus_result.scalars.return_value = scalars_mock

        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            (bolus_time + timedelta(minutes=10), 130),
            (bolus_time + timedelta(minutes=30), 150),
            (bolus_time + timedelta(minutes=60), 160),
            (bolus_time + timedelta(minutes=90), 145),
            (bolus_time + timedelta(minutes=120), 130),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_post_meal_patterns(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        lunch = next(p for p in periods if p.period == "lunch")
        assert lunch.bolus_count == 1
        assert lunch.spike_count == 0  # peak 160 <= 180
        assert lunch.avg_peak_glucose == 160.0

    async def test_bolus_with_no_readings_skipped(self):
        """Test that boluses with no subsequent readings are skipped."""
        mock_db = AsyncMock()

        bolus_time = datetime(2026, 2, 7, 18, 0, tzinfo=UTC)
        mock_bolus = SimpleNamespace(
            event_timestamp=bolus_time,
            event_type="bolus",
            is_automated=False,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_bolus]
        bolus_result.scalars.return_value = scalars_mock

        # No glucose readings in the window
        glucose_result = MagicMock()
        glucose_result.all.return_value = []

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_post_meal_patterns(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        dinner = next(p for p in periods if p.period == "dinner")
        assert dinner.bolus_count == 0  # skipped because no readings

    async def test_multiple_boluses_same_period(self):
        """Test averaging across multiple meals in the same period."""
        mock_db = AsyncMock()

        bolus1_time = datetime(2026, 2, 6, 7, 0, tzinfo=UTC)
        bolus2_time = datetime(2026, 2, 7, 8, 0, tzinfo=UTC)
        bolus1 = SimpleNamespace(
            event_timestamp=bolus1_time,
            event_type="bolus",
            is_automated=False,
        )
        bolus2 = SimpleNamespace(
            event_timestamp=bolus2_time,
            event_type="bolus",
            is_automated=False,
        )

        bolus_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [bolus1, bolus2]
        bolus_result.scalars.return_value = scalars_mock

        # All readings sorted by timestamp, covering both bolus windows
        glucose_result = MagicMock()
        glucose_result.all.return_value = [
            # Bolus 1 window (Feb 6, 7:00-9:00): spike to 200
            (bolus1_time + timedelta(minutes=30), 160),
            (bolus1_time + timedelta(minutes=60), 200),
            (bolus1_time + timedelta(minutes=120), 180),
            # Bolus 2 window (Feb 7, 8:00-10:00): spike to 190
            (bolus2_time + timedelta(minutes=30), 140),
            (bolus2_time + timedelta(minutes=60), 190),
            (bolus2_time + timedelta(minutes=120), 165),
        ]

        mock_db.execute.side_effect = [bolus_result, glucose_result]

        now = datetime.now(UTC)
        periods = await analyze_post_meal_patterns(
            uuid.uuid4(), mock_db, now - timedelta(days=7), now
        )

        breakfast = next(p for p in periods if p.period == "breakfast")
        assert breakfast.bolus_count == 2
        assert breakfast.spike_count == 2  # both > 180
        assert breakfast.avg_peak_glucose == 195.0  # (200 + 190) / 2
        assert breakfast.avg_2hr_glucose == 172.5  # (180 + 165) / 2


class TestGenerateMealAnalysis:
    """Tests for generate_meal_analysis service function."""

    @patch("src.services.meal_analysis.get_ai_client")
    @patch("src.services.meal_analysis.analyze_post_meal_patterns")
    async def test_generate_analysis_success(self, mock_analyze, mock_get_client):
        """Test successful meal analysis generation."""
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
                bolus_count=4,
                spike_count=1,
                avg_peak_glucose=165.0,
                avg_2hr_glucose=145.0,
            ),
            MealPeriodData(
                period="dinner",
                bolus_count=3,
                spike_count=0,
                avg_peak_glucose=155.0,
                avg_2hr_glucose=135.0,
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
        mock_client.generate.return_value = _mock_ai_response()
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        analysis = await generate_meal_analysis(mock_user, mock_db, days=7)

        assert analysis.total_boluses == 12
        assert analysis.total_spikes == 4
        # Weighted avg: (195*5 + 165*4 + 155*3) / 12 = 2100/12 = 175.0
        assert analysis.avg_post_meal_peak == 175.0
        assert "Breakfast shows consistent spikes." in analysis.ai_analysis
        assert "Safety Notice" in analysis.ai_analysis
        assert len(analysis.meal_periods_data) == 4
        # db.add called twice: once for analysis, once for safety log
        assert mock_db.add.call_count == 2
        mock_db.commit.assert_called_once()

    @patch("src.services.meal_analysis.analyze_post_meal_patterns")
    async def test_generate_analysis_insufficient_data(self, mock_analyze):
        """Test that insufficient boluses raises 400."""
        from fastapi import HTTPException

        from src.services.meal_analysis import generate_meal_analysis

        mock_analyze.return_value = [
            MealPeriodData(
                period="breakfast",
                bolus_count=2,
                spike_count=1,
                avg_peak_glucose=190.0,
                avg_2hr_glucose=170.0,
            ),
            MealPeriodData(
                period="lunch",
                bolus_count=1,
                spike_count=0,
                avg_peak_glucose=150.0,
                avg_2hr_glucose=130.0,
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

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await generate_meal_analysis(mock_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Insufficient meal data" in exc_info.value.detail

    @patch("src.services.meal_analysis.get_ai_client")
    @patch("src.services.meal_analysis.analyze_post_meal_patterns")
    async def test_generate_analysis_ai_error_propagates(
        self, mock_analyze, mock_get_client
    ):
        """Test that AI provider errors propagate."""
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
        mock_client.generate.side_effect = RuntimeError("AI failed")
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4(), glucose_unit=GlucoseUnit.MGDL)
        mock_db = AsyncMock()

        with pytest.raises(RuntimeError, match="AI failed"):
            await generate_meal_analysis(mock_user, mock_db)


class TestListMealAnalyses:
    """Tests for list_meal_analyses."""

    async def test_list_empty(self):
        """Test listing when no analyses exist."""
        from src.services.meal_analysis import list_meal_analyses

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        analyses_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        analyses_result.scalars.return_value = scalars_mock
        mock_db.execute.side_effect = [count_result, analyses_result]

        analyses, total = await list_meal_analyses(uuid.uuid4(), mock_db)

        assert analyses == []
        assert total == 0


class TestGetMealAnalysisById:
    """Tests for get_meal_analysis_by_id."""

    async def test_not_found(self):
        """Test that missing analysis raises 404."""
        from fastapi import HTTPException

        from src.services.meal_analysis import get_meal_analysis_by_id

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await get_meal_analysis_by_id(uuid.uuid4(), uuid.uuid4(), mock_db)

        assert exc_info.value.status_code == 404

    async def test_found(self):
        """Test successful retrieval."""
        from src.services.meal_analysis import get_meal_analysis_by_id

        mock_analysis = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_analysis
        mock_db.execute.return_value = result

        analysis = await get_meal_analysis_by_id(
            mock_analysis.id, mock_analysis.user_id, mock_db
        )

        assert analysis.id == mock_analysis.id


class TestMealAnalysisEndpoints:
    """Integration tests for meal analysis API endpoints."""

    @patch("src.services.meal_analysis.get_ai_client")
    @patch("src.services.meal_analysis.analyze_post_meal_patterns")
    async def test_analyze_endpoint(self, mock_analyze, mock_get_client):
        """Test POST /api/ai/meals/analyze returns 201."""
        mock_analyze.return_value = [
            MealPeriodData(
                period="breakfast",
                bolus_count=6,
                spike_count=4,
                avg_peak_glucose=200.0,
                avg_2hr_glucose=180.0,
            ),
            MealPeriodData(
                period="lunch",
                bolus_count=5,
                spike_count=1,
                avg_peak_glucose=165.0,
                avg_2hr_glucose=145.0,
            ),
            MealPeriodData(
                period="dinner",
                bolus_count=4,
                spike_count=0,
                avg_peak_glucose=155.0,
                avg_2hr_glucose=135.0,
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
        mock_client.generate.return_value = _mock_ai_response(
            "Your breakfast carb ratio may need adjustment."
        )
        mock_get_client.return_value = mock_client

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/meals/analyze",
                json={"days": 7},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["total_boluses"] == 15
        assert data["total_spikes"] == 5
        assert "Your breakfast carb ratio may need adjustment." in data["ai_analysis"]
        assert "Safety Notice" in data["ai_analysis"]
        assert len(data["meal_periods_data"]) == 4
        assert "id" in data
        assert "created_at" in data

    @patch("src.services.meal_analysis.analyze_post_meal_patterns")
    async def test_analyze_insufficient_data_endpoint(self, mock_analyze):
        """Test POST /api/ai/meals/analyze returns 400 with insufficient data."""
        mock_analyze.return_value = [
            MealPeriodData(
                period=p,
                bolus_count=1 if p == "breakfast" else 0,
                spike_count=0,
                avg_peak_glucose=150.0 if p == "breakfast" else 0.0,
                avg_2hr_glucose=130.0 if p == "breakfast" else 0.0,
            )
            for p in ["breakfast", "lunch", "dinner", "snack"]
        ]

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/meals/analyze",
                json={"days": 7},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 400
        assert "Insufficient meal data" in response.json()["detail"]

    async def test_analyze_unauthenticated(self):
        """Test POST /api/ai/meals/analyze returns 401 without auth."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/ai/meals/analyze",
                json={"days": 7},
            )

        assert response.status_code == 401

    async def test_list_analyses_endpoint(self):
        """Test GET /api/ai/meals returns 200."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.get(
                "/api/ai/meals",
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert "analyses" in data
        assert "total" in data

    async def test_list_analyses_unauthenticated(self):
        """Test GET /api/ai/meals returns 401 without auth."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/ai/meals")

        assert response.status_code == 401

    async def test_get_analysis_not_found(self):
        """Test GET /api/ai/meals/{id} returns 404."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            fake_id = uuid.uuid4()
            response = await client.get(
                f"/api/ai/meals/{fake_id}",
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 404

    @patch("src.services.meal_analysis.get_ai_client")
    @patch("src.services.meal_analysis.analyze_post_meal_patterns")
    async def test_analyze_then_list_and_get(self, mock_analyze, mock_get_client):
        """Test generating an analysis, then listing and getting it."""
        mock_analyze.return_value = [
            MealPeriodData(
                period="breakfast",
                bolus_count=5,
                spike_count=3,
                avg_peak_glucose=190.0,
                avg_2hr_glucose=170.0,
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
                "/api/ai/meals/analyze",
                json={"days": 7},
                cookies=cookies,
            )
            assert gen_response.status_code == 201
            analysis_id = gen_response.json()["id"]

            # List analyses
            list_response = await client.get(
                "/api/ai/meals",
                cookies=cookies,
            )
            assert list_response.status_code == 200
            assert list_response.json()["total"] >= 1

            # Get specific analysis
            get_response = await client.get(
                f"/api/ai/meals/{analysis_id}",
                cookies=cookies,
            )
            assert get_response.status_code == 200
            assert get_response.json()["id"] == analysis_id

    async def test_analyze_invalid_days(self):
        """Test POST /api/ai/meals/analyze rejects days < 3."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/meals/analyze",
                json={"days": 1},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 422

    async def test_analyze_days_too_large(self):
        """Test POST /api/ai/meals/analyze rejects days > 30."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/meals/analyze",
                json={"days": 60},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 422


def test_build_meal_prompt_is_public_and_pure():
    from src.schemas.meal_analysis import MealPeriodData
    from src.services.meal_analysis import _build_system_prompt, build_meal_prompt

    periods = [
        MealPeriodData(
            period="breakfast", bolus_count=10, spike_count=7,
            avg_peak_glucose=187.0, avg_2hr_glucose=164.0,
        )
    ]
    prompt = build_meal_prompt(periods, total_boluses=10, days=7, profile_summary=None)
    assert "Breakfast" in prompt
    assert "187" in prompt
    system_prompt = _build_system_prompt()
    assert isinstance(system_prompt, str) and "Type 1 diabetes" in system_prompt
