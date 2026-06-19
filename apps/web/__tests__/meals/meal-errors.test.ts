/**
 * Unit tests for the meal API error -> UX-state mapping. Mirrors the mobile
 * client's detail-substring contract.
 */

import { MealApiError } from "@/lib/api";
import { classifyMealError } from "@/lib/meal-errors";

describe("classifyMealError", () => {
  it("maps a 404 'not enabled' to a non-retryable feature-off state", () => {
    const info = classifyMealError(
      new MealApiError(404, "Meal intelligence is not enabled.")
    );
    expect(info.kind).toBe("feature_off");
    expect(info.retryable).toBe(false);
  });

  it("maps a 404 'AI provider' to a no-provider state pointing at Settings", () => {
    const info = classifyMealError(
      new MealApiError(404, "No AI provider configured.")
    );
    expect(info.kind).toBe("no_provider");
    expect(info.retryable).toBe(false);
    expect(info.settingsHref).toBe("/dashboard/settings/ai-provider");
  });

  it("maps a 422 'vision' to a vision-unavailable state", () => {
    const info = classifyMealError(
      new MealApiError(422, "Vision is not available on your current AI provider.")
    );
    expect(info.kind).toBe("vision_unavailable");
    expect(info.retryable).toBe(false);
    expect(info.settingsHref).toBe("/dashboard/settings/ai-provider");
  });

  it("maps an unverified-local-model 422 to a non-retryable model-not-certified state", () => {
    const info = classifyMealError(
      new MealApiError(
        422,
        "The local model 'llava' has not been verified to estimate meal carbs reliably enough, so photo estimates are turned off for it. Use a cloud AI provider."
      )
    );
    expect(info.kind).toBe("model_not_certified");
    expect(info.retryable).toBe(false);
    expect(info.settingsHref).toBe("/dashboard/settings/ai-provider");
    expect(info.message).toContain("has not been verified");
  });

  it("maps a generic 422 to a retryable estimate-failed state, surfacing the server detail", () => {
    const info = classifyMealError(
      new MealApiError(422, "Could not read a carbohydrate estimate from this photo.")
    );
    expect(info.kind).toBe("estimate_failed");
    expect(info.retryable).toBe(true);
    expect(info.message).toContain("carbohydrate estimate");
  });

  it("maps a plain 404 (record not found) to a non-retryable not-found state", () => {
    const info = classifyMealError(
      new MealApiError(404, "Food record not found.")
    );
    expect(info.kind).toBe("not_found");
    expect(info.retryable).toBe(false);
  });

  it.each([
    [413, "image_too_large"],
    [415, "unsupported_image"],
    [429, "rate_limited"],
    [502, "service_unavailable"],
    [400, "estimate_failed"],
  ])("maps HTTP %s to %s", (status, kind) => {
    expect(classifyMealError(new MealApiError(status, "")).kind).toBe(kind);
  });

  it("maps a non-API error to a retryable generic state", () => {
    const info = classifyMealError(new Error("boom"));
    expect(info.kind).toBe("generic");
    expect(info.retryable).toBe(true);
    expect(info.message).toBe("boom");
  });
});
