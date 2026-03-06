"""Tests for analytics configuration: DisplayLabel validation and defaults."""

import pytest
from pydantic import ValidationError

from src.schemas.analytics_config import (
    COMPUTATION_ROLES,
    DEFAULT_CATEGORY_LABELS,
    DEFAULT_DISPLAY_LABELS,
    MAX_DISPLAY_LABELS,
    AnalyticsConfigDefaults,
    AnalyticsConfigUpdate,
    DisplayLabel,
    display_labels_to_category_labels,
)

# -- DisplayLabel validation tests --


class TestDisplayLabel:
    """Tests for DisplayLabel schema validation."""

    def test_valid_label(self):
        label = DisplayLabel(
            id="auto_corr",
            label="Auto Corr",
            computation_role="AUTO_CORRECTION",
            pump_source=None,
            sort_order=0,
        )
        assert label.id == "auto_corr"
        assert label.computation_role == "AUTO_CORRECTION"

    def test_label_without_role(self):
        label = DisplayLabel(
            id="my_custom",
            label="Custom Label",
            computation_role=None,
            pump_source=None,
            sort_order=6,
        )
        assert label.computation_role is None

    def test_label_with_pump_source(self):
        label = DisplayLabel(
            id="auto_corr",
            label="Auto Corr",
            computation_role="AUTO_CORRECTION",
            pump_source="CONTROL_IQ",
            sort_order=0,
        )
        assert label.pump_source == "CONTROL_IQ"

    def test_id_must_start_with_letter(self):
        with pytest.raises(ValidationError, match="must match"):
            DisplayLabel(id="1bad", label="Bad", sort_order=0)

    def test_id_uppercase_rejected(self):
        with pytest.raises(ValidationError, match="must match"):
            DisplayLabel(id="AutoCorr", label="Auto", sort_order=0)

    def test_id_too_long_rejected(self):
        with pytest.raises(ValidationError):
            DisplayLabel(id="a" * 33, label="Label", sort_order=0)

    def test_label_blank_rejected(self):
        with pytest.raises(ValidationError, match="must not be blank"):
            DisplayLabel(id="test", label="   ", sort_order=0)

    def test_label_empty_rejected(self):
        with pytest.raises(ValidationError, match="must not be blank"):
            DisplayLabel(id="test", label="", sort_order=0)

    def test_label_too_long_rejected(self):
        with pytest.raises(ValidationError):
            DisplayLabel(id="test", label="A" * 21, sort_order=0)

    def test_label_html_rejected(self):
        with pytest.raises(ValidationError, match="HTML"):
            DisplayLabel(id="test", label="<script>xss</script>", sort_order=0)

    def test_invalid_computation_role_rejected(self):
        with pytest.raises(ValidationError, match="computation_role"):
            DisplayLabel(
                id="test",
                label="Test",
                computation_role="INVALID_ROLE",
                sort_order=0,
            )

    def test_ai_suggested_not_a_computation_role(self):
        with pytest.raises(ValidationError, match="computation_role"):
            DisplayLabel(
                id="ai_sugg",
                label="AI Suggested",
                computation_role="AI_SUGGESTED",
                sort_order=0,
            )

    def test_negative_sort_order_rejected(self):
        with pytest.raises(ValidationError):
            DisplayLabel(id="test", label="Test", sort_order=-1)

    def test_pump_source_too_long_rejected(self):
        with pytest.raises(ValidationError):
            DisplayLabel(id="test", label="Test", pump_source="A" * 33, sort_order=0)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            DisplayLabel(id="test", label="Test", sort_order=0, unknown_field="bad")


# -- AnalyticsConfigUpdate validation tests --


class TestAnalyticsConfigUpdate:
    """Tests for AnalyticsConfigUpdate schema validation."""

    def test_all_none_is_valid(self):
        update = AnalyticsConfigUpdate()
        assert update.day_boundary_hour is None
        assert update.display_labels is None

    def test_valid_boundary_hour(self):
        update = AnalyticsConfigUpdate(day_boundary_hour=12)
        assert update.day_boundary_hour == 12

    def test_boundary_hour_below_range_fails(self):
        with pytest.raises(ValidationError):
            AnalyticsConfigUpdate(day_boundary_hour=-1)

    def test_boundary_hour_above_range_fails(self):
        with pytest.raises(ValidationError):
            AnalyticsConfigUpdate(day_boundary_hour=24)

    def test_valid_display_labels(self):
        labels = [
            DisplayLabel(
                id="meal", label="Meal", computation_role="FOOD", sort_order=0
            ),
        ]
        update = AnalyticsConfigUpdate(display_labels=labels)
        assert update.display_labels is not None
        assert len(update.display_labels) == 1

    def test_full_default_labels(self):
        labels = [DisplayLabel(**item) for item in DEFAULT_DISPLAY_LABELS]
        update = AnalyticsConfigUpdate(display_labels=labels)
        assert len(update.display_labels) == 6

    def test_empty_labels_rejected(self):
        with pytest.raises(ValidationError, match="At least one"):
            AnalyticsConfigUpdate(display_labels=[])

    def test_too_many_labels_rejected(self):
        labels = [
            DisplayLabel(id=f"label_{i}", label=f"Label {i}", sort_order=i)
            for i in range(MAX_DISPLAY_LABELS + 1)
        ]
        with pytest.raises(ValidationError, match="At most"):
            AnalyticsConfigUpdate(display_labels=labels)

    def test_duplicate_ids_rejected(self):
        labels = [
            DisplayLabel(id="dup", label="First", sort_order=0),
            DisplayLabel(id="dup", label="Second", sort_order=1),
        ]
        with pytest.raises(ValidationError, match="ids must be unique"):
            AnalyticsConfigUpdate(display_labels=labels)

    def test_duplicate_computation_roles_rejected(self):
        labels = [
            DisplayLabel(id="a", label="A", computation_role="FOOD", sort_order=0),
            DisplayLabel(id="b", label="B", computation_role="FOOD", sort_order=1),
        ]
        with pytest.raises(ValidationError, match="at most one label"):
            AnalyticsConfigUpdate(display_labels=labels)

    def test_mixed_roles_and_null_is_valid(self):
        labels = [
            DisplayLabel(
                id="meal", label="Meal", computation_role="FOOD", sort_order=0
            ),
            DisplayLabel(
                id="custom", label="Custom", computation_role=None, sort_order=1
            ),
        ]
        update = AnalyticsConfigUpdate(display_labels=labels)
        assert len(update.display_labels) == 2

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            AnalyticsConfigUpdate(unknown_field="value")

    def test_mixed_update(self):
        labels = [
            DisplayLabel(
                id="meal", label="Meals", computation_role="FOOD", sort_order=0
            ),
        ]
        update = AnalyticsConfigUpdate(
            day_boundary_hour=6,
            display_labels=labels,
        )
        assert update.day_boundary_hour == 6
        assert update.display_labels[0].label == "Meals"


# -- Defaults tests --


class TestAnalyticsConfigDefaults:
    """Tests for AnalyticsConfigDefaults schema."""

    def test_defaults_include_display_labels(self):
        defaults = AnalyticsConfigDefaults()
        assert defaults.day_boundary_hour == 0
        assert defaults.display_labels is not None
        assert len(defaults.display_labels) == 6

    def test_all_computation_roles_have_defaults(self):
        defaults = AnalyticsConfigDefaults()
        roles = {
            d["computation_role"]
            for d in defaults.display_labels
            if d.get("computation_role")
        }
        assert roles == COMPUTATION_ROLES

    def test_default_labels_under_20_chars(self):
        for item in DEFAULT_DISPLAY_LABELS:
            label = item["label"]
            assert len(label) <= 20, f"Default label too long: {label}"
            assert len(label.strip()) > 0, "Default label is blank"

    def test_defaults_include_legacy_category_labels(self):
        defaults = AnalyticsConfigDefaults()
        assert defaults.category_labels is not None
        assert len(defaults.category_labels) == 6
        for role in COMPUTATION_ROLES:
            assert role in defaults.category_labels

    def test_six_default_labels(self):
        assert len(DEFAULT_DISPLAY_LABELS) == 6


# -- Constants tests --


class TestComputationRoles:
    """Tests for COMPUTATION_ROLES constant."""

    def test_six_roles(self):
        assert len(COMPUTATION_ROLES) == 6

    def test_ai_suggested_not_a_role(self):
        assert "AI_SUGGESTED" not in COMPUTATION_ROLES

    def test_expected_roles_present(self):
        expected = {
            "AUTO_CORRECTION",
            "FOOD",
            "FOOD_AND_CORRECTION",
            "CORRECTION",
            "OVERRIDE",
            "OTHER",
        }
        assert expected == COMPUTATION_ROLES


# -- Legacy compat helper tests --


class TestDisplayLabelsToCategoyLabels:
    """Tests for display_labels_to_category_labels helper."""

    def test_none_returns_defaults(self):
        result = display_labels_to_category_labels(None)
        assert result == DEFAULT_CATEGORY_LABELS

    def test_empty_list_returns_defaults(self):
        result = display_labels_to_category_labels([])
        assert result == DEFAULT_CATEGORY_LABELS

    def test_converts_labels_with_roles(self):
        labels = [
            {"id": "meal", "label": "My Meals", "computation_role": "FOOD"},
            {"id": "corr", "label": "Fixes", "computation_role": "CORRECTION"},
            {"id": "custom", "label": "Custom", "computation_role": None},
        ]
        result = display_labels_to_category_labels(labels)
        assert result["FOOD"] == "My Meals"
        assert result["CORRECTION"] == "Fixes"
        assert "custom" not in result  # no computation_role -> excluded

    def test_handles_pydantic_models(self):
        labels = [
            DisplayLabel(
                id="meal", label="Meal", computation_role="FOOD", sort_order=0
            ),
        ]
        result = display_labels_to_category_labels(labels)
        assert result["FOOD"] == "Meal"
