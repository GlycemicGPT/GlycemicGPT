"""Tests for glucose unit preference API behavior."""

import uuid

from src.config import settings


def unique_email(prefix: str = "glucose_unit") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client) -> str:
    email = unique_email()
    password = "SecurePass123"

    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    return login_response.cookies.get(settings.jwt_cookie_name)


async def test_auth_me_returns_default_glucose_unit(client):
    cookie = await register_and_login(client)

    response = await client.get(
        "/api/auth/me",
        cookies={settings.jwt_cookie_name: cookie},
    )

    assert response.status_code == 200
    assert response.json()["glucose_unit"] == "mgdl"


async def test_glucose_unit_preference_round_trips_to_auth_me(client):
    cookie = await register_and_login(client)
    cookies = {settings.jwt_cookie_name: cookie}

    default_response = await client.get("/api/settings/glucose-unit", cookies=cookies)
    update_response = await client.patch(
        "/api/settings/glucose-unit",
        json={"glucose_unit": "mmol"},
        cookies=cookies,
    )
    me_response = await client.get("/api/auth/me", cookies=cookies)

    assert default_response.status_code == 200
    assert default_response.json() == {"glucose_unit": "mgdl"}
    assert update_response.status_code == 200
    assert update_response.json() == {"glucose_unit": "mmol"}
    assert me_response.status_code == 200
    assert me_response.json()["glucose_unit"] == "mmol"


async def test_glucose_unit_preference_rejects_unknown_value(client):
    cookie = await register_and_login(client)

    response = await client.patch(
        "/api/settings/glucose-unit",
        json={"glucose_unit": "mg/dl"},
        cookies={settings.jwt_cookie_name: cookie},
    )

    assert response.status_code == 422


async def test_settings_export_includes_glucose_unit_preference(client):
    cookie = await register_and_login(client)
    cookies = {settings.jwt_cookie_name: cookie}

    await client.patch(
        "/api/settings/glucose-unit",
        json={"glucose_unit": "mmol"},
        cookies=cookies,
    )
    response = await client.post(
        "/api/settings/export",
        json={"export_type": "settings_only"},
        cookies=cookies,
    )

    assert response.status_code == 200
    export = response.json()["export_data"]
    assert export["settings"]["glucose_unit"] == "mmol"


async def test_glucose_unit_requires_authentication(client):
    get_response = await client.get("/api/settings/glucose-unit")
    patch_response = await client.patch(
        "/api/settings/glucose-unit",
        json={"glucose_unit": "mmol"},
    )

    assert get_response.status_code == 401
    assert patch_response.status_code == 401


async def test_glucose_unit_forbidden_for_caregiver(client, db_session):
    from sqlalchemy import update

    from src.models.user import User, UserRole

    email = unique_email("caregiver")
    password = "SecurePass123"
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    cookie = login_response.cookies.get(settings.jwt_cookie_name)

    # Registration defaults to DIABETIC; demote to CAREGIVER, who must not read
    # or write settings (mirrors every sibling settings endpoint's role guard).
    await db_session.execute(
        update(User).where(User.email == email).values(role=UserRole.CAREGIVER)
    )
    await db_session.commit()

    cookies = {settings.jwt_cookie_name: cookie}
    get_response = await client.get("/api/settings/glucose-unit", cookies=cookies)
    patch_response = await client.patch(
        "/api/settings/glucose-unit",
        json={"glucose_unit": "mmol"},
        cookies=cookies,
    )

    assert get_response.status_code == 403
    assert patch_response.status_code == 403
