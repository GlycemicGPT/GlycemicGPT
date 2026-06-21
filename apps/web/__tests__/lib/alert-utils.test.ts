/**
 * formatAlertSummary renders the alert glucose line from the STRUCTURED numeric
 * fields in the active unit (never the frozen mg/dL message string, which goes
 * stale after a unit-preference change). IoB warnings describe insulin units and
 * are returned verbatim — never glucose-converted.
 */

import { formatAlertSummary } from "@/lib/alert-utils";

type SummaryArg = Parameters<typeof formatAlertSummary>[0];

function makeAlert(overrides: Partial<SummaryArg> = {}): SummaryArg {
  return {
    alert_type: "low_urgent",
    current_value: 70,
    predicted_value: null,
    prediction_minutes: null,
    message: "Urgent low glucose: 70 mg/dL (threshold: 70)",
    ...overrides,
  };
}

describe("formatAlertSummary", () => {
  it("renders a current-value glucose alert in mg/dL", () => {
    expect(formatAlertSummary(makeAlert(), "mgdl")).toBe(
      "Urgent Low Glucose: 70 mg/dL"
    );
  });

  it("converts the current value to mmol/L", () => {
    expect(formatAlertSummary(makeAlert(), "mmol")).toBe(
      "Urgent Low Glucose: 3.9 mmol/L"
    );
  });

  it("renders a predictive alert with current -> predicted in N min (mg/dL)", () => {
    const alert = makeAlert({
      alert_type: "high_warning",
      current_value: 180,
      predicted_value: 220,
      prediction_minutes: 30,
    });
    expect(formatAlertSummary(alert, "mgdl")).toBe(
      "High Glucose Warning: 180 mg/dL → 220 mg/dL in 30min"
    );
  });

  it("converts both current and predicted to mmol/L", () => {
    const alert = makeAlert({
      alert_type: "high_warning",
      current_value: 180,
      predicted_value: 220,
      prediction_minutes: 30,
    });
    // 180 -> 10.0, 220 -> 12.2 mmol/L
    expect(formatAlertSummary(alert, "mmol")).toBe(
      "High Glucose Warning: 10.0 mmol/L → 12.2 mmol/L in 30min"
    );
  });

  it("returns the IoB-warning message verbatim (insulin units never convert)", () => {
    const message = "High insulin on board: 2.5 units (threshold: 2.0)";
    const alert = makeAlert({
      alert_type: "iob_warning",
      current_value: 120,
      message,
    });
    expect(formatAlertSummary(alert, "mgdl")).toBe(message);
    expect(formatAlertSummary(alert, "mmol")).toBe(message);
  });
});
