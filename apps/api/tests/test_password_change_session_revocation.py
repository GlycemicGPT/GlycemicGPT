"""Tests for session/refresh-token revocation on password change (CR-04).

Changing a password must invalidate every outstanding session and refresh
token for that user, not just the token used to make the change request. This
is enforced by a per-user session generation (``users.token_version``): every
token embeds it as a ``ver`` claim at mint time, a change increments it, and any
token carrying a lower ``ver`` is rejected.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt
from sqlalchemy import select

from src.config import settings
from src.core.security import is_token_version_stale
from src.database import get_session_maker
from src.models.user import User


class TestIsTokenVersionStale:
    """Unit tests for the session-generation comparison."""

    def test_equal_version_is_fresh(self):
        """A token at the user's current generation is accepted."""
        assert is_token_version_stale(2, 2) is False

    def test_lower_version_is_stale(self):
        """A token from an older generation is rejected."""
        assert is_token_version_stale(1, 2) is True

    def test_higher_version_is_fresh(self):
        """A token ahead of the user (shouldn't occur) is not treated as stale."""
        assert is_token_version_stale(3, 2) is False

    def test_missing_version_treated_as_v1(self):
        """A legacy token (no ver claim) is grandfathered while the user is at v1."""
        assert is_token_version_stale(None, 1) is False

    def test_missing_version_stale_after_bump(self):
        """A legacy token is revoked once the user's generation advances."""
        assert is_token_version_stale(None, 2) is True


def _encode(
    token_type: str, user_id: uuid.UUID, email: str, ver: int | None = None
) -> str:
    """Encode an access/refresh JWT, optionally with an explicit ``ver`` claim.

    ``ver=None`` omits the claim, simulating a token minted before the field
    existed.
    """
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": "diabetic",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
        "type": token_type,
        "jti": str(uuid.uuid4()),
    }
    if ver is not None:
        payload["ver"] = ver
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


async def _register(client, email: str, password: str = "TestPass1") -> uuid.UUID:
    """Register a diabetic user and return their id."""
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert reg.status_code == 201
    return uuid.UUID(reg.json()["id"])


async def _register_and_cookie(client, email: str, password: str = "TestPass1") -> str:
    """Register a user and return a valid session cookie."""
    await _register(client, email, password)
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    return login.cookies.get(settings.jwt_cookie_name)


async def _change_password(client, cookie: str) -> None:
    """Change the password via a session cookie (bumps token_version)."""
    changed = await client.post(
        "/api/auth/change-password",
        json={"current_password": "TestPass1", "new_password": "TestPass2"},
        cookies={settings.jwt_cookie_name: cookie},
    )
    assert changed.status_code == 200


class TestPasswordChangeRevokesOtherSessions:
    """Endpoint tests: a password change invalidates other tokens."""

    @pytest.mark.asyncio
    async def test_other_session_access_token_rejected_after_change(self, client):
        """An access token from a different session is rejected post-change."""
        email = f"cr04_access_{uuid.uuid4().hex[:8]}@test.com"
        user_id = await _register(client, email)

        # A second session's access token at the current generation (v1).
        other_token = _encode("access", user_id, email, ver=1)
        before = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {other_token}"}
        )
        assert before.status_code == 200

        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "TestPass1"}
        )
        await _change_password(client, login.cookies.get(settings.jwt_cookie_name))

        # Session 2's token -- never blacklisted, but an older generation -- is dead.
        after = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {other_token}"}
        )
        assert after.status_code == 401

    @pytest.mark.asyncio
    async def test_legacy_token_without_ver_grandfathered_then_revoked(self, client):
        """A token minted before this field existed works until the next change."""
        email = f"cr04_legacy_{uuid.uuid4().hex[:8]}@test.com"
        user_id = await _register(client, email)

        legacy_token = _encode("access", user_id, email, ver=None)
        before = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {legacy_token}"}
        )
        assert before.status_code == 200

        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "TestPass1"}
        )
        await _change_password(client, login.cookies.get(settings.jwt_cookie_name))

        after = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {legacy_token}"}
        )
        assert after.status_code == 401

    @pytest.mark.asyncio
    async def test_pre_change_refresh_token_rejected_after_change(self, client):
        """A refresh token from an older generation can no longer be exchanged."""
        email = f"cr04_refresh_{uuid.uuid4().hex[:8]}@test.com"
        user_id = await _register(client, email)

        # Two distinct v1 refresh tokens (one consumed by the sanity check).
        sanity_refresh = _encode("refresh", user_id, email, ver=1)
        pre_change_refresh = _encode("refresh", user_id, email, ver=1)
        sanity = await client.post(
            "/api/auth/mobile/refresh", json={"refresh_token": sanity_refresh}
        )
        assert sanity.status_code == 200

        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "TestPass1"}
        )
        await _change_password(client, login.cookies.get(settings.jwt_cookie_name))

        after = await client.post(
            "/api/auth/mobile/refresh", json={"refresh_token": pre_change_refresh}
        )
        assert after.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_minted_token_revoked_by_later_change(self, client):
        """A refresh cannot launder a token past a later change (race invariant).

        Tokens minted by mobile/refresh carry the generation read at mint time,
        so a change that lands afterward still revokes them -- the property that
        makes a refresh racing a concurrent change safe without row locking.
        """
        email = f"cr04_race_{uuid.uuid4().hex[:8]}@test.com"
        password = "TestPass1"
        await _register(client, email, password)
        mobile_login = await client.post(
            "/api/auth/mobile/login", json={"email": email, "password": password}
        )
        refresh_token = mobile_login.json()["refresh_token"]

        # A refresh mints a fresh access token at the current generation (v1).
        refreshed = await client.post(
            "/api/auth/mobile/refresh", json={"refresh_token": refresh_token}
        )
        assert refreshed.status_code == 200
        minted_access = refreshed.json()["access_token"]
        assert (
            await client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {minted_access}"}
            )
        ).status_code == 200

        login = await client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        await _change_password(client, login.cookies.get(settings.jwt_cookie_name))

        # The refresh-minted token is now an older generation -> rejected.
        after = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {minted_access}"}
        )
        assert after.status_code == 401

    @pytest.mark.asyncio
    async def test_token_issued_after_change_still_works(self, client):
        """A session started after the change is unaffected (no over-rejection)."""
        email = f"cr04_control_{uuid.uuid4().hex[:8]}@test.com"
        cookie = await _register_and_cookie(client, email)
        await _change_password(client, cookie)

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
    async def test_change_password_bumps_version_and_stamps_timestamp(self, client):
        """The change increments token_version and records password_changed_at."""
        email = f"cr04_bump_{uuid.uuid4().hex[:8]}@test.com"
        cookie = await _register_and_cookie(client, email)

        before = datetime.now(UTC) - timedelta(seconds=1)
        await _change_password(client, cookie)

        # Read back through a self-contained session (closed within this test's
        # event loop) to avoid the session-scoped-engine teardown race.
        async with get_session_maker()() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()
        assert user.token_version == 2  # 1 (default) -> 2 after one change
        assert user.password_changed_at is not None
        assert user.password_changed_at >= before
