"""Tests for plugin declaration schema validation."""

import pytest
from pydantic import ValidationError

from src.schemas.analytics_config import VALID_CATEGORY_KEYS
from src.schemas.plugin_declaration import (
    PluginDeclarationCreate,
    PluginDeclarationResponse,
)

# -- PluginDeclarationCreate validation tests --


class TestPluginDeclarationCreate:
    """Tests for PluginDeclarationCreate schema validation."""

    def _valid_data(self, **overrides):
        base = {
            "plugin_id": "com.tandem.pump",
            "plugin_name": "Tandem Insulin Pump",
            "plugin_version": "1.0.0",
            "declared_categories": ["CONTROL_IQ", "BG_FOOD", "BG_ONLY"],
            "category_mappings": {
                "CONTROL_IQ": "AUTO_CORRECTION",
                "BG_FOOD": "FOOD_AND_CORRECTION",
                "BG_ONLY": "CORRECTION",
            },
        }
        base.update(overrides)
        return base

    def test_valid_declaration(self):
        decl = PluginDeclarationCreate(**self._valid_data())
        assert decl.plugin_id == "com.tandem.pump"
        assert len(decl.declared_categories) == 3
        assert decl.category_mappings["CONTROL_IQ"] == "AUTO_CORRECTION"

    def test_all_seven_mappings(self):
        decl = PluginDeclarationCreate(
            **self._valid_data(
                declared_categories=[
                    "CONTROL_IQ",
                    "FOOD_ONLY",
                    "BG_FOOD",
                    "BG_ONLY",
                    "OVERRIDE",
                    "AI_REC",
                    "QUICK",
                ],
                category_mappings={
                    "CONTROL_IQ": "AUTO_CORRECTION",
                    "FOOD_ONLY": "FOOD",
                    "BG_FOOD": "FOOD_AND_CORRECTION",
                    "BG_ONLY": "CORRECTION",
                    "OVERRIDE": "OVERRIDE",
                    "AI_REC": "AI_SUGGESTED",
                    "QUICK": "OTHER",
                },
            )
        )
        assert len(decl.category_mappings) == 7

    def test_plugin_id_invalid_chars_rejected(self):
        with pytest.raises(ValidationError, match="plugin_id"):
            PluginDeclarationCreate(**self._valid_data(plugin_id="foo bar"))

    def test_plugin_id_empty_rejected(self):
        with pytest.raises(ValidationError):
            PluginDeclarationCreate(**self._valid_data(plugin_id=""))

    def test_plugin_id_too_long_rejected(self):
        with pytest.raises(ValidationError):
            PluginDeclarationCreate(**self._valid_data(plugin_id="a" * 129))

    def test_plugin_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            PluginDeclarationCreate(**self._valid_data(plugin_name="a" * 65))

    def test_plugin_version_too_long_rejected(self):
        with pytest.raises(ValidationError):
            PluginDeclarationCreate(**self._valid_data(plugin_version="a" * 33))

    def test_empty_declared_categories_rejected(self):
        with pytest.raises(ValidationError):
            PluginDeclarationCreate(**self._valid_data(declared_categories=[]))

    def test_declared_category_too_long_rejected(self):
        with pytest.raises(ValidationError, match="at most 32 chars"):
            PluginDeclarationCreate(**self._valid_data(declared_categories=["A" * 33]))

    def test_declared_category_invalid_pattern_rejected(self):
        with pytest.raises(ValidationError, match=r"\^"):
            PluginDeclarationCreate(
                **self._valid_data(declared_categories=["lowercase"])
            )

    def test_invalid_mapping_value_rejected(self):
        with pytest.raises(ValidationError, match="valid platform categories"):
            PluginDeclarationCreate(
                **self._valid_data(
                    category_mappings={"CONTROL_IQ": "INVALID_PLATFORM_KEY"}
                )
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            PluginDeclarationCreate(**self._valid_data(extra_field="bad"))

    def test_mapping_values_all_valid_category_keys(self):
        """Every VALID_CATEGORY_KEY should be accepted as a mapping value."""
        for key in VALID_CATEGORY_KEYS:
            decl = PluginDeclarationCreate(
                **self._valid_data(
                    declared_categories=["TEST_CAT"],
                    category_mappings={"TEST_CAT": key},
                )
            )
            assert decl.category_mappings["TEST_CAT"] == key

    def test_duplicate_declared_categories_rejected(self):
        with pytest.raises(ValidationError, match="unique"):
            PluginDeclarationCreate(
                **self._valid_data(
                    declared_categories=["CONTROL_IQ", "CONTROL_IQ", "BG_FOOD"]
                )
            )

    def test_mapping_keys_not_in_declared_rejected(self):
        """Mapping keys must be a subset of declared_categories."""
        with pytest.raises(ValidationError, match="subset of declared_categories"):
            PluginDeclarationCreate(
                **self._valid_data(
                    declared_categories=["CONTROL_IQ"],
                    category_mappings={
                        "CONTROL_IQ": "AUTO_CORRECTION",
                        "UNDECLARED": "FOOD",
                    },
                )
            )

    def test_plugin_name_with_script_tags_rejected(self):
        with pytest.raises(ValidationError, match="plugin_name"):
            PluginDeclarationCreate(
                **self._valid_data(plugin_name="<script>alert(1)</script>")
            )

    def test_plugin_name_blank_rejected(self):
        with pytest.raises(ValidationError, match="blank"):
            PluginDeclarationCreate(**self._valid_data(plugin_name="   "))

    def test_plugin_version_with_html_rejected(self):
        with pytest.raises(ValidationError, match="plugin_version"):
            PluginDeclarationCreate(**self._valid_data(plugin_version="<img src=x>"))

    def test_plugin_version_blank_rejected(self):
        with pytest.raises(ValidationError, match="blank"):
            PluginDeclarationCreate(**self._valid_data(plugin_version="   "))

    def test_plugin_name_valid_chars_accepted(self):
        """Names with spaces, parens, and hyphens are valid."""
        decl = PluginDeclarationCreate(
            **self._valid_data(plugin_name="Tandem (Mobi) Pump-Driver")
        )
        assert decl.plugin_name == "Tandem (Mobi) Pump-Driver"

    def test_plugin_version_semver_plus_accepted(self):
        """Versions like '1.0.0+build.42' are valid."""
        decl = PluginDeclarationCreate(
            **self._valid_data(plugin_version="1.0.0+build.42")
        )
        assert decl.plugin_version == "1.0.0+build.42"


# -- PluginDeclarationResponse tests --


class TestPluginDeclarationResponse:
    """Tests for PluginDeclarationResponse schema."""

    def test_response_from_attributes(self):
        class FakeDecl:
            id = "550e8400-e29b-41d4-a716-446655440000"
            plugin_id = "com.tandem.pump"
            plugin_name = "Tandem"
            plugin_version = "1.0.0"
            declared_categories = ["CONTROL_IQ"]
            category_mappings = {"CONTROL_IQ": "AUTO_CORRECTION"}
            updated_at = "2026-01-01T00:00:00Z"

        resp = PluginDeclarationResponse.model_validate(FakeDecl())
        assert resp.plugin_id == "com.tandem.pump"
        assert resp.declared_categories == ["CONTROL_IQ"]
