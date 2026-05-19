"""Tandem cloud region/country routing.

Tandem operates exactly two cloud backends (US and EU) and uses per-country
dynamic config files to route uploads. We store the user's ISO-3166-1 alpha-2
country code on ``IntegrationCredential.region`` and derive the backend bucket
at upload time.

The country list was determined empirically by probing
``https://assets.tandemdiabetes.com/configuration/mobile-urls/{COUNTRY}.json``
on 2026-05-17. Any country not listed here is not provisioned by Tandem.
"""

TANDEM_COUNTRY_TO_CLOUD: dict[str, str] = {
    # US cloud (tdcservices.tandemdiabetes.com)
    "US": "US",
    "CA": "US",
    "MX": "US",
    # EU cloud (tdcservices.eu.tandemdiabetes.com) - Western Europe
    "GB": "EU",
    "DE": "EU",
    "FR": "EU",
    "IT": "EU",
    "ES": "EU",
    "NL": "EU",
    "BE": "EU",
    "SE": "EU",
    "NO": "EU",
    "FI": "EU",
    "DK": "EU",
    "PT": "EU",
    "IE": "EU",
    "LU": "EU",
    "CH": "EU",
    "AT": "EU",
    "GR": "EU",
    # EU cloud - Central / Eastern Europe
    "PL": "EU",
    "CZ": "EU",
    "HU": "EU",
    "RO": "EU",
    "BG": "EU",
    "HR": "EU",
    "SI": "EU",
    "SK": "EU",
    "EE": "EU",
    "LV": "EU",
    "LT": "EU",
    "MT": "EU",
    "IS": "EU",
    # EU cloud - Other regions
    "AU": "EU",
    "NZ": "EU",
    "IL": "EU",
    "ZA": "EU",
    # EU cloud - Additional provisioned countries
    "RU": "EU",
    "UA": "EU",
    "RS": "EU",
    "BA": "EU",
    "AL": "EU",
    "ME": "EU",
    "MK": "EU",
}

SUPPORTED_TANDEM_COUNTRIES: frozenset[str] = frozenset(TANDEM_COUNTRY_TO_CLOUD.keys())

LEGACY_TANDEM_REGION_VALUES: frozenset[str] = frozenset({"EU"})
"""Legacy region values that pre-date country-based routing.

Pre-existing rows with these values cannot be resolved to a country reliably,
so the user must re-select on next interaction. ``"US"`` is not legacy because
it remains valid as both the old region value and the new country code.
"""


class TandemLegacyRegionError(RuntimeError):
    """The user's stored Tandem region predates country-based routing.

    Pre-existing rows with bucket labels like ``"EU"`` cannot be reliably
    resolved to a single country, so the user must re-select their country
    before reads or uploads can resume.
    """


def country_to_cloud(country: str) -> str:
    """Return the Tandem cloud bucket ("US" or "EU") for a supported country.

    Raises ``ValueError`` if the country is unsupported.
    """
    bucket = TANDEM_COUNTRY_TO_CLOUD.get(country)
    if bucket is None:
        raise ValueError(
            f"Country code '{country}' is not supported by Tandem cloud. "
            f"Supported countries: {sorted(SUPPORTED_TANDEM_COUNTRIES)}"
        )
    return bucket


def is_legacy_tandem_region(value: str) -> bool:
    """Return True if ``value`` is a legacy region string requiring re-selection."""
    return value in LEGACY_TANDEM_REGION_VALUES


def resolve_country_or_raise(value: str) -> tuple[str, str]:
    """Validate a stored region value and return ``(country, cloud)``.

    Raises ``TandemLegacyRegionError`` if the value is a legacy bucket label
    or otherwise unsupported. Callers should translate this into a
    user-facing "please re-select your country" prompt.
    """
    if is_legacy_tandem_region(value):
        raise TandemLegacyRegionError(
            f"Stored Tandem region '{value}' is from an older schema and "
            "cannot be resolved to a country. Please re-select your country "
            "in the Tandem integration settings."
        )
    if value not in SUPPORTED_TANDEM_COUNTRIES:
        raise TandemLegacyRegionError(
            f"Stored Tandem country '{value}' is not in the supported list. "
            "Please re-select your country."
        )
    return value, country_to_cloud(value)
