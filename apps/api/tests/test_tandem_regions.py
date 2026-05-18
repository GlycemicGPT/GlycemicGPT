"""Unit tests for the Tandem country/region routing helpers."""

import pytest

from src.core.tandem_regions import (
    LEGACY_TANDEM_REGION_VALUES,
    SUPPORTED_TANDEM_COUNTRIES,
    TANDEM_COUNTRY_TO_CLOUD,
    TandemLegacyRegionError,
    country_to_cloud,
    is_legacy_tandem_region,
    resolve_country_or_raise,
)


class TestCountryToCloud:
    """``country_to_cloud`` resolves ISO codes to one of two cloud buckets."""

    @pytest.mark.parametrize("code", ["US", "CA", "MX"])
    def test_us_cloud_countries(self, code: str):
        assert country_to_cloud(code) == "US"

    @pytest.mark.parametrize(
        "code", ["GB", "DE", "FR", "IT", "ES", "NL", "AU", "NZ", "IL", "ZA"]
    )
    def test_eu_cloud_countries(self, code: str):
        assert country_to_cloud(code) == "EU"

    def test_unsupported_country_raises(self):
        with pytest.raises(ValueError, match="not supported"):
            country_to_cloud("JP")  # Tandem does not sell in JP

    def test_lowercase_not_accepted(self):
        # We store and pass uppercase ISO codes; lowercase is a caller bug.
        with pytest.raises(ValueError):
            country_to_cloud("us")


class TestIsLegacyTandemRegion:
    """Legacy bucket labels (``"EU"``) must be detectable for re-select prompts."""

    def test_eu_is_legacy(self):
        assert is_legacy_tandem_region("EU") is True

    def test_us_is_not_legacy(self):
        # "US" is valid as both a country code and the old bucket label
        # because they coincide -- never trigger the re-select prompt.
        assert is_legacy_tandem_region("US") is False

    def test_iso_country_not_legacy(self):
        for code in ["GB", "DE", "CA", "AU"]:
            assert is_legacy_tandem_region(code) is False


class TestResolveCountryOrRaise:
    """Combined helper used by the service layer."""

    def test_valid_country_returns_pair(self):
        assert resolve_country_or_raise("US") == ("US", "US")
        assert resolve_country_or_raise("GB") == ("GB", "EU")
        assert resolve_country_or_raise("CA") == ("CA", "US")

    def test_legacy_eu_raises_legacy_error(self):
        with pytest.raises(TandemLegacyRegionError, match="older schema"):
            resolve_country_or_raise("EU")

    def test_unknown_country_raises_legacy_error(self):
        # An ISO code Tandem doesn't provision (e.g. "JP") is treated as
        # "needs re-select" so the user picks something supported.
        with pytest.raises(TandemLegacyRegionError):
            resolve_country_or_raise("JP")

    def test_empty_string_raises(self):
        with pytest.raises(TandemLegacyRegionError):
            resolve_country_or_raise("")


class TestCountryMapConsistency:
    """Guard against silent drift between the constants."""

    def test_country_map_and_supported_set_match(self):
        assert set(TANDEM_COUNTRY_TO_CLOUD.keys()) == SUPPORTED_TANDEM_COUNTRIES

    def test_legacy_values_not_in_supported(self):
        # "EU" must not also be in the supported country list, otherwise
        # is_legacy_tandem_region and country_to_cloud would disagree.
        assert "EU" not in SUPPORTED_TANDEM_COUNTRIES
        assert LEGACY_TANDEM_REGION_VALUES.isdisjoint(SUPPORTED_TANDEM_COUNTRIES)

    def test_only_two_cloud_buckets(self):
        # tconnectsync supports exactly US and EU -- adding a third here
        # would silently break TandemSourceApi auth.
        assert set(TANDEM_COUNTRY_TO_CLOUD.values()) == {"US", "EU"}
