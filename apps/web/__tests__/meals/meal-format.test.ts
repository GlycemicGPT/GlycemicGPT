/**
 * Unit tests for meal display formatting/derivation helpers.
 */

import {
  effectiveCarbRange,
  formatCarbRange,
  confidenceLabel,
  sourceMeta,
  mealTitle,
  macroEntries,
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
    grounding_source: null,
    grounding_source_url: null,
    grounding_trust_tier: null,
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

describe("macroEntries", () => {
  it("returns an empty list for null nutrition", () => {
    expect(macroEntries(null)).toEqual([]);
  });

  it("orders known macros and gram-suffixes them (calories unit-less)", () => {
    const entries = macroEntries({
      calories: 250.6,
      protein_grams: 12.4,
      fat_grams: 8,
    });
    expect(entries.map((e) => e.key)).toEqual([
      "protein_grams",
      "fat_grams",
      "calories",
    ]);
    expect(entries).toEqual([
      { key: "protein_grams", label: "Protein", value: "12 g" },
      { key: "fat_grams", label: "Fat", value: "8 g" },
      { key: "calories", label: "Calories", value: "251" },
    ]);
  });

  it("skips absent keys and passes unknown keys through with a humanised label", () => {
    const entries = macroEntries({ sugar_grams: 5 });
    expect(entries).toEqual([
      { key: "sugar_grams", label: "Sugar", value: "5 g" },
    ]);
  });

  it("title-cases each word of an unknown multi-word key", () => {
    expect(macroEntries({ added_sugar_grams: 9 })).toEqual([
      { key: "added_sugar_grams", label: "Added Sugar", value: "9 g" },
    ]);
  });
});
