/**
 * Map a food-records API failure to a user-facing UX state.
 *
 * Mirrors the mobile client's detail-substring contract (MealRepository.mapError)
 * so the web surfaces the same distinctions: a missing-provider / vision-
 * unavailable / feature-off response is a non-retryable "dead end" that points
 * the user at Settings, while transient failures are retryable. None of these
 * strings are carb/nutrition descriptive copy -- they steer the user away from
 * (never toward) acting on a number.
 */

import { MealApiError } from "./api";

export type MealErrorKind =
  | "feature_off"
  | "no_provider"
  | "vision_unavailable"
  | "model_not_certified"
  | "estimate_failed"
  | "image_too_large"
  | "unsupported_image"
  | "rate_limited"
  | "service_unavailable"
  | "not_found"
  | "generic";

export interface MealErrorInfo {
  kind: MealErrorKind;
  title: string;
  message: string;
  /**
   * Retryable failures render as a dismissible inline banner; non-retryable
   * ones (feature off, no provider, vision unavailable) render as a blocking
   * card that points the user to Settings.
   */
  retryable: boolean;
  /** When set, the card offers a link to this settings route. */
  settingsHref?: string;
}

const AI_PROVIDER_HREF = "/dashboard/settings/ai-provider";

export function classifyMealError(err: unknown): MealErrorInfo {
  if (err instanceof MealApiError) {
    const { status } = err;
    const detail = err.detail.toLowerCase();

    if (status === 404) {
      if (detail.includes("not enabled")) {
        return {
          kind: "feature_off",
          title: "Meal logging isn't turned on",
          message:
            "Meal intelligence is turned off for this server. Ask your server admin to enable it.",
          retryable: false,
        };
      }
      if (detail.includes("ai provider")) {
        return {
          kind: "no_provider",
          title: "No AI provider configured",
          message:
            "Set up an AI provider in Settings to estimate carbs from a photo.",
          retryable: false,
          settingsHref: AI_PROVIDER_HREF,
        };
      }
      return {
        kind: "not_found",
        title: "Meal not found",
        message: err.detail || "That meal could not be found.",
        retryable: false,
      };
    }

    if (status === 422) {
      if (detail.includes("vision")) {
        return {
          kind: "vision_unavailable",
          title: "Vision isn't available on your AI provider",
          message:
            "Carb estimates from photos need a vision-capable AI provider. Switch to one in Settings, then try again.",
          retryable: false,
          settingsHref: AI_PROVIDER_HREF,
        };
      }
      // An unverified local vision model is refused outright (the model is gated
      // off, so retrying can't succeed). Surface the server's actionable message
      // and point at Settings rather than implying a clearer photo would help.
      if (detail.includes("not been verified") || detail.includes("turned off for it")) {
        return {
          kind: "model_not_certified",
          title: "This model can't estimate meal carbs",
          message:
            err.detail ||
            "The configured local AI model isn't verified for meal photos. Switch to a cloud AI provider in Settings.",
          retryable: false,
          settingsHref: AI_PROVIDER_HREF,
        };
      }
      // Estimate rejected, out-of-range, etc. -- a different photo may succeed.
      return {
        kind: "estimate_failed",
        title: "Couldn't estimate carbs",
        message:
          err.detail ||
          "We couldn't read a carb estimate from that photo. Try a clearer one.",
        retryable: true,
      };
    }

    if (status === 413) {
      return {
        kind: "image_too_large",
        title: "That photo is too large",
        message: "Try a smaller photo.",
        retryable: true,
      };
    }
    if (status === 415) {
      return {
        kind: "unsupported_image",
        title: "Unsupported image type",
        message: "Use a JPEG, PNG, or WebP photo.",
        retryable: true,
      };
    }
    if (status === 429) {
      return {
        kind: "rate_limited",
        title: "Too many uploads",
        message: "You're uploading too fast. Wait a moment and try again.",
        retryable: true,
      };
    }
    if (status === 502) {
      return {
        kind: "service_unavailable",
        title: "AI vision service unavailable",
        message:
          "The AI vision service is temporarily unavailable. Try again shortly.",
        retryable: true,
      };
    }
    if (status === 400) {
      return {
        kind: "estimate_failed",
        title: "Couldn't estimate carbs",
        message: "We couldn't process that photo. Try a different one.",
        retryable: true,
      };
    }

    return {
      kind: "generic",
      title: "Something went wrong",
      message: err.detail || "Please try again.",
      retryable: true,
    };
  }

  return {
    kind: "generic",
    title: "Something went wrong",
    message: err instanceof Error ? err.message : "Please try again.",
    retryable: true,
  };
}
