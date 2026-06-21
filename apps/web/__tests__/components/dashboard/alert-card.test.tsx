/**
 * Glucose-unit conversion on the alert card: current/predicted BG convert via
 * formatGlucose and the trend RATE via formatTrendRate (2-decimal mmol so the
 * arrow buckets don't collapse), never a naive toFixed(1).
 */

import { render } from "@testing-library/react";
import { AlertCard } from "@/components/dashboard/alert-card";
import type { PredictiveAlert } from "@/lib/api";

function makeAlert(overrides: Partial<PredictiveAlert> = {}): PredictiveAlert {
  return {
    id: "a1",
    alert_type: "predicted_low",
    severity: "warning", // non-urgent: no EscalationTimeline / fetch
    current_value: 180,
    predicted_value: 70,
    prediction_minutes: 30,
    iob_value: null,
    message: "Predicted low",
    trend_rate: 3,
    source: "predictive",
    acknowledged: false,
    acknowledged_at: null,
    created_at: "2026-06-21T00:00:00Z",
    expires_at: "2099-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("AlertCard glucose unit", () => {
  it("renders mg/dL by default (value + 1-decimal trend rate)", () => {
    const { container } = render(
      <AlertCard alert={makeAlert()} onAcknowledge={jest.fn()} />
    );
    expect(container.textContent).toContain("180");
    expect(container.textContent).toContain("mg/dL");
    expect(container.textContent).toContain("+3.0 mg/dL/min");
  });

  it("converts current/predicted BG and the trend rate to mmol", () => {
    const { container } = render(
      <AlertCard alert={makeAlert()} onAcknowledge={jest.fn()} unit="mmol" />
    );
    expect(container.textContent).toContain("10.0"); // 180 mg/dL
    expect(container.textContent).toContain("3.9"); // predicted 70 mg/dL
    expect(container.textContent).toContain("mmol/L");
    // 3 mg/dL/min -> 0.17 mmol/L/min (2 decimals; 1 decimal would collapse to 0.2)
    expect(container.textContent).toContain("+0.17 mmol/L/min");
  });
});
