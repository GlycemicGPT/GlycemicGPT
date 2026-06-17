"""Tests for disclaimer acknowledgment API.

Story 1.3: First-Run Safety Disclaimer
- AC1: Given I am a new user who has never acknowledged the disclaimer,
       When I access the web application,
       Then I see a modal with safety disclaimers
- AC2: I must check two acknowledgment checkboxes
- AC3: I must click "I Understand & Accept" to proceed
- AC4: My acknowledgment is stored in the database with timestamp
"""

import uuid
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client():
    """Create async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


class TestDisclaimerStatus:
    """Tests for GET /api/disclaimer/status endpoint."""

    @pytest.mark.asyncio
    async def test_returns_not_acknowledged_for_new_session(self, client):
        """
        Status returns acknowledged=False for a session that has not
        acknowledged the disclaimer.
        """
        session_id = str(uuid.uuid4())

        with patch(
            "src.routers.disclaimer.get_session_maker"
        ) as mock_get_session_maker:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            # get_session_maker() returns a factory, factory() returns session context
            mock_get_session_maker.return_value.return_value = mock_session

            response = await client.get(
                f"/api/disclaimer/status?session_id={session_id}"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["acknowledged"] is False
            assert data["acknowledged_at"] is None
            assert data["disclaimer_version"] == "1.2"

    @pytest.mark.asyncio
    async def test_returns_acknowledged_for_existing_session(self, client):
        """
        Status returns acknowledged=True for a session that has
        previously acknowledged the current disclaimer version.
        """
        from datetime import datetime

        from src.routers.disclaimer import DISCLAIMER_VERSION

        session_id = str(uuid.uuid4())
        acknowledged_at = datetime.now(UTC)

        with patch(
            "src.routers.disclaimer.get_session_maker"
        ) as mock_get_session_maker:
            mock_acknowledgment = MagicMock()
            mock_acknowledgment.acknowledged_at = acknowledged_at
            mock_acknowledgment.disclaimer_version = DISCLAIMER_VERSION

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_acknowledgment
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_get_session_maker.return_value.return_value = mock_session

            response = await client.get(
                f"/api/disclaimer/status?session_id={session_id}"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["acknowledged"] is True
            assert data["acknowledged_at"] is not None
            assert data["disclaimer_version"] == DISCLAIMER_VERSION

    @pytest.mark.asyncio
    async def test_returns_not_acknowledged_when_stored_version_is_outdated(
        self, client
    ):
        """
        Status returns acknowledged=False when the stored acknowledgment is
        for a previous disclaimer version. This forces users who acknowledged
        an older disclaimer to re-acknowledge when substantive new wording
        (e.g., AI data-handling in 1.1) is added.
        """
        from datetime import datetime

        session_id = str(uuid.uuid4())
        acknowledged_at = datetime.now(UTC)

        with patch(
            "src.routers.disclaimer.get_session_maker"
        ) as mock_get_session_maker:
            mock_acknowledgment = MagicMock()
            mock_acknowledgment.acknowledged_at = acknowledged_at
            # Stored version is older than current DISCLAIMER_VERSION
            mock_acknowledgment.disclaimer_version = "1.0"

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_acknowledgment
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_get_session_maker.return_value.return_value = mock_session

            response = await client.get(
                f"/api/disclaimer/status?session_id={session_id}"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["acknowledged"] is False
            assert data["acknowledged_at"] is None
            assert data["disclaimer_version"] == "1.2"


class TestDisclaimerAcknowledge:
    """Tests for POST /api/disclaimer/acknowledge endpoint."""

    @pytest.mark.asyncio
    async def test_requires_all_checkboxes_checked(self, client):
        """
        User must check all acknowledgment checkboxes.
        Returns 400 if not all checked.
        """
        session_id = str(uuid.uuid4())

        # All three required, one unchecked -> 400
        response = await client.post(
            "/api/disclaimer/acknowledge",
            json={
                "session_id": session_id,
                "checkbox_experimental": True,
                "checkbox_not_medical_advice": False,
                "checkbox_ai_data_flow": True,
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "all" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_requires_ai_data_flow_checkbox_checked(self, client):
        """
        Specifically: the AI data-handling checkbox must be checked.
        Returns 400 if it is unchecked even when the other two are.
        """
        session_id = str(uuid.uuid4())

        response = await client.post(
            "/api/disclaimer/acknowledge",
            json={
                "session_id": session_id,
                "checkbox_experimental": True,
                "checkbox_not_medical_advice": True,
                "checkbox_ai_data_flow": False,
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_missing_ai_data_flow_field(self, client):
        """
        Request schema requires checkbox_ai_data_flow. Missing field -> 422.
        Guards against clients silently downgrading to the v1.0 payload.
        """
        session_id = str(uuid.uuid4())

        response = await client.post(
            "/api/disclaimer/acknowledge",
            json={
                "session_id": session_id,
                "checkbox_experimental": True,
                "checkbox_not_medical_advice": True,
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_stores_acknowledgment_with_timestamp(self, client):
        """
        AC4: Acknowledgment is stored in the database with timestamp.
        """
        from datetime import datetime

        session_id = str(uuid.uuid4())
        acknowledged_at = datetime.now(UTC)

        with patch(
            "src.routers.disclaimer.get_session_maker"
        ) as mock_get_session_maker:
            # First check returns None (not acknowledged)
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=mock_result)

            # Create mock acknowledgment after save
            mock_acknowledgment = MagicMock()
            mock_acknowledgment.acknowledged_at = acknowledged_at

            async def mock_refresh(obj):
                obj.acknowledged_at = acknowledged_at

            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()
            mock_session.refresh = mock_refresh
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_get_session_maker.return_value.return_value = mock_session

            response = await client.post(
                "/api/disclaimer/acknowledge",
                json={
                    "session_id": session_id,
                    "checkbox_experimental": True,
                    "checkbox_not_medical_advice": True,
                    "checkbox_ai_data_flow": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["acknowledged_at"] is not None
            assert "successfully" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_advances_version_on_reacknowledge(self, client):
        """Regression (Story 50.S): re-acknowledging a session whose stored
        version is outdated advances the stored version + persists it, so /status
        stops re-prompting. Without this, session_id never rotates and the user
        is trapped in an inescapable disclaimer loop after a version bump."""
        from datetime import datetime

        from src.routers.disclaimer import DISCLAIMER_VERSION

        session_id = str(uuid.uuid4())

        with patch(
            "src.routers.disclaimer.get_session_maker"
        ) as mock_get_session_maker:
            existing = MagicMock()
            existing.disclaimer_version = "1.1"  # outdated
            existing.acknowledged_at = datetime.now(UTC)

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = existing
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_session.refresh = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_get_session_maker.return_value.return_value = mock_session

            response = await client.post(
                "/api/disclaimer/acknowledge",
                json={
                    "session_id": session_id,
                    "checkbox_experimental": True,
                    "checkbox_not_medical_advice": True,
                    "checkbox_ai_data_flow": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "successfully" in data["message"].lower()
            # The stored row was advanced to the current version and committed.
            assert existing.disclaimer_version == DISCLAIMER_VERSION
            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_idempotent_when_session_version_is_current(self, client):
        """A session already at the current version is a no-op: no version
        rewrite, no commit, and the 'previously acknowledged' message."""
        from datetime import datetime

        from src.routers.disclaimer import DISCLAIMER_VERSION

        session_id = str(uuid.uuid4())

        with patch(
            "src.routers.disclaimer.get_session_maker"
        ) as mock_get_session_maker:
            existing = MagicMock()
            existing.disclaimer_version = DISCLAIMER_VERSION  # already current
            existing.acknowledged_at = datetime.now(UTC)

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = existing
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_get_session_maker.return_value.return_value = mock_session

            response = await client.post(
                "/api/disclaimer/acknowledge",
                json={
                    "session_id": session_id,
                    "checkbox_experimental": True,
                    "checkbox_not_medical_advice": True,
                    "checkbox_ai_data_flow": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "previously" in data["message"].lower()
            mock_session.commit.assert_not_awaited()


class TestDisclaimerAcknowledgeAuth:
    """Tests for POST /api/disclaimer/acknowledge-auth endpoint.

    Story 15.5: Authenticated disclaimer acknowledgment sets
    user.disclaimer_acknowledged = True.
    """

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client):
        """Returns 401 when no session cookie is provided."""
        response = await client.post("/api/disclaimer/acknowledge-auth")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_sets_disclaimer_acknowledged_on_user(self, client):
        """Sets disclaimer_acknowledged=True + the version, commits, succeeds."""
        from src.core.auth import get_current_user
        from src.database import get_db
        from src.routers.disclaimer import DISCLAIMER_VERSION

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.email = "test@example.com"
        mock_user.disclaimer_acknowledged = False
        mock_user.disclaimer_version = None
        mock_user.is_active = True

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            response = await client.post("/api/disclaimer/acknowledge-auth")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "successfully" in data["message"].lower()
            assert mock_user.disclaimer_acknowledged is True
            # The acknowledged version is recorded so a future bump re-prompts.
            assert mock_user.disclaimer_version == DISCLAIMER_VERSION
            mock_db.commit.assert_awaited_once()
            mock_db.refresh.assert_awaited_once_with(mock_user)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_idempotent_when_current_version_acknowledged(self, client):
        """Returns early without DB write if the CURRENT version is acked."""
        from src.core.auth import get_current_user
        from src.database import get_db
        from src.routers.disclaimer import DISCLAIMER_VERSION

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.email = "test@example.com"
        mock_user.disclaimer_acknowledged = True
        mock_user.disclaimer_version = DISCLAIMER_VERSION
        mock_user.is_active = True

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            response = await client.post("/api/disclaimer/acknowledge-auth")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "previously" in data["message"].lower()
            mock_db.commit.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_reacknowledges_when_stored_version_is_outdated(self, client):
        """Regression (Story 50.S): an authenticated user whose stored version is
        outdated re-acknowledges and the new version is recorded -- the 1.x->1.2
        bump must not be a silent no-op for logged-in users."""
        from src.core.auth import get_current_user
        from src.database import get_db
        from src.routers.disclaimer import DISCLAIMER_VERSION

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.email = "test@example.com"
        mock_user.disclaimer_acknowledged = True
        mock_user.disclaimer_version = "1.1"  # outdated
        mock_user.is_active = True

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            response = await client.post("/api/disclaimer/acknowledge-auth")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "successfully" in data["message"].lower()
            assert mock_user.disclaimer_version == DISCLAIMER_VERSION
            mock_db.commit.assert_awaited_once()
        finally:
            app.dependency_overrides.clear()


class TestDisclaimerContent:
    """Tests for GET /api/disclaimer/content endpoint."""

    @pytest.mark.asyncio
    async def test_returns_disclaimer_content(self, client):
        """
        AC1: Disclaimer content includes all required warnings.
        v1.1 adds an AI Data Processing warning; v1.2 adds a photo-carb-estimate
        warning (Story 50.S).
        """
        response = await client.get("/api/disclaimer/content")

        assert response.status_code == 200
        data = response.json()

        assert data["version"] == "1.2"
        assert data["title"] == "Important Safety Information"

        # Check all required warnings are present
        warning_titles = [w["title"] for w in data["warnings"]]
        assert "Experimental Software" in warning_titles
        assert "AI Limitations" in warning_titles
        assert "Not FDA Approved" in warning_titles
        assert "Consult Your Healthcare Provider" in warning_titles
        assert "AI Data Processing" in warning_titles
        assert "Photo Carb Estimates Are Guesses" in warning_titles

        # Check warning text contains required phrases
        warning_texts = " ".join([w["text"] for w in data["warnings"]])
        assert "experimental" in warning_texts.lower()
        assert "ai" in warning_texts.lower()
        assert "fda" in warning_texts.lower()
        assert "healthcare provider" in warning_texts.lower()
        # The photo-carb warning must name the prohibited action explicitly.
        assert "insulin dose or bolus" in warning_texts.lower()
        # v1.1: AI data-flow disclosure uses vendor-agnostic cloud/local framing
        assert "cloud" in warning_texts.lower()
        assert "local" in warning_texts.lower()
        assert "byoai" in warning_texts.lower()

    @pytest.mark.asyncio
    async def test_returns_three_checkboxes(self, client):
        """
        v1.1: Three acknowledgment checkboxes, including AI data-flow.
        """
        response = await client.get("/api/disclaimer/content")

        assert response.status_code == 200
        data = response.json()

        assert len(data["checkboxes"]) == 3
        checkbox_ids = [c["id"] for c in data["checkboxes"]]
        assert "checkbox_experimental" in checkbox_ids
        assert "checkbox_not_medical_advice" in checkbox_ids
        assert "checkbox_ai_data_flow" in checkbox_ids

    @pytest.mark.asyncio
    async def test_returns_accept_button(self, client):
        """
        AC3: There is an "I Understand & Accept" button.
        """
        response = await client.get("/api/disclaimer/content")

        assert response.status_code == 200
        data = response.json()

        assert "I Understand & Accept" in data["button_text"]


class TestUserResponseDisclaimerGating:
    """The authenticated /me + login user payload must report
    disclaimer_acknowledged as version-aware, so clients re-prompt on a bump
    (Story 50.S) without knowing the current version themselves."""

    def _base_fields(self) -> dict:
        from datetime import datetime

        from src.models.user import UserRole

        return {
            "id": uuid.uuid4(),
            "email": "user@example.com",
            "display_name": None,
            "role": UserRole.DIABETIC,
            "is_active": True,
            "email_verified": True,
            "created_at": datetime.now(UTC),
        }

    def test_current_version_reads_acknowledged(self):
        from src.routers.disclaimer import DISCLAIMER_VERSION
        from src.schemas.auth import UserResponse

        resp = UserResponse(
            **self._base_fields(),
            disclaimer_acknowledged=True,
            disclaimer_version=DISCLAIMER_VERSION,
        )
        assert resp.disclaimer_acknowledged is True

    def test_outdated_version_reads_not_acknowledged(self):
        from src.schemas.auth import UserResponse

        resp = UserResponse(
            **self._base_fields(),
            disclaimer_acknowledged=True,
            disclaimer_version="1.1",
        )
        assert resp.disclaimer_acknowledged is False

    def test_never_acknowledged_reads_not_acknowledged(self):
        from src.schemas.auth import UserResponse

        resp = UserResponse(
            **self._base_fields(),
            disclaimer_acknowledged=False,
            disclaimer_version=None,
        )
        assert resp.disclaimer_acknowledged is False
