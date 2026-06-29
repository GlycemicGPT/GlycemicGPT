/**
 * Guards the web insulin catalog (apps/web/src/lib/insulin.ts) against the kind
 * of drift the backend already guards in test_insulin_config.py: every dropdown
 * label except "custom" must have a fallback preset, every preset must have a
 * label, and every preset must be savable (within the PATCH validator's DIA/onset
 * bounds, so the auto-filled value never 422s offline). "custom" must stay last
 * so it renders at the bottom of the dropdown.
 */

import { FALLBACK_PRESETS, INSULIN_LABELS, INSULIN_LIMITS } from "@/lib/insulin";

describe("insulin catalog parity", () => {
  it("gives every preset a dropdown label", () => {
    for (const key of Object.keys(FALLBACK_PRESETS)) {
      expect(INSULIN_LABELS).toHaveProperty(key);
    }
  });

  it("gives every non-custom label a preset, and only custom has none", () => {
    const labelsWithoutPreset = Object.keys(INSULIN_LABELS).filter(
      (key) => !(key in FALLBACK_PRESETS)
    );
    expect(labelsWithoutPreset).toEqual(["custom"]);
  });

  it("keeps every preset within the savable DIA/onset bounds", () => {
    for (const [key, preset] of Object.entries(FALLBACK_PRESETS)) {
      expect(preset.dia_hours).toBeGreaterThanOrEqual(INSULIN_LIMITS.diaMinHours);
      expect(preset.dia_hours).toBeLessThanOrEqual(INSULIN_LIMITS.diaMaxHours);
      expect(preset.onset_minutes).toBeGreaterThanOrEqual(INSULIN_LIMITS.onsetMinMinutes);
      expect(preset.onset_minutes).toBeLessThanOrEqual(INSULIN_LIMITS.onsetMaxMinutes);
      // Touch `key` so a failure names the offending insulin.
      expect(key).toBeTruthy();
    }
  });

  it("renders custom last in the dropdown", () => {
    const keys = Object.keys(INSULIN_LABELS);
    expect(keys[keys.length - 1]).toBe("custom");
  });
});
