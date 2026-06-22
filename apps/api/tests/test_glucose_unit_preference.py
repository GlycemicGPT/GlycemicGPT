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
    # A fresh account's unit is a smart default (registration locale), so its
    # provenance is "seed"; an explicit PATCH flips it to "user".
    assert default_response.json() == {
        "glucose_unit": "mgdl",
        "glucose_unit_source": "seed",
    }
    assert update_response.status_code == 200
    assert update_response.json() == {
        "glucose_unit": "mmol",
        "glucose_unit_source": "user",
    }
    assert me_response.status_code == 200
    assert me_response.json()["glucose_unit"] == "mmol"
    assert me_response.json()["glucose_unit_source"] == "user"


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


async def _register(client, *, accept_language: str | None = None) -> dict:
    """Register a fresh account (optionally with an Accept-Language header) and
    return the auth cookies."""
    email = unique_email("seed")
    password = "SecurePass123"
    headers = {"Accept-Language": accept_language} if accept_language else {}
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
        headers=headers,
    )
    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    return {
        settings.jwt_cookie_name: login_response.cookies.get(settings.jwt_cookie_name)
    }


async def test_registration_seeds_mmol_for_mmol_region_locale(client):
    cookies = await _register(client, accept_language="en-GB,en;q=0.9")

    response = await client.get("/api/settings/glucose-unit", cookies=cookies)

    assert response.status_code == 200
    assert response.json() == {"glucose_unit": "mmol", "glucose_unit_source": "seed"}


async def test_registration_seeds_mgdl_for_us_locale(client):
    cookies = await _register(client, accept_language="en-US,en;q=0.9")

    response = await client.get("/api/settings/glucose-unit", cookies=cookies)

    assert response.status_code == 200
    # US is mg/dL: seeded value matches today's default, provenance still "seed".
    assert response.json() == {"glucose_unit": "mgdl", "glucose_unit_source": "seed"}


async def test_auth_me_exposes_seed_provenance_for_a_seeded_account(client):
    """The web seed notice gates on `glucose_unit_source` read from /api/auth/me,
    so the UserResponse serializer must carry the 'seed' value -- a separate path
    from the settings GET asserted elsewhere."""
    cookies = await _register(client, accept_language="en-GB")

    response = await client.get("/api/auth/me", cookies=cookies)

    assert response.status_code == 200
    body = response.json()
    assert body["glucose_unit"] == "mmol"
    assert body["glucose_unit_source"] == "seed"


async def test_registration_seeds_mgdl_without_accept_language(client):
    cookies = await _register(client, accept_language=None)

    response = await client.get("/api/settings/glucose-unit", cookies=cookies)

    assert response.status_code == 200
    assert response.json()["glucose_unit"] == "mgdl"


async def test_registration_seed_leaves_canonical_settings_in_mgdl(client):
    """The mmol display seed must not convert canonical mg/dL settings."""
    cookies = await _register(client, accept_language="en-GB")

    unit_response = await client.get("/api/settings/glucose-unit", cookies=cookies)
    range_response = await client.get(
        "/api/settings/target-glucose-range", cookies=cookies
    )

    assert unit_response.json()["glucose_unit"] == "mmol"
    # Default target range stays canonical mg/dL (70/180), NOT mmol-converted.
    body = range_response.json()
    assert body["low_target"] == 70.0
    assert body["high_target"] == 180.0


async def test_acknowledge_flips_seed_to_user_without_changing_unit(client):
    cookies = await _register(client, accept_language="en-GB")

    before = await client.get("/api/settings/glucose-unit", cookies=cookies)
    ack = await client.post("/api/settings/glucose-unit/acknowledge", cookies=cookies)
    after = await client.get("/api/settings/glucose-unit", cookies=cookies)

    assert before.json() == {"glucose_unit": "mmol", "glucose_unit_source": "seed"}
    assert ack.status_code == 200
    # Dismiss = "treat the seeded unit as my choice": unit unchanged, source=user.
    assert ack.json() == {"glucose_unit": "mmol", "glucose_unit_source": "user"}
    assert after.json() == {"glucose_unit": "mmol", "glucose_unit_source": "user"}


async def test_acknowledge_is_idempotent(client):
    cookies = await _register(client, accept_language="en-GB")

    first = await client.post("/api/settings/glucose-unit/acknowledge", cookies=cookies)
    second = await client.post(
        "/api/settings/glucose-unit/acknowledge", cookies=cookies
    )

    assert first.json() == {"glucose_unit": "mmol", "glucose_unit_source": "user"}
    assert second.json() == {"glucose_unit": "mmol", "glucose_unit_source": "user"}


async def test_acknowledge_requires_authentication(client):
    response = await client.post("/api/settings/glucose-unit/acknowledge")
    assert response.status_code == 401


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
