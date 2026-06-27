"""Story 6.7: Tests for automatic escalation engine."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.config import settings
from src.core.units import GlucoseUnit
from src.database import get_session_maker
from src.models.alert import Alert, AlertSeverity, AlertType
from src.models.emergency_contact import ContactPriority, EmergencyContact
from src.models.escalation_config import EscalationConfig
from src.models.escalation_event import (
    EscalationEvent,
    EscalationTier,
    NotificationStatus,
)
from src.services.escalation_engine import (
    _resolve_contact_chat_id,
    build_escalation_message,
    create_escalation_event,
    determine_next_escalation_tier,
    dispatch_notification,
    escalate_alert,
    get_contacts_for_tier,
    process_escalations_for_user,
)


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client) -> tuple[str, str]:
    """Register a new user and return (cookie_value, email)."""
    email = unique_email("esc_eng")
    password = "SecurePass123"

    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )

    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    return login_response.cookies.get(settings.jwt_cookie_name), email


def make_alert(
    user_id: uuid.UUID,
    severity: AlertSeverity = AlertSeverity.URGENT,
    acknowledged: bool = False,
    age_minutes: float = 15,
    expired: bool = False,
) -> MagicMock:
    """Create a mock Alert with typical fields."""
    now = datetime.now(UTC)
    alert = MagicMock(spec=Alert)
    alert.id = uuid.uuid4()
    alert.user_id = user_id
    alert.severity = severity
    alert.acknowledged = acknowledged
    alert.created_at = now - timedelta(minutes=age_minutes)
    alert.expires_at = now - timedelta(hours=1) if expired else now + timedelta(hours=2)
    alert.current_value = 55.0
    alert.message = "Glucose predicted to drop below 70 mg/dL"
    alert.alert_type = AlertType.LOW_URGENT
    return alert


def make_config(
    user_id: uuid.UUID,
    reminder: int = 5,
    primary: int = 10,
    all_contacts: int = 20,
) -> MagicMock:
    """Create a mock EscalationConfig."""
    config = MagicMock(spec=EscalationConfig)
    config.user_id = user_id
    config.reminder_delay_minutes = reminder
    config.primary_contact_delay_minutes = primary
    config.all_contacts_delay_minutes = all_contacts
    return config


def make_event(
    alert_id: uuid.UUID,
    tier: EscalationTier,
) -> MagicMock:
    """Create a mock EscalationEvent."""
    event = MagicMock(spec=EscalationEvent)
    event.id = uuid.uuid4()
    event.alert_id = alert_id
    event.tier = tier
    event.triggered_at = datetime.now(UTC)
    event.notification_status = NotificationStatus.SENT
    event.contacts_notified = []
    return event


def make_contact(
    user_id: uuid.UUID,
    name: str = "Jane Doe",
    priority: ContactPriority = ContactPriority.PRIMARY,
    position: int = 0,
) -> MagicMock:
    """Create a mock EmergencyContact."""
    contact = MagicMock(spec=EmergencyContact)
    contact.id = uuid.uuid4()
    contact.user_id = user_id
    contact.name = name
    contact.telegram_username = f"@{name.lower().replace(' ', '_')}"
    contact.priority = priority
    contact.position = position
    return contact


# ── Tier determination tests (pure logic) ──


class TestDetermineNextEscalationTier:
    """Tests for determine_next_escalation_tier pure logic."""

    def test_reminder_triggers_after_delay(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=6)
        config = make_config(user_id, reminder=5)

        decision = determine_next_escalation_tier(alert, config, [])

        assert decision.should_escalate is True
        assert decision.tier == EscalationTier.REMINDER

    def test_no_escalation_before_reminder_delay(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=3)
        config = make_config(user_id, reminder=5)

        decision = determine_next_escalation_tier(alert, config, [])

        assert decision.should_escalate is False
        assert decision.tier is None

    def test_primary_triggers_after_reminder_done(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=12)
        config = make_config(user_id, primary=10)

        existing = [make_event(alert.id, EscalationTier.REMINDER)]

        decision = determine_next_escalation_tier(alert, config, existing)

        assert decision.should_escalate is True
        assert decision.tier == EscalationTier.PRIMARY_CONTACT

    def test_no_primary_before_primary_delay(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=8)
        config = make_config(user_id, primary=10)

        existing = [make_event(alert.id, EscalationTier.REMINDER)]

        decision = determine_next_escalation_tier(alert, config, existing)

        assert decision.should_escalate is False
        assert decision.tier is None

    def test_all_contacts_triggers_after_primary_done(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=25)
        config = make_config(user_id, all_contacts=20)

        existing = [
            make_event(alert.id, EscalationTier.REMINDER),
            make_event(alert.id, EscalationTier.PRIMARY_CONTACT),
        ]

        decision = determine_next_escalation_tier(alert, config, existing)

        assert decision.should_escalate is True
        assert decision.tier == EscalationTier.ALL_CONTACTS

    def test_no_all_contacts_before_delay(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=18)
        config = make_config(user_id, all_contacts=20)

        existing = [
            make_event(alert.id, EscalationTier.REMINDER),
            make_event(alert.id, EscalationTier.PRIMARY_CONTACT),
        ]

        decision = determine_next_escalation_tier(alert, config, existing)

        assert decision.should_escalate is False

    def test_all_tiers_triggered_stops_escalation(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=60)
        config = make_config(user_id)

        existing = [
            make_event(alert.id, EscalationTier.REMINDER),
            make_event(alert.id, EscalationTier.PRIMARY_CONTACT),
            make_event(alert.id, EscalationTier.ALL_CONTACTS),
        ]

        decision = determine_next_escalation_tier(alert, config, existing)

        assert decision.should_escalate is False
        assert "All escalation tiers already triggered" in decision.reason

    def test_exact_delay_threshold_triggers(self):
        """Alert age exactly at delay threshold should trigger."""
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=5)
        config = make_config(user_id, reminder=5)

        decision = determine_next_escalation_tier(alert, config, [])

        assert decision.should_escalate is True
        assert decision.tier == EscalationTier.REMINDER

    def test_decision_reason_includes_timing(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=3)
        config = make_config(user_id, reminder=5)

        decision = determine_next_escalation_tier(alert, config, [])

        assert "3.0m" in decision.reason or "reminder delay" in decision.reason


# ── Message building tests ──


class TestBuildEscalationMessage:
    """Tests for build_escalation_message."""

    def test_reminder_message_format(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id)

        msg = build_escalation_message(alert, EscalationTier.REMINDER, "user@test.com")

        assert "[REMINDER]" in msg
        assert "URGENT" in msg
        assert "55 mg/dL" in msg
        assert "acknowledge" in msg.lower()

    def test_primary_contact_message_includes_email(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, severity=AlertSeverity.EMERGENCY)

        msg = build_escalation_message(
            alert, EscalationTier.PRIMARY_CONTACT, "patient@test.com"
        )

        assert "patient@test.com" in msg
        assert "has not responded" in msg
        assert "EMERGENCY" in msg
        assert "55 mg/dL" in msg
        assert "check on them immediately" in msg.lower()

    def test_all_contacts_message_mentions_primary_not_responded(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id)

        msg = build_escalation_message(
            alert, EscalationTier.ALL_CONTACTS, "patient@test.com"
        )

        assert "patient@test.com" in msg
        assert "Primary contact has not responded" in msg

    def test_message_includes_glucose_value(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id)
        alert.current_value = 42.0

        msg = build_escalation_message(
            alert, EscalationTier.PRIMARY_CONTACT, "user@test.com"
        )

        assert "42 mg/dL" in msg

    def test_message_renders_current_glucose_in_mmol(self):
        """The 'Current glucose' line converts to the patient's unit
        (42 -> 2.3); Alert.message is already rendered in mmol at persist time."""
        user_id = uuid.uuid4()
        alert = make_alert(user_id)
        alert.current_value = 42.0
        alert.message = "Predicted low glucose: 2.3 mmol/L"

        msg = build_escalation_message(
            alert, EscalationTier.REMINDER, "user@test.com", GlucoseUnit.MMOL
        )

        assert "Current glucose: 2.3 mmol/L" in msg
        assert "mg/dL" not in msg


# ── Dispatch notification tests ──


class TestDispatchNotification:
    """Tests for dispatch_notification with real Telegram delivery."""

    @pytest.mark.asyncio
    async def test_reminder_returns_sent(self):
        status = await dispatch_notification(
            AsyncMock(), EscalationTier.REMINDER, "test msg", []
        )
        assert status == NotificationStatus.SENT

    @pytest.mark.asyncio
    @patch(
        "src.services.escalation_engine._resolve_contact_chat_id",
        new_callable=AsyncMock,
    )
    @patch("src.services.escalation_engine.send_message", new_callable=AsyncMock)
    async def test_primary_contact_resolves_and_sends(self, mock_send, mock_resolve):
        mock_resolve.return_value = 12345
        mock_send.return_value = True

        user_id = uuid.uuid4()
        contacts = [make_contact(user_id)]
        status = await dispatch_notification(
            AsyncMock(),
            EscalationTier.PRIMARY_CONTACT,
            "test msg",
            contacts,
        )
        assert status == NotificationStatus.SENT
        mock_send.assert_called_once_with(12345, "test msg")

    @pytest.mark.asyncio
    @patch(
        "src.services.escalation_engine._resolve_contact_chat_id",
        new_callable=AsyncMock,
    )
    @patch("src.services.escalation_engine.send_message", new_callable=AsyncMock)
    async def test_all_contacts_sends_to_each(self, mock_send, mock_resolve):
        mock_resolve.return_value = 99999
        mock_send.return_value = True

        user_id = uuid.uuid4()
        contacts = [make_contact(user_id), make_contact(user_id, name="Bob")]
        status = await dispatch_notification(
            AsyncMock(),
            EscalationTier.ALL_CONTACTS,
            "test msg",
            contacts,
        )
        assert status == NotificationStatus.SENT
        assert mock_send.call_count == 2

    @pytest.mark.asyncio
    async def test_no_contacts_returns_failed(self):
        """Contact tier with empty contact list should return FAILED."""
        status = await dispatch_notification(
            AsyncMock(), EscalationTier.PRIMARY_CONTACT, "test msg", []
        )
        assert status == NotificationStatus.FAILED

    @pytest.mark.asyncio
    async def test_contact_without_username_skipped(self):
        """Contacts without telegram_username are skipped; all skipped = FAILED."""
        user_id = uuid.uuid4()
        contact = make_contact(user_id, name="No TG")
        contact.telegram_username = None

        status = await dispatch_notification(
            AsyncMock(),
            EscalationTier.PRIMARY_CONTACT,
            "test msg",
            [contact],
        )
        assert status == NotificationStatus.FAILED

    @pytest.mark.asyncio
    @patch(
        "src.services.escalation_engine._resolve_contact_chat_id",
        new_callable=AsyncMock,
    )
    async def test_contact_not_linked_to_bot_skipped(self, mock_resolve):
        """Contacts without a linked Telegram bot are skipped."""
        mock_resolve.return_value = None

        user_id = uuid.uuid4()
        contacts = [make_contact(user_id)]
        status = await dispatch_notification(
            AsyncMock(),
            EscalationTier.PRIMARY_CONTACT,
            "test msg",
            contacts,
        )
        assert status == NotificationStatus.FAILED

    @pytest.mark.asyncio
    @patch(
        "src.services.escalation_engine._resolve_contact_chat_id",
        new_callable=AsyncMock,
    )
    @patch("src.services.escalation_engine.send_message", new_callable=AsyncMock)
    async def test_send_failure_caught_gracefully(self, mock_send, mock_resolve):
        """TelegramBotError per contact is caught, doesn't crash."""
        from src.services.telegram_bot import TelegramBotError

        mock_resolve.return_value = 12345
        mock_send.side_effect = TelegramBotError("Bot blocked")

        user_id = uuid.uuid4()
        contacts = [make_contact(user_id)]
        status = await dispatch_notification(
            AsyncMock(),
            EscalationTier.PRIMARY_CONTACT,
            "test msg",
            contacts,
        )
        assert status == NotificationStatus.FAILED


# ── Resolve contact chat_id tests ──


class TestResolveContactChatId:
    """Direct unit tests for _resolve_contact_chat_id."""

    @pytest.mark.asyncio
    async def test_strips_at_sign(self):
        """Leading @ is stripped before querying."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 12345
        db.execute.return_value = mock_result

        result = await _resolve_contact_chat_id(db, "@alice")
        assert result == 12345

    @pytest.mark.asyncio
    async def test_empty_after_strip_returns_none(self):
        """Username that is just '@' returns None without DB call."""
        db = AsyncMock()
        result = await _resolve_contact_chat_id(db, "@")
        assert result is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_string_returns_none(self):
        """Empty string returns None without DB call."""
        db = AsyncMock()
        result = await _resolve_contact_chat_id(db, "")
        assert result is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        """Username not found in TelegramLink returns None."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        result = await _resolve_contact_chat_id(db, "unknown_user")
        assert result is None

    @pytest.mark.asyncio
    async def test_case_insensitive_lookup(self):
        """Username matching should be case-insensitive."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 99999
        db.execute.return_value = mock_result

        result = await _resolve_contact_chat_id(db, "@Alice")
        assert result == 99999


# ── Contact retrieval tests ──


class TestGetContactsForTier:
    """Tests for get_contacts_for_tier."""

    @pytest.mark.asyncio
    async def test_reminder_returns_no_contacts(self):
        mock_db = AsyncMock()
        contacts = await get_contacts_for_tier(
            mock_db, uuid.uuid4(), EscalationTier.REMINDER
        )
        assert contacts == []
        # No DB query should happen for reminders
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_primary_queries_primary_contacts(self):
        user_id = uuid.uuid4()
        primary_contact = make_contact(user_id, priority=ContactPriority.PRIMARY)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [primary_contact]

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        contacts = await get_contacts_for_tier(
            mock_db, user_id, EscalationTier.PRIMARY_CONTACT
        )

        assert len(contacts) == 1
        assert contacts[0].priority == ContactPriority.PRIMARY
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_contacts_queries_all(self):
        user_id = uuid.uuid4()
        primary = make_contact(
            user_id, name="Primary", priority=ContactPriority.PRIMARY
        )
        secondary = make_contact(
            user_id, name="Secondary", priority=ContactPriority.SECONDARY
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [primary, secondary]

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        contacts = await get_contacts_for_tier(
            mock_db, user_id, EscalationTier.ALL_CONTACTS
        )

        assert len(contacts) == 2
        mock_db.execute.assert_called_once()


# ── Event creation tests ──


class TestCreateEscalationEvent:
    """Tests for create_escalation_event."""

    @pytest.mark.asyncio
    async def test_creates_event_successfully(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id)
        contact = make_contact(user_id)

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        event = await create_escalation_event(
            mock_db,
            alert,
            EscalationTier.REMINDER,
            "Test message",
            [contact],
            NotificationStatus.SENT,
        )

        assert event is not None
        assert event.alert_id == alert.id
        assert event.tier == EscalationTier.REMINDER
        assert event.notification_status == NotificationStatus.SENT
        assert str(contact.id) in event.contacts_notified
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_integrity_error_returns_none(self):
        """Duplicate tier for same alert returns None (race condition handling)."""
        user_id = uuid.uuid4()
        alert = make_alert(user_id)

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock(side_effect=IntegrityError("dup", {}, Exception()))
        mock_db.rollback = AsyncMock()

        event = await create_escalation_event(
            mock_db,
            alert,
            EscalationTier.REMINDER,
            "Test message",
            [],
            NotificationStatus.SENT,
        )

        assert event is None
        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_contacts_notified_stores_uuids(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id)
        c1 = make_contact(user_id, name="Contact1")
        c2 = make_contact(user_id, name="Contact2")

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        event = await create_escalation_event(
            mock_db,
            alert,
            EscalationTier.ALL_CONTACTS,
            "Test",
            [c1, c2],
            NotificationStatus.SENT,
        )

        assert len(event.contacts_notified) == 2
        assert str(c1.id) in event.contacts_notified
        assert str(c2.id) in event.contacts_notified


# ── Full escalation flow tests ──


class TestEscalateAlert:
    """Tests for escalate_alert orchestration."""

    @pytest.mark.asyncio
    async def test_escalates_when_due(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=6)

        mock_config = make_config(user_id, reminder=5)

        # Mock: no existing events, DB operations succeed
        mock_db = AsyncMock()

        # get_or_create_config
        with (
            patch(
                "src.services.escalation_engine.get_or_create_config",
                return_value=mock_config,
            ),
            patch(
                "src.services.escalation_engine.get_escalation_events_for_alert",
                return_value=[],
            ),
            patch(
                "src.services.escalation_engine.get_contacts_for_tier",
                return_value=[],
            ),
            patch(
                "src.services.escalation_engine.dispatch_notification",
                return_value=NotificationStatus.SENT,
            ),
            patch(
                "src.services.escalation_engine.create_escalation_event",
            ) as mock_create,
        ):
            mock_event = make_event(alert.id, EscalationTier.REMINDER)
            mock_create.return_value = mock_event

            result = await escalate_alert(mock_db, alert, "user@test.com")

            assert result is not None
            assert result.tier == EscalationTier.REMINDER

    @pytest.mark.asyncio
    async def test_no_escalation_when_not_due(self):
        user_id = uuid.uuid4()
        alert = make_alert(user_id, age_minutes=2)
        mock_config = make_config(user_id, reminder=5)

        mock_db = AsyncMock()

        with (
            patch(
                "src.services.escalation_engine.get_or_create_config",
                return_value=mock_config,
            ),
            patch(
                "src.services.escalation_engine.get_escalation_events_for_alert",
                return_value=[],
            ),
        ):
            result = await escalate_alert(mock_db, alert, "user@test.com")

            assert result is None


class TestProcessEscalationsForUser:
    """Tests for process_escalations_for_user."""

    @pytest.mark.asyncio
    async def test_no_alerts_returns_zero(self):
        mock_db = AsyncMock()

        with patch(
            "src.services.escalation_engine.get_unacknowledged_critical_alerts",
            return_value=[],
        ):
            count = await process_escalations_for_user(
                mock_db, uuid.uuid4(), "user@test.com"
            )
            assert count == 0

    @pytest.mark.asyncio
    async def test_processes_multiple_alerts(self):
        user_id = uuid.uuid4()
        alert1 = make_alert(user_id, age_minutes=10)
        alert2 = make_alert(user_id, age_minutes=15)

        mock_db = AsyncMock()
        mock_event = make_event(alert1.id, EscalationTier.REMINDER)

        with (
            patch(
                "src.services.escalation_engine.get_unacknowledged_critical_alerts",
                return_value=[alert1, alert2],
            ),
            patch(
                "src.services.escalation_engine.escalate_alert",
                return_value=mock_event,
            ),
        ):
            count = await process_escalations_for_user(
                mock_db, user_id, "user@test.com"
            )
            assert count == 2

    @pytest.mark.asyncio
    async def test_counts_only_successful_escalations(self):
        user_id = uuid.uuid4()
        alert1 = make_alert(user_id)
        alert2 = make_alert(user_id)

        mock_db = AsyncMock()
        mock_event = make_event(alert1.id, EscalationTier.REMINDER)

        with (
            patch(
                "src.services.escalation_engine.get_unacknowledged_critical_alerts",
                return_value=[alert1, alert2],
            ),
            patch(
                "src.services.escalation_engine.escalate_alert",
                side_effect=[mock_event, None],
            ),
        ):
            count = await process_escalations_for_user(
                mock_db, user_id, "user@test.com"
            )
            assert count == 1


# ── Endpoint tests ──


class TestEscalationTimelineEndpoint:
    """Tests for GET /api/escalation/alerts/{alert_id}/timeline."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        alert_id = uuid.uuid4()
        response = await client.get(f"/api/escalation/alerts/{alert_id}/timeline")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_alert_returns_404(self, client):
        cookie, _ = await register_and_login(client)
        fake_alert_id = uuid.uuid4()

        response = await client.get(
            f"/api/escalation/alerts/{fake_alert_id}/timeline",
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert response.status_code == 404
        assert "Alert not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_returns_empty_timeline_for_alert_with_no_escalations(self, client):
        """Create a real alert and verify empty timeline is returned."""
        cookie, email = await register_and_login(client)

        me_response = await client.get(
            "/api/auth/me",
            cookies={settings.jwt_cookie_name: cookie},
        )
        user_id = me_response.json()["id"]

        # Seed data using a standalone session
        now = datetime.now(UTC)
        async with get_session_maker()() as db:
            alert = Alert(
                user_id=user_id,
                alert_type=AlertType.LOW_URGENT,
                severity=AlertSeverity.URGENT,
                current_value=55.0,
                predicted_value=50.0,
                prediction_minutes=30,
                message="Test alert for escalation timeline",
                source="predictive",
                acknowledged=False,
                created_at=now,
                expires_at=now + timedelta(hours=4),
            )
            db.add(alert)
            await db.commit()
            await db.refresh(alert)
            alert_id = alert.id

        response = await client.get(
            f"/api/escalation/alerts/{alert_id}/timeline",
            cookies={settings.jwt_cookie_name: cookie},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["alert_id"] == str(alert_id)
        assert data["events"] == []
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_returns_timeline_with_events(self, client):
        """Create alert + escalation events and verify timeline content."""
        cookie, email = await register_and_login(client)

        me_response = await client.get(
            "/api/auth/me",
            cookies={settings.jwt_cookie_name: cookie},
        )
        user_id = me_response.json()["id"]

        now = datetime.now(UTC)
        async with get_session_maker()() as db:
            alert = Alert(
                user_id=user_id,
                alert_type=AlertType.LOW_URGENT,
                severity=AlertSeverity.URGENT,
                current_value=55.0,
                predicted_value=50.0,
                prediction_minutes=30,
                message="Test alert",
                source="predictive",
                acknowledged=False,
                created_at=now - timedelta(minutes=30),
                expires_at=now + timedelta(hours=4),
            )
            db.add(alert)
            await db.commit()
            await db.refresh(alert)
            alert_id = alert.id

            event1 = EscalationEvent(
                alert_id=alert_id,
                user_id=user_id,
                tier=EscalationTier.REMINDER,
                triggered_at=now - timedelta(minutes=25),
                message_content="Reminder message",
                notification_status=NotificationStatus.SENT,
                contacts_notified=[],
                created_at=now - timedelta(minutes=25),
            )
            event2 = EscalationEvent(
                alert_id=alert_id,
                user_id=user_id,
                tier=EscalationTier.PRIMARY_CONTACT,
                triggered_at=now - timedelta(minutes=20),
                message_content="Primary contact message",
                notification_status=NotificationStatus.SENT,
                contacts_notified=[str(uuid.uuid4())],
                created_at=now - timedelta(minutes=20),
            )
            db.add(event1)
            db.add(event2)
            await db.commit()

        response = await client.get(
            f"/api/escalation/alerts/{alert_id}/timeline",
            cookies={settings.jwt_cookie_name: cookie},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["events"]) == 2
        assert data["events"][0]["tier"] == "reminder"
        assert data["events"][1]["tier"] == "primary_contact"
        assert data["events"][0]["notification_status"] == "sent"

    @pytest.mark.asyncio
    async def test_cannot_view_other_users_alert_timeline(self, client):
        """User A cannot view User B's alert escalation timeline."""
        cookie_a, _ = await register_and_login(client)

        cookie_b, _ = await register_and_login(client)
        me_b = await client.get(
            "/api/auth/me",
            cookies={settings.jwt_cookie_name: cookie_b},
        )
        user_b_id = me_b.json()["id"]

        now = datetime.now(UTC)
        async with get_session_maker()() as db:
            alert = Alert(
                user_id=user_b_id,
                alert_type=AlertType.LOW_URGENT,
                severity=AlertSeverity.URGENT,
                current_value=55.0,
                predicted_value=50.0,
                prediction_minutes=30,
                message="User B alert",
                source="predictive",
                acknowledged=False,
                created_at=now,
                expires_at=now + timedelta(hours=4),
            )
            db.add(alert)
            await db.commit()
            await db.refresh(alert)
            alert_id = alert.id

        # User A tries to view User B's alert timeline
        response = await client.get(
            f"/api/escalation/alerts/{alert_id}/timeline",
            cookies={settings.jwt_cookie_name: cookie_a},
        )
        assert response.status_code == 404


# ── Enum value tests ──


class TestEscalationEnums:
    """Tests for enum values used in the escalation system."""

    def test_escalation_tier_values(self):
        assert EscalationTier.REMINDER.value == "reminder"
        assert EscalationTier.PRIMARY_CONTACT.value == "primary_contact"
        assert EscalationTier.ALL_CONTACTS.value == "all_contacts"

    def test_notification_status_values(self):
        assert NotificationStatus.PENDING.value == "pending"
        assert NotificationStatus.SENT.value == "sent"
        assert NotificationStatus.FAILED.value == "failed"
