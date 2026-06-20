"""Story 16.12: Tests for mobile token refresh endpoint."""

import uuid

from httpx import ASGITransport, AsyncClient

from src.core.security import create_refresh_token, decode_refresh_token
from src.main import app


def _email() -> str:
    return f"refresh_{uuid.uuid4().hex[:8]}@test.com"


async def _register_and_mobile_login(
    client: AsyncClient, email: str, password: str = "TestPass1"
) -> dict:
    """Register a user and return the full mobile login response."""
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    resp = await client.post(
        "/api/auth/mobile/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()


class TestMobileLoginRefreshToken:
    async def test_mobile_login_returns_refresh_token(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            body = await _register_and_mobile_login(c, email)

        assert "refresh_token" in body
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 3600  # 60 minutes

    async def test_refresh_token_is_valid_jwt(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            body = await _register_and_mobile_login(c, email)

        payload = decode_refresh_token(body["refresh_token"])
        assert payload is not None
        assert payload["type"] == "refresh"
        assert payload["email"] == email


class TestMobileRefreshEndpoint:
    async def test_refresh_returns_new_tokens(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            login_body = await _register_and_mobile_login(c, email)

            resp = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": login_body["refresh_token"]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["user"]["email"] == email
        assert body["expires_in"] == 3600

    async def test_new_access_token_works(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            login_body = await _register_and_mobile_login(c, email)

            refresh_resp = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": login_body["refresh_token"]},
            )
            new_token = refresh_resp.json()["access_token"]

            me_resp = await c.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {new_token}"},
            )
        assert me_resp.status_code == 200
        assert me_resp.json()["email"] == email

    async def test_invalid_refresh_token_returns_401(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": "invalid.token.here"},
            )
        assert resp.status_code == 401

    async def test_access_token_used_as_refresh_returns_401(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            login_body = await _register_and_mobile_login(c, email)

            resp = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": login_body["access_token"]},
            )
        assert resp.status_code == 401

    async def test_expired_refresh_token_returns_401(self):
        from datetime import timedelta

        # Create an already-expired refresh token
        fake_user_id = uuid.uuid4()
        expired_token = create_refresh_token(
            user_id=fake_user_id,
            email="expired@test.com",
            role="diabetic",
            expires_delta=timedelta(seconds=-1),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": expired_token},
            )
        assert resp.status_code == 401

    async def test_refresh_token_replay_returns_401(self):
        """Rotation: a refresh token that was already exchanged is rejected."""
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            login_body = await _register_and_mobile_login(c, email)
            refresh_token = login_body["refresh_token"]

            first = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": refresh_token},
            )
            replay = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": refresh_token},
            )
        assert first.status_code == 200
        assert replay.status_code == 401

    async def test_refresh_returns_503_when_consumption_unavailable(self, monkeypatch):
        """A Redis outage must map to a retryable 503, not a 401 -- mobile
        clients treat refresh-401 as revocation and delete their token."""
        from src.core.token_blacklist import TokenConsumeUnavailableError
        from src.routers import auth as auth_router

        async def _unavailable(jti: str, ttl_seconds: int) -> bool:
            raise TokenConsumeUnavailableError("redis down")

        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            login_body = await _register_and_mobile_login(c, email)
            monkeypatch.setattr(auth_router, "consume_token_once", _unavailable)
            resp = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": login_body["refresh_token"]},
            )
        assert resp.status_code == 503

    async def test_refresh_token_without_jti_returns_401(self):
        """A refresh token lacking a jti cannot be consumed once, so it must
        be rejected rather than skipping replay protection. Use a real,
        active user so the 401 can only come from the missing-jti gate, not
        from the later user-existence check."""
        from datetime import UTC, datetime, timedelta

        from jose import jwt

        from src.config import settings

        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            login_body = await _register_and_mobile_login(c, email)
            payload = {
                "sub": login_body["user"]["id"],
                "email": email,
                "role": "diabetic",
                "exp": datetime.now(UTC) + timedelta(days=1),
                "iat": datetime.now(UTC),
                "type": "refresh",
                # no "jti"
            }
            token = jwt.encode(
                payload, settings.secret_key, algorithm=settings.jwt_algorithm
            )
            resp = await c.post(
                "/api/auth/mobile/refresh",
                json={"refresh_token": token},
            )
        assert resp.status_code == 401


class TestRefreshTokenFunctions:
    def test_create_and_decode_refresh_token(self):
        user_id = uuid.uuid4()
        token = create_refresh_token(user_id, "test@example.com", "diabetic")
        payload = decode_refresh_token(token)
        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["email"] == "test@example.com"
        assert payload["role"] == "diabetic"
        assert payload["type"] == "refresh"

    def test_decode_access_token_as_refresh_returns_none(self):
        from src.core.security import create_access_token

        user_id = uuid.uuid4()
        access_token = create_access_token(user_id, "test@example.com", "diabetic")
        result = decode_refresh_token(access_token)
        assert result is None

    def test_decode_garbage_returns_none(self):
        result = decode_refresh_token("not.a.valid.jwt")
        assert result is None
