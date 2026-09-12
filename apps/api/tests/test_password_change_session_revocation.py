"""Tests for session/refresh-token revocation on password change (CR-04).

Changing a password must invalidate every outstanding session and refresh
token for that user, not just the token used to make the change request. This
is enforced by stamping ``users.password_changed_at`` on change and rejecting
any access or refresh token whose ``iat`` predates that timestamp.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt
from sqlalchemy import select

from src.config import settings
from src.core.security import is_token_issued_before
from src.database import get_session_maker
from src.models.user import User


class TestIsTokenIssuedBefore:
    """Unit tests for the iat-vs-cutoff comparison (whole-second granularity)."""

    def test_null_cutoff_never_stale(self):
        """A user who never changed their password imposes no restriction."""
        iat = int(datetime.now(UTC).timestamp())
        assert is_token_issued_before(iat, None) is False

    def test_iat_before_cutoff_is_stale(self):
        """A token issued before the cutoff is rejected."""
        cutoff = datetime.now(UTC)
        iat = int((cutoff - timedelta(seconds=60)).timestamp())
        assert is_token_issued_before(iat, cutoff) is True

    def test_iat_after_cutoff_is_fresh(self):
        """A token issued after the cutoff is accepted."""
        cutoff = datetime.now(UTC)
        iat = int((cutoff + timedelta(seconds=60)).timestamp())
        assert is_token_issued_before(iat, cutoff) is False

    def test_same_second_is_not_stale(self):
        """A token minted in the same second as the change survives (grace)."""
        cutoff = datetime.now(UTC).replace(microsecond=500_000)
        iat = int(cutoff.timestamp())  # same whole second, no microseconds
        assert is_token_issued_before(iat, cutoff) is False

    def test_missing_iat_with_cutoff_is_stale(self):
        """A token with no iat cannot be proven fresh, so it is rejected."""
        assert is_token_issued_before(None, datetime.now(UTC)) is True


def _encode(token_type: str, user_id: uuid.UUID, email: str, iat: datetime) -> str:
    """Encode an access/refresh JWT with an explicit issued-at time."""
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": "diabetic",
        "exp": iat + timedelta(hours=1),
        "iat": iat,
        "type": token_type,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


async def _register_and_cookie(client, email: str, password: str = "TestPass1") -> str:
    """Register a user and return a valid session cookie."""
    reg = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code == 201
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    return login.cookies.get(settings.jwt_cookie_name)


class TestPasswordChangeRevokesOtherSessions:
    """Endpoint tests: a password change invalidates other tokens."""

    @pytest.mark.asyncio
    async def test_other_session_access_token_rejected_after_change(self, client):
        """An access token from a different session is rejected post-change."""
        email = f"cr04_access_{uuid.uuid4().hex[:8]}@test.com"
        reg = await client.post(
            "/api/auth/register", json={"email": email, "password": "TestPass1"}
        )
        user_id = uuid.UUID(reg.json()["id"])

        # A second, older session's access token (issued before the change).
        other_token = _encode(
            "access", user_id, email, datetime.now(UTC) - timedelta(seconds=60)
        )
        # It works before the password change.
        before = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {other_token}"}
        )
        assert before.status_code == 200

        # Change the password using session 1 (a cookie).
        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "TestPass1"}
        )
        cookie = login.cookies.get(settings.jwt_cookie_name)
        changed = await client.post(
            "/api/auth/change-password",
            json={"current_password": "TestPass1", "new_password": "TestPass2"},
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert changed.status_code == 200

        # Session 2's token -- never blacklisted, but pre-change -- is now dead.
        after = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {other_token}"}
        )
        assert after.status_code == 401

    @pytest.mark.asyncio
    async def test_pre_change_refresh_token_rejected_after_change(self, client):
        """A refresh token issued before the change can no longer be exchanged."""
        email = f"cr04_refresh_{uuid.uuid4().hex[:8]}@test.com"
        reg = await client.post(
            "/api/auth/register", json={"email": email, "password": "TestPass1"}
        )
        user_id = uuid.UUID(reg.json()["id"])

        # Two distinct pre-change refresh tokens (one for the sanity check that
        # consumes it, one to test after the change).
        sanity_refresh = _encode(
            "refresh", user_id, email, datetime.now(UTC) - timedelta(seconds=60)
        )
        pre_change_refresh = _encode(
            "refresh", user_id, email, datetime.now(UTC) - timedelta(seconds=60)
        )
        sanity = await client.post(
            "/api/auth/mobile/refresh", json={"refresh_token": sanity_refresh}
        )
        assert sanity.status_code == 200

        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "TestPass1"}
        )
        cookie = login.cookies.get(settings.jwt_cookie_name)
        changed = await client.post(
            "/api/auth/change-password",
            json={"current_password": "TestPass1", "new_password": "TestPass2"},
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert changed.status_code == 200

        after = await client.post(
            "/api/auth/mobile/refresh", json={"refresh_token": pre_change_refresh}
        )
        assert after.status_code == 401

    @pytest.mark.asyncio
    async def test_token_issued_after_change_still_works(self, client):
        """A session started after the change is unaffected (no over-rejection)."""
        email = f"cr04_control_{uuid.uuid4().hex[:8]}@test.com"
        cookie = await _register_and_cookie(client, email)
        changed = await client.post(
            "/api/auth/change-password",
            json={"current_password": "TestPass1", "new_password": "TestPass2"},
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert changed.status_code == 200

        # Fresh login after the change.
        relogin = await client.post(
            "/api/auth/login", json={"email": email, "password": "TestPass2"}
        )
        new_cookie = relogin.cookies.get(settings.jwt_cookie_name)
        me = await client.get(
            "/api/auth/me", cookies={settings.jwt_cookie_name: new_cookie}
        )
        assert me.status_code == 200
        assert me.json()["email"] == email

    @pytest.mark.asyncio
    async def test_change_password_stamps_password_changed_at(self, client):
        """The change writes users.password_changed_at (was never set before)."""
        email = f"cr04_stamp_{uuid.uuid4().hex[:8]}@test.com"
        cookie = await _register_and_cookie(client, email)

        before = datetime.now(UTC) - timedelta(seconds=1)
        changed = await client.post(
            "/api/auth/change-password",
            json={"current_password": "TestPass1", "new_password": "TestPass2"},
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert changed.status_code == 200

        # Read back through a self-contained session (closed within this test's
        # event loop) to avoid the session-scoped-engine teardown race.
        async with get_session_maker()() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()
        assert user.password_changed_at is not None
        assert user.password_changed_at >= before
