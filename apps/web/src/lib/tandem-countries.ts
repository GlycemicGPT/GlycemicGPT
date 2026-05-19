/**
 * Tandem-supported countries grouped for the integration's country picker.
 *
 * Mirrors `apps/api/src/core/tandem_regions.py::TANDEM_COUNTRY_TO_CLOUD`.
 * The two must stay in sync -- the regex pattern in the backend schema is
 * derived from the same source, so adding a country here without updating
 * the backend will surface as a 422 validation error.
 */

export interface TandemCountryOption {
  /** ISO-3166-1 alpha-2 code persisted to the credential. */
  code: string;
  /** Label shown in the picker. */
  label: string;
}

export interface TandemCountryGroup {
  /** Group label shown as an `<optgroup>`. */
  label: string;
  options: TandemCountryOption[];
}

/**
 * Country list grouped by which Tandem cloud bucket they route to and
 * by rough geography for readability.
 */
export const TANDEM_COUNTRY_GROUPS: readonly TandemCountryGroup[] = [
  {
    label: "Americas (US cloud)",
    options: [
      { code: "US", label: "United States" },
      { code: "CA", label: "Canada" },
      { code: "MX", label: "Mexico" },
    ],
  },
  {
    label: "United Kingdom & Ireland (EU cloud)",
    options: [
      { code: "GB", label: "United Kingdom" },
      { code: "IE", label: "Ireland" },
    ],
  },
  {
    label: "Western Europe (EU cloud)",
    options: [
      { code: "DE", label: "Germany" },
      { code: "FR", label: "France" },
      { code: "IT", label: "Italy" },
      { code: "ES", label: "Spain" },
      { code: "PT", label: "Portugal" },
      { code: "NL", label: "Netherlands" },
      { code: "BE", label: "Belgium" },
      { code: "LU", label: "Luxembourg" },
      { code: "AT", label: "Austria" },
      { code: "CH", label: "Switzerland" },
    ],
  },
  {
    label: "Nordics (EU cloud)",
    options: [
      { code: "SE", label: "Sweden" },
      { code: "NO", label: "Norway" },
      { code: "FI", label: "Finland" },
      { code: "DK", label: "Denmark" },
      { code: "IS", label: "Iceland" },
    ],
  },
  {
    label: "Central & Eastern Europe (EU cloud)",
    options: [
      { code: "PL", label: "Poland" },
      { code: "CZ", label: "Czechia" },
      { code: "SK", label: "Slovakia" },
      { code: "HU", label: "Hungary" },
      { code: "SI", label: "Slovenia" },
      { code: "HR", label: "Croatia" },
      { code: "RO", label: "Romania" },
      { code: "BG", label: "Bulgaria" },
      { code: "GR", label: "Greece" },
      { code: "EE", label: "Estonia" },
      { code: "LV", label: "Latvia" },
      { code: "LT", label: "Lithuania" },
      { code: "MT", label: "Malta" },
    ],
  },
  {
    label: "Asia-Pacific & Middle East (EU cloud)",
    options: [
      { code: "AU", label: "Australia" },
      { code: "NZ", label: "New Zealand" },
      { code: "IL", label: "Israel" },
    ],
  },
  {
    label: "Africa (EU cloud)",
    options: [{ code: "ZA", label: "South Africa" }],
  },
  {
    label: "Other (EU cloud)",
    options: [
      { code: "RU", label: "Russia" },
      { code: "UA", label: "Ukraine" },
      { code: "RS", label: "Serbia" },
      { code: "BA", label: "Bosnia and Herzegovina" },
      { code: "AL", label: "Albania" },
      { code: "ME", label: "Montenegro" },
      { code: "MK", label: "North Macedonia" },
    ],
  },
];

/** Flat lookup: country code → human label. */
export const TANDEM_COUNTRY_LABELS: Readonly<Record<string, string>> =
  Object.fromEntries(
    TANDEM_COUNTRY_GROUPS.flatMap((g) =>
      g.options.map((o) => [o.code, o.label] as const)
    )
  );

export function isSupportedTandemCountry(code: string): boolean {
  return code in TANDEM_COUNTRY_LABELS;
}
