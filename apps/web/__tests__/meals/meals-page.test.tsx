/**
 * Tests for the Meals list page: renders records (range + qualifier + source
 * badge + identity indicator), empty state, the feature-off dead end (no raw
 * 404), and pagination. Behavioural assertions only -- never pins exact carbs.
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

const mockList = jest.fn();

jest.mock("@/lib/api", () => ({
  __esModule: true,
  ...jest.requireActual("@/lib/api"),
  listFoodRecords: (...args: unknown[]) => mockList(...args),
  // The photo is fetched lazily by MealPhoto; default to "no photo" so the
  // placeholder renders and these tests stay focused on the list behaviour.
  fetchFoodRecordPhotoObjectUrl: jest.fn(() =>
    Promise.reject(new Error("no photo"))
  ),
}));

import MealsPage from "../../src/app/dashboard/meals/page";
import { MealApiError, type FoodRecord } from "@/lib/api";

function makeRecord(overrides: Partial<FoodRecord> = {}): FoodRecord {
  return {
    id: "rec-1",
    meal_timestamp: "2026-06-19T12:00:00Z",
    food_description: "Bowl of oatmeal",
    carbs_low: 40,
    carbs_high: 55,
    confidence: "medium",
    safety_qualifier: "Rough estimate — an AI guess. Never dose from it.",
    nutrition_json: null,
    assumptions: null,
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
    grounding_source: null,
    grounding_source_url: null,
    grounding_trust_tier: null,
    nutrition_facts: null,
    comorbidity_nutrition: null,
    created_at: "2026-06-19T12:00:01Z",
    ...overrides,
  };
}

describe("Meals list page", () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  it("renders a record with carb range, source badge, identity indicator, and the safety qualifier", async () => {
    mockList.mockResolvedValue({
      records: [makeRecord({ identity_confirmed: true })],
      total: 1,
    });

    render(<MealsPage />);

    const card = await screen.findByTestId("meal-card");
    expect(card).toBeInTheDocument();
    expect(screen.getByTestId("meal-carb-range")).toHaveTextContent(/g carbs/);
    expect(screen.getByTestId("meal-source-badge")).toHaveTextContent(
      "AI estimate"
    );
    expect(screen.getByTestId("meal-identity-confirmed")).toBeInTheDocument();
    expect(screen.getByTestId("meal-safety-qualifier")).toHaveTextContent(
      /never dose/i
    );
    expect(card).toHaveAttribute("href", "/dashboard/meals/rec-1");
  });

  it("shows an empty state when there are no records", async () => {
    mockList.mockResolvedValue({ records: [], total: 0 });
    render(<MealsPage />);
    expect(await screen.findByTestId("meal-empty")).toBeInTheDocument();
  });

  it("renders a clear feature-off state (not a raw 404) when meal intelligence is disabled", async () => {
    mockList.mockRejectedValue(
      new MealApiError(404, "Meal intelligence is not enabled.")
    );
    render(<MealsPage />);
    expect(await screen.findByTestId("meal-feature-off")).toBeInTheDocument();
    expect(screen.queryByTestId("meal-card")).not.toBeInTheDocument();
  });

  it("paginates: Next requests the following offset", async () => {
    mockList.mockResolvedValue({
      records: [makeRecord()],
      total: 120,
    });
    render(<MealsPage />);

    await screen.findByTestId("meal-card");
    expect(screen.getByText(/Page 1 of 3/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() => {
      expect(mockList).toHaveBeenLastCalledWith(50, 50);
    });
  });
});
