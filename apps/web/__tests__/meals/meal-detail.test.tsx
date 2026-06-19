/**
 * Tests for the Meal detail page: renders range + empirical confidence + macros
 * with no dose element, the delete-confirm flow, and the owner-scoped not-found
 * state for a cross-user id.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("next/link", () => {
  const Link = ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  );
  Link.displayName = "Link";
  return Link;
});

const mockPush = jest.fn();
jest.mock("next/navigation", () => ({
  useParams: () => ({ id: "rec-1" }),
  useRouter: () => ({ push: mockPush }),
}));

const mockGet = jest.fn();
const mockDelete = jest.fn();
const mockCorrect = jest.fn();
const mockConfirm = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  ...jest.requireActual("@/lib/api"),
  getFoodRecord: (...args: unknown[]) => mockGet(...args),
  deleteFoodRecord: (...args: unknown[]) => mockDelete(...args),
  correctFoodRecord: (...args: unknown[]) => mockCorrect(...args),
  confirmFoodIdentity: (...args: unknown[]) => mockConfirm(...args),
  // MealPhoto fetches the photo lazily; default to "no photo" -> placeholder.
  fetchFoodRecordPhotoObjectUrl: jest.fn(() =>
    Promise.reject(new Error("no photo"))
  ),
}));

import MealDetailPage from "../../src/app/dashboard/meals/[id]/page";
import { MealApiError, type FoodRecord } from "@/lib/api";

function makeRecord(overrides: Partial<FoodRecord> = {}): FoodRecord {
  return {
    id: "rec-1",
    meal_timestamp: "2026-06-19T12:00:00Z",
    food_description: "Bowl of oatmeal",
    carbs_low: 40,
    carbs_high: 55,
    confidence: "medium",
    safety_qualifier: "Rough estimate — never dose from it.",
    nutrition_json: { protein_grams: 12, fat_grams: 8 },
    assumptions: "standard restaurant portion",
    source: "ai_estimate",
    corrected_carbs_low: null,
    corrected_carbs_high: null,
    corrected_nutrition_json: null,
    corrected_at: null,
    common_food_id: null,
    ai_model: "claude-sonnet-4-5",
    ai_provider: "anthropic",
    confirmed_food_name: null,
    identity_confirmed: false,
    suggested_identity: null,
    grounding_source: null,
    grounding_source_url: null,
    grounding_trust_tier: null,
    nutrition_facts: {
      portion: "standard restaurant portion",
      macros: [
        {
          key: "protein_grams",
          label: "Protein",
          value: 12,
          unit: "g",
          glucose_note: "Protein can nudge glucose up later, in the hours after a meal.",
        },
        {
          key: "fat_grams",
          label: "Fat",
          value: 8,
          unit: "g",
          glucose_note: "Fat can slow digestion, so glucose may rise later, hours after a meal.",
        },
      ],
      net_carbs: null,
      disclaimer:
        "These nutrition figures are rough AI estimates that describe the meal — never use it to dose or bolus.",
    },
    created_at: "2026-06-19T12:00:01Z",
    ...overrides,
  };
}

describe("Meal detail page", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockDelete.mockReset();
    mockCorrect.mockReset();
    mockConfirm.mockReset();
    mockPush.mockReset();
  });

  it("renders the carb range, empirical confidence band, and read-only macros with no dose element", async () => {
    mockGet.mockResolvedValue(makeRecord());
    render(<MealDetailPage />);

    expect(await screen.findByTestId("meal-carb-range")).toHaveTextContent(
      /g carbs/
    );
    expect(screen.getByTestId("meal-confidence")).toHaveTextContent(
      "Medium confidence"
    );
    expect(screen.getAllByTestId("meal-macro").length).toBe(2);
    // No dose/insulin element is ever presented (the safety qualifier warning aside).
    expect(screen.queryByText(/recommended (dose|bolus)/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/units of insulin/i)).not.toBeInTheDocument();
  });

  it("surfaces the assumed portion prominently as the primary sanity-check", async () => {
    mockGet.mockResolvedValue(makeRecord());
    render(<MealDetailPage />);

    const portion = await screen.findByTestId("meal-portion");
    expect(portion).toHaveTextContent("standard restaurant portion");
    expect(portion).toHaveTextContent(/does this match what you ate/i);
  });

  it("frames protein/fat as a later rise with no specific timing number", async () => {
    mockGet.mockResolvedValue(makeRecord());
    render(<MealDetailPage />);

    const notes = await screen.findAllByTestId("meal-macro-note");
    expect(notes.length).toBe(2);
    for (const note of notes) {
      expect(note.textContent ?? "").toMatch(/later/i);
      // AC2: no peak-timing number is stated.
      expect(note.textContent ?? "").not.toMatch(/\d/);
    }
    expect(screen.getByTestId("meal-nutrition-disclaimer")).toHaveTextContent(
      /never use it to dose or bolus/i
    );
  });

  it("keeps the never-dose disclaimer for a portion-only payload (no macros/net carbs)", async () => {
    mockGet.mockResolvedValue(
      makeRecord({
        nutrition_facts: {
          portion: "one bowl, about 1.5 cups",
          macros: [],
          net_carbs: null,
          disclaimer:
            "These nutrition figures are rough AI estimates that describe the meal — never use it to dose or bolus.",
        },
      })
    );
    render(<MealDetailPage />);

    expect(await screen.findByTestId("meal-portion")).toBeInTheDocument();
    // No macros/net carbs render, but the never-dose disclaimer must not vanish.
    expect(screen.queryByTestId("meal-macro")).not.toBeInTheDocument();
    expect(screen.getByTestId("meal-nutrition-disclaimer")).toHaveTextContent(
      /never use it to dose or bolus/i
    );
  });

  it("shows net carbs only behind the never-dose + count-total-carbs caveat", async () => {
    mockGet.mockResolvedValue(
      makeRecord({
        nutrition_facts: {
          portion: null,
          macros: [
            {
              key: "fiber_grams",
              label: "Fiber",
              value: 6,
              unit: "g",
              glucose_note: "Fiber slows and blunts the rise in glucose.",
            },
          ],
          net_carbs: {
            low: 34,
            high: 49,
            caveat:
              "Net carbs (total carbs minus fiber) is a rough estimate, not exact — the ADA recommends counting total carbs. AI estimate, often wrong — never use it to dose or bolus.",
          },
          disclaimer:
            "These nutrition figures are rough AI estimates that describe the meal — never use it to dose or bolus.",
        },
      })
    );
    render(<MealDetailPage />);

    expect(await screen.findByTestId("meal-net-carbs")).toHaveTextContent(
      "≈ 34–49 g"
    );
    const caveat = screen.getByTestId("meal-net-carbs-caveat");
    expect(caveat).toHaveTextContent(/ADA recommends counting total carbs/i);
    expect(caveat).toHaveTextContent(/never use it to dose or bolus/i);
  });

  it("shows the corrected band and the original AI estimate when corrected", async () => {
    mockGet.mockResolvedValue(
      makeRecord({
        source: "user_corrected",
        corrected_carbs_low: 30,
        corrected_carbs_high: 30,
        corrected_at: "2026-06-19T13:00:00Z",
      })
    );
    render(<MealDetailPage />);
    await screen.findByTestId("meal-carb-range");
    expect(screen.getByText(/You corrected this\. AI estimated/)).toBeInTheDocument();
  });

  it("deletes after confirmation and navigates back to the list", async () => {
    mockGet.mockResolvedValue(makeRecord());
    mockDelete.mockResolvedValue(undefined);
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);

    render(<MealDetailPage />);
    fireEvent.click(await screen.findByTestId("meal-delete"));

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith("rec-1");
    });
    expect(mockPush).toHaveBeenCalledWith("/dashboard/meals");
    confirmSpy.mockRestore();
  });

  it("does not delete when the confirmation is cancelled", async () => {
    mockGet.mockResolvedValue(makeRecord());
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);

    render(<MealDetailPage />);
    fireEvent.click(await screen.findByTestId("meal-delete"));

    expect(mockDelete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("renders an owner-scoped not-found state for a cross-user / missing id", async () => {
    mockGet.mockRejectedValue(new MealApiError(404, "Food record not found."));
    render(<MealDetailPage />);
    expect(await screen.findByTestId("meal-not-found")).toBeInTheDocument();
    expect(screen.queryByTestId("meal-carb-range")).not.toBeInTheDocument();
  });

  it("shows a fallback (no stale meal) on a retryable error", async () => {
    mockGet.mockRejectedValue(
      new MealApiError(502, "AI vision service is unreachable.")
    );
    render(<MealDetailPage />);
    expect(
      await screen.findByText(/temporarily unavailable/i)
    ).toBeInTheDocument();
    // The record state is cleared, so no stale meal content renders.
    expect(screen.queryByTestId("meal-carb-range")).not.toBeInTheDocument();
  });

  // --- carb correction ---

  it("corrects the carb range: shows the corrected band, retains the original, flips the source", async () => {
    mockGet.mockResolvedValue(makeRecord());
    mockCorrect.mockResolvedValue(
      makeRecord({
        source: "user_corrected",
        corrected_carbs_low: 30,
        corrected_carbs_high: 30,
        corrected_at: "2026-06-19T13:00:00Z",
      })
    );
    render(<MealDetailPage />);

    fireEvent.click(await screen.findByTestId("meal-correct-button"));
    // AC2: the editor states the corrected values never feed dosing math.
    expect(screen.getByTestId("meal-correct-decoupling")).toHaveTextContent(
      /never fed to IoB, treatment safety, or carb-ratio/i
    );
    fireEvent.change(screen.getByTestId("meal-correct-low"), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByTestId("meal-correct-high"), {
      target: { value: "30" },
    });
    fireEvent.click(screen.getByTestId("meal-correct-save"));

    await waitFor(() =>
      expect(mockCorrect).toHaveBeenCalledWith("rec-1", {
        corrected_carbs_low: 30,
        corrected_carbs_high: 30,
      })
    );
    // Refreshed in place: corrected band shown, source flipped, original retained.
    expect(await screen.findByTestId("meal-carb-range")).toHaveTextContent(
      "≈ 30 g carbs"
    );
    expect(screen.getByTestId("meal-source-badge")).toHaveTextContent(
      "You corrected this"
    );
    expect(screen.getByText(/AI estimated/)).toHaveTextContent(
      "≈ 40–55 g carbs"
    );
    // Two distinct actions: correcting carbs never confirms identity.
    expect(mockConfirm).not.toHaveBeenCalled();
  });

  it("rejects an inverted correction client-side, without any network call", async () => {
    mockGet.mockResolvedValue(makeRecord());
    render(<MealDetailPage />);

    fireEvent.click(await screen.findByTestId("meal-correct-button"));
    fireEvent.change(screen.getByTestId("meal-correct-low"), {
      target: { value: "50" },
    });
    fireEvent.change(screen.getByTestId("meal-correct-high"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByTestId("meal-correct-save"));

    expect(await screen.findByTestId("meal-correct-error")).toHaveTextContent(
      /low value must not exceed/i
    );
    expect(mockCorrect).not.toHaveBeenCalled();
  });

  it("handles a server-side out-of-range 422 gracefully and does not mutate the record", async () => {
    mockGet.mockResolvedValue(makeRecord());
    mockCorrect.mockRejectedValue(
      new MealApiError(422, "carbohydrate bound above 1000 g")
    );
    render(<MealDetailPage />);

    fireEvent.click(await screen.findByTestId("meal-correct-button"));
    fireEvent.change(screen.getByTestId("meal-correct-low"), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByTestId("meal-correct-high"), {
      target: { value: "40" },
    });
    fireEvent.click(screen.getByTestId("meal-correct-save"));

    expect(await screen.findByTestId("meal-correct-error")).toHaveTextContent(
      /between 0 and 1000/i
    );
    // A rejected correction never mutates the displayed estimate or its source.
    expect(screen.getByTestId("meal-carb-range")).toHaveTextContent(
      "≈ 40–55 g carbs"
    );
    expect(screen.getByTestId("meal-source-badge")).toHaveTextContent(
      "AI estimate"
    );
  });

  it("surfaces a 404 (deleted / cross-user) on correction without mutating the record (IDOR)", async () => {
    mockGet.mockResolvedValue(makeRecord());
    mockCorrect.mockRejectedValue(new MealApiError(404, "Food record not found."));
    render(<MealDetailPage />);

    fireEvent.click(await screen.findByTestId("meal-correct-button"));
    fireEvent.change(screen.getByTestId("meal-correct-low"), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByTestId("meal-correct-high"), {
      target: { value: "40" },
    });
    fireEvent.click(screen.getByTestId("meal-correct-save"));

    expect(await screen.findByTestId("meal-correct-error")).toHaveTextContent(
      /no longer exists/i
    );
    expect(screen.getByTestId("meal-carb-range")).toHaveTextContent(
      "≈ 40–55 g carbs"
    );
  });

  // --- identity confirmation + grounding gate ---

  it("keeps an unconfirmed record vision-only with no authoritative citation", async () => {
    mockGet.mockResolvedValue(
      makeRecord({ identity_confirmed: false, grounding_source: null })
    );
    render(<MealDetailPage />);

    expect(
      await screen.findByTestId("meal-grounding-vision-only")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("meal-grounding-grounded")
    ).not.toBeInTheDocument();
    // Confirm-identity and correct-carbs are two distinct actions on the surface.
    expect(screen.getByTestId("meal-identity-confirm")).toBeInTheDocument();
    expect(screen.getByTestId("meal-correct-button")).toBeInTheDocument();
  });

  it("confirm-identity opens grounding: vision-only before, attribution after", async () => {
    mockGet.mockResolvedValue(makeRecord());
    mockConfirm.mockResolvedValue(
      makeRecord({
        identity_confirmed: true,
        confirmed_food_name: "Bowl of oatmeal",
        source: "external_grounded",
        grounding_source: "USDA FoodData Central",
        grounding_source_url: "https://fdc.nal.usda.gov/",
        grounding_trust_tier: "AUTHORITATIVE",
      })
    );
    render(<MealDetailPage />);

    // Before: vision-only, no authoritative citation.
    expect(
      await screen.findByTestId("meal-grounding-vision-only")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("meal-grounding-grounded")
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("meal-identity-confirm"));

    await waitFor(() =>
      expect(mockConfirm).toHaveBeenCalledWith("rec-1", "Bowl of oatmeal")
    );
    // After: refreshes to show the grounding attribution + a safe outbound link.
    expect(
      await screen.findByTestId("meal-grounding-grounded")
    ).toHaveTextContent("USDA FoodData Central");
    const link = screen.getByTestId("meal-grounding-link");
    expect(link).toHaveAttribute("href", "https://fdc.nal.usda.gov/");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
    expect(
      screen.queryByTestId("meal-grounding-vision-only")
    ).not.toBeInTheDocument();
    // Two distinct actions: confirming identity never corrects carbs.
    expect(mockCorrect).not.toHaveBeenCalled();
  });

  it("corrects the identity to a different name via the editor", async () => {
    mockGet.mockResolvedValue(makeRecord());
    mockConfirm.mockResolvedValue(
      makeRecord({ identity_confirmed: true, confirmed_food_name: "Steel-cut oats" })
    );
    render(<MealDetailPage />);

    fireEvent.click(await screen.findByTestId("meal-identity-correct"));
    fireEvent.change(screen.getByTestId("meal-identity-input"), {
      target: { value: "Steel-cut oats" },
    });
    fireEvent.click(screen.getByTestId("meal-identity-save"));

    await waitFor(() =>
      expect(mockConfirm).toHaveBeenCalledWith("rec-1", "Steel-cut oats")
    );
  });

  it("pre-fills and surfaces an own-history suggested identity", async () => {
    mockGet.mockResolvedValue(makeRecord({ suggested_identity: "Saved oatmeal" }));
    mockConfirm.mockResolvedValue(
      makeRecord({ identity_confirmed: true, confirmed_food_name: "Saved oatmeal" })
    );
    render(<MealDetailPage />);

    expect(await screen.findByTestId("meal-identity-prompt")).toHaveTextContent(
      /Saved oatmeal/
    );
    fireEvent.click(screen.getByTestId("meal-identity-confirm"));
    await waitFor(() =>
      expect(mockConfirm).toHaveBeenCalledWith("rec-1", "Saved oatmeal")
    );
  });
});
