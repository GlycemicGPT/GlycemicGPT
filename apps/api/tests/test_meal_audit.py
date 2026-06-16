"""Story 50.H3: estimate auditability & provenance retention.

Covers: the create-time audit (raw samples + dispersion + vision-only precedence),
the grounding decision appended at identity confirmation, the self-reported
confidence being stored-but-not-surfaced, owner-scoped retrieval, and the
cascade-delete that ties the audit's lifetime to the food record (AC5).

External HTTP is mocked; embeddings are stubbed by the autouse conftest fixture.
"""

import json
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image
from sqlalchemy import func, select

from src.config import settings
from src.database import get_session_maker
from src.models.ai_provider import AIProviderConfig, AIProviderStatus, AIProviderType
from src.models.food_record import FoodRecord
from src.models.food_record_audit import FoodRecordAudit
from src.models.knowledge_chunk import KnowledgeChunk
from src.models.user import User, UserRole
from src.schemas.food_record import FoodRecordAuditResponse
from src.services import common_food as common_food_service
from src.services import food_vision, meal_audit, meal_rag, nutrition_sources


@pytest.fixture(autouse=True)
def _enable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "meal_intelligence_enabled", True)
    monkeypatch.setattr(settings, "meal_estimate_sample_count", 3)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), (50, 60, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _estimate_json(desc, low=40, high=55, confidence="high") -> str:
    return json.dumps(
        {
            "food_description": desc,
            "carbs_grams_low": low,
            "carbs_grams_high": high,
            "confidence": confidence,
        }
    )


async def _user_with_provider(db) -> User:
    user = User(
        email=f"h3_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role=UserRole.DIABETIC,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(
        AIProviderConfig(
            user_id=user.id,
            provider_type=AIProviderType.CLAUDE_API,
            model_name="claude-sonnet-4-5-20250929",
            status=AIProviderStatus.CONNECTED,
        )
    )
    await db.commit()
    return user


async def _create(db, user, desc) -> FoodRecord:
    with patch.object(
        food_vision, "_call_vision", AsyncMock(return_value=_estimate_json(desc))
    ):
        return await food_vision.create_food_record_from_image(
            db=db, user=user, raw_image=_png_bytes()
        )


async def _fetch_audit(food_record_id) -> FoodRecordAudit | None:
    async with get_session_maker()() as db:
        return await db.scalar(
            select(FoodRecordAudit).where(
                FoodRecordAudit.food_record_id == food_record_id
            )
        )


class TestCreateAudit:
    async def test_create_writes_raw_samples_and_dispersion(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            record = await _create(db, user, _uniq("oatmeal"))

        audit = await _fetch_audit(record.id)
        assert audit is not None
        assert audit.user_id == user.id
        # Raw per-sample outputs retained (3 samples).
        assert isinstance(audit.samples_json, list) and len(audit.samples_json) == 3
        sample = audit.samples_json[0]
        assert "carbs_low" in sample and "identity" in sample
        # Self-reported confidence retained in STORAGE (internal eval data).
        assert "self_reported_confidence" in sample
        # Dispersion summary captured.
        assert audit.dispersion_json["samples_used"] == 3
        # Precedence is vision-only at create (identity not yet confirmed).
        assert audit.precedence_json["outcome"] == "vision_only"
        assert audit.precedence_json["identity_confirmed"] is False

    async def test_audit_response_hides_self_reported_confidence(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            record = await _create(db, user, _uniq("toast"))
        audit = await _fetch_audit(record.id)

        response = FoodRecordAuditResponse.from_audit(audit)
        dumped = response.model_dump()
        # The surfaced samples carry carbs + identity but NOT the self-reported
        # confidence, which is internal-only (50.H1).
        assert dumped["samples"]
        for s in dumped["samples"]:
            assert "self_reported_confidence" not in s
            assert "carbs_low" in s and "identity" in s
        # The full serialized response (what the endpoint returns) never leaks it.
        assert "self_reported_confidence" not in response.model_dump_json()


class TestGroundingDecisionAudit:
    async def test_confirm_records_grounded_precedence(self):
        desc = _uniq("greek yogurt")
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            record = await _create(db, user, desc)

            usda = nutrition_sources.NutritionFact(
                source_name="USDA FoodData Central",
                source_url="https://fdc.nal.usda.gov/x",
                trust_tier=KnowledgeChunk.TIER_AUTHORITATIVE,
                name="greek yogurt",
                carbs_grams=6,
                serving="per 100 g",
                disclaimer=None,
            )
            with (
                patch.object(
                    meal_rag, "recall_similar_meal", AsyncMock(return_value=None)
                ),
                patch.object(
                    nutrition_sources,
                    "lookup_published_nutrition",
                    AsyncMock(return_value=(usda, None)),
                ),
            ):
                await common_food_service.confirm_food_identity(
                    db, record, "greek yogurt"
                )

        audit = await _fetch_audit(record.id)
        assert audit.precedence_json["outcome"] == "grounded"
        assert audit.precedence_json["chosen_source"] == "USDA FoodData Central"
        assert audit.precedence_json["identity_used"] == "greek yogurt"
        assert audit.precedence_json["identity_confirmed"] is True

    async def test_confirm_without_match_records_vision_only(self):
        desc = _uniq("mystery dish")
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            record = await _create(db, user, desc)
            with (
                patch.object(
                    meal_rag, "recall_similar_meal", AsyncMock(return_value=None)
                ),
                patch.object(
                    nutrition_sources,
                    "lookup_published_nutrition",
                    AsyncMock(return_value=(None, None)),
                ),
            ):
                await common_food_service.confirm_food_identity(
                    db, record, "mystery dish"
                )

        audit = await _fetch_audit(record.id)
        assert audit.precedence_json["outcome"] == "vision_only"
        assert audit.precedence_json["identity_confirmed"] is True
        assert audit.precedence_json["identity_used"] == "mystery dish"


class TestAuditRetention:
    async def test_get_audit_is_owner_scoped(self):
        async with get_session_maker()() as db:
            owner = await _user_with_provider(db)
            other = await _user_with_provider(db)
            record = await _create(db, owner, _uniq("salad"))

        async with get_session_maker()() as db:
            assert await meal_audit.get_audit(db, record.id, owner.id) is not None
            # Another user must never retrieve it.
            assert await meal_audit.get_audit(db, record.id, other.id) is None

    async def test_deleting_record_cascades_audit(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            record = await _create(db, user, _uniq("burrito"))
            record_id = record.id

        assert await _fetch_audit(record_id) is not None

        # Deleting the food record drops its audit trail (FK ON DELETE CASCADE).
        async with get_session_maker()() as db:
            row = await db.get(FoodRecord, record_id)
            await db.delete(row)
            await db.commit()

        async with get_session_maker()() as db:
            remaining = await db.scalar(
                select(func.count())
                .select_from(FoodRecordAudit)
                .where(FoodRecordAudit.food_record_id == record_id)
            )
        assert remaining == 0
