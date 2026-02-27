"""Story 5.3: Tests for daily brief generation."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app
from src.models.ai_provider import AIProviderType
from src.schemas.ai_response import AIResponse, AIUsage
from src.schemas.daily_brief import DailyBriefMetrics
from src.services.daily_brief import (
    HIGH_THRESHOLD,
    LOW_THRESHOLD,
    MIN_READINGS,
    _build_analysis_prompt,
    calculate_metrics,
)


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client: AsyncClient) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email("brief")
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


def _mock_ai_response(content: str = "Your glucose was well controlled.") -> AIResponse:
    """Create a mock AI response for testing."""
    return AIResponse(
        content=content,
        model="claude-sonnet-4-5-20250929",
        provider=AIProviderType.CLAUDE,
        usage=AIUsage(input_tokens=100, output_tokens=50),
    )


class TestCalculateMetrics:
    """Tests for calculate_metrics function."""

    async def test_no_readings_returns_zero_metrics(self):
        """Test that zero readings returns all-zero metrics."""
        mock_db = AsyncMock()

        # Mock glucose query - no readings
        glucose_result = MagicMock()
        glucose_result.all.return_value = []

        mock_db.execute.return_value = glucose_result

        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        metrics = await calculate_metrics(
            user_id, mock_db, now - timedelta(hours=24), now
        )

        assert metrics.readings_count == 0
        assert metrics.average_glucose == 0.0
        assert metrics.time_in_range_pct == 0.0
        assert metrics.low_count == 0
        assert metrics.high_count == 0

    async def test_all_in_range_readings(self):
        """Test metrics with all readings in range."""
        mock_db = AsyncMock()

        # Mock glucose query - all in range (70-180)
        glucose_result = MagicMock()
        glucose_result.all.return_value = [(120,), (130,), (110,), (140,), (100,)]

        # Mock correction count query
        correction_result = MagicMock()
        correction_result.scalar.return_value = 0

        # Mock total insulin query
        insulin_result = MagicMock()
        insulin_result.scalar.return_value = 25.5

        mock_db.execute.side_effect = [
            glucose_result,
            correction_result,
            insulin_result,
        ]

        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        metrics = await calculate_metrics(
            user_id, mock_db, now - timedelta(hours=24), now
        )

        assert metrics.readings_count == 5
        assert metrics.time_in_range_pct == 100.0
        assert metrics.average_glucose == 120.0
        assert metrics.low_count == 0
        assert metrics.high_count == 0
        assert metrics.total_insulin == 25.5

    async def test_mixed_readings_with_lows_and_highs(self):
        """Test metrics with a mix of low, in-range, and high readings."""
        mock_db = AsyncMock()

        # 2 low, 3 in range, 1 high = 6 readings
        glucose_result = MagicMock()
        glucose_result.all.return_value = [(55,), (65,), (120,), (130,), (150,), (200,)]

        correction_result = MagicMock()
        correction_result.scalar.return_value = 3

        insulin_result = MagicMock()
        insulin_result.scalar.return_value = None

        mock_db.execute.side_effect = [
            glucose_result,
            correction_result,
            insulin_result,
        ]

        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        metrics = await calculate_metrics(
            user_id, mock_db, now - timedelta(hours=24), now
        )

        assert metrics.readings_count == 6
        assert metrics.time_in_range_pct == 50.0
        assert metrics.low_count == 2
        assert metrics.high_count == 1
        assert metrics.correction_count == 3
        assert metrics.total_insulin is None

    async def test_boundary_values(self):
        """Test that boundary values are classified correctly."""
        mock_db = AsyncMock()

        # 70 is in range, 69 is low, 180 is in range, 181 is high
        glucose_result = MagicMock()
        glucose_result.all.return_value = [(69,), (70,), (180,), (181,)]

        correction_result = MagicMock()
        correction_result.scalar.return_value = 0

        insulin_result = MagicMock()
        insulin_result.scalar.return_value = None

        mock_db.execute.side_effect = [
            glucose_result,
            correction_result,
            insulin_result,
        ]

        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        metrics = await calculate_metrics(
            user_id, mock_db, now - timedelta(hours=24), now
        )

        assert metrics.low_count == 1  # 69
        assert metrics.high_count == 1  # 181
        assert metrics.time_in_range_pct == 50.0  # 70, 180 in range


class TestBuildAnalysisPrompt:
    """Tests for _build_analysis_prompt."""

    def test_prompt_includes_metrics(self):
        """Test that the prompt includes all metric values."""
        metrics = DailyBriefMetrics(
            time_in_range_pct=75.5,
            average_glucose=142.3,
            low_count=2,
            high_count=5,
            readings_count=288,
            correction_count=4,
            total_insulin=35.2,
        )

        prompt = _build_analysis_prompt(metrics, 24)

        assert "24-hour" in prompt
        assert "288" in prompt
        assert "142" in prompt
        assert "75.5%" in prompt
        assert f"<{LOW_THRESHOLD}" in prompt
        assert f">{HIGH_THRESHOLD}" in prompt
        assert "2" in prompt  # lows
        assert "5" in prompt  # highs
        assert "4" in prompt  # corrections
        assert "35.2 units" in prompt

    def test_prompt_without_insulin_data(self):
        """Test that insulin line is omitted when data is None."""
        metrics = DailyBriefMetrics(
            time_in_range_pct=80.0,
            average_glucose=130.0,
            low_count=0,
            high_count=3,
            readings_count=100,
            correction_count=1,
            total_insulin=None,
        )

        prompt = _build_analysis_prompt(metrics, 24)

        assert "insulin delivered" not in prompt

    def test_prompt_custom_hours(self):
        """Test that custom hour count is reflected in the prompt."""
        metrics = DailyBriefMetrics(
            time_in_range_pct=80.0,
            average_glucose=130.0,
            low_count=0,
            high_count=0,
            readings_count=50,
            correction_count=0,
        )

        prompt = _build_analysis_prompt(metrics, 48)

        assert "48-hour" in prompt


class TestGenerateDailyBrief:
    """Tests for the generate_daily_brief service function."""

    @patch("src.services.daily_brief.notify_user_of_brief", new_callable=AsyncMock)
    @patch("src.services.daily_brief.get_ai_client")
    @patch("src.services.daily_brief.calculate_metrics")
    async def test_generate_brief_success(
        self, mock_calc, mock_get_client, mock_notify
    ):
        """Test successful brief generation."""
        from src.services.daily_brief import generate_daily_brief

        mock_calc.return_value = DailyBriefMetrics(
            time_in_range_pct=72.5,
            average_glucose=145.0,
            low_count=1,
            high_count=8,
            readings_count=288,
            correction_count=5,
            total_insulin=40.0,
        )

        mock_client = AsyncMock()
        mock_client.generate.return_value = _mock_ai_response()
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_db = AsyncMock()

        brief = await generate_daily_brief(mock_user, mock_db, hours=24)

        assert brief.time_in_range_pct == 72.5
        assert brief.average_glucose == 145.0
        assert brief.low_count == 1
        assert brief.high_count == 8
        assert brief.readings_count == 288
        assert "Your glucose was well controlled." in brief.ai_summary
        assert "Safety Notice" in brief.ai_summary
        assert brief.ai_model == "claude-sonnet-4-5-20250929"
        assert brief.ai_provider == "claude"
        assert brief.input_tokens == 100
        assert brief.output_tokens == 50
        assert mock_db.add.call_count == 2  # brief + safety log
        mock_db.flush.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("src.services.daily_brief.calculate_metrics")
    async def test_generate_brief_insufficient_data(self, mock_calc):
        """Test that insufficient readings raises 400."""
        from fastapi import HTTPException

        from src.services.daily_brief import generate_daily_brief

        mock_calc.return_value = DailyBriefMetrics(
            time_in_range_pct=0.0,
            average_glucose=0.0,
            low_count=0,
            high_count=0,
            readings_count=MIN_READINGS - 1,
            correction_count=0,
        )

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await generate_daily_brief(mock_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Insufficient glucose data" in exc_info.value.detail

    @patch("src.services.daily_brief.get_ai_client")
    @patch("src.services.daily_brief.calculate_metrics")
    async def test_generate_brief_ai_error_propagates(self, mock_calc, mock_get_client):
        """Test that AI provider errors propagate."""
        from src.services.daily_brief import generate_daily_brief

        mock_calc.return_value = DailyBriefMetrics(
            time_in_range_pct=80.0,
            average_glucose=130.0,
            low_count=0,
            high_count=2,
            readings_count=200,
            correction_count=1,
        )

        mock_client = AsyncMock()
        mock_client.generate.side_effect = RuntimeError("AI provider failed")
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_db = AsyncMock()

        with pytest.raises(RuntimeError, match="AI provider failed"):
            await generate_daily_brief(mock_user, mock_db)

    @patch("src.services.daily_brief.notify_user_of_brief", new_callable=AsyncMock)
    @patch("src.services.daily_brief.get_ai_client")
    @patch("src.services.daily_brief.calculate_metrics")
    async def test_generate_brief_custom_hours(
        self, mock_calc, mock_get_client, mock_notify
    ):
        """Test that custom hours parameter is used."""
        from src.services.daily_brief import generate_daily_brief

        mock_calc.return_value = DailyBriefMetrics(
            time_in_range_pct=80.0,
            average_glucose=130.0,
            low_count=0,
            high_count=2,
            readings_count=500,
            correction_count=1,
        )

        mock_client = AsyncMock()
        mock_client.generate.return_value = _mock_ai_response()
        mock_get_client.return_value = mock_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_db = AsyncMock()

        brief = await generate_daily_brief(mock_user, mock_db, hours=48)

        # Verify period is roughly 48 hours
        delta = brief.period_end - brief.period_start
        assert abs(delta.total_seconds() - 48 * 3600) < 5


class TestListBriefs:
    """Tests for list_briefs service function."""

    async def test_list_briefs_empty(self):
        """Test listing briefs when none exist."""
        from src.services.daily_brief import list_briefs

        mock_db = AsyncMock()

        # Mock count query
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        # Mock briefs query
        briefs_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        briefs_result.scalars.return_value = scalars_mock

        mock_db.execute.side_effect = [count_result, briefs_result]

        briefs, total = await list_briefs(uuid.uuid4(), mock_db)

        assert briefs == []
        assert total == 0

    async def test_list_briefs_with_pagination(self):
        """Test that pagination parameters are passed to the query."""
        from src.services.daily_brief import list_briefs

        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 25

        briefs_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = ["brief1", "brief2"]
        briefs_result.scalars.return_value = scalars_mock

        mock_db.execute.side_effect = [count_result, briefs_result]

        briefs, total = await list_briefs(uuid.uuid4(), mock_db, limit=2, offset=10)

        assert len(briefs) == 2
        assert total == 25


class TestGetBriefById:
    """Tests for get_brief_by_id service function."""

    async def test_get_brief_not_found(self):
        """Test that missing brief raises 404."""
        from fastapi import HTTPException

        from src.services.daily_brief import get_brief_by_id

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await get_brief_by_id(uuid.uuid4(), uuid.uuid4(), mock_db)

        assert exc_info.value.status_code == 404

    async def test_get_brief_found(self):
        """Test successful brief retrieval."""
        from src.services.daily_brief import get_brief_by_id

        mock_brief = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_brief
        mock_db.execute.return_value = result

        brief = await get_brief_by_id(mock_brief.id, mock_brief.user_id, mock_db)

        assert brief.id == mock_brief.id


class TestBriefsEndpoints:
    """Integration tests for daily brief API endpoints."""

    @patch("src.services.daily_brief.get_ai_client")
    @patch("src.services.daily_brief.calculate_metrics")
    async def test_generate_brief_endpoint(self, mock_calc, mock_get_client):
        """Test POST /api/ai/briefs/generate returns 201."""
        mock_calc.return_value = DailyBriefMetrics(
            time_in_range_pct=75.0,
            average_glucose=140.0,
            low_count=1,
            high_count=5,
            readings_count=288,
            correction_count=3,
            total_insulin=38.0,
        )

        mock_client = AsyncMock()
        mock_client.generate.return_value = _mock_ai_response(
            "Good day overall with some highs."
        )
        mock_get_client.return_value = mock_client

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/briefs/generate",
                json={"hours": 24},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["time_in_range_pct"] == 75.0
        assert data["average_glucose"] == 140.0
        assert "Good day overall with some highs." in data["ai_summary"]
        assert "Safety Notice" in data["ai_summary"]
        assert data["ai_model"] == "claude-sonnet-4-5-20250929"
        assert "id" in data
        assert "created_at" in data

    @patch("src.services.daily_brief.calculate_metrics")
    async def test_generate_brief_insufficient_data_endpoint(self, mock_calc):
        """Test POST /api/ai/briefs/generate returns 400 with insufficient data."""
        mock_calc.return_value = DailyBriefMetrics(
            time_in_range_pct=0.0,
            average_glucose=0.0,
            low_count=0,
            high_count=0,
            readings_count=5,
            correction_count=0,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/briefs/generate",
                json={"hours": 24},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 400
        assert "Insufficient glucose data" in response.json()["detail"]

    async def test_generate_brief_unauthenticated(self):
        """Test POST /api/ai/briefs/generate returns 401 without auth."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/ai/briefs/generate",
                json={"hours": 24},
            )

        assert response.status_code == 401

    async def test_list_briefs_endpoint(self):
        """Test GET /api/ai/briefs returns 200."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.get(
                "/api/ai/briefs",
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert "briefs" in data
        assert "total" in data
        assert data["total"] == 0

    async def test_list_briefs_unauthenticated(self):
        """Test GET /api/ai/briefs returns 401 without auth."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/ai/briefs")

        assert response.status_code == 401

    async def test_get_brief_not_found_endpoint(self):
        """Test GET /api/ai/briefs/{id} returns 404 for missing brief."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            fake_id = uuid.uuid4()
            response = await client.get(
                f"/api/ai/briefs/{fake_id}",
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 404

    @patch("src.services.daily_brief.get_ai_client")
    @patch("src.services.daily_brief.calculate_metrics")
    async def test_generate_then_list_and_get(self, mock_calc, mock_get_client):
        """Test generating a brief, then listing and getting it by ID."""
        mock_calc.return_value = DailyBriefMetrics(
            time_in_range_pct=85.0,
            average_glucose=125.0,
            low_count=0,
            high_count=2,
            readings_count=280,
            correction_count=1,
            total_insulin=32.0,
        )

        mock_client = AsyncMock()
        mock_client.generate.return_value = _mock_ai_response("Great control today!")
        mock_get_client.return_value = mock_client

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)
            cookies = {settings.jwt_cookie_name: cookie}

            # Generate a brief
            gen_response = await client.post(
                "/api/ai/briefs/generate",
                json={"hours": 24},
                cookies=cookies,
            )
            assert gen_response.status_code == 201
            brief_id = gen_response.json()["id"]

            # List briefs
            list_response = await client.get(
                "/api/ai/briefs",
                cookies=cookies,
            )
            assert list_response.status_code == 200
            list_data = list_response.json()
            assert list_data["total"] >= 1

            # Get specific brief
            get_response = await client.get(
                f"/api/ai/briefs/{brief_id}",
                cookies=cookies,
            )
            assert get_response.status_code == 200
            assert get_response.json()["id"] == brief_id
            assert "Great control today!" in get_response.json()["ai_summary"]
            assert "Safety Notice" in get_response.json()["ai_summary"]

    async def test_generate_brief_invalid_hours(self):
        """Test POST /api/ai/briefs/generate rejects invalid hours."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/briefs/generate",
                json={"hours": 0},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 422

    async def test_generate_brief_hours_too_large(self):
        """Test POST /api/ai/briefs/generate rejects hours > 72."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/briefs/generate",
                json={"hours": 100},
                cookies={settings.jwt_cookie_name: cookie},
            )

        assert response.status_code == 422
