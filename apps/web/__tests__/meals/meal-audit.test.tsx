/**
 * Tests for the "How this was estimated" audit / provenance panel.
 *
 * Behavioral assertions only: the panel surfaces the per-sample reads, the
 * EMPIRICAL dispersion, and the precedence decision; renders the grounding
 * citation only when the record is grounded (identity-gated, per Story 50.W2);
 * never shows the model's self-reported confidence; carries the never-dose
 * qualifier; presents no dose/recommendation; and degrades gracefully on a 404
 * (no audit / cross-user) without leaking another record's data.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

const mockGetAudit = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  ...jest.requireActual("@/lib/api"),
  getFoodRecordAudit: (...args: unknown[]) => mockGetAudit(...args),
}));

import { MealAuditPanel } from "@/components/meals/meal-audit";
import {
  MealApiError,
  type FoodRecord,
  type FoodRecordAudit,
} from "@/lib/api";

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
    ai_model: "claude-sonnet-4-5",
    ai_provider: "anthropic",
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

function makeAudit(overrides: Partial<FoodRecordAudit> = {}): FoodRecordAudit {
  return {
    food_record_id: "rec-1",
    samples: [
      { carbs_low: 40, carbs_high: 50, identity: "oatmeal with berries", parse_ok: true },
      { carbs_low: 45, carbs_high: 60, identity: "porridge", parse_ok: true },
      { carbs_low: null, carbs_high: null, identity: null, parse_ok: false },
    ],
    dispersion: {
      confidence: "medium",
      coefficient_of_variation: 0.12,
      samples_requested: 3,
      samples_used: 2,
      identity_agreement: true,
      distinct_identities: ["oatmeal with berries", "porridge"],
      wide_spread: false,
    },
    precedence: {
      outcome: "vision_only",
      chosen_source: "vision-only",
      trust_tier: null,
      source_url: null,
      identity_used: null,
      identity_confirmed: false,
      reason: "Identity not yet confirmed; estimate is vision-only.",
      ladder: [
        "own-history corrected",
        "USDA FoodData Central",
        "Open Food Facts",
        "vision-only",
      ],
    },
    created_at: "2026-06-19T12:00:00Z",
    updated_at: "2026-06-19T12:00:00Z",
    ...overrides,
  };
}

describe("MealAuditPanel", () => {
  beforeEach(() => {
    mockGetAudit.mockReset();
  });

  it("renders collapsed with the never-dose qualifier and no detail until expanded", () => {
    render(<MealAuditPanel record={makeRecord()} />);

    expect(screen.getByTestId("meal-audit-panel")).toBeInTheDocument();
    expect(screen.getByTestId("meal-audit-safety-qualifier")).toHaveTextContent(
      /never dose/i
    );
    // Lazy: nothing is fetched or shown until the user opens it.
    expect(mockGetAudit).not.toHaveBeenCalled();
    expect(screen.queryByTestId("meal-audit-details")).not.toBeInTheDocument();
  });

  it("expands to show per-sample reads, empirical dispersion, and the precedence decision", async () => {
    mockGetAudit.mockResolvedValue(makeAudit());
    render(<MealAuditPanel record={makeRecord()} />);

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));

    await waitFor(() => expect(mockGetAudit).toHaveBeenCalledWith("rec-1"));

    // Per-sample reads (one row per sample, including the unreadable one).
    const samples = await screen.findAllByTestId("meal-audit-sample");
    expect(samples).toHaveLength(3);
    expect(samples[0]).toHaveTextContent("oatmeal with berries");
    expect(samples[0]).toHaveTextContent("≈ 40–50 g carbs");
    expect(samples[2]).toHaveTextContent(/unreadable/i);

    // Empirical dispersion (the confidence is the dispersion-derived band).
    const dispersion = screen.getByTestId("meal-audit-dispersion");
    expect(dispersion).toHaveTextContent("Medium confidence");
    expect(dispersion).toHaveTextContent("12%");
    expect(dispersion).toHaveTextContent("2 of 3");

    // Precedence decision + the ladder as it stood.
    const precedence = screen.getByTestId("meal-audit-precedence");
    expect(precedence).toHaveTextContent(/Vision-only estimate/i);
    expect(precedence).toHaveTextContent("USDA FoodData Central");
  });

  it("renders the grounding citation (with a safe outbound link) only when grounded", async () => {
    mockGetAudit.mockResolvedValue(
      makeAudit({
        precedence: {
          outcome: "grounded",
          chosen_source: "USDA FoodData Central",
          trust_tier: "AUTHORITATIVE",
          source_url: "https://fdc.nal.usda.gov/",
          identity_used: "Bowl of oatmeal",
          identity_confirmed: true,
          reason: null,
          ladder: ["own-history corrected", "USDA FoodData Central", "vision-only"],
        },
      })
    );
    render(
      <MealAuditPanel
        record={makeRecord({
          identity_confirmed: true,
          confirmed_food_name: "Bowl of oatmeal",
          source: "external_grounded",
          grounding_source: "USDA FoodData Central",
          grounding_source_url: "https://fdc.nal.usda.gov/",
          grounding_trust_tier: "AUTHORITATIVE",
        })}
      />
    );

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));

    const citation = await screen.findByTestId("meal-audit-grounding");
    expect(citation).toHaveTextContent("USDA FoodData Central");
    const link = within(citation).getByTestId("meal-audit-grounding-link");
    expect(link).toHaveAttribute("href", "https://fdc.nal.usda.gov/");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
    // The ladder marks the chosen source as used.
    expect(screen.getByTestId("meal-audit-precedence")).toHaveTextContent(
      /USDA FoodData Central — used/i
    );
  });

  it("withholds the grounding citation for an unconfirmed identity even if a source is present (W2 gate)", async () => {
    mockGetAudit.mockResolvedValue(makeAudit());
    render(
      <MealAuditPanel
        record={makeRecord({
          identity_confirmed: false,
          grounding_source: "USDA FoodData Central",
          grounding_source_url: "https://fdc.nal.usda.gov/",
          grounding_trust_tier: "AUTHORITATIVE",
        })}
      />
    );

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));
    await screen.findByTestId("meal-audit-details");
    // Not identity-confirmed -> no authoritative citation, no outbound link.
    expect(screen.queryByTestId("meal-audit-grounding")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("meal-audit-grounding-link")
    ).not.toBeInTheDocument();
  });

  it("never surfaces the model's self-reported confidence (only the empirical band)", async () => {
    // A stray self-reported field on the wire must never reach the UI.
    const auditWithLeak = makeAudit();
    (auditWithLeak.samples[0] as unknown as Record<string, unknown>)[
      "self_reported_confidence"
    ] = "model-says-99-percent";
    mockGetAudit.mockResolvedValue(auditWithLeak);
    render(<MealAuditPanel record={makeRecord()} />);

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));
    await screen.findByTestId("meal-audit-details");

    expect(screen.queryByText(/model-says-99-percent/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/self-reported/i)).not.toBeInTheDocument();
    // The empirical dispersion confidence is what's shown.
    expect(screen.getByTestId("meal-audit-dispersion")).toHaveTextContent(
      "Medium confidence"
    );
  });

  it("presents no dose or recommendation element", async () => {
    mockGetAudit.mockResolvedValue(makeAudit());
    render(<MealAuditPanel record={makeRecord()} />);

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));
    await screen.findByTestId("meal-audit-details");

    expect(screen.queryByText(/units of insulin/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/recommended (dose|bolus)/i)
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/take \d/i)).not.toBeInTheDocument();
  });

  it("shows a benign unavailable state on a 404 (no audit / cross-user) without leaking", async () => {
    mockGetAudit.mockRejectedValue(new MealApiError(404, "Audit trail not found"));
    render(<MealAuditPanel record={makeRecord()} />);

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));

    expect(
      await screen.findByTestId("meal-audit-unavailable")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("meal-audit-details")).not.toBeInTheDocument();
    // No scary error banner for the benign "no trail recorded" case.
    expect(screen.queryByTestId("meal-audit-error")).not.toBeInTheDocument();
  });

  it("surfaces a transient failure and retries on a second click", async () => {
    mockGetAudit
      .mockRejectedValueOnce(new MealApiError(502, "upstream down"))
      .mockResolvedValueOnce(makeAudit());
    render(<MealAuditPanel record={makeRecord()} />);

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));
    expect(await screen.findByTestId("meal-audit-error")).toBeInTheDocument();
    // Stays collapsed so the button can retry.
    expect(screen.queryByTestId("meal-audit-details")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));
    expect(await screen.findByTestId("meal-audit-details")).toBeInTheDocument();
    expect(screen.queryByTestId("meal-audit-error")).not.toBeInTheDocument();
    expect(mockGetAudit).toHaveBeenCalledTimes(2);
  });

  it("collapses without refetching once loaded", async () => {
    mockGetAudit.mockResolvedValue(makeAudit());
    render(<MealAuditPanel record={makeRecord()} />);

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));
    await screen.findByTestId("meal-audit-details");

    fireEvent.click(screen.getByTestId("meal-audit-toggle")); // collapse
    expect(screen.queryByTestId("meal-audit-details")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("meal-audit-toggle")); // re-open
    expect(await screen.findByTestId("meal-audit-details")).toBeInTheDocument();
    expect(mockGetAudit).toHaveBeenCalledTimes(1);
  });

  it("invalidates the cached audit when the record is swapped in place (e.g. identity confirmed)", async () => {
    mockGetAudit
      .mockResolvedValueOnce(makeAudit()) // vision-only trail
      .mockResolvedValueOnce(
        makeAudit({
          precedence: {
            outcome: "grounded",
            chosen_source: "USDA FoodData Central",
            trust_tier: "AUTHORITATIVE",
            source_url: "https://fdc.nal.usda.gov/",
            identity_used: "Bowl of oatmeal",
            identity_confirmed: true,
            reason: null,
            ladder: ["own-history corrected", "USDA FoodData Central", "vision-only"],
          },
        })
      );
    const { rerender } = render(<MealAuditPanel record={makeRecord()} />);

    fireEvent.click(screen.getByTestId("meal-audit-toggle"));
    expect(await screen.findByTestId("meal-audit-precedence")).toHaveTextContent(
      /Vision-only estimate/i
    );

    // The detail view confirms identity and swaps the record in place.
    rerender(
      <MealAuditPanel
        record={makeRecord({
          identity_confirmed: true,
          confirmed_food_name: "Bowl of oatmeal",
          source: "external_grounded",
          grounding_source: "USDA FoodData Central",
        })}
      />
    );

    // Stale trail dropped + collapsed; re-opening refetches the current decision.
    expect(screen.queryByTestId("meal-audit-details")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("meal-audit-toggle"));
    expect(await screen.findByTestId("meal-audit-precedence")).toHaveTextContent(
      /Grounded against USDA FoodData Central/i
    );
    expect(mockGetAudit).toHaveBeenCalledTimes(2);
  });
});
