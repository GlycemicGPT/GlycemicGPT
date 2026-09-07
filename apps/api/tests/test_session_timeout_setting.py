"""Tests for the per-user web-session timeout setting API.

The web session lifetime is a per-user preference
(``users.session_timeout_minutes``, default 1440 = 24h) that is baked into the
JWT ``exp`` and the session cookie ``max-age`` when the browser session is
minted at login. These cover the read/update endpoint, bound enforcement,
owner-scoping, the default, availability to every authenticated role (unlike
the role-guarded meal-intelligence setting), and -- the behavioural contract
that matters -- that a changed value actually shortens the next session's token
and cookie.
"""

import uuid

import pytest
from pydantic import ValidationError

from src.config import Settings, settings
from src.core.security import decode_access_token


def unique_email(prefix: str = "session_to") -> str:
    """Generate an isolated account address for each test."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client, prefix: str = "session_to") -> dict:
    """Register + log in a fresh diabetic user; return the auth cookies."""
    email = unique_email(prefix)
    password = "SecurePass123"
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    return {settings.jwt_cookie_name: login.cookies.get(settings.jwt_cookie_name)}


async def test_get_session_timeout_defaults_to_24h(client):
    """New accounts retain the historical 24-hour session and default presets."""
    cookies = await register_and_login(client)

    response = await client.get("/api/settings/session-timeout", cookies=cookies)

    assert response.status_code == 200
    body = response.json()
    assert body["minutes"] == 1440  # 24h, matching the historical default
    assert body["min_minutes"] == settings.session_timeout_min_minutes
    assert body["max_minutes"] == settings.session_timeout_max_minutes
    assert body["presets"] == [15, 60, 360, 720, 1440, 10080]


async def test_patch_session_timeout_round_trips(client):
    """A saved session duration is returned by subsequent preference reads."""
    cookies = await register_and_login(client)

    update = await client.patch(
        "/api/settings/session-timeout", json={"minutes": 360}, cookies=cookies
    )
    settings_get = await client.get("/api/settings/session-timeout", cookies=cookies)

    assert update.status_code == 200
    assert update.json()["minutes"] == 360
    assert settings_get.json()["minutes"] == 360


async def test_patch_below_minimum_is_rejected(client):
    """Reject durations shorter than the configured deployment minimum."""
    cookies = await register_and_login(client)

    response = await client.patch(
        "/api/settings/session-timeout",
        json={"minutes": settings.session_timeout_min_minutes - 1},
        cookies=cookies,
    )

    assert response.status_code == 422


async def test_patch_above_maximum_is_rejected(client):
    """Reject durations longer than the configured deployment maximum."""
    cookies = await register_and_login(client)

    response = await client.patch(
        "/api/settings/session-timeout",
        json={"minutes": settings.session_timeout_max_minutes + 1},
        cookies=cookies,
    )

    assert response.status_code == 422


async def test_patch_requires_minutes_field(client):
    """Reject incomplete updates instead of silently retaining a preference."""
    cookies = await register_and_login(client)

    response = await client.patch(
        "/api/settings/session-timeout", json={}, cookies=cookies
    )

    assert response.status_code == 422


async def test_session_timeout_is_owner_scoped(client):
    """One user's change never affects another's (no user_id parameter)."""
    cookies_a = await register_and_login(client)
    cookies_b = await register_and_login(client)

    await client.patch(
        "/api/settings/session-timeout", json={"minutes": 15}, cookies=cookies_a
    )

    a_get = await client.get("/api/settings/session-timeout", cookies=cookies_a)
    b_get = await client.get("/api/settings/session-timeout", cookies=cookies_b)

    assert a_get.json()["minutes"] == 15
    assert b_get.json()["minutes"] == 1440  # B is unaffected


async def test_session_timeout_requires_authentication(client):
    """Anonymous clients cannot read or change session preferences."""
    get_response = await client.get("/api/settings/session-timeout")
    patch_response = await client.patch(
        "/api/settings/session-timeout", json={"minutes": 60}
    )

    assert get_response.status_code == 401
    assert patch_response.status_code == 401


async def test_session_timeout_allowed_for_caregiver(client, db_session):
    """Unlike meal-intelligence, session length is available to every role.

    A caregiver logs into the web UI too, so they manage their own session
    length; the endpoint gates on authentication only, not the diabetic/admin
    role guard.
    """
    from sqlalchemy import update

    from src.models.user import User, UserRole

    email = unique_email("caregiver")
    password = "SecurePass123"
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    cookies = {settings.jwt_cookie_name: login.cookies.get(settings.jwt_cookie_name)}

    await db_session.execute(
        update(User).where(User.email == email).values(role=UserRole.CAREGIVER)
    )
    await db_session.commit()

    get_response = await client.get("/api/settings/session-timeout", cookies=cookies)
    patch_response = await client.patch(
        "/api/settings/session-timeout", json={"minutes": 60}, cookies=cookies
    )

    assert get_response.status_code == 200
    assert patch_response.status_code == 200


async def test_changed_timeout_shortens_next_login_token_and_cookie(client):
    """The behavioural contract: a smaller value shortens the *next* session.

    This is the original symptom the feature targets -- the JWT ``exp`` and the
    session cookie ``max-age`` both reflect the user's chosen lifetime, not the
    fixed 24h default, once they log in again.
    """
    email = unique_email("relogin")
    password = "SecurePass123"
    await client.post("/api/auth/register", json={"email": email, "password": password})
    first_login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    cookies = {
        settings.jwt_cookie_name: first_login.cookies.get(settings.jwt_cookie_name)
    }

    # Choose a 15-minute session, then log in again to mint a fresh token.
    await client.patch(
        "/api/settings/session-timeout", json={"minutes": 15}, cookies=cookies
    )
    second_login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )

    # Cookie max-age is computed directly from the preference -> exactly 900s.
    set_cookie = "\n".join(second_login.headers.get_list("set-cookie")).lower()
    assert f"{settings.jwt_cookie_name.lower()}=" in set_cookie
    assert "max-age=900" in set_cookie

    # JWT exp is ~15 minutes out (two now() calls straddle the delta, so allow a
    # small truncation tolerance rather than asserting an exact second).
    token = second_login.cookies.get(settings.jwt_cookie_name)
    payload = decode_access_token(token)
    assert payload is not None
    assert 898 <= (payload["exp"] - payload["iat"]) <= 900


@pytest.mark.parametrize(
    "low,high", [(15, 10080), (60, 1440), (1440, 1440), (1440, 10080)]
)
def test_config_accepts_ordered_session_timeout_bounds(low, high):
    """Deployment bounds allow both ranges and a single permitted duration."""
    config = Settings(
        _env_file=None,
        session_timeout_min_minutes=low,
        session_timeout_max_minutes=high,
    )
    assert config.session_timeout_min_minutes == low
    assert config.session_timeout_max_minutes == high


def test_config_rejects_inverted_session_timeout_bounds():
    """Fail at startup instead of rejecting every user's timeout update."""
    with pytest.raises(ValidationError, match="must not exceed"):
        Settings(
            _env_file=None,
            session_timeout_min_minutes=61,
            session_timeout_max_minutes=60,
        )


@pytest.mark.parametrize(
    "field", ["session_timeout_min_minutes", "session_timeout_max_minutes"]
)
@pytest.mark.parametrize("value", [-1, 0, 14, 10081])
def test_config_rejects_session_timeout_outside_absolute_bounds(field, value):
    """Neither deployment bound may escape the absolute 15-minute to 7-day range."""
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, **{field: value})
    assert exc.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("low,high", [(15, 60), (60, 60), (1441, 10080)])
def test_config_rejects_bounds_excluding_new_account_default(low, high):
    """Reject max=60 at startup before accounts can receive an invalid default."""
    with pytest.raises(ValidationError, match="1440-minute new-account default"):
        Settings(
            _env_file=None,
            session_timeout_min_minutes=low,
            session_timeout_max_minutes=high,
        )


async def test_new_account_default_with_narrowed_deployment_bounds(client, monkeypatch):
    """Registration and login retain a valid default at the narrowest allowed range."""
    monkeypatch.setattr(settings, "session_timeout_min_minutes", 1440)
    monkeypatch.setattr(settings, "session_timeout_max_minutes", 1440)
    cookies = await register_and_login(client)
    response = await client.get("/api/settings/session-timeout", cookies=cookies)
    assert response.status_code == 200
    body = response.json()
    assert body["minutes"] == 1440
    assert body["min_minutes"] == body["max_minutes"] == 1440
    payload = decode_access_token(cookies[settings.jwt_cookie_name])
    assert payload is not None
    assert 86398 <= payload["exp"] - payload["iat"] <= 86400
