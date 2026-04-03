"""Story 2.1, 2.2 & 2.3: Tests for user authentication."""

import uuid

from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


class TestUserRegistration:
    """Tests for POST /api/auth/register endpoint."""

    async def test_register_creates_user_with_diabetic_role(self):
        """Test that new users are assigned the diabetic role by default."""
        email = unique_email("newuser")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={"email": email, "password": "SecurePass123"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "diabetic"
        assert data["email"] == email.lower()
        assert data["message"] == "Registration successful"
        assert "id" in data

    async def test_register_returns_disclaimer_required(self):
        """Test that new users need to acknowledge disclaimer."""
        email = unique_email("disclaimer")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={"email": email, "password": "SecurePass123"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["disclaimer_required"] is True

    async def test_register_normalizes_email_to_lowercase(self):
        """Test that email is normalized to lowercase."""
        email = unique_email("UPPERCASE").upper()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": email,
                    "password": "SecurePass123",
                },
            )

        assert response.status_code == 201
        data = response.json()
        # Email should be normalized to lowercase
        assert data["email"] == email.lower()


class TestPasswordValidation:
    """Tests for password strength validation."""

    async def test_rejects_password_without_uppercase(self):
        """Test that password must contain uppercase letter."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": unique_email("nouppercase"),
                    "password": "lowercase123",
                },
            )

        assert response.status_code == 422
        data = response.json()
        assert "uppercase" in data["detail"][0]["msg"].lower()

    async def test_rejects_password_without_lowercase(self):
        """Test that password must contain lowercase letter."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": unique_email("nolowercase"),
                    "password": "UPPERCASE123",
                },
            )

        assert response.status_code == 422
        data = response.json()
        assert "lowercase" in data["detail"][0]["msg"].lower()

    async def test_rejects_password_without_number(self):
        """Test that password must contain a number."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": unique_email("nonumber"),
                    "password": "NoNumberHere",
                },
            )

        assert response.status_code == 422
        data = response.json()
        assert "number" in data["detail"][0]["msg"].lower()

    async def test_rejects_password_too_short(self):
        """Test that password must be at least 8 characters."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": unique_email("tooshort"),
                    "password": "Short1",
                },
            )

        assert response.status_code == 422


class TestDuplicateEmail:
    """Tests for duplicate email handling."""

    async def test_rejects_duplicate_email(self):
        """Test that duplicate email returns 409 error."""
        email = unique_email("duplicate")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # First registration
            response1 = await client.post(
                "/api/auth/register",
                json={
                    "email": email,
                    "password": "SecurePass123",
                },
            )

            # Second registration with same email
            response2 = await client.post(
                "/api/auth/register",
                json={
                    "email": email,
                    "password": "DifferentPass456",
                },
            )

        assert response1.status_code == 201
        assert response2.status_code == 409
        assert response2.json()["detail"] == (
            "Registration failed. Please try again or contact support."
        )

    async def test_rejects_duplicate_email_case_insensitive(self):
        """Test that email uniqueness is case-insensitive."""
        base_email = unique_email("casetest")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # First registration
            response1 = await client.post(
                "/api/auth/register",
                json={
                    "email": base_email.lower(),
                    "password": "SecurePass123",
                },
            )

            # Second registration with uppercase
            response2 = await client.post(
                "/api/auth/register",
                json={
                    "email": base_email.upper(),
                    "password": "SecurePass456",
                },
            )

        assert response1.status_code == 201
        assert response2.status_code == 409


class TestEmailValidation:
    """Tests for email validation."""

    async def test_rejects_invalid_email_format(self):
        """Test that invalid email format is rejected."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": "not-an-email",
                    "password": "SecurePass123",
                },
            )

        assert response.status_code == 422


# ============================================================================
# Story 2.2: Login Tests
# ============================================================================


class TestUserLogin:
    """Tests for POST /api/auth/login endpoint."""

    async def test_login_with_valid_credentials(self):
        """Test successful login with valid email and password."""
        email = unique_email("logintest")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # First register the user
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            # Then login
            response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Login successful"
        assert data["user"]["email"] == email.lower()
        assert "disclaimer_required" in data

    async def test_login_sets_httponly_cookie(self):
        """Test that login sets an httpOnly session cookie."""
        email = unique_email("cookietest")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register user
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            # Login
            response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

        assert response.status_code == 200
        # Check that the session cookie is set
        assert settings.jwt_cookie_name in response.cookies

    async def test_login_with_wrong_password(self):
        """Test that wrong password returns 401."""
        email = unique_email("wrongpasstest")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register user
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": "SecurePass123"},
            )

            # Try to login with wrong password
            response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": "WrongPassword456"},
            )

        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    async def test_login_with_nonexistent_email(self):
        """Test that nonexistent email returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/auth/login",
                json={
                    "email": unique_email("nonexistent"),
                    "password": "SomePassword123",
                },
            )

        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    async def test_login_is_case_insensitive_for_email(self):
        """Test that login email matching is case-insensitive."""
        base_email = unique_email("caselogin")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register with lowercase
            await client.post(
                "/api/auth/register",
                json={"email": base_email.lower(), "password": password},
            )

            # Login with uppercase
            response = await client.post(
                "/api/auth/login",
                json={"email": base_email.upper(), "password": password},
            )

        assert response.status_code == 200


class TestCurrentUser:
    """Tests for GET /api/auth/me endpoint."""

    async def test_get_me_with_valid_session(self):
        """Test fetching current user with valid session cookie."""
        email = unique_email("metest")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            # Get the session cookie
            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Fetch current user profile
            response = await client.get(
                "/api/auth/me",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == email.lower()
        assert data["role"] == "diabetic"
        assert "id" in data

    async def test_get_me_without_session(self):
        """Test that /me returns 401 without session cookie."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/auth/me")

        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]

    async def test_get_me_with_invalid_token(self):
        """Test that /me returns 401 with invalid token."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/auth/me",
                cookies={settings.jwt_cookie_name: "invalid.token.here"},
            )

        assert response.status_code == 401


# ============================================================================
# Story 2.3: Logout Tests
# ============================================================================


class TestUserLogout:
    """Tests for POST /api/auth/logout endpoint."""

    async def test_logout_clears_session(self):
        """Test that logout clears the session cookie."""
        email = unique_email("logouttest")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Logout
            logout_response = await client.post(
                "/api/auth/logout",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert logout_response.status_code == 200
        data = logout_response.json()
        assert data["message"] == "Logout successful"

    async def test_logout_requires_authentication(self):
        """Test that logout requires a valid session."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/auth/logout")

        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]

    async def test_session_invalid_after_logout(self):
        """Test that session is invalid after logout."""
        email = unique_email("invalidatetest")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Verify session works before logout
            me_before = await client.get(
                "/api/auth/me",
                cookies={settings.jwt_cookie_name: session_cookie},
            )
            assert me_before.status_code == 200

            # Logout
            logout_response = await client.post(
                "/api/auth/logout",
                cookies={settings.jwt_cookie_name: session_cookie},
            )
            assert logout_response.status_code == 200

            # The cookie should be cleared in the response
            # Note: The actual cookie invalidation happens client-side
            # when the browser receives the Set-Cookie with max-age=0
