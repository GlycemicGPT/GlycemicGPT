"""Tests for analytics configuration: category_labels, custom_categories validation."""

import pytest
from pydantic import ValidationError

from src.schemas.analytics_config import (
    DEFAULT_CATEGORY_LABELS,
    MAX_CUSTOM_CATEGORIES,
    VALID_CATEGORY_KEYS,
    AnalyticsConfigDefaults,
    AnalyticsConfigUpdate,
    CustomCategoryItem,
)

# -- Schema validation tests --


class TestAnalyticsConfigUpdate:
    """Tests for AnalyticsConfigUpdate schema validation."""

    def test_all_none_is_valid(self):
        update = AnalyticsConfigUpdate()
        assert update.day_boundary_hour is None
        assert update.category_labels is None

    def test_valid_boundary_hour(self):
        update = AnalyticsConfigUpdate(day_boundary_hour=12)
        assert update.day_boundary_hour == 12

    def test_boundary_hour_below_range_fails(self):
        with pytest.raises(ValidationError):
            AnalyticsConfigUpdate(day_boundary_hour=-1)

    def test_boundary_hour_above_range_fails(self):
        with pytest.raises(ValidationError):
            AnalyticsConfigUpdate(day_boundary_hour=24)

    def test_valid_category_labels(self):
        labels = {"AUTO_CORRECTION": "Auto", "FOOD": "Food Bolus"}
        update = AnalyticsConfigUpdate(category_labels=labels)
        assert update.category_labels == labels

    def test_full_category_labels(self):
        update = AnalyticsConfigUpdate(category_labels=dict(DEFAULT_CATEGORY_LABELS))
        assert update.category_labels is not None
        assert len(update.category_labels) == 7

    def test_invalid_category_key_rejected(self):
        with pytest.raises(ValidationError, match="Invalid category keys"):
            AnalyticsConfigUpdate(category_labels={"BOGUS_KEY": "Bad"})

    def test_label_too_long_rejected(self):
        with pytest.raises(ValidationError, match="at most 20 characters"):
            AnalyticsConfigUpdate(category_labels={"FOOD": "A" * 21})

    def test_blank_label_rejected(self):
        with pytest.raises(ValidationError, match="must not be blank"):
            AnalyticsConfigUpdate(category_labels={"FOOD": "   "})

    def test_empty_string_label_rejected(self):
        with pytest.raises(ValidationError, match="must not be blank"):
            AnalyticsConfigUpdate(category_labels={"CORRECTION": ""})

    def test_partial_update_merges_with_existing(self):
        """Partial label updates should be valid -- only some keys provided."""
        update = AnalyticsConfigUpdate(category_labels={"OTHER": "Misc"})
        assert update.category_labels == {"OTHER": "Misc"}

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            AnalyticsConfigUpdate(unknown_field="value")

    def test_mixed_update(self):
        update = AnalyticsConfigUpdate(
            day_boundary_hour=6,
            category_labels={"FOOD": "Meals"},
        )
        assert update.day_boundary_hour == 6
        assert update.category_labels == {"FOOD": "Meals"}


# -- Defaults tests --


class TestAnalyticsConfigDefaults:
    """Tests for AnalyticsConfigDefaults schema."""

    def test_defaults_include_category_labels(self):
        defaults = AnalyticsConfigDefaults()
        assert defaults.day_boundary_hour == 0
        assert defaults.category_labels is not None
        assert len(defaults.category_labels) == len(VALID_CATEGORY_KEYS)

    def test_all_valid_keys_have_defaults(self):
        defaults = AnalyticsConfigDefaults()
        for key in VALID_CATEGORY_KEYS:
            assert key in defaults.category_labels, f"Missing default for {key}"

    def test_default_labels_under_20_chars(self):
        for key, label in DEFAULT_CATEGORY_LABELS.items():
            assert len(label) <= 20, f"Default label for {key} too long: {label}"
            assert len(label.strip()) > 0, f"Default label for {key} is blank"


# -- Constants tests --


class TestCustomCategories:
    """Tests for custom_categories field validation."""

    def test_valid_custom_categories(self):
        update = AnalyticsConfigUpdate(
            custom_categories=[
                CustomCategoryItem(key="EXERCISE_CORR", display_name="Exercise Corr"),
            ]
        )
        assert update.custom_categories is not None
        assert len(update.custom_categories) == 1
        assert update.custom_categories[0].key == "EXERCISE_CORR"

    def test_none_is_valid(self):
        update = AnalyticsConfigUpdate(custom_categories=None)
        assert update.custom_categories is None

    def test_empty_list_is_valid(self):
        update = AnalyticsConfigUpdate(custom_categories=[])
        assert update.custom_categories == []

    def test_key_overlapping_builtin_rejected(self):
        with pytest.raises(ValidationError, match="must not overlap"):
            AnalyticsConfigUpdate(
                custom_categories=[
                    CustomCategoryItem(key="FOOD", display_name="Custom Food"),
                ]
            )

    def test_key_invalid_pattern_rejected(self):
        with pytest.raises(ValidationError, match=r"\^"):
            AnalyticsConfigUpdate(
                custom_categories=[
                    CustomCategoryItem(key="lowercase", display_name="Bad"),
                ]
            )

    def test_key_starting_with_number_rejected(self):
        with pytest.raises(ValidationError, match=r"\^"):
            AnalyticsConfigUpdate(
                custom_categories=[
                    CustomCategoryItem(key="1_BAD", display_name="Bad"),
                ]
            )

    def test_display_name_blank_rejected(self):
        with pytest.raises(ValidationError, match="must not be blank"):
            AnalyticsConfigUpdate(
                custom_categories=[
                    CustomCategoryItem(key="CUSTOM_ONE", display_name="   "),
                ]
            )

    def test_display_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            AnalyticsConfigUpdate(
                custom_categories=[
                    CustomCategoryItem(key="CUSTOM_ONE", display_name="A" * 21),
                ]
            )

    def test_too_many_custom_categories_rejected(self):
        items = [
            CustomCategoryItem(key=f"CUSTOM_{i}", display_name=f"Custom {i}")
            for i in range(MAX_CUSTOM_CATEGORIES + 1)
        ]
        with pytest.raises(ValidationError, match="At most"):
            AnalyticsConfigUpdate(custom_categories=items)

    def test_duplicate_keys_rejected(self):
        with pytest.raises(ValidationError, match="must be unique"):
            AnalyticsConfigUpdate(
                custom_categories=[
                    CustomCategoryItem(key="CUSTOM_A", display_name="A"),
                    CustomCategoryItem(key="CUSTOM_A", display_name="B"),
                ]
            )

    def test_defaults_have_empty_custom_categories(self):
        defaults = AnalyticsConfigDefaults()
        assert defaults.custom_categories == []


class TestCategoryConstants:
    """Tests for VALID_CATEGORY_KEYS and DEFAULT_CATEGORY_LABELS alignment."""

    def test_valid_keys_match_defaults(self):
        assert set(DEFAULT_CATEGORY_LABELS.keys()) == VALID_CATEGORY_KEYS

    def test_seven_categories(self):
        assert len(VALID_CATEGORY_KEYS) == 7
