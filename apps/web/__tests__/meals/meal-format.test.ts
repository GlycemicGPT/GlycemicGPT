/**
 * Unit tests for meal display formatting/derivation helpers.
 */

import {
  effectiveCarbRange,
  formatCarbRange,
  formatCoefficientOfVariation,
  confidenceLabel,
  sourceMeta,
  mealTitle,
  formatMacroValue,
  formatNetCarbs,
  parseCarbInputs,
  validateCarbBounds,
  prefillIdentity,
  isGrounded,
  isSafeHttpUrl,
} from "@/lib/meal-format";
import type { FoodRecord } from "@/lib/api";

function makeRecord(overrides: Partial<FoodRecord> = {}): FoodRecord {
  return {
    id: "rec-1",
    meal_timestamp: "2026-06-19T12:00:00Z",
    food_description: "Bowl of oatmeal",
    carbs_low: 40,
    carbs_high: 55,
    confidence: "medium",
    safety_qualifier: "Rough estimate — never dose.",
    nutrition_json: null,
    source: "ai_estimate",
    corrected_carbs_low: null,
    corrected_carbs_high: null,
    corrected_nutrition_json: null,
    corrected_at: null,
    common_food_id: null,
    ai_model: null,
    ai_provider: null,
    confirmed_food_name: null,
    identity_confirmed: false,
    suggested_identity: null,
    assumptions: null,
    grounding_source: null,
    grounding_source_url: null,
    grounding_trust_tier: null,
    nutrition_facts: null,
    created_at: "2026-06-19T12:00:01Z",
    ...overrides,
  };
}

describe("formatCarbRange", () => {
  it("renders a band as ≈ low–high g carbs", () => {
    expect(formatCarbRange(40, 55)).toBe("≈ 40–55 g carbs");
  });

  it("collapses to a single value when the rounded endpoints coincide", () => {
    expect(formatCarbRange(50.1, 50.4)).toBe("≈ 50 g carbs");
  });

  it("rounds to whole grams (no false precision)", () => {
    expect(formatCarbRange(40.6, 54.5)).toBe("≈ 41–55 g carbs");
  });
});

describe("formatCoefficientOfVariation", () => {
  it("renders a fraction as a whole-percent spread", () => {
    expect(formatCoefficientOfVariation(0.123)).toBe("12%");
  });

  it("rounds to the nearest whole percent (no false precision)", () => {
    expect(formatCoefficientOfVariation(0.156)).toBe("16%");
  });

  it("renders zero spread as 0%", () => {
    expect(formatCoefficientOfVariation(0)).toBe("0%");
  });

  it("returns null when no CV was recorded", () => {
    expect(formatCoefficientOfVariation(null)).toBeNull();
    expect(formatCoefficientOfVariation(undefined)).toBeNull();
    expect(formatCoefficientOfVariation(NaN)).toBeNull();
  });
});

describe("effectiveCarbRange", () => {
  it("uses the AI estimate when not corrected", () => {
    expect(effectiveCarbRange(makeRecord())).toEqual({
      low: 40,
      high: 55,
      corrected: false,
    });
  });

  it("prefers the corrected band when both values are present", () => {
    const record = makeRecord({
      corrected_carbs_low: 30,
      corrected_carbs_high: 45,
      source: "user_corrected",
    });
    expect(effectiveCarbRange(record)).toEqual({
      low: 30,
      high: 45,
      corrected: true,
    });
  });
});

describe("confidenceLabel", () => {
  it.each([
    ["low", "Low confidence"],
    ["medium", "Medium confidence"],
    ["high", "High confidence"],
    ["HIGH", "High confidence"],
  ])("labels %s as %s", (input, expected) => {
    expect(confidenceLabel(input)).toBe(expected);
  });

  it("handles a null/unknown band", () => {
    expect(confidenceLabel(null)).toBe("Confidence unavailable");
    expect(confidenceLabel("garbage")).toBe("Confidence unavailable");
  });
});

describe("sourceMeta", () => {
  it("labels the known sources", () => {
    expect(sourceMeta("ai_estimate").label).toBe("AI estimate");
    expect(sourceMeta("user_corrected").label).toBe("You corrected this");
    expect(sourceMeta("external_grounded").label).toBe("Grounded");
  });

  it("falls back to the raw value for an unknown source", () => {
    expect(sourceMeta("mystery").label).toBe("mystery");
  });
});

describe("mealTitle", () => {
  it("prefers the confirmed identity", () => {
    expect(
      mealTitle(makeRecord({ confirmed_food_name: "Steel-cut oats" }))
    ).toBe("Steel-cut oats");
  });

  it("falls back to the AI description then to a placeholder", () => {
    expect(mealTitle(makeRecord({ food_description: "Pizza" }))).toBe("Pizza");
    expect(
      mealTitle(makeRecord({ food_description: null, confirmed_food_name: null }))
    ).toBe("Unidentified meal");
  });
});

describe("formatMacroValue", () => {
  it("renders grams and kilocalories with whole-unit rounding", () => {
    expect(formatMacroValue(12.4, "g")).toBe("12 g");
    expect(formatMacroValue(250.6, "kcal")).toBe("251 kcal");
  });
});

describe("formatNetCarbs", () => {
  it("renders a band as ≈ low–high g", () => {
    expect(formatNetCarbs(34, 49)).toBe("≈ 34–49 g");
  });

  it("collapses to a single value when the rounded endpoints coincide", () => {
    expect(formatNetCarbs(26, 26)).toBe("≈ 26 g");
  });
});

describe("validateCarbBounds", () => {
  it("accepts an in-range, well-ordered band", () => {
    expect(validateCarbBounds(30, 45)).toBeNull();
    expect(validateCarbBounds(0, 1000)).toBeNull();
  });

  it("rejects an inverted band", () => {
    expect(validateCarbBounds(50, 10)).toMatch(/low value must not exceed/i);
  });

  it("rejects negative and over-cap values", () => {
    expect(validateCarbBounds(-1, 10)).toMatch(/can't be negative/i);
    expect(validateCarbBounds(10, 1001)).toMatch(/can't exceed 1000/i);
  });

  it("rejects NaN input", () => {
    expect(validateCarbBounds(NaN, 10)).toMatch(/enter a number/i);
  });
});

describe("parseCarbInputs", () => {
  it("parses two numeric strings into an ordered range", () => {
    expect(parseCarbInputs("30", "45")).toEqual({ ok: true, low: 30, high: 45 });
  });

  it("rejects blank input before any network call", () => {
    expect(parseCarbInputs("", "45")).toEqual({
      ok: false,
      reason: "Enter both carb values in grams.",
    });
  });

  it("rejects non-numeric input", () => {
    expect(parseCarbInputs("abc", "45")).toMatchObject({ ok: false });
  });

  it("rejects an inverted range with the shared bounds copy", () => {
    expect(parseCarbInputs("50", "10")).toMatchObject({
      ok: false,
      reason: expect.stringMatching(/low value must not exceed/i),
    });
  });
});

describe("prefillIdentity", () => {
  it("prefers a fresh own-history suggestion", () => {
    expect(
      prefillIdentity(
        makeRecord({
          suggested_identity: "Saved oatmeal",
          confirmed_food_name: "Confirmed thing",
          food_description: "AI desc",
        })
      )
    ).toBe("Saved oatmeal");
  });

  it("falls back to the confirmed name, then the AI description", () => {
    expect(
      prefillIdentity(
        makeRecord({ suggested_identity: null, confirmed_food_name: "Confirmed thing" })
      )
    ).toBe("Confirmed thing");
    expect(
      prefillIdentity(
        makeRecord({
          suggested_identity: null,
          confirmed_food_name: null,
          food_description: "AI desc",
        })
      )
    ).toBe("AI desc");
  });

  it("is empty when nothing is known", () => {
    expect(
      prefillIdentity(
        makeRecord({
          suggested_identity: null,
          confirmed_food_name: null,
          food_description: null,
        })
      )
    ).toBe("");
  });
});

describe("isGrounded", () => {
  it("is false for a vision-only record (no grounding source)", () => {
    expect(
      isGrounded(makeRecord({ identity_confirmed: true, grounding_source: null }))
    ).toBe(false);
    expect(
      isGrounded(makeRecord({ identity_confirmed: true, grounding_source: "  " }))
    ).toBe(false);
  });

  it("is true once a confirmed identity has been grounded by an external source", () => {
    expect(
      isGrounded(
        makeRecord({
          identity_confirmed: true,
          grounding_source: "USDA FoodData Central",
        })
      )
    ).toBe(true);
  });

  it("requires identity confirmation: a stale source without confirmation is not grounded", () => {
    expect(
      isGrounded(
        makeRecord({
          identity_confirmed: false,
          grounding_source: "USDA FoodData Central",
        })
      )
    ).toBe(false);
  });
});

describe("isSafeHttpUrl", () => {
  it("accepts http(s) URLs", () => {
    expect(isSafeHttpUrl("https://fdc.nal.usda.gov/")).toBe(true);
    expect(isSafeHttpUrl("http://example.com")).toBe(true);
  });

  it("rejects non-http schemes and junk", () => {
    expect(isSafeHttpUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeHttpUrl("data:text/html,<script>")).toBe(false);
    expect(isSafeHttpUrl("not a url")).toBe(false);
    expect(isSafeHttpUrl(null)).toBe(false);
    expect(isSafeHttpUrl("")).toBe(false);
  });
});
