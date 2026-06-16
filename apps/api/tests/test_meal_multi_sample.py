"""Story 50.H1: multi-sample estimation + empirical confidence.

Covers the safety rework: confidence/range come from how much N samples of the
same photo disagree (empirical), NOT the model's self-reported confidence; wide
spread is surfaced viscerally; identity disagreement forces low confidence and
flags the H2 gate; per-sample reject-not-clamp bounds; graceful partial-failure;
and the cornerstone safety invariant (no dosing output, nothing coupled to
therapy math).

Pure-aggregation tests build ``ParsedEstimate`` samples directly. Pipeline tests
patch ``food_vision._call_vision`` with a ``side_effect`` list so the N concurrent
samples return controlled, differing responses. Embeddings are stubbed by the
autouse conftest fixture; no live vision calls are made.
"""

import json
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from src.config import settings
from src.database import get_session_maker
from src.models.ai_provider import AIProviderConfig, AIProviderStatus, AIProviderType
from src.models.user import User, UserRole
from src.services import food_vision
from src.services import meal_estimate_aggregate as agg
from src.vision.carb_contract import ParsedEstimate, find_dosing_violations

# (asyncio_mode = "auto" in pyproject -- async tests need no explicit mark.)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _sample(
    low: float | None,
    high: float | None,
    desc: str = "a bowl of pasta",
    *,
    confidence: str | None = "high",
    parse_ok: bool = True,
) -> ParsedEstimate:
    return ParsedEstimate(
        carbs_low=low,
        carbs_high=high,
        confidence=confidence,
        food_description=desc,
        raw_text="{}",
        nutrition={"protein_grams": 10},
        parse_ok=parse_ok,
    )


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), (70, 40, 20)).save(buf, format="PNG")
    return buf.getvalue()


def _estimate_json(low=40, high=55, desc="a bowl of pasta", confidence="high") -> str:
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
        email=f"h1_{uuid.uuid4().hex[:8]}@example.com",
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


# --------------------------------------------------------------------------- #
# Aggregation: empirical range + dispersion -> confidence band (AC2/AC3)
# --------------------------------------------------------------------------- #
class TestAggregation:
    def test_tight_agreement_is_high_confidence(self):
        samples = [_sample(40, 50), _sample(41, 51), _sample(40, 50)]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result is not None
        assert result.confidence == agg.CONFIDENCE_HIGH
        assert result.wide_spread is False

    def test_empirical_band_is_union_of_sample_ranges(self):
        # The presented band spans every usable sample's own range.
        samples = [_sample(40, 50), _sample(45, 60), _sample(38, 52)]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result.carbs_low == 38
        assert result.carbs_high == 60

    def test_moderate_spread_is_medium(self):
        # Midpoints 45 / 55 / 50 -> CV ~0.08... tune inputs to land in [0.10,0.25).
        samples = [_sample(30, 40), _sample(54, 64), _sample(42, 52)]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result.confidence == agg.CONFIDENCE_MEDIUM

    def test_wide_spread_is_low_and_flagged(self):
        samples = [_sample(40, 50), _sample(120, 140), _sample(80, 100)]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result.confidence == agg.CONFIDENCE_LOW
        assert result.wide_spread is True
        # CV is real and large.
        assert result.dispersion_cv is not None and result.dispersion_cv > 0.25

    def test_single_sample_can_never_exceed_low_confidence(self):
        # One draw can't measure dispersion -- exactly the lucky-draw problem.
        result = agg.aggregate_samples([_sample(40, 50)], samples_requested=1)
        assert result is not None
        assert result.confidence == agg.CONFIDENCE_LOW
        assert result.samples_ok == 1

    def test_identity_disagreement_forces_low_and_flags(self):
        # Same numbers, but the model can't agree what the food IS.
        samples = [
            _sample(40, 50, "creme brulee"),
            _sample(41, 51, "crema catalana"),
            _sample(42, 52, "flan custard tart"),
        ]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result.identity_agreement is False
        assert result.confidence == agg.CONFIDENCE_LOW
        assert result.wide_spread is True
        assert len(result.distinct_identities) >= 2

    def test_identity_clusters_through_filler_words(self):
        # Wording noise must not read as disagreement.
        samples = [
            _sample(40, 50, "a plate of grilled chicken"),
            _sample(41, 51, "grilled chicken breast"),
            _sample(40, 52, "grilled chicken"),
        ]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result.identity_agreement is True

    def test_no_usable_samples_returns_none(self):
        samples = [_sample(None, None, parse_ok=False), _sample(10, 20, parse_ok=False)]
        assert agg.aggregate_samples(samples, samples_requested=2) is None

    def test_partial_failure_uses_only_successes(self):
        samples = [
            _sample(40, 50),
            _sample(None, None, parse_ok=False),
            _sample(44, 54),
        ]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result is not None
        assert result.samples_ok == 2
        assert result.samples_requested == 3
        assert result.carbs_low == 40 and result.carbs_high == 54

    def test_out_of_bounds_sample_dropped_not_poisoning_union(self):
        # A hallucinated 99999 g sample is rejected per-sample (AC7), not folded
        # into the union where it would blow the absolute bound.
        samples = [_sample(40, 50), _sample(10, 99999), _sample(42, 52)]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result is not None
        assert result.samples_ok == 2
        assert result.carbs_high == 52  # the 99999 sample was dropped

    def test_self_reported_confidence_kept_in_audit_only(self):
        # Self-reported "high" survives in per-sample audit, but the aggregate's
        # surfaced confidence is dispersion-derived and can disagree with it.
        samples = [
            _sample(40, 50, confidence="high"),
            _sample(120, 140, confidence="high"),
            _sample(80, 100, confidence="high"),
        ]
        result = agg.aggregate_samples(samples, samples_requested=3)
        assert result.confidence == agg.CONFIDENCE_LOW  # NOT "high"
        assert {s.self_reported_confidence for s in result.samples} == {"high"}


# --------------------------------------------------------------------------- #
# Pipeline: multi-sample wired end-to-end (AC1/AC4/AC6/AC7)
# --------------------------------------------------------------------------- #
class TestPipelineMultiSample:
    @pytest.fixture(autouse=True)
    def _uploads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
        monkeypatch.setattr(settings, "meal_estimate_sample_count", 3)

    def _patch_vision(self, *responses):
        return patch.object(
            food_vision, "_call_vision", AsyncMock(side_effect=list(responses))
        )

    async def test_persists_empirical_band_and_dispersion(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with self._patch_vision(
                _estimate_json(40, 50, "pasta"),
                _estimate_json(44, 54, "pasta"),
                _estimate_json(42, 52, "pasta"),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

        assert record.carbs_low == 40 and record.carbs_high == 54  # union
        assert record.estimate_dispersion is not None
        d = record.estimate_dispersion
        assert d.samples_requested == 3 and d.samples_used == 3
        assert d.confidence == record.confidence  # surfaced band is the empirical one
        assert d.identity_agreement is True

    async def test_wide_spread_low_confidence_and_visceral_note(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with self._patch_vision(
                _estimate_json(40, 50, "pasta", confidence="high"),
                _estimate_json(120, 140, "pasta", confidence="high"),
                _estimate_json(80, 100, "pasta", confidence="high"),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

        d = record.estimate_dispersion
        # Despite every sample self-reporting "high", the surfaced confidence is
        # low -- proving self-reported confidence is not what we show.
        assert record.confidence == "low"
        assert d.wide_spread is True
        assert d.note and "rough guess" in d.note
        assert not find_dosing_violations(d.note)

    async def test_identity_disagreement_requires_confirmation(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with self._patch_vision(
                _estimate_json(40, 50, "creme brulee"),
                _estimate_json(42, 52, "crema catalana"),
                _estimate_json(41, 51, "flan custard"),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

        d = record.estimate_dispersion
        assert d.identity_agreement is False
        assert record.confidence == "low"
        assert "confirm the food" in (d.note or "")

    async def test_partial_sample_failure_degrades_gracefully(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with self._patch_vision(
                _estimate_json(40, 50, "pasta"),
                food_vision.VisionServiceError("transient"),
                _estimate_json(44, 54, "pasta"),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

        assert record.carbs_low == 40 and record.carbs_high == 54
        assert record.estimate_dispersion.samples_used == 2
        assert record.estimate_dispersion.samples_requested == 3

    async def test_all_samples_service_error_raises_service_error(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with (
                self._patch_vision(
                    food_vision.VisionServiceError("down"),
                    food_vision.VisionServiceError("down"),
                    food_vision.VisionServiceError("down"),
                ),
                pytest.raises(food_vision.VisionServiceError),
            ):
                await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

    async def test_all_samples_unavailable_raises_unavailable(self):
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with (
                self._patch_vision(
                    food_vision.VisionUnavailableError("no vision"),
                    food_vision.VisionUnavailableError("no vision"),
                    food_vision.VisionUnavailableError("no vision"),
                ),
                pytest.raises(food_vision.VisionUnavailableError),
            ):
                await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

    async def test_per_sample_dosing_scrub_before_aggregation(self):
        # A sample that smuggles dosing advice into its description has the
        # description nulled; its (safe) numbers still count toward the band.
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with self._patch_vision(
                _estimate_json(40, 50, "pasta -- inject 5 units of insulin"),
                _estimate_json(42, 52, "pasta -- inject 5 units of insulin"),
                _estimate_json(41, 51, "pasta -- inject 5 units of insulin"),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

        # Every description was dosing-laden and scrubbed -> none persisted.
        assert record.food_description is None
        # Numbers survived; the band is still produced.
        assert record.carbs_low == 40 and record.carbs_high == 52


# --------------------------------------------------------------------------- #
# Safety: empirical confidence carries no dosing language / therapy coupling
# --------------------------------------------------------------------------- #
class TestSafety:
    def test_dispersion_notes_never_contain_dosing_language(self):
        # Exercise every note branch; none may read as dosing advice.
        cases = [
            agg.AggregatedEstimate(
                carbs_low=40,
                carbs_high=90,
                confidence="low",
                food_description="x",
                nutrition={},
                dispersion_cv=0.4,
                identity_agreement=False,
                distinct_identities=["a", "b"],
                samples_requested=3,
                samples_ok=3,
                wide_spread=True,
            ),
            agg.AggregatedEstimate(
                carbs_low=40,
                carbs_high=90,
                confidence="low",
                food_description="x",
                nutrition={},
                dispersion_cv=0.4,
                identity_agreement=True,
                distinct_identities=["a"],
                samples_requested=3,
                samples_ok=3,
                wide_spread=True,
            ),
            agg.AggregatedEstimate(
                carbs_low=40,
                carbs_high=50,
                confidence="low",
                food_description="x",
                nutrition={},
                dispersion_cv=None,
                identity_agreement=True,
                distinct_identities=["a"],
                samples_requested=3,
                samples_ok=1,
                wide_spread=False,
            ),
            agg.AggregatedEstimate(
                carbs_low=40,
                carbs_high=50,
                confidence="high",
                food_description="x",
                nutrition={},
                dispersion_cv=0.02,
                identity_agreement=True,
                distinct_identities=["a"],
                samples_requested=3,
                samples_ok=3,
                wide_spread=False,
            ),
        ]
        for case in cases:
            note = food_vision._dispersion_note(case)
            assert note
            assert not find_dosing_violations(note)
