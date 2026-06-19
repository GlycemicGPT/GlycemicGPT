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
jest.mock("@/lib/api", () => ({
  __esModule: true,
  ...jest.requireActual("@/lib/api"),
  getFoodRecord: (...args: unknown[]) => mockGet(...args),
  deleteFoodRecord: (...args: unknown[]) => mockDelete(...args),
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
});
