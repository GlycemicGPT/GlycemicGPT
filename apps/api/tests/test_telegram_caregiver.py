"""Story 7.6: Tests for caregiver Telegram access."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.units import GlucoseUnit
from src.models.caregiver_link import CaregiverLink
from src.models.glucose import GlucoseReading, TrendDirection
from src.models.user import User, UserRole
from src.services.telegram_caregiver import (
    _handle_blocked_command,
    _handle_caregiver_chat,
    _handle_caregiver_help,
    _handle_caregiver_status,
    _handle_no_patients,
    _resolve_patient_for_chat,
    get_linked_patients,
    handle_caregiver_command,
)

# ── Helpers ──


def make_user(
    role: UserRole = UserRole.DIABETIC,
    email: str = "patient@example.com",
    glucose_unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> MagicMock:
    """Create a mock User."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.role = role
    user.glucose_unit = glucose_unit
    return user


def make_link(
    caregiver_id: uuid.UUID | None = None,
    patient: MagicMock | None = None,
) -> MagicMock:
    """Create a mock CaregiverLink with patient loaded."""
    link = MagicMock(spec=CaregiverLink)
    link.id = uuid.uuid4()
    link.caregiver_id = caregiver_id or uuid.uuid4()
    patient = patient or make_user()
    link.patient_id = patient.id
    link.patient = patient
    return link


def make_reading(
    value: int = 120,
    trend_rate: float = 0.5,
    minutes_ago: int = 3,
) -> MagicMock:
    """Create a mock GlucoseReading."""
    reading = MagicMock(spec=GlucoseReading)
    reading.value = value
    reading.trend_rate = trend_rate
    reading.trend = TrendDirection.FLAT
    reading.reading_timestamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    reading.user_id = uuid.uuid4()
    return reading


# ── TestGetLinkedPatients ──


class TestGetLinkedPatients:
    """Tests for get_linked_patients."""

    @pytest.mark.asyncio
    async def test_one_patient(self):
        link = make_link()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [link]

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_linked_patients(db, uuid.uuid4())
        assert len(result) == 1
        assert result[0] is link

    @pytest.mark.asyncio
    async def test_multiple_patients(self):
        links = [make_link(), make_link()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = links

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_linked_patients(db, uuid.uuid4())
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_no_patients(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_linked_patients(db, uuid.uuid4())
        assert result == []


# ── TestHandleCaregiverStatus ──


class TestHandleCaregiverStatus:
    """Tests for _handle_caregiver_status."""

    @pytest.mark.asyncio
    @patch("src.services.telegram_commands._handle_status", new_callable=AsyncMock)
    @patch("src.services.caregiver.check_caregiver_permission", new_callable=AsyncMock)
    async def test_single_patient_shows_patient_label(self, mock_perm, mock_status):
        mock_perm.return_value = True
        mock_status.return_value = "120 mg/dL"
        patient = make_user(email="alice@example.com")
        caregiver_id = uuid.uuid4()
        link = make_link(caregiver_id=caregiver_id, patient=patient)

        result = await _handle_caregiver_status(AsyncMock(), caregiver_id, [link])

        assert "alice@example.com" in result
        assert "120 mg/dL" in result
        assert "Patient" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.dexcom_sync.get_latest_glucose_reading", new_callable=AsyncMock
    )
    @patch("src.services.caregiver.check_caregiver_permission", new_callable=AsyncMock)
    async def test_multiple_patients_lists_all(self, mock_perm, mock_glucose):
        mock_perm.return_value = True
        patient1 = make_user(email="alice@example.com")
        patient2 = make_user(email="bob@example.com")
        caregiver_id = uuid.uuid4()
        link1 = make_link(caregiver_id=caregiver_id, patient=patient1)
        link2 = make_link(caregiver_id=caregiver_id, patient=patient2)

        reading1 = make_reading(value=110)
        reading2 = make_reading(value=200)
        mock_glucose.side_effect = [reading1, reading2]

        db = AsyncMock()

        result = await _handle_caregiver_status(db, caregiver_id, [link1, link2])

        assert "alice@example.com" in result
        assert "bob@example.com" in result
        assert "110 mg/dL" in result
        assert "200 mg/dL" in result
        assert "Linked Patients" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.dexcom_sync.get_latest_glucose_reading", new_callable=AsyncMock
    )
    @patch("src.services.caregiver.check_caregiver_permission", new_callable=AsyncMock)
    async def test_multiple_patients_each_in_own_unit(self, mock_perm, mock_glucose):
        """Each patient's glucose renders in THAT patient's own unit within the
        same status message -- a regression to one shared unit must fail here."""
        mock_perm.return_value = True
        patient_mgdl = make_user(
            email="alice@example.com", glucose_unit=GlucoseUnit.MGDL
        )
        patient_mmol = make_user(email="bob@example.com", glucose_unit=GlucoseUnit.MMOL)
        caregiver_id = uuid.uuid4()
        link1 = make_link(caregiver_id=caregiver_id, patient=patient_mgdl)
        link2 = make_link(caregiver_id=caregiver_id, patient=patient_mmol)

        # Same stored mg/dL value (200) so only the per-patient unit differs.
        mock_glucose.side_effect = [make_reading(value=200), make_reading(value=200)]

        db = AsyncMock()
        result = await _handle_caregiver_status(db, caregiver_id, [link1, link2])

        assert "alice@example.com" in result
        assert "200 mg/dL" in result  # mg/dL patient
        assert "bob@example.com" in result
        assert "11.1 mmol/L" in result  # mmol patient: 200 -> 11.1

    @pytest.mark.asyncio
    @patch(
        "src.services.dexcom_sync.get_latest_glucose_reading", new_callable=AsyncMock
    )
    @patch("src.services.caregiver.check_caregiver_permission", new_callable=AsyncMock)
    async def test_multiple_patients_no_data(self, mock_perm, mock_glucose):
        mock_perm.return_value = True
        mock_glucose.return_value = None
        patient = make_user(email="empty@example.com")
        caregiver_id = uuid.uuid4()
        link = make_link(caregiver_id=caregiver_id, patient=patient)

        db = AsyncMock()

        result = await _handle_caregiver_status(
            db, caregiver_id, [link, make_link(caregiver_id=caregiver_id)]
        )

        assert "No data available" in result


# ── TestHandleCaregiverChat ──


class TestHandleCaregiverChat:
    """Tests for _handle_caregiver_chat."""

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_chat.handle_caregiver_chat",
        new_callable=AsyncMock,
    )
    @patch("src.services.caregiver.check_caregiver_permission", new_callable=AsyncMock)
    async def test_single_patient_routes_to_chat(self, mock_perm, mock_chat):
        mock_perm.return_value = True
        mock_chat.return_value = "AI response"
        caregiver_id = uuid.uuid4()
        link = make_link(caregiver_id=caregiver_id)

        result = await _handle_caregiver_chat(
            AsyncMock(), caregiver_id, [link], "How are they?"
        )

        assert result == "AI response"
        mock_chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_patients_no_match_lists_patients(self):
        patient1 = make_user(email="alice@example.com")
        patient2 = make_user(email="bob@example.com")
        links = [
            make_link(patient=patient1),
            make_link(patient=patient2),
        ]

        result = await _handle_caregiver_chat(
            AsyncMock(), uuid.uuid4(), links, "How are they?"
        )

        assert "multiple linked patients" in result
        assert "alice@example.com" in result
        assert "bob@example.com" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_chat.handle_caregiver_chat",
        new_callable=AsyncMock,
    )
    @patch("src.services.caregiver.check_caregiver_permission", new_callable=AsyncMock)
    async def test_multiple_patients_name_match(self, mock_perm, mock_chat):
        mock_perm.return_value = True
        mock_chat.return_value = "AI response about Alice"
        patient1 = make_user(email="alice@example.com")
        patient2 = make_user(email="bob@example.com")
        links = [
            make_link(patient=patient1),
            make_link(patient=patient2),
        ]

        result = await _handle_caregiver_chat(
            AsyncMock(), uuid.uuid4(), links, "How is alice doing?"
        )

        assert result == "AI response about Alice"
        # Should have called with alice's patient_id
        call_args = mock_chat.call_args
        assert call_args[0][2] == patient1.id

    @pytest.mark.asyncio
    @patch("src.services.caregiver.check_caregiver_permission", new_callable=AsyncMock)
    async def test_import_error_returns_unavailable(self, mock_perm):
        """ImportError for telegram_chat is caught gracefully."""
        import builtins

        mock_perm.return_value = True
        link = make_link()
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "src.services.telegram_chat":
                raise ImportError("no module")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = await _handle_caregiver_chat(
                AsyncMock(), uuid.uuid4(), [link], "How are they?"
            )
        assert "temporarily unavailable" in result


# ── TestResolvePatientForChat ──


class TestResolvePatientForChat:
    """Tests for _resolve_patient_for_chat."""

    def test_single_patient_returns_that_link(self):
        link = make_link()
        result = _resolve_patient_for_chat([link], "anything")
        assert result is link

    def test_multiple_no_match_returns_none(self):
        links = [make_link(), make_link()]
        result = _resolve_patient_for_chat(links, "no match here")
        assert result is None

    def test_multiple_email_prefix_match(self):
        patient = make_user(email="alice@example.com")
        link1 = make_link(patient=patient)
        link2 = make_link()

        result = _resolve_patient_for_chat([link1, link2], "How is alice doing?")
        assert result is link1

    def test_short_prefix_matches_cautiously(self):
        """Short email prefixes like 'a' can match unintended text."""
        patient1 = make_user(email="a@example.com")
        patient2 = make_user(email="bob@example.com")
        link1 = make_link(patient=patient1)
        link2 = make_link(patient=patient2)

        # "a" matches in almost any message — this is documented behavior
        result = _resolve_patient_for_chat([link1, link2], "How is a doing?")
        assert result is link1


# ── TestHandleCaregiverHelp ──


class TestHandleCaregiverHelp:
    """Tests for _handle_caregiver_help."""

    def test_lists_status_and_help(self):
        result = _handle_caregiver_help()
        assert "/status" in result
        assert "/help" in result

    def test_mentions_ai_chat(self):
        result = _handle_caregiver_help()
        assert "question" in result.lower()

    def test_notes_blocked_commands(self):
        result = _handle_caregiver_help()
        assert "/acknowledge" in result
        assert "/brief" in result
        assert "not available" in result


# ── TestCaregiverCommandBlocking ──


class TestCaregiverCommandBlocking:
    """Tests for blocked commands."""

    def test_blocked_message_mentions_patient(self):
        result = _handle_blocked_command()
        assert "patient accounts" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_caregiver.get_linked_patients",
        new_callable=AsyncMock,
    )
    async def test_acknowledge_blocked(self, mock_links):
        result = await handle_caregiver_command(
            AsyncMock(), uuid.uuid4(), "/acknowledge"
        )
        assert "patient accounts" in result
        mock_links.assert_not_called()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_caregiver.get_linked_patients",
        new_callable=AsyncMock,
    )
    async def test_brief_blocked(self, mock_links):
        result = await handle_caregiver_command(AsyncMock(), uuid.uuid4(), "/brief")
        assert "patient accounts" in result
        mock_links.assert_not_called()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_caregiver.get_linked_patients",
        new_callable=AsyncMock,
    )
    async def test_acknowledge_with_id_blocked(self, mock_links):
        alert_id = uuid.uuid4()
        result = await handle_caregiver_command(
            AsyncMock(), uuid.uuid4(), f"/acknowledge_{alert_id}"
        )
        assert "patient accounts" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_caregiver.get_linked_patients",
        new_callable=AsyncMock,
    )
    async def test_status_allowed(self, mock_links):
        mock_links.return_value = [make_link()]

        with patch(
            "src.services.telegram_caregiver._handle_caregiver_status",
            new_callable=AsyncMock,
        ) as mock_status:
            mock_status.return_value = "status OK"
            result = await handle_caregiver_command(
                AsyncMock(), uuid.uuid4(), "/status"
            )

        assert result == "status OK"


# ── TestHandleCaregiverCommand ──


class TestHandleCaregiverCommand:
    """Integration tests for handle_caregiver_command routing."""

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_caregiver.get_linked_patients",
        new_callable=AsyncMock,
    )
    async def test_no_patients_status(self, mock_links):
        mock_links.return_value = []
        result = await handle_caregiver_command(AsyncMock(), uuid.uuid4(), "/status")
        assert "No patients linked" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_caregiver.get_linked_patients",
        new_callable=AsyncMock,
    )
    async def test_no_patients_plain_text(self, mock_links):
        mock_links.return_value = []
        result = await handle_caregiver_command(
            AsyncMock(), uuid.uuid4(), "how is she?"
        )
        assert "No patients linked" in result

    @pytest.mark.asyncio
    async def test_help_command(self):
        result = await handle_caregiver_command(AsyncMock(), uuid.uuid4(), "/help")
        assert "Caregiver Commands" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_caregiver.get_linked_patients",
        new_callable=AsyncMock,
    )
    async def test_unknown_slash_command(self, mock_links):
        mock_links.return_value = []
        result = await handle_caregiver_command(AsyncMock(), uuid.uuid4(), "/foobar")
        assert "Unrecognized command" in result

    @pytest.mark.asyncio
    async def test_exception_caught(self):
        """Exceptions are caught and return friendly error."""
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("DB error")

        result = await handle_caregiver_command(db, uuid.uuid4(), "/status")
        assert "Something went wrong" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_caregiver.get_linked_patients",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.telegram_caregiver._handle_caregiver_chat",
        new_callable=AsyncMock,
    )
    async def test_plain_text_routes_to_chat(self, mock_chat, mock_links):
        mock_links.return_value = [make_link()]
        mock_chat.return_value = "AI response"

        result = await handle_caregiver_command(
            AsyncMock(), uuid.uuid4(), "How is patient doing?"
        )
        assert result == "AI response"


# ── TestNoPatients ──


class TestNoPatients:
    """Tests for _handle_no_patients."""

    def test_message_content(self):
        result = _handle_no_patients()
        assert "No patients linked" in result
        assert "web app" in result
