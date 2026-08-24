"""Story 7.1: Telegram bot setup & configuration tests.

Tests for the Telegram bot service, verification flow, and API endpoints.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete, func, select, update

from src.database import get_session_maker
from src.models.telegram_bot_config import TelegramBotConfig
from src.models.telegram_link import TelegramLink
from src.models.telegram_verification import TelegramVerificationCode
from src.models.user import User, UserRole
from src.services.telegram_bot import (
    CODE_ALPHABET,
    CODE_LENGTH,
    TelegramBotError,
    TelegramBotIdentity,
    _generate_code,
    generate_verification_code,
    get_bot_info,
    get_telegram_link,
    reset_bot_cache,
    send_message,
    unlink_telegram,
    verify_telegram_link,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def register_and_login(client, email="tg@example.com", password="Test1234!"):
    """Register a user and return auth cookies as a dict."""
    from src.config import settings as app_settings

    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    cookie_value = resp.cookies.get(app_settings.jwt_cookie_name)
    return {app_settings.jwt_cookie_name: cookie_value}


async def register_admin_and_login(
    client,
    email="tg-admin@example.com",
    password="SecurePass123",
):
    """Register an administrator and return auth cookies as a dict."""
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    async with get_session_maker()() as db:
        await db.execute(
            update(User).where(User.email == email).values(role=UserRole.ADMIN)
        )
        await db.commit()

    from src.config import settings as app_settings

    response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    cookie_value = response.cookies.get(app_settings.jwt_cookie_name)
    return {app_settings.jwt_cookie_name: cookie_value}


async def create_test_user(email: str = "tgtest@example.com") -> uuid.UUID:
    """Create a real user in the DB and return their UUID."""
    from bcrypt import gensalt, hashpw

    user_id = uuid.uuid4()
    hashed = hashpw(b"Test1234!", gensalt()).decode()

    async with get_session_maker()() as db:
        user = User(
            id=user_id,
            email=email,
            hashed_password=hashed,
        )
        db.add(user)
        await db.commit()

    return user_id


async def cleanup_user(user_id: uuid.UUID) -> None:
    """Clean up test user and related data."""
    async with get_session_maker()() as db:
        await db.execute(delete(TelegramLink).where(TelegramLink.user_id == user_id))
        await db.execute(
            delete(TelegramVerificationCode).where(
                TelegramVerificationCode.user_id == user_id
            )
        )
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


async def cleanup_bot_config_test_data(user_id: uuid.UUID) -> None:
    """Remove the shared bot config and user-owned Telegram test data."""
    async with get_session_maker()() as db:
        await db.execute(delete(TelegramBotConfig))
        await db.commit()

    await cleanup_user(user_id)


# ---------------------------------------------------------------------------
# Service tests: Code generation (pure, no DB)
# ---------------------------------------------------------------------------
class TestCodeGeneration:
    """Tests for verification code generation."""

    def test_generate_code_length(self):
        """Code should be exactly CODE_LENGTH characters."""
        code = _generate_code()
        assert len(code) == CODE_LENGTH

    def test_generate_code_alphabet(self):
        """Code should only contain characters from CODE_ALPHABET."""
        for _ in range(100):
            code = _generate_code()
            for char in code:
                assert char in CODE_ALPHABET

    def test_generate_code_no_ambiguous_chars(self):
        """Code should not contain ambiguous characters (0, O, 1, I)."""
        for _ in range(100):
            code = _generate_code()
            assert "O" not in code
            assert "I" not in code
            assert "0" not in code
            assert "1" not in code

    def test_generate_code_uniqueness(self):
        """Codes should be unique (probabilistic)."""
        codes = {_generate_code() for _ in range(100)}
        assert len(codes) >= 95


# ---------------------------------------------------------------------------
# Service tests: Verification code DB operations
# ---------------------------------------------------------------------------
class TestGenerateVerificationCode:
    """Tests for database verification code generation."""

    @pytest.mark.asyncio
    async def test_generates_code_and_expiry(self):
        """Should create a code with ~10 minute expiry."""
        user_id = await create_test_user("tg_gen_code@example.com")
        try:
            async with get_session_maker()() as db:
                code, expires_at = await generate_verification_code(db, user_id)

            assert len(code) == CODE_LENGTH
            assert expires_at > datetime.now(UTC)
            assert expires_at < datetime.now(UTC) + timedelta(minutes=11)
        finally:
            await cleanup_user(user_id)

    @pytest.mark.asyncio
    async def test_replaces_existing_code(self):
        """Generating a new code should replace the old one."""
        user_id = await create_test_user("tg_replace@example.com")
        try:
            async with get_session_maker()() as db:
                code1, _ = await generate_verification_code(db, user_id)
                code2, _ = await generate_verification_code(db, user_id)

            assert code1 != code2

            async with get_session_maker()() as db:
                result = await db.execute(
                    select(func.count()).where(
                        TelegramVerificationCode.user_id == user_id
                    )
                )
                count = result.scalar()
                assert count == 1
        finally:
            await cleanup_user(user_id)


# ---------------------------------------------------------------------------
# Service tests: Verification and linking
# ---------------------------------------------------------------------------
class TestVerifyTelegramLink:
    """Tests for the verification and linking flow."""

    @pytest.mark.asyncio
    @patch("src.services.telegram_bot.send_message", new_callable=AsyncMock)
    async def test_valid_code_creates_link(self, mock_send):
        """A valid, non-expired code should create a TelegramLink."""
        user_id = await create_test_user("tg_verify@example.com")
        try:
            async with get_session_maker()() as db:
                code, _ = await generate_verification_code(db, user_id)

            async with get_session_maker()() as db:
                result = await verify_telegram_link(db, code, 123456789, "testuser")
                assert result is True

            async with get_session_maker()() as db:
                link = await get_telegram_link(db, user_id)
                assert link is not None
                assert link.chat_id == 123456789
                assert link.username == "testuser"
                assert link.is_verified is True
        finally:
            await cleanup_user(user_id)

    @pytest.mark.asyncio
    async def test_expired_code_returns_false(self):
        """An expired code should not create a link."""
        user_id = await create_test_user("tg_expired@example.com")
        try:
            async with get_session_maker()() as db:
                verification = TelegramVerificationCode(
                    user_id=user_id,
                    code="EXPRD2",
                    expires_at=datetime.now(UTC) - timedelta(minutes=1),
                )
                db.add(verification)
                await db.commit()

            async with get_session_maker()() as db:
                result = await verify_telegram_link(db, "EXPRD2", 987654321, None)
                assert result is False
        finally:
            await cleanup_user(user_id)

    @pytest.mark.asyncio
    async def test_invalid_code_returns_false(self):
        """A non-existent code should not create a link."""
        async with get_session_maker()() as db:
            result = await verify_telegram_link(db, "NONEXISTENT", 111111111, None)
            assert result is False

    @pytest.mark.asyncio
    @patch("src.services.telegram_bot.send_message", new_callable=AsyncMock)
    async def test_verification_deletes_code(self, mock_send):
        """Successful verification should delete the verification code."""
        user_id = await create_test_user("tg_delcode@example.com")
        try:
            async with get_session_maker()() as db:
                code, _ = await generate_verification_code(db, user_id)

            async with get_session_maker()() as db:
                await verify_telegram_link(db, code, 555555555, None)

            async with get_session_maker()() as db:
                result = await db.execute(
                    select(TelegramVerificationCode).where(
                        TelegramVerificationCode.user_id == user_id
                    )
                )
                assert result.scalar_one_or_none() is None
        finally:
            await cleanup_user(user_id)


# ---------------------------------------------------------------------------
# Service tests: Unlink
# ---------------------------------------------------------------------------
class TestUnlinkTelegram:
    """Tests for unlinking Telegram accounts."""

    @pytest.mark.asyncio
    @patch("src.services.telegram_bot.send_message", new_callable=AsyncMock)
    async def test_unlink_success(self, mock_send):
        """Should delete the link and return True."""
        user_id = await create_test_user("tg_unlink_svc@example.com")
        try:
            async with get_session_maker()() as db:
                link = TelegramLink(
                    user_id=user_id,
                    chat_id=777777777,
                    username="unlinkme",
                    is_verified=True,
                    linked_at=datetime.now(UTC),
                )
                db.add(link)
                await db.commit()

            async with get_session_maker()() as db:
                result = await unlink_telegram(db, user_id)
                assert result is True

            async with get_session_maker()() as db:
                link = await get_telegram_link(db, user_id)
                assert link is None
        finally:
            await cleanup_user(user_id)

    @pytest.mark.asyncio
    async def test_unlink_not_found(self):
        """Should return False if no link exists."""
        async with get_session_maker()() as db:
            result = await unlink_telegram(db, uuid.uuid4())
            assert result is False

    @pytest.mark.asyncio
    @patch("src.services.telegram_bot.send_message", new_callable=AsyncMock)
    async def test_unlink_cleans_up_verification_codes(self, mock_send):
        """Unlink should also delete any pending verification codes."""
        user_id = await create_test_user("tg_unlink_codes@example.com")
        try:
            # Create a link AND a pending verification code
            async with get_session_maker()() as db:
                link = TelegramLink(
                    user_id=user_id,
                    chat_id=888888888,
                    username="unlinkclean",
                    is_verified=True,
                    linked_at=datetime.now(UTC),
                )
                db.add(link)
                await db.commit()

            async with get_session_maker()() as db:
                await generate_verification_code(db, user_id)

            async with get_session_maker()() as db:
                result = await unlink_telegram(db, user_id)
                assert result is True

            # Verify both link and code are gone
            async with get_session_maker()() as db:
                code_result = await db.execute(
                    select(TelegramVerificationCode).where(
                        TelegramVerificationCode.user_id == user_id
                    )
                )
                assert code_result.scalar_one_or_none() is None
        finally:
            await cleanup_user(user_id)


# ---------------------------------------------------------------------------
# Service tests: Duplicate chat_id
# ---------------------------------------------------------------------------
class TestDuplicateChatId:
    """Tests for duplicate chat_id protection."""

    @pytest.mark.asyncio
    @patch("src.services.telegram_bot.send_message", new_callable=AsyncMock)
    async def test_verify_rejects_duplicate_chat_id(self, mock_send):
        """Linking a chat_id already used by another user returns False."""
        user_a = await create_test_user("tg_dup_a@example.com")
        user_b = await create_test_user("tg_dup_b@example.com")
        try:
            # Link user_a with chat_id 123456789
            async with get_session_maker()() as db:
                code_a, _ = await generate_verification_code(db, user_a)
            async with get_session_maker()() as db:
                result_a = await verify_telegram_link(db, code_a, 123456789, "userA")
                assert result_a is True

            # Try to link user_b with the SAME chat_id
            async with get_session_maker()() as db:
                code_b, _ = await generate_verification_code(db, user_b)
            async with get_session_maker()() as db:
                result_b = await verify_telegram_link(db, code_b, 123456789, "userB")
                assert result_b is False

            # Verify user_b has no link
            async with get_session_maker()() as db:
                link = await get_telegram_link(db, user_b)
                assert link is None
        finally:
            await cleanup_user(user_a)
            await cleanup_user(user_b)


# ---------------------------------------------------------------------------
# Service tests: Bot API calls (mocked, no DB)
# ---------------------------------------------------------------------------
class TestBotApiCalls:
    """Tests for Telegram Bot API calls (httpx mocked)."""

    @pytest.mark.asyncio
    async def test_get_bot_info_success(self):
        """Should return the bot username."""
        reset_bot_cache()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"id": 123456789, "username": "GlycemicGPT_bot"},
        }

        with (
            patch("src.services.telegram_bot.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.telegram_bot_token = "fake-token"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await get_bot_info()
            assert result == "GlycemicGPT_bot"

        reset_bot_cache()

    @pytest.mark.asyncio
    async def test_get_bot_info_no_token(self):
        """Should raise TelegramBotError if no token configured."""
        reset_bot_cache()
        with patch("src.services.telegram_bot.settings") as mock_settings:
            mock_settings.telegram_bot_token = ""
            with pytest.raises(TelegramBotError, match="not configured"):
                await get_bot_info()
        reset_bot_cache()

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Should return True on successful send."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        with (
            patch("src.services.telegram_bot.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.telegram_bot_token = "fake-token"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await send_message(123456, "Hello")
            assert result is True

    @pytest.mark.asyncio
    async def test_send_message_failure(self):
        """Should raise TelegramBotError on API failure."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with (
            patch("src.services.telegram_bot.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.telegram_bot_token = "fake-token"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(TelegramBotError, match="Failed to send"):
                await send_message(123456, "Hello")


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------
class TestTelegramEndpoints:
    """Tests for the Telegram API endpoints."""

    @pytest.mark.asyncio
    @patch("src.routers.telegram.get_bot_identity", new_callable=AsyncMock)
    async def test_bot_config_can_be_saved_read_and_removed(
        self, mock_bot_identity, client
    ):
        """The web token setup flow must have a persistent API contract."""
        mock_bot_identity.return_value = TelegramBotIdentity(
            bot_id=123456789,
            username="ConfiguredBot",
        )
        cookies = await register_admin_and_login(client, "tg_config_admin@example.com")

        save_resp = await client.post(
            "/api/telegram/bot-config",
            json={"token": "123456789:test-token"},
            cookies=cookies,
        )
        assert save_resp.status_code == 200
        assert save_resp.json() == {
            "valid": True,
            "bot_username": "ConfiguredBot",
        }

        get_resp = await client.get("/api/telegram/bot-config", cookies=cookies)
        assert get_resp.status_code == 200
        assert get_resp.json()["configured"] is True
        assert get_resp.json()["can_manage"] is True
        assert get_resp.json()["bot_username"] == "ConfiguredBot"
        assert get_resp.json()["configured_at"] is not None

        async with get_session_maker()() as db:
            stored_config = await db.get(TelegramBotConfig, 1)
            assert stored_config is not None
            assert stored_config.encrypted_token != "123456789:test-token"
            assert "test-token" not in stored_config.encrypted_token
            assert stored_config.bot_id == "123456789"

            primary_user = (
                await db.execute(
                    select(User).where(User.email == "tg_config_admin@example.com")
                )
            ).scalar_one()
            primary_user_id = primary_user.id
            db.add(
                TelegramLink(
                    user_id=primary_user.id,
                    chat_id=987654321,
                    username="configured_user",
                    is_verified=True,
                )
            )
            db.add(
                TelegramVerificationCode(
                    user_id=primary_user.id,
                    code="FRESH2",
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            )
            await db.commit()

        delete_resp = await client.delete("/api/telegram/bot-config", cookies=cookies)
        assert delete_resp.status_code == 204

        get_after_delete = await client.get("/api/telegram/bot-config", cookies=cookies)
        assert get_after_delete.status_code == 200
        assert get_after_delete.json() == {
            "configured": False,
            "can_manage": True,
            "bot_username": None,
            "configured_at": None,
        }

        async with get_session_maker()() as db:
            remaining_links = await db.scalar(
                select(func.count()).select_from(TelegramLink)
            )
            remaining_codes = await db.scalar(
                select(func.count()).select_from(TelegramVerificationCode)
            )
            assert remaining_links == 0
            assert remaining_codes == 0

        await cleanup_bot_config_test_data(primary_user_id)

    @pytest.mark.asyncio
    @patch("src.routers.telegram.get_bot_identity", new_callable=AsyncMock)
    async def test_replacing_bot_clears_existing_link_state(
        self,
        mock_bot_identity,
        client,
    ):
        """Links and pending codes cannot carry over to another Telegram bot."""
        mock_bot_identity.side_effect = [
            TelegramBotIdentity(bot_id=111, username="FirstBot"),
            TelegramBotIdentity(bot_id=222, username="SecondBot"),
        ]
        cookies = await register_admin_and_login(
            client,
            "tg_replace_bot@example.com",
        )

        first_response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "111:first-token"},
            cookies=cookies,
        )
        assert first_response.status_code == 200

        async with get_session_maker()() as db:
            user = (
                await db.execute(
                    select(User).where(User.email == "tg_replace_bot@example.com")
                )
            ).scalar_one()
            user_id = user.id
            db.add(
                TelegramLink(
                    user_id=user.id,
                    chat_id=111111,
                    username="linked_user",
                    is_verified=True,
                )
            )
            db.add(
                TelegramVerificationCode(
                    user_id=user.id,
                    code="OLD123",
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            )
            await db.commit()

        second_response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "222:second-token"},
            cookies=cookies,
        )
        assert second_response.status_code == 200

        async with get_session_maker()() as db:
            config = await db.get(TelegramBotConfig, 1)
            assert config is not None
            assert config.bot_id == "222"
            assert await db.scalar(select(func.count()).select_from(TelegramLink)) == 0
            assert (
                await db.scalar(
                    select(func.count()).select_from(TelegramVerificationCode)
                )
                == 0
            )

        await cleanup_bot_config_test_data(user_id)

    @pytest.mark.asyncio
    @patch("src.routers.telegram.get_bot_identity", new_callable=AsyncMock)
    async def test_refreshing_same_bot_preserves_existing_link_state(
        self,
        mock_bot_identity,
        client,
    ):
        """Refreshing credentials for the same bot keeps user connections."""
        mock_bot_identity.side_effect = [
            TelegramBotIdentity(bot_id=333, username="StableBot"),
            TelegramBotIdentity(bot_id=333, username="RenamedStableBot"),
        ]
        cookies = await register_admin_and_login(
            client,
            "tg_same_bot@example.com",
        )

        first_response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "333:first-token"},
            cookies=cookies,
        )
        assert first_response.status_code == 200

        async with get_session_maker()() as db:
            user = (
                await db.execute(
                    select(User).where(User.email == "tg_same_bot@example.com")
                )
            ).scalar_one()
            user_id = user.id
            db.add(
                TelegramLink(
                    user_id=user.id,
                    chat_id=333333,
                    username="linked_user",
                    is_verified=True,
                )
            )
            db.add(
                TelegramVerificationCode(
                    user_id=user.id,
                    code="KEEP33",
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            )
            await db.commit()

        second_response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "333:refreshed-token"},
            cookies=cookies,
        )
        assert second_response.status_code == 200

        async with get_session_maker()() as db:
            config = await db.get(TelegramBotConfig, 1)
            assert config is not None
            assert config.bot_id == "333"
            assert config.bot_username == "RenamedStableBot"
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(TelegramLink)
                    .where(TelegramLink.user_id == user_id)
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(TelegramVerificationCode)
                    .where(TelegramVerificationCode.user_id == user_id)
                )
                == 1
            )

        await cleanup_bot_config_test_data(user_id)

    @pytest.mark.asyncio
    async def test_bot_config_mutations_reject_caregivers(self, client):
        """Caregivers cannot change deployment-wide bot credentials."""
        email = "tg_caregiver@example.com"
        cookies = await register_and_login(client, email)
        async with get_session_maker()() as db:
            await db.execute(
                update(User).where(User.email == email).values(role=UserRole.CAREGIVER)
            )
            await db.commit()

        get_response = await client.get("/api/telegram/bot-config", cookies=cookies)
        save_response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "123456789:test-token"},
            cookies=cookies,
        )
        delete_response = await client.delete(
            "/api/telegram/bot-config",
            cookies=cookies,
        )

        assert get_response.status_code == 200
        assert get_response.json()["can_manage"] is False
        assert save_response.status_code == 403
        assert delete_response.status_code == 403

    @pytest.mark.asyncio
    async def test_bot_config_mutations_reject_diabetics(self, client):
        """Regular diabetic users cannot change deployment credentials."""
        cookies = await register_and_login(client, "tg_diabetic@example.com")

        get_response = await client.get("/api/telegram/bot-config", cookies=cookies)
        save_response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "123456789:test-token"},
            cookies=cookies,
        )
        delete_response = await client.delete(
            "/api/telegram/bot-config",
            cookies=cookies,
        )

        assert get_response.status_code == 200
        assert get_response.json()["can_manage"] is False
        assert save_response.status_code == 403
        assert delete_response.status_code == 403

    @pytest.mark.asyncio
    async def test_bot_config_mutations_require_authentication(self, client):
        """Anonymous callers cannot change deployment credentials."""
        save_response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "123456789:test-token"},
        )
        delete_response = await client.delete("/api/telegram/bot-config")

        assert save_response.status_code == 401
        assert delete_response.status_code == 401

    @pytest.mark.asyncio
    @patch("src.routers.telegram.reset_bot_cache")
    @patch("src.routers.telegram.get_bot_identity", new_callable=AsyncMock)
    async def test_rejected_bot_token_preserves_active_polling_state(
        self,
        mock_bot_identity,
        mock_reset_bot_cache,
        client,
    ):
        """Rejected candidate tokens must not reset the active bot poller."""
        mock_bot_identity.side_effect = TelegramBotError("invalid token")
        cookies = await register_admin_and_login(
            client,
            "tg_invalid_config_admin@example.com",
        )

        response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "invalid-token"},
            cookies=cookies,
        )

        assert response.status_code == 400
        mock_reset_bot_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_blank_bot_token_returns_declared_bad_request(self, client):
        """Whitespace-only credentials use the documented invalid-token response."""
        cookies = await register_admin_and_login(
            client,
            "tg_blank_config_admin@example.com",
        )

        response = await client.post(
            "/api/telegram/bot-config",
            json={"token": "   "},
            cookies=cookies,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Telegram bot token is required"

    @pytest.mark.asyncio
    async def test_status_unauthenticated_returns_401(self, client):
        """GET /api/telegram/status without auth should return 401."""
        resp = await client.get("/api/telegram/status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @patch("src.routers.telegram.get_bot_info", new_callable=AsyncMock)
    @patch("src.routers.telegram.get_telegram_link", new_callable=AsyncMock)
    async def test_status_returns_unlinked(self, mock_get_link, mock_bot_info, client):
        """GET /api/telegram/status should return unlinked status."""
        mock_bot_info.return_value = "TestBot"
        mock_get_link.return_value = None

        with patch("src.routers.telegram.settings") as mock_settings:
            mock_settings.telegram_bot_token = "fake-token"

            cookies = await register_and_login(client, "tg_status@example.com")
            resp = await client.get("/api/telegram/status", cookies=cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert data["linked"] is False
        assert data["link"] is None
        assert data["bot_username"] == "TestBot"

    @pytest.mark.asyncio
    @patch("src.routers.telegram.get_bot_info", new_callable=AsyncMock)
    @patch("src.routers.telegram.get_telegram_link", new_callable=AsyncMock)
    @patch(
        "src.routers.telegram.generate_verification_code",
        new_callable=AsyncMock,
    )
    async def test_link_generates_code(
        self, mock_gen_code, mock_get_link, mock_bot_info, client
    ):
        """POST /api/telegram/link should return a verification code."""
        mock_bot_info.return_value = "TestBot"
        mock_get_link.return_value = None
        mock_gen_code.return_value = (
            "ABC123",
            datetime(2026, 2, 9, 12, 0, 0, tzinfo=UTC),
        )

        with patch("src.routers.telegram.settings") as mock_settings:
            mock_settings.telegram_bot_token = "fake-token"

            cookies = await register_and_login(client, "tg_link@example.com")
            resp = await client.post("/api/telegram/link", cookies=cookies)

        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "ABC123"
        assert data["bot_username"] == "TestBot"

    @pytest.mark.asyncio
    @patch("src.routers.telegram.get_bot_info", new_callable=AsyncMock)
    @patch("src.routers.telegram.get_telegram_link", new_callable=AsyncMock)
    async def test_link_already_linked_returns_409(
        self, mock_get_link, mock_bot_info, client
    ):
        """POST /api/telegram/link when already linked returns 409."""
        mock_bot_info.return_value = "TestBot"
        mock_get_link.return_value = MagicMock()  # Truthy = linked

        with patch("src.routers.telegram.settings") as mock_settings:
            mock_settings.telegram_bot_token = "fake-token"

            cookies = await register_and_login(client, "tg_linked@example.com")
            resp = await client.post("/api/telegram/link", cookies=cookies)

        assert resp.status_code == 409

    @pytest.mark.asyncio
    @patch("src.routers.telegram.unlink_telegram", new_callable=AsyncMock)
    async def test_unlink_success(self, mock_unlink, client):
        """DELETE /api/telegram/link should return success."""
        mock_unlink.return_value = True

        cookies = await register_and_login(client, "tg_unlink@example.com")
        resp = await client.delete("/api/telegram/link", cookies=cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @patch("src.routers.telegram.unlink_telegram", new_callable=AsyncMock)
    async def test_unlink_not_found_returns_404(self, mock_unlink, client):
        """DELETE /api/telegram/link when not linked returns 404."""
        mock_unlink.return_value = False

        cookies = await register_and_login(client, "tg_unlink404@example.com")
        resp = await client.delete("/api/telegram/link", cookies=cookies)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("src.routers.telegram.get_telegram_link", new_callable=AsyncMock)
    async def test_test_message_not_linked_returns_400(self, mock_get_link, client):
        """POST /api/telegram/test when not linked returns 400."""
        mock_get_link.return_value = None

        with patch("src.routers.telegram.settings") as mock_settings:
            mock_settings.telegram_bot_token = "fake-token"

            cookies = await register_and_login(client, "tg_test400@example.com")
            resp = await client.post("/api/telegram/test", cookies=cookies)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.routers.telegram.send_message", new_callable=AsyncMock)
    @patch("src.routers.telegram.get_telegram_link", new_callable=AsyncMock)
    async def test_test_message_success(self, mock_get_link, mock_send, client):
        """POST /api/telegram/test should send and return success."""
        mock_link = MagicMock()
        mock_link.chat_id = 999999
        mock_get_link.return_value = mock_link
        mock_send.return_value = True

        with patch("src.routers.telegram.settings") as mock_settings:
            mock_settings.telegram_bot_token = "fake-token"

            cookies = await register_and_login(client, "tg_test_ok@example.com")
            resp = await client.post("/api/telegram/test", cookies=cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------
class TestTelegramSchemas:
    """Tests for Pydantic schema serialization."""

    def test_status_response_unlinked(self):
        """TelegramStatusResponse should serialize with no link."""
        from src.schemas.telegram import TelegramStatusResponse

        resp = TelegramStatusResponse(linked=False, link=None, bot_username="TestBot")
        data = resp.model_dump()
        assert data["linked"] is False
        assert data["link"] is None
        assert data["bot_username"] == "TestBot"

    def test_status_response_linked(self):
        """TelegramStatusResponse should serialize with a link."""
        from src.schemas.telegram import (
            TelegramLinkResponse,
            TelegramStatusResponse,
        )

        link = TelegramLinkResponse(
            id=uuid.uuid4(),
            chat_id=123456,
            username="testuser",
            is_verified=True,
            linked_at=datetime.now(UTC),
        )
        resp = TelegramStatusResponse(linked=True, link=link, bot_username="TestBot")
        data = resp.model_dump()
        assert data["linked"] is True
        assert data["link"]["chat_id"] == 123456
        assert data["link"]["username"] == "testuser"

    def test_verification_code_response(self):
        """TelegramVerificationCodeResponse should serialize."""
        from src.schemas.telegram import TelegramVerificationCodeResponse

        resp = TelegramVerificationCodeResponse(
            code="ABC123",
            expires_at=datetime.now(UTC),
            bot_username="TestBot",
        )
        data = resp.model_dump()
        assert data["code"] == "ABC123"
        assert data["bot_username"] == "TestBot"
