"""Unit tests for the locale -> glucose-unit seed mapping.

Covers the pure ``glucose_unit_for_locale`` mapping: the mmol-region set, the
mg/dL miss/absent fallback, and BCP-47 tag parsing edge cases. The seed is a
display-preference best guess, not a detector, so the contract under test is
"recognized mmol region -> mmol; everything else -> mg/dL".
"""

import pytest

from src.core.units import GlucoseUnit
from src.services.glucose_unit_seed import (
    MMOL_REGIONS,
    glucose_unit_for_locale,
)


@pytest.mark.parametrize(
    "header",
    [
        "en-GB",
        "en-GB,en;q=0.9",
        "en-IE",
        "en-AU,en;q=0.8",
        "en-NZ",
        "en-CA,fr-CA;q=0.7",
        "sv-SE",
        "nl-NL",
        "zh-Hans-CN",  # script subtag is skipped; region CN is mmol
        "ru-RU",
        "EN-gb",  # case-insensitive region match
    ],
)
def test_mmol_region_locales_seed_mmol(header):
    assert glucose_unit_for_locale(header) == GlucoseUnit.MMOL


@pytest.mark.parametrize(
    "header",
    [
        "en-US",
        "en-US,en;q=0.9",
        "de-DE",  # Germany reports mg/dL -- deliberately excluded
        "fr-FR",
        "es-ES",
        "ja-JP",
        "pt-BR",
        "en",  # language only, no region
        "*",
        "",
        "   ",
        "xx-ZZ",  # unknown region
    ],
)
def test_non_mmol_or_regionless_locales_seed_mgdl(header):
    assert glucose_unit_for_locale(header) == GlucoseUnit.MGDL


def test_absent_header_seeds_mgdl():
    assert glucose_unit_for_locale(None) == GlucoseUnit.MGDL


def test_first_recognized_region_in_list_order_wins():
    # Lower-priority mmol region behind a higher-priority mg/dL one: list order
    # is honored, so the leading mg/dL tag (US) decides -> mg/dL.
    assert glucose_unit_for_locale("en-US,en-GB;q=0.5") == GlucoseUnit.MGDL
    # A leading region-less tag is skipped; the next tag (GB) decides.
    assert glucose_unit_for_locale("en,en-GB;q=0.5") == GlucoseUnit.MMOL


def test_us_excluded_and_anglosphere_included():
    assert "US" not in MMOL_REGIONS
    for region in ("GB", "IE", "AU", "NZ", "CA"):
        assert region in MMOL_REGIONS
