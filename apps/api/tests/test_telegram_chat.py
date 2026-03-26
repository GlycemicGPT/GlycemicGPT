"""Stories 7.5 & 15.7: Tests for AI chat via Telegram."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.ai_provider import AIProviderType
from src.models.glucose import GlucoseReading, TrendDirection
from src.models.user import User
from src.schemas.ai_response import AIResponse, AIUsage
from src.services.diabetes_context import (
    build_control_iq_section,
    build_diabetes_context,
    build_glucose_section,
    build_iob_section,
    build_pump_profile_section,
    build_pump_section,
    build_settings_section,
)
from src.services.iob_projection import IoBProjection
from src.services.telegram_chat import (
    MAX_USER_MESSAGE_LENGTH,
    SAFETY_DISCLAIMER,
    TELEGRAM_MAX_LENGTH,
    _build_system_prompt,
    _truncate_response,
    handle_chat,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def make_reading(
    value: int = 120,
    trend_rate: float = 0.5,
    minutes_ago: int = 3,
    trend: TrendDirection = TrendDirection.FLAT,
    user_id: uuid.UUID | None = None,
) -> MagicMock:
    """Create a mock GlucoseReading."""
    reading = MagicMock(spec=GlucoseReading)
    reading.value = value
    reading.trend_rate = trend_rate
    reading.trend = trend
    reading.reading_timestamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    reading.user_id = user_id or uuid.uuid4()
    return reading


def make_iob(
    projected_iob: float = 2.5,
    is_stale: bool = False,
) -> IoBProjection:
    """Create a real IoBProjection dataclass."""
    now = datetime.now(UTC)
    return IoBProjection(
        confirmed_iob=3.0,
        confirmed_at=now - timedelta(minutes=30),
        projected_iob=projected_iob,
        projected_at=now,
        projected_30min=1.8,
        projected_60min=0.9,
        minutes_since_confirmed=30,
        is_stale=is_stale,
        stale_warning="IoB data is stale" if is_stale else None,
    )


def make_ai_response(content: str = "AI says hello") -> AIResponse:
    """Create a mock AIResponse."""
    return AIResponse(
        content=content,
        model="claude-sonnet-4-5-20250929",
        provider=AIProviderType.CLAUDE,
        usage=AIUsage(input_tokens=100, output_tokens=50),
    )


def make_user(user_id: uuid.UUID | None = None) -> MagicMock:
    """Create a mock User."""
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.email = "test@example.com"
    return user


def make_pump_event(
    event_type: str = "bolus",
    units: float | None = 2.0,
    is_automated: bool = False,
    basal_adjustment_pct: float | None = None,
    minutes_ago: int = 30,
) -> MagicMock:
    """Create a mock PumpEvent."""
    from src.models.pump_data import PumpEvent, PumpEventType

    event = MagicMock(spec=PumpEvent)
    event.event_type = PumpEventType(event_type)
    event.units = units
    event.is_automated = is_automated
    event.basal_adjustment_pct = basal_adjustment_pct
    event.event_timestamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return event


def make_ciq_summary(**kwargs) -> MagicMock:
    """Create a mock ControlIQActivitySummary."""
    defaults = {
        "total_events": 50,
        "automated_events": 35,
        "manual_events": 15,
        "correction_count": 8,
        "total_correction_units": 3.5,
        "basal_increase_count": 12,
        "basal_decrease_count": 6,
        "avg_basal_adjustment_pct": 10.5,
        "suspend_count": 2,
        "automated_suspend_count": 1,
        "sleep_mode_events": 10,
        "exercise_mode_events": 0,
        "standard_mode_events": 25,
        "start_time": datetime.now(UTC) - timedelta(hours=24),
        "end_time": datetime.now(UTC),
    }
    defaults.update(kwargs)
    summary = MagicMock()
    for k, v in defaults.items():
        setattr(summary, k, v)
    return summary


# ---------------------------------------------------------------------------
# Individual section builder tests (Story 15.7)
# ---------------------------------------------------------------------------
class TestBuildGlucoseSection:
    """Tests for build_glucose_section."""

    @pytest.mark.asyncio
    async def test_no_readings_returns_none(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await build_glucose_section(db, uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_formats_glucose_summary(self):
        readings = [make_reading(value=150, trend_rate=1.5, minutes_ago=3)]
        readings += [make_reading(value=120, minutes_ago=i * 5) for i in range(1, 10)]

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = readings
        db.execute = AsyncMock(side_effect=[mock_result, _mock_none_scalar()])

        result = await build_glucose_section(db, uuid.uuid4())

        assert result is not None
        assert "[Glucose - last 6h]" in result
        assert "150 mg/dL" in result
        assert "Readings: 10" in result

    @pytest.mark.asyncio
    async def test_uses_custom_target_range_for_tir(self):
        readings = [make_reading(value=85, minutes_ago=i * 5) for i in range(5)]

        mock_range = MagicMock()
        mock_range.low_target = 80.0
        mock_range.high_target = 120.0

        db = AsyncMock()
        mock_readings_result = MagicMock()
        mock_readings_result.scalars.return_value.all.return_value = readings
        mock_range_result = MagicMock()
        mock_range_result.scalar_one_or_none.return_value = mock_range
        db.execute = AsyncMock(side_effect=[mock_readings_result, mock_range_result])

        result = await build_glucose_section(db, uuid.uuid4())

        assert "80-120" in result
        assert "100%" in result  # All readings are in range 80-120

    @pytest.mark.asyncio
    async def test_single_reading_calculates_correctly(self):
        readings = [make_reading(value=200, minutes_ago=2)]

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = readings
        db.execute = AsyncMock(side_effect=[mock_result, _mock_none_scalar()])

        result = await build_glucose_section(db, uuid.uuid4())

        assert "200-200" in result  # min==max for single reading
        assert "Avg: 200" in result
        assert "Readings: 1" in result


class TestBuildIobSection:
    """Tests for build_iob_section."""

    @pytest.mark.asyncio
    @patch("src.services.diabetes_context.get_iob_projection", new_callable=AsyncMock)
    @patch("src.services.diabetes_context.get_user_dia", new_callable=AsyncMock)
    async def test_formats_iob(self, mock_dia, mock_iob):
        mock_dia.return_value = 4.0
        mock_iob.return_value = make_iob(projected_iob=2.5)

        result = await build_iob_section(AsyncMock(), uuid.uuid4())

        assert "[Insulin on Board]" in result
        assert "2.5 units" in result
        assert "30min" in result
        assert "60min" in result

    @pytest.mark.asyncio
    @patch("src.services.diabetes_context.get_iob_projection", new_callable=AsyncMock)
    @patch("src.services.diabetes_context.get_user_dia", new_callable=AsyncMock)
    async def test_stale_iob_shows_warning(self, mock_dia, mock_iob):
        mock_dia.return_value = 4.0
        mock_iob.return_value = make_iob(projected_iob=1.0, is_stale=True)

        result = await build_iob_section(AsyncMock(), uuid.uuid4())

        assert "stale" in result.lower()

    @pytest.mark.asyncio
    @patch("src.services.diabetes_context.get_iob_projection", new_callable=AsyncMock)
    @patch("src.services.diabetes_context.get_user_dia", new_callable=AsyncMock)
    async def test_no_iob_returns_none(self, mock_dia, mock_iob):
        mock_dia.return_value = 4.0
        mock_iob.return_value = None

        result = await build_iob_section(AsyncMock(), uuid.uuid4())
        assert result is None


class TestBuildPumpSection:
    """Tests for build_pump_section."""

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_pump_events", new_callable=AsyncMock)
    async def test_no_events_returns_none(self, mock_get_events):
        mock_get_events.return_value = []
        result = await build_pump_section(AsyncMock(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_pump_events", new_callable=AsyncMock)
    async def test_counts_manual_boluses(self, mock_get_events):
        mock_get_events.return_value = [
            make_pump_event("bolus", units=3.0, is_automated=False),
            make_pump_event("bolus", units=5.0, is_automated=False),
        ]
        result = await build_pump_section(AsyncMock(), uuid.uuid4())

        assert "Manual boluses: 2" in result
        assert "8.0u total" in result

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_pump_events", new_callable=AsyncMock)
    async def test_counts_auto_corrections(self, mock_get_events):
        mock_get_events.return_value = [
            make_pump_event("correction", units=0.5, is_automated=True, minutes_ago=10),
        ]
        result = await build_pump_section(AsyncMock(), uuid.uuid4())

        assert "Auto-corrections (Control-IQ): 1" in result
        assert "0.5u total" in result
        assert "Last auto-correction" in result

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_pump_events", new_callable=AsyncMock)
    async def test_counts_basal_adjustments(self, mock_get_events):
        mock_get_events.return_value = [
            make_pump_event("basal", is_automated=True, basal_adjustment_pct=15.0),
            make_pump_event("basal", is_automated=True, basal_adjustment_pct=-10.0),
            make_pump_event("basal", is_automated=True, basal_adjustment_pct=20.0),
        ]
        result = await build_pump_section(AsyncMock(), uuid.uuid4())

        assert "2 increases" in result
        assert "1 decreases" in result

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_pump_events", new_callable=AsyncMock)
    async def test_counts_suspends(self, mock_get_events):
        mock_get_events.return_value = [
            make_pump_event("suspend", units=None),
        ]
        result = await build_pump_section(AsyncMock(), uuid.uuid4())

        assert "Suspends: 1" in result


class TestBuildControlIqSection:
    """Tests for build_control_iq_section."""

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_control_iq_activity", new_callable=AsyncMock)
    async def test_no_events_returns_none(self, mock_activity):
        mock_activity.return_value = make_ciq_summary(total_events=0)
        result = await build_control_iq_section(AsyncMock(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_control_iq_activity", new_callable=AsyncMock)
    async def test_formats_summary(self, mock_activity):
        mock_activity.return_value = make_ciq_summary()
        result = await build_control_iq_section(AsyncMock(), uuid.uuid4())

        assert "[Control-IQ Activity - last 24h]" in result
        assert "Total events: 50" in result
        assert "35 automated" in result
        assert "15 manual" in result
        assert "Auto-corrections: 8" in result
        assert "3.5u total" in result

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_control_iq_activity", new_callable=AsyncMock)
    async def test_includes_mode_breakdown(self, mock_activity):
        mock_activity.return_value = make_ciq_summary(
            sleep_mode_events=10, standard_mode_events=25
        )
        result = await build_control_iq_section(AsyncMock(), uuid.uuid4())

        assert "Sleep: 10" in result
        assert "Standard: 25" in result

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_control_iq_activity", new_callable=AsyncMock)
    async def test_includes_suspend_count(self, mock_activity):
        mock_activity.return_value = make_ciq_summary(
            suspend_count=3, automated_suspend_count=2
        )
        result = await build_control_iq_section(AsyncMock(), uuid.uuid4())

        assert "Suspends: 3 (2 automated)" in result

    @pytest.mark.asyncio
    @patch("src.services.tandem_sync.get_control_iq_activity", new_callable=AsyncMock)
    async def test_includes_avg_basal_adjustment(self, mock_activity):
        mock_activity.return_value = make_ciq_summary(avg_basal_adjustment_pct=12.3)
        result = await build_control_iq_section(AsyncMock(), uuid.uuid4())

        assert "+12.3%" in result


class TestBuildSettingsSection:
    """Tests for build_settings_section."""

    @pytest.mark.asyncio
    async def test_no_settings_returns_none(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_mock_none_scalar(), _mock_none_scalar()])
        result = await build_settings_section(db, uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_target_range_only(self):
        mock_range = MagicMock()
        mock_range.low_target = 70.0
        mock_range.high_target = 180.0

        db = AsyncMock()
        mock_range_result = MagicMock()
        mock_range_result.scalar_one_or_none.return_value = mock_range
        mock_insulin_result = MagicMock()
        mock_insulin_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[mock_range_result, mock_insulin_result])

        result = await build_settings_section(db, uuid.uuid4())

        assert "[User Settings]" in result
        assert "70-180 mg/dL" in result

    @pytest.mark.asyncio
    async def test_insulin_config_included(self):
        mock_config = MagicMock()
        mock_config.insulin_type = "humalog"
        mock_config.dia_hours = 4.0
        mock_config.onset_minutes = 15.0

        db = AsyncMock()
        mock_range_result = MagicMock()
        mock_range_result.scalar_one_or_none.return_value = None
        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = mock_config
        db.execute = AsyncMock(side_effect=[mock_range_result, mock_config_result])

        result = await build_settings_section(db, uuid.uuid4())

        assert "humalog" in result
        assert "DIA: 4.0h" in result
        assert "Onset: 15 minutes" in result


def make_pump_profile(
    profile_name: str = "Default",
    is_active: bool = True,
    segments: list[dict] | None = None,
    insulin_duration_min: int = 300,
    max_bolus_units: float = 30.0,
    cgm_high_alert_mgdl: int | None = 240,
    cgm_low_alert_mgdl: int | None = 70,
) -> MagicMock:
    """Create a mock PumpProfile."""
    from src.models.pump_profile import PumpProfile

    profile = MagicMock(spec=PumpProfile)
    profile.profile_name = profile_name
    profile.is_active = is_active
    profile.segments = segments or [
        {
            "time": "12:00 AM",
            "start_minutes": 0,
            "basal_rate": 1.5,
            "correction_factor": 31,
            "carb_ratio": 8.0,
            "target_bg": 110,
        },
        {
            "time": "5:00 AM",
            "start_minutes": 300,
            "basal_rate": 1.65,
            "correction_factor": 25,
            "carb_ratio": 7.0,
            "target_bg": 110,
        },
    ]
    profile.insulin_duration_min = insulin_duration_min
    profile.max_bolus_units = max_bolus_units
    profile.cgm_high_alert_mgdl = cgm_high_alert_mgdl
    profile.cgm_low_alert_mgdl = cgm_low_alert_mgdl
    return profile


def _mock_none_scalar() -> MagicMock:
    """Create a mock DB result that returns None for scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    return result


def _mock_scalars_first(value: object) -> MagicMock:
    """Create a mock DB result that returns value via scalars().first()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.first.return_value = value
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# build_pump_profile_section tests (Story 15.8)
# ---------------------------------------------------------------------------
class TestBuildPumpProfileSection:
    """Tests for build_pump_profile_section."""

    @pytest.mark.asyncio
    async def test_no_profile_returns_none(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_first(None))

        result = await build_pump_profile_section(db, uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_formats_active_profile(self):
        profile = make_pump_profile()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_first(profile))

        result = await build_pump_profile_section(db, uuid.uuid4())

        assert result is not None
        assert '[Pump Profile - "Default" (active)]' in result
        assert "12:00 AM" in result
        assert "Basal 1.500 u/hr" in result
        assert "CF 1:31" in result
        assert "CR 1:8" in result
        assert "Target 110" in result
        assert "5:00 AM" in result
        assert "Basal 1.650 u/hr" in result

    @pytest.mark.asyncio
    async def test_includes_insulin_duration_and_max_bolus(self):
        profile = make_pump_profile(insulin_duration_min=300, max_bolus_units=30.0)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_first(profile))

        result = await build_pump_profile_section(db, uuid.uuid4())

        assert "Insulin duration: 5hr" in result
        assert "Max bolus: 30.0u" in result

    @pytest.mark.asyncio
    async def test_includes_cgm_alerts(self):
        profile = make_pump_profile(cgm_high_alert_mgdl=240, cgm_low_alert_mgdl=70)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_first(profile))

        result = await build_pump_profile_section(db, uuid.uuid4())

        assert "CGM alerts:" in result
        assert "High 240 mg/dL" in result
        assert "Low 70 mg/dL" in result

    @pytest.mark.asyncio
    async def test_no_cgm_alerts_when_none(self):
        profile = make_pump_profile(cgm_high_alert_mgdl=None, cgm_low_alert_mgdl=None)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_first(profile))

        result = await build_pump_profile_section(db, uuid.uuid4())

        assert "CGM alerts" not in result

    @pytest.mark.asyncio
    async def test_empty_segments(self):
        profile = make_pump_profile(segments=[])

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_first(profile))

        result = await build_pump_profile_section(db, uuid.uuid4())

        assert result is not None
        assert '[Pump Profile - "Default" (active)]' in result
        # No segment lines, just header + extras
        assert "Insulin duration" in result


# ---------------------------------------------------------------------------
# build_diabetes_context tests (Story 15.7)
# ---------------------------------------------------------------------------
class TestBuildDiabetesContext:
    """Tests for build_diabetes_context with 6 section builders."""

    @pytest.mark.asyncio
    @patch(
        "src.services.diabetes_context.build_pump_profile_section",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.diabetes_context.build_settings_section", new_callable=AsyncMock
    )
    @patch(
        "src.services.diabetes_context.build_control_iq_section", new_callable=AsyncMock
    )
    @patch("src.services.diabetes_context.build_pump_section", new_callable=AsyncMock)
    @patch("src.services.diabetes_context.build_iob_section", new_callable=AsyncMock)
    @patch(
        "src.services.diabetes_context.build_glucose_section", new_callable=AsyncMock
    )
    async def test_assembles_all_sections(
        self, mock_glucose, mock_iob, mock_pump, mock_ciq, mock_settings, mock_profile
    ):
        mock_glucose.return_value = "[Glucose - last 6h]\n- Current: 150 mg/dL"
        mock_iob.return_value = "[Insulin on Board]\n- Current IoB: 2.5 units"
        mock_pump.return_value = "[Pump Activity - last 6h]\n- Manual boluses: 3"
        mock_ciq.return_value = "[Control-IQ Activity - last 24h]\n- Total events: 50"
        mock_settings.return_value = "[User Settings]\n- Target range: 70-180 mg/dL"
        mock_profile.return_value = (
            '[Pump Profile - "Default" (active)]\n- 12:00 AM: Basal 1.500 u/hr'
        )

        db = AsyncMock()
        context = await build_diabetes_context(db, uuid.uuid4())

        assert "[Glucose" in context
        assert "[Insulin on Board]" in context
        assert "[Pump Activity" in context
        assert "[Control-IQ Activity" in context
        assert "[User Settings]" in context
        assert "[Pump Profile" in context
        # Sections separated by double newlines
        assert "\n\n" in context

    @pytest.mark.asyncio
    @patch(
        "src.services.diabetes_context.build_pump_profile_section",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.diabetes_context.build_settings_section", new_callable=AsyncMock
    )
    @patch(
        "src.services.diabetes_context.build_control_iq_section", new_callable=AsyncMock
    )
    @patch("src.services.diabetes_context.build_pump_section", new_callable=AsyncMock)
    @patch("src.services.diabetes_context.build_iob_section", new_callable=AsyncMock)
    @patch(
        "src.services.diabetes_context.build_glucose_section", new_callable=AsyncMock
    )
    async def test_skips_none_sections(
        self, mock_glucose, mock_iob, mock_pump, mock_ciq, mock_settings, mock_profile
    ):
        mock_glucose.return_value = "[Glucose]\n- Current: 120 mg/dL"
        mock_iob.return_value = None  # No IoB data
        mock_pump.return_value = None  # No pump data
        mock_ciq.return_value = None  # No Control-IQ data
        mock_settings.return_value = "[User Settings]\n- Target: 70-180"
        mock_profile.return_value = None  # No pump profile

        db = AsyncMock()
        context = await build_diabetes_context(db, uuid.uuid4())

        assert "[Glucose]" in context
        assert "[User Settings]" in context
        assert "[Insulin on Board]" not in context
        assert "[Pump Activity" not in context
        assert "[Pump Profile" not in context

    @pytest.mark.asyncio
    @patch(
        "src.services.diabetes_context.build_pump_profile_section",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.diabetes_context.build_settings_section", new_callable=AsyncMock
    )
    @patch(
        "src.services.diabetes_context.build_control_iq_section", new_callable=AsyncMock
    )
    @patch("src.services.diabetes_context.build_pump_section", new_callable=AsyncMock)
    @patch("src.services.diabetes_context.build_iob_section", new_callable=AsyncMock)
    @patch(
        "src.services.diabetes_context.build_glucose_section", new_callable=AsyncMock
    )
    async def test_all_sections_none_returns_fallback(
        self, mock_glucose, mock_iob, mock_pump, mock_ciq, mock_settings, mock_profile
    ):
        mock_glucose.return_value = None
        mock_iob.return_value = None
        mock_pump.return_value = None
        mock_ciq.return_value = None
        mock_settings.return_value = None
        mock_profile.return_value = None

        db = AsyncMock()
        context = await build_diabetes_context(db, uuid.uuid4())

        assert "No data available" in context

    @pytest.mark.asyncio
    @patch(
        "src.services.diabetes_context.build_pump_profile_section",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.diabetes_context.build_settings_section", new_callable=AsyncMock
    )
    @patch(
        "src.services.diabetes_context.build_control_iq_section", new_callable=AsyncMock
    )
    @patch("src.services.diabetes_context.build_pump_section", new_callable=AsyncMock)
    @patch("src.services.diabetes_context.build_iob_section", new_callable=AsyncMock)
    @patch(
        "src.services.diabetes_context.build_glucose_section", new_callable=AsyncMock
    )
    async def test_section_error_doesnt_crash(
        self, mock_glucose, mock_iob, mock_pump, mock_ciq, mock_settings, mock_profile
    ):
        """Each section builder is independently resilient."""
        mock_glucose.return_value = "[Glucose]\n- Current: 120"
        mock_iob.side_effect = RuntimeError("DB error")  # This one crashes
        mock_pump.return_value = "[Pump Activity]\n- Boluses: 2"
        mock_ciq.side_effect = RuntimeError("Connection lost")  # This one too
        mock_settings.return_value = None
        mock_profile.return_value = None

        db = AsyncMock()
        context = await build_diabetes_context(db, uuid.uuid4())

        # Glucose and pump still present despite IoB and CIQ failures
        assert "[Glucose]" in context
        assert "[Pump Activity]" in context
        assert "[Insulin on Board]" not in context


# ---------------------------------------------------------------------------
# _build_system_prompt tests
# ---------------------------------------------------------------------------
class TestBuildSystemPrompt:
    """Tests for _build_system_prompt."""

    def test_includes_diabetes_context(self):
        context = "[Glucose]\n- Current: 120 mg/dL (stable)"
        prompt = _build_system_prompt(context)

        assert "120 mg/dL" in prompt
        assert "stable" in prompt

    def test_includes_safety_guidelines(self):
        prompt = _build_system_prompt("")

        assert "NOT prescribe specific insulin dose" in prompt
        assert "endocrinologist" in prompt

    def test_includes_telegram_instruction(self):
        prompt = _build_system_prompt("")

        assert "concise" in prompt.lower()
        assert "Telegram" in prompt

    def test_includes_pump_guidance(self):
        """Story 15.7: System prompt allows discussing pump patterns."""
        prompt = _build_system_prompt("")

        assert "pump activity" in prompt.lower() or "Control-IQ" in prompt
        assert "basal rates" in prompt or "correction frequency" in prompt


# ---------------------------------------------------------------------------
# _truncate_response tests
# ---------------------------------------------------------------------------
class TestTruncateResponse:
    """Tests for _truncate_response."""

    def test_short_response_gets_disclaimer(self):
        result = _truncate_response("Hello world")

        assert result.endswith(SAFETY_DISCLAIMER)
        assert "Hello world" in result

    def test_long_response_truncated_with_ellipsis(self):
        long_text = "x" * TELEGRAM_MAX_LENGTH
        result = _truncate_response(long_text)

        assert len(result) <= TELEGRAM_MAX_LENGTH
        assert "..." in result
        assert result.endswith(SAFETY_DISCLAIMER)

    def test_exact_limit_not_truncated(self):
        max_content = TELEGRAM_MAX_LENGTH - len(SAFETY_DISCLAIMER)
        exact_text = "y" * max_content
        result = _truncate_response(exact_text)

        assert len(result) == TELEGRAM_MAX_LENGTH
        assert "..." not in result


# ---------------------------------------------------------------------------
# handle_chat tests
# ---------------------------------------------------------------------------
class TestHandleChat:
    """Tests for handle_chat."""

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_successful_response(self, mock_get_client, mock_context):
        mock_context.return_value = "[Glucose]\n- Current: 120 mg/dL"

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response(
            "Your glucose looks stable."
        )
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "How am I doing?")

        assert "glucose looks stable" in msg
        assert "Not medical advice" in msg
        mock_client.generate.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_no_ai_provider_returns_friendly_error(self, mock_get_client):
        from fastapi import HTTPException

        mock_get_client.side_effect = HTTPException(
            status_code=404, detail="No AI provider"
        )

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "Hello")

        assert "No AI provider configured" in msg
        assert "Settings" in msg

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_ai_error_caught_gracefully(self, mock_get_client, mock_context):
        mock_context.return_value = ""

        mock_client = AsyncMock()
        mock_client.generate.side_effect = ConnectionError("API timeout")
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "Why am I high?")

        assert "Unable to get a response" in msg

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_safety_disclaimer_appended(self, mock_get_client, mock_context):
        mock_context.return_value = ""

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response("Some advice here.")
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "What should I do?")

        assert "Not medical advice" in msg
        assert msg.endswith(SAFETY_DISCLAIMER)

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_long_response_truncated(self, mock_get_client, mock_context):
        mock_context.return_value = ""

        long_content = "a" * 5000
        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response(long_content)
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "Tell me everything")

        assert len(msg) <= TELEGRAM_MAX_LENGTH
        assert "..." in msg
        assert "Not medical advice" in msg

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_empty_response_handled(self, mock_get_client, mock_context):
        mock_context.return_value = ""

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response("")
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "...")

        assert "empty response" in msg.lower()

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, uuid.uuid4(), "Hello")

        assert "Something went wrong" in msg

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_diabetes_context_passed_to_system_prompt(
        self, mock_get_client, mock_context
    ):
        mock_context.return_value = "[Glucose]\n- Current: 180 mg/dL (rising)"

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response("Response")
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        await handle_chat(db, user.id, "What's happening?")

        # Verify the system prompt contains diabetes context
        call_kwargs = mock_client.generate.call_args
        system_prompt = call_kwargs.kwargs.get(
            "system_prompt", call_kwargs[1].get("system_prompt", "")
        )
        assert "180 mg/dL" in system_prompt

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_html_in_ai_response_is_escaped(self, mock_get_client, mock_context):
        mock_context.return_value = ""

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response(
            "<script>alert('xss')</script> advice"
        )
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "Tell me something")

        assert "<script>" not in msg
        assert "&lt;script&gt;" in msg

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_whitespace_only_response_treated_as_empty(
        self, mock_get_client, mock_context
    ):
        mock_context.return_value = ""

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response("   \n  ")
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "test")

        assert "empty response" in msg.lower()

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_user_message_passed_to_ai(self, mock_get_client, mock_context):
        """Verify user's question text reaches the AI provider."""
        mock_context.return_value = ""

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response("Response")
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        await handle_chat(db, user.id, "Why am I spiking?")

        call_kwargs = mock_client.generate.call_args
        messages = call_kwargs.kwargs.get(
            "messages", call_kwargs[1].get("messages", [])
        )
        assert len(messages) == 1
        assert messages[0].content == "Why am I spiking?"
        assert messages[0].role == "user"

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_long_user_message_truncated(self, mock_get_client, mock_context):
        """Overly long user messages are truncated before sending to AI."""
        mock_context.return_value = ""

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response("Response")
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        long_message = "x" * (MAX_USER_MESSAGE_LENGTH + 500)
        await handle_chat(db, user.id, long_message)

        call_kwargs = mock_client.generate.call_args
        messages = call_kwargs.kwargs.get(
            "messages", call_kwargs[1].get("messages", [])
        )
        assert len(messages[0].content) == MAX_USER_MESSAGE_LENGTH

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.build_diabetes_context", new_callable=AsyncMock)
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_diabetes_context_error_uses_fallback(
        self, mock_get_client, mock_context
    ):
        """DB error in diabetes context doesn't crash the handler."""
        mock_context.side_effect = RuntimeError("DB connection lost")

        mock_client = AsyncMock()
        mock_client.generate.return_value = make_ai_response("Still works")
        mock_get_client.return_value = mock_client

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "How am I doing?")

        assert "Still works" in msg
        mock_client.generate.assert_called_once()
        # Verify fallback context was used in the system prompt
        call_kwargs = mock_client.generate.call_args
        system_prompt = call_kwargs.kwargs.get(
            "system_prompt", call_kwargs[1].get("system_prompt", "")
        )
        assert "unavailable due to a temporary error" in system_prompt

    @pytest.mark.asyncio
    @patch("src.services.telegram_chat.get_ai_client", new_callable=AsyncMock)
    async def test_unsupported_provider_returns_config_error(self, mock_get_client):
        """HTTP 400 (unsupported provider) gets distinct message."""
        from fastapi import HTTPException

        mock_get_client.side_effect = HTTPException(
            status_code=400, detail="Unsupported AI provider"
        )

        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await handle_chat(db, user.id, "Hello")

        assert "issue with your AI provider configuration" in msg
        assert "No AI provider configured" not in msg


class TestBuildSystemPromptSafety:
    """Test that braces in context don't break prompt."""

    def test_braces_in_context_are_safe(self):
        context = "Data: {unknown_key} and more {stuff}"
        prompt = _build_system_prompt(context)

        assert "{unknown_key}" in prompt
        assert "{stuff}" in prompt

    def test_empty_context_no_trailing_whitespace(self):
        """Empty context should not produce trailing newlines."""
        prompt = _build_system_prompt("")
        assert not prompt.endswith("\n")
