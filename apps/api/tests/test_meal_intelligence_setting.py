"""Tests for the per-user meal-intelligence setting API.

The meal-intelligence feature is gated by a per-user preference
(``users.meal_intelligence_enabled``) that defaults ON, replacing the former
global env flag. These cover the read/update endpoint, the auth/me echo, the
per-user gate on the meal surfaces, owner-scoping (no cross-user access), the
default-on behavior, and the role guard.
"""

import uuid

from src.config import settings


def unique_email(prefix: str = "meal_intel") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client) -> dict:
    """Register + log in a fresh diabetic user; return the auth cookies."""
    email = unique_email()
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


async def test_auth_me_returns_default_meal_intelligence_enabled(client):
    cookies = await register_and_login(client)

    response = await client.get("/api/auth/me", cookies=cookies)

    assert response.status_code == 200
    # Default ON so the shipped feature is discoverable for a fresh account.
    assert response.json()["meal_intelligence_enabled"] is True


async def test_get_meal_intelligence_defaults_on(client):
    cookies = await register_and_login(client)

    response = await client.get("/api/settings/meal-intelligence", cookies=cookies)

    assert response.status_code == 200
    assert response.json() == {"enabled": True}


async def test_meal_intelligence_round_trips_to_auth_me(client):
    cookies = await register_and_login(client)

    update = await client.patch(
        "/api/settings/meal-intelligence",
        json={"enabled": False},
        cookies=cookies,
    )
    settings_get = await client.get("/api/settings/meal-intelligence", cookies=cookies)
    me = await client.get("/api/auth/me", cookies=cookies)

    assert update.status_code == 200
    assert update.json() == {"enabled": False}
    assert settings_get.json() == {"enabled": False}
    assert me.json()["meal_intelligence_enabled"] is False


async def test_meal_intelligence_toggles_back_on(client):
    cookies = await register_and_login(client)

    await client.patch(
        "/api/settings/meal-intelligence", json={"enabled": False}, cookies=cookies
    )
    re_enable = await client.patch(
        "/api/settings/meal-intelligence", json={"enabled": True}, cookies=cookies
    )

    assert re_enable.status_code == 200
    assert re_enable.json() == {"enabled": True}


async def test_disabling_hides_meal_endpoints(client):
    """The per-user gate: turning the setting off makes the meal surface 404."""
    cookies = await register_and_login(client)

    # On by default -> the listing is reachable (empty, but 200).
    assert (await client.get("/api/food-records", cookies=cookies)).status_code == 200

    await client.patch(
        "/api/settings/meal-intelligence", json={"enabled": False}, cookies=cookies
    )

    assert (await client.get("/api/food-records", cookies=cookies)).status_code == 404
    assert (await client.get("/api/common-foods", cookies=cookies)).status_code == 404


async def test_meal_intelligence_is_owner_scoped(client):
    """One user's setting never affects another's.

    The endpoint resolves the user from the session and accepts no user_id
    parameter, so there is no way to read or write another account's setting
    (IDOR is structurally impossible); disabling for A leaves B untouched.
    """
    cookies_a = await register_and_login(client)
    cookies_b = await register_and_login(client)

    await client.patch(
        "/api/settings/meal-intelligence", json={"enabled": False}, cookies=cookies_a
    )

    a_get = await client.get("/api/settings/meal-intelligence", cookies=cookies_a)
    b_get = await client.get("/api/settings/meal-intelligence", cookies=cookies_b)

    assert a_get.json() == {"enabled": False}
    assert b_get.json() == {"enabled": True}  # B is unaffected


async def test_patch_requires_enabled_field(client):
    cookies = await register_and_login(client)

    response = await client.patch(
        "/api/settings/meal-intelligence", json={}, cookies=cookies
    )

    assert response.status_code == 422


async def test_meal_intelligence_requires_authentication(client):
    get_response = await client.get("/api/settings/meal-intelligence")
    patch_response = await client.patch(
        "/api/settings/meal-intelligence", json={"enabled": False}
    )

    assert get_response.status_code == 401
    assert patch_response.status_code == 401


async def test_meal_intelligence_forbidden_for_caregiver(client, db_session):
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

    # Registration defaults to DIABETIC; demote to CAREGIVER, who must not read
    # or write settings (mirrors every sibling settings endpoint's role guard).
    await db_session.execute(
        update(User).where(User.email == email).values(role=UserRole.CAREGIVER)
    )
    await db_session.commit()

    get_response = await client.get("/api/settings/meal-intelligence", cookies=cookies)
    patch_response = await client.patch(
        "/api/settings/meal-intelligence", json={"enabled": False}, cookies=cookies
    )

    assert get_response.status_code == 403
    assert patch_response.status_code == 403
