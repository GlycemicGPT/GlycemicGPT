"""Smart-default glucose-unit seeding.

The platform stores every glucose value in canonical mg/dL and defaults every
new account to an ``mgdl`` *display* preference. For users in mmol/L regions
that default is wrong, and there is no honest way to auto-*detect* the unit on
mobile (all inbound glucose is canonical mg/dL ``int`` -- there is no mmol
stream to key off). The only available signals are weak proxies usable as a
one-time, overridable *seed*: the registration request's locale/region and a
connected Nightscout's classified display unit.

This module owns the locale->unit mapping. It is a best-guess **default**, not
a detector: the manual per-account toggle always wins, and a visible one-time
notice (gated on a still-seed-owned non-mgdl value) lets the user correct a
wrong guess. Nothing here touches stored values, conversion, or the 20-500
mg/dL safety invariant.
"""

from __future__ import annotations

import re

from src.core.units import GlucoseUnit

# ISO 3166-1 alpha-2 regions where blood glucose is conventionally reported in
# mmol/L. Curated best-guess, not exhaustive: the Anglosphere (minus the US),
# the Nordics, and the other commonly-mmol European / rest-of-world markets.
# A region absent from this set -- including the US and the mg/dL-reporting
# parts of Europe (DE, FR, ES, IT, PT) and Asia -- falls back to mg/dL, which
# is today's behavior. The user can always override; this only sets the
# starting point so mmol-region users aren't silently defaulted to mg/dL.
MMOL_REGIONS: frozenset[str] = frozenset(
    {
        # Anglosphere (mmol/L) -- US deliberately excluded (mg/dL).
        "GB",  # United Kingdom
        "IE",  # Ireland
        "AU",  # Australia
        "NZ",  # New Zealand
        "CA",  # Canada
        # Nordics
        "SE",  # Sweden
        "NO",  # Norway
        "FI",  # Finland
        "DK",  # Denmark
        "IS",  # Iceland
        # Other commonly-mmol European markets
        "NL",  # Netherlands
        "CH",  # Switzerland
        "CZ",  # Czechia
        "SK",  # Slovakia
        "HR",  # Croatia
        "EE",  # Estonia
        "LV",  # Latvia
        "LT",  # Lithuania
        # Rest of world
        "CN",  # China (mainland)
        "HK",  # Hong Kong
        "RU",  # Russia
        "UA",  # Ukraine
        "BY",  # Belarus
        "KZ",  # Kazakhstan
        "ZA",  # South Africa
        "MY",  # Malaysia
    }
)

# A BCP-47 region subtag is exactly two ASCII letters (e.g. ``GB`` in
# ``en-GB``) or three digits (a UN M.49 area code, which we do not map).
# Script subtags are four letters and language subtags lead, so a 2-letter
# subtag in any position after the first is the region.
_REGION_SUBTAG = re.compile(r"^[A-Za-z]{2}$")


def _region_from_language_tag(tag: str) -> str | None:
    """Extract the upper-cased region from one BCP-47 language tag.

    Handles ``en-GB`` -> ``GB``, ``zh-Hans-CN`` -> ``CN`` (the 4-letter script
    subtag is skipped), and ``en`` / ``*`` -> ``None`` (no region present).
    """
    subtags = tag.strip().split("-")
    for subtag in subtags[1:]:
        if _REGION_SUBTAG.match(subtag):
            return subtag.upper()
    return None


def glucose_unit_for_locale(accept_language: str | None) -> GlucoseUnit:
    """Map an ``Accept-Language`` header to a seeded glucose display unit.

    Decides from the user's highest-priority *regional* preference: the first
    language tag (in the header's listed order, which clients send
    most-preferred-first) that carries a region subtag wins. Its region maps to
    ``MMOL`` if it is a known mmol region, else ``MGDL``. A region-less leading
    tag (e.g. bare ``en``) is skipped in favor of the next regional tag. An
    absent, malformed, or wholly region-less header falls back to ``MGDL``
    (today's default). Quality values (``;q=...``) are ignored beyond list
    order, which is sufficient for a best-guess default.

    Deciding on the *first regional* tag -- not the first *mmol* tag anywhere in
    the list -- means a US-primary user with a UK fallback (``en-US,en-GB``)
    correctly seeds mg/dL rather than being pulled to mmol by a lower-priority
    locale.
    """
    if not accept_language:
        return GlucoseUnit.MGDL

    for entry in accept_language.split(","):
        # Drop any ``;q=`` weight; we honor list order, not the weight value.
        tag = entry.split(";", 1)[0].strip()
        if not tag or tag == "*":
            continue
        region = _region_from_language_tag(tag)
        if region is not None:
            return GlucoseUnit.MMOL if region in MMOL_REGIONS else GlucoseUnit.MGDL
    return GlucoseUnit.MGDL
