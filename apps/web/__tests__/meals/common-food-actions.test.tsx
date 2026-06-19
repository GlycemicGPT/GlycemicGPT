/**
 * Tests for the meal detail save-as / link-to common-food actions
 * (MealCommonFoodSection). Behavioural: save-as forwards the record + name to the
 * promotion endpoint (which uses corrected values + dedupes server-side) and
 * reflects the link locally; link attaches to a chosen baseline; both handle the
 * owner-scoped 404 gracefully. The never-dose baseline note is always present.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockSaveAs = jest.fn();
const mockLink = jest.fn();
const mockListCommon = jest.fn();
const mockGetRecord = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  ...jest.requireActual("@/lib/api"),
  saveRecordAsCommonFood: (...args: unknown[]) => mockSaveAs(...args),
  linkRecordToCommonFood: (...args: unknown[]) => mockLink(...args),
  listCommonFoods: (...args: unknown[]) => mockListCommon(...args),
  getFoodRecord: (...args: unknown[]) => mockGetRecord(...args),
}));

import { MealCommonFoodSection } from "../../src/components/meals/common-food-actions";
import { MealApiError, type CommonFood, type FoodRecord } from "@/lib/api";

function makeRecord(overrides: Partial<FoodRecord> = {}): FoodRecord {
  return {
    id: "rec-1",
    meal_timestamp: "2026-06-19T12:00:00Z",
    food_description: "Bowl of oatmeal",
    carbs_low: 40,
    carbs_high: 55,
    confidence: "medium",
    safety_qualifier: "Rough estimate — never dose from it.",
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
    created_at: "2026-06-19T12:00:01Z",
    ...overrides,
  };
}

function makeFood(overrides: Partial<CommonFood> = {}): CommonFood {
  return {
    id: "cf-1",
    name: "Oatmeal",
    carbs_low: 40,
    carbs_high: 55,
    nutrition_json: null,
    created_at: "2026-06-19T12:00:00Z",
    updated_at: "2026-06-19T12:00:00Z",
    ...overrides,
  };
}

describe("MealCommonFoodSection", () => {
  beforeEach(() => {
    mockSaveAs.mockReset();
    mockLink.mockReset();
    mockListCommon.mockReset();
    mockGetRecord.mockReset();
  });

  it("always shows the never-dose baseline note", () => {
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={jest.fn()} />);
    expect(screen.getByTestId("meal-common-food-note")).toHaveTextContent(
      /not a dose target/i
    );
  });

  it("saves the record as a common food, prefilling the meal title", async () => {
    const onUpdated = jest.fn();
    mockSaveAs.mockResolvedValue(makeFood({ id: "cf-9", name: "Bowl of oatmeal" }));
    // The promotion links the record server-side; the section re-fetches it.
    mockGetRecord.mockResolvedValue(makeRecord({ common_food_id: "cf-9" }));
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={onUpdated} />);

    fireEvent.click(screen.getByTestId("meal-save-as-common-food"));
    // Prefilled with the record's display title.
    expect((screen.getByTestId("meal-save-as-name") as HTMLInputElement).value).toBe(
      "Bowl of oatmeal"
    );
    fireEvent.click(screen.getByTestId("meal-save-as-submit"));

    await waitFor(() =>
      expect(mockSaveAs).toHaveBeenCalledWith("rec-1", "Bowl of oatmeal")
    );
    // Re-fetches from the source of truth and swaps in the now-linked record.
    await waitFor(() => expect(mockGetRecord).toHaveBeenCalledWith("rec-1"));
    expect(onUpdated).toHaveBeenCalledWith(
      expect.objectContaining({ id: "rec-1", common_food_id: "cf-9" })
    );
    expect(screen.getByTestId("meal-common-food-success")).toHaveTextContent(
      /Bowl of oatmeal/
    );
  });

  it("clamps the save-as name prefill to the server's 120-char cap", () => {
    const longDescription = "Grilled ".repeat(40).trim(); // well over 120 chars
    render(
      <MealCommonFoodSection
        record={makeRecord({ food_description: longDescription })}
        onUpdated={jest.fn()}
      />
    );

    fireEvent.click(screen.getByTestId("meal-save-as-common-food"));
    const input = screen.getByTestId("meal-save-as-name") as HTMLInputElement;
    expect(input.value.length).toBe(120);
  });

  it("still shows success even if the post-save refresh blips", async () => {
    const onUpdated = jest.fn();
    mockSaveAs.mockResolvedValue(makeFood({ id: "cf-9", name: "Oatmeal" }));
    mockGetRecord.mockRejectedValue(new MealApiError(502, "transient"));
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={onUpdated} />);

    fireEvent.click(screen.getByTestId("meal-save-as-common-food"));
    fireEvent.click(screen.getByTestId("meal-save-as-submit"));

    expect(
      await screen.findByTestId("meal-common-food-success")
    ).toBeInTheDocument();
    // No stale snapshot written back when the refresh failed.
    expect(onUpdated).not.toHaveBeenCalled();
  });

  it("disables save-as for a blank name, so no empty-name request is sent", async () => {
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={jest.fn()} />);

    fireEvent.click(screen.getByTestId("meal-save-as-common-food"));
    fireEvent.change(screen.getByTestId("meal-save-as-name"), {
      target: { value: "   " },
    });

    expect(screen.getByTestId("meal-save-as-submit")).toBeDisabled();
    fireEvent.click(screen.getByTestId("meal-save-as-submit"));
    expect(mockSaveAs).not.toHaveBeenCalled();
  });

  it("handles a save-as 404 (deleted / cross-user record) gracefully (IDOR)", async () => {
    mockSaveAs.mockRejectedValue(new MealApiError(404, "Food record not found."));
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={jest.fn()} />);

    fireEvent.click(screen.getByTestId("meal-save-as-common-food"));
    fireEvent.click(screen.getByTestId("meal-save-as-submit"));

    expect(await screen.findByTestId("meal-save-as-error")).toHaveTextContent(
      /no longer exists/i
    );
  });

  it("links the record to a chosen existing baseline", async () => {
    const onUpdated = jest.fn();
    mockListCommon.mockResolvedValue({
      common_foods: [
        makeFood({ id: "cf-1", name: "Oatmeal" }),
        makeFood({ id: "cf-2", name: "Greek yogurt" }),
      ],
      total: 2,
    });
    mockLink.mockResolvedValue(makeRecord({ common_food_id: "cf-2" }));
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={onUpdated} />);

    fireEvent.click(screen.getByTestId("meal-link-common-food"));
    const select = (await screen.findByTestId(
      "meal-link-select"
    )) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "cf-2" } });
    fireEvent.click(screen.getByTestId("meal-link-submit"));

    await waitFor(() =>
      expect(mockLink).toHaveBeenCalledWith("rec-1", "cf-2")
    );
    expect(onUpdated).toHaveBeenCalledWith(
      expect.objectContaining({ common_food_id: "cf-2" })
    );
  });

  it("shows an empty state in the link picker when there are no baselines", async () => {
    mockListCommon.mockResolvedValue({ common_foods: [], total: 0 });
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={jest.fn()} />);

    fireEvent.click(screen.getByTestId("meal-link-common-food"));
    expect(await screen.findByTestId("meal-link-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("meal-link-select")).not.toBeInTheDocument();
  });

  it("shows an error (not the empty state) when the baseline list fails to load", async () => {
    mockListCommon.mockRejectedValue(new MealApiError(502, "transient"));
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={jest.fn()} />);

    fireEvent.click(screen.getByTestId("meal-link-common-food"));
    expect(await screen.findByTestId("meal-link-error")).toBeInTheDocument();
    // A load failure must not masquerade as "you have no common foods".
    expect(screen.queryByTestId("meal-link-empty")).not.toBeInTheDocument();
    expect(screen.queryByTestId("meal-link-select")).not.toBeInTheDocument();
  });

  it("handles a link 404 (cross-user baseline) gracefully (IDOR)", async () => {
    mockListCommon.mockResolvedValue({
      common_foods: [makeFood({ id: "cf-1", name: "Oatmeal" })],
      total: 1,
    });
    mockLink.mockRejectedValue(new MealApiError(404, "Common food not found."));
    render(<MealCommonFoodSection record={makeRecord()} onUpdated={jest.fn()} />);

    fireEvent.click(screen.getByTestId("meal-link-common-food"));
    await screen.findByTestId("meal-link-select");
    fireEvent.click(screen.getByTestId("meal-link-submit"));

    expect(await screen.findByTestId("meal-link-error")).toHaveTextContent(
      /no longer exists/i
    );
  });

  it("shows the linked note when the record is already linked to a baseline", () => {
    render(
      <MealCommonFoodSection
        record={makeRecord({ common_food_id: "cf-1" })}
        onUpdated={jest.fn()}
      />
    );
    expect(screen.getByTestId("meal-common-food-linked")).toBeInTheDocument();
  });
});
