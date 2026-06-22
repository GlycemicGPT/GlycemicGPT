/**
 * The alert toast renders glucose from the structured fields in the viewer's
 * unit (via formatAlertSummary), not the persisted mg/dL message string.
 */

import { render } from "@testing-library/react";
import { AlertToast } from "@/components/dashboard/alert-toast";
import type { AlertEventData } from "@/hooks/use-glucose-stream";

function makeAlert(overrides: Partial<AlertEventData> = {}): AlertEventData {
  return {
    id: "a1",
    alert_type: "low_urgent",
    severity: "warning", // 15s auto-dismiss; won't fire during the test
    current_value: 70,
    predicted_value: null,
    prediction_minutes: null,
    iob_value: null,
    message: "Urgent low glucose: 70 mg/dL (threshold: 70)",
    trend_rate: null,
    source: "current",
    created_at: "2026-06-21T00:00:00Z",
    expires_at: "2099-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("AlertToast glucose unit", () => {
  it("renders the summary in mg/dL by default", () => {
    const { container } = render(
      <AlertToast alert={makeAlert()} onDismiss={jest.fn()} />
    );
    expect(container.textContent).toContain("Urgent Low Glucose: 70 mg/dL");
  });

  it("renders the summary converted to the viewer's mmol unit", () => {
    const { container } = render(
      <AlertToast alert={makeAlert()} onDismiss={jest.fn()} unit="mmol" />
    );
    expect(container.textContent).toContain("Urgent Low Glucose: 3.9 mmol/L");
  });
});
