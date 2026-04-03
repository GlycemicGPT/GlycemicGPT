"""Story 8.4: Tests for caregiver AI chat endpoint and service."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.models.caregiver_link import CaregiverLink
from src.models.user import User, UserRole
from src.schemas.caregiver_dashboard import CaregiverChatRequest, CaregiverChatResponse

# ── Helpers ──


def _make_link(
    patient_id: uuid.UUID | None = None,
    caregiver_id: uuid.UUID | None = None,
    can_view_ai_suggestions: bool = True,
) -> MagicMock:
    """Create a mock CaregiverLink."""
    link = MagicMock(spec=CaregiverLink)
    link.id = uuid.uuid4()
    link.patient_id = patient_id or uuid.uuid4()
    link.caregiver_id = caregiver_id or uuid.uuid4()
    link.can_view_glucose = True
    link.can_view_history = True
    link.can_view_iob = True
    link.can_view_ai_suggestions = can_view_ai_suggestions
    link.can_receive_alerts = True
    patient = MagicMock(spec=User)
    patient.id = link.patient_id
    patient.email = "patient@example.com"
    patient.role = UserRole.DIABETIC
    link.patient = patient
    return link


# ── TestCaregiverChatSchemas ──


class TestCaregiverChatSchemas:
    """Tests for chat request/response schemas."""

    def test_request_validates_min_length(self):
        """Empty message is rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CaregiverChatRequest(message="")

    def test_request_validates_max_length(self):
        """Message exceeding 2000 chars is rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CaregiverChatRequest(message="x" * 2001)

    def test_request_rejects_whitespace_only(self):
        """Whitespace-only message is rejected after stripping."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CaregiverChatRequest(message="   ")

    def test_request_strips_whitespace(self):
        """Leading/trailing whitespace is stripped from message."""
        req = CaregiverChatRequest(message="  How is my patient?  ")
        assert req.message == "How is my patient?"

    def test_request_accepts_valid_message(self):
        """Valid message is accepted."""
        req = CaregiverChatRequest(message="How is my patient doing?")
        assert req.message == "How is my patient doing?"

    def test_response_has_default_disclaimer(self):
        """Response schema includes default disclaimer."""
        resp = CaregiverChatResponse(response="test")
        assert "medical advice" in resp.disclaimer.lower()

    def test_response_custom_disclaimer(self):
        """Response schema accepts custom disclaimer."""
        resp = CaregiverChatResponse(response="test", disclaimer="Custom")
        assert resp.disclaimer == "Custom"


# ── TestCaregiverChatEndpoint ──


class TestCaregiverChatEndpoint:
    """Tests for POST /patients/{patient_id}/chat."""

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_chat.handle_caregiver_chat_web",
        new_callable=AsyncMock,
    )
    @patch("src.routers.caregivers._get_caregiver_link", new_callable=AsyncMock)
    async def test_successful_chat(self, mock_get_link, mock_web_chat):
        """Returns AI response when permission granted."""
        from src.routers.caregivers import caregiver_ai_chat

        caregiver_id = uuid.uuid4()
        patient_id = uuid.uuid4()
        link = _make_link(caregiver_id=caregiver_id, patient_id=patient_id)
        mock_get_link.return_value = link
        mock_web_chat.return_value = "Your patient is at 120 mg/dL and stable."

        mock_user = MagicMock()
        mock_user.id = caregiver_id

        request = CaregiverChatRequest(message="How is my patient doing?")

        result = await caregiver_ai_chat(
            patient_id=patient_id,
            data=request,
            current_user=mock_user,
            db=AsyncMock(),
        )

        assert isinstance(result, CaregiverChatResponse)
        assert "120 mg/dL" in result.response
        assert "medical advice" in result.disclaimer.lower()
        mock_web_chat.assert_called_once()
        args = mock_web_chat.call_args[0]
        assert args[2] == patient_id  # patient_id forwarded correctly
        assert args[3] == "How is my patient doing?"  # message forwarded

    @pytest.mark.asyncio
    @patch("src.routers.caregivers._get_caregiver_link", new_callable=AsyncMock)
    async def test_ai_permission_denied_returns_403(self, mock_get_link):
        """Returns 403 when can_view_ai_suggestions is False."""
        from src.routers.caregivers import caregiver_ai_chat

        link = _make_link(can_view_ai_suggestions=False)
        mock_get_link.return_value = link

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        request = CaregiverChatRequest(message="How is my patient?")

        with pytest.raises(HTTPException) as exc_info:
            await caregiver_ai_chat(
                patient_id=uuid.uuid4(),
                data=request,
                current_user=mock_user,
                db=AsyncMock(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @patch("src.routers.caregivers._get_caregiver_link", new_callable=AsyncMock)
    async def test_unlinked_patient_returns_404(self, mock_get_link):
        """Returns 404 for unlinked patient."""
        from src.routers.caregivers import caregiver_ai_chat

        mock_get_link.side_effect = HTTPException(
            status_code=404, detail="Patient not linked to your account"
        )

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        request = CaregiverChatRequest(message="How is my patient?")

        with pytest.raises(HTTPException) as exc_info:
            await caregiver_ai_chat(
                patient_id=uuid.uuid4(),
                data=request,
                current_user=mock_user,
                db=AsyncMock(),
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_chat.handle_caregiver_chat_web",
        new_callable=AsyncMock,
    )
    @patch("src.routers.caregivers._get_caregiver_link", new_callable=AsyncMock)
    async def test_ai_provider_error_returns_502(self, mock_get_link, mock_web_chat):
        """Returns 502 when AI provider fails."""
        from src.routers.caregivers import caregiver_ai_chat

        link = _make_link()
        mock_get_link.return_value = link
        mock_web_chat.side_effect = HTTPException(
            status_code=502,
            detail="Unable to get a response from the AI provider",
        )

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        request = CaregiverChatRequest(message="How is my patient?")

        with pytest.raises(HTTPException) as exc_info:
            await caregiver_ai_chat(
                patient_id=uuid.uuid4(),
                data=request,
                current_user=mock_user,
                db=AsyncMock(),
            )

        assert exc_info.value.status_code == 502


# ── TestHandleCaregiverChatWeb ──


class TestHandleCaregiverChatWeb:
    """Tests for the web-optimized caregiver chat service."""

    @pytest.mark.asyncio
    async def test_returns_plain_text_without_html_escape(self):
        """Web handler returns raw AI content without HTML escaping."""
        from src.services.telegram_chat import handle_caregiver_chat_web

        mock_patient = MagicMock(spec=User)
        mock_patient.id = uuid.uuid4()
        mock_patient.email = "patient@example.com"

        mock_ai_response = MagicMock()
        mock_ai_response.content = "Patient is at 120 mg/dL & stable."
        mock_ai_response.model = "test-model"
        mock_ai_response.provider.value = "openai"
        mock_ai_response.usage.input_tokens = 100
        mock_ai_response.usage.output_tokens = 50

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_patient
        db.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_client.generate.return_value = mock_ai_response

        with (
            patch(
                "src.services.telegram_chat.get_ai_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "src.services.telegram_chat.build_diabetes_context",
                new_callable=AsyncMock,
                return_value="[Glucose - last 6h]\n- Current: 120 mg/dL",
            ),
        ):
            result = await handle_caregiver_chat_web(
                db, uuid.uuid4(), mock_patient.id, "How is my patient?"
            )

        # Should NOT be HTML-escaped (& should remain as &, not &amp;)
        assert "&" in result
        assert "&amp;" not in result
        # Should NOT have Telegram HTML disclaimer tags
        assert "<i>" not in result

    @pytest.mark.asyncio
    async def test_patient_not_found_raises_404(self):
        """Raises 404 when patient not found."""
        from src.services.telegram_chat import handle_caregiver_chat_web

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await handle_caregiver_chat_web(
                db, uuid.uuid4(), uuid.uuid4(), "How is my patient?"
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_ai_provider_error_raises_502(self):
        """Raises 502 when AI provider fails."""
        from src.services.telegram_chat import handle_caregiver_chat_web

        mock_patient = MagicMock(spec=User)
        mock_patient.id = uuid.uuid4()
        mock_patient.email = "patient@example.com"

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_patient
        db.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_client.generate.side_effect = RuntimeError("API timeout")

        with (
            patch(
                "src.services.telegram_chat.get_ai_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "src.services.telegram_chat.build_diabetes_context",
                new_callable=AsyncMock,
                return_value="",
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await handle_caregiver_chat_web(
                db, uuid.uuid4(), mock_patient.id, "How is my patient?"
            )

        assert exc_info.value.status_code == 502
