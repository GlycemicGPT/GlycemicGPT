/**
 * Glucose-unit conversion on the CGM summary: mean and SD convert (SD scaled by
 * /18.0156 like a value, keeping mmol precision); CV%/GMI stay percentages.
 */

import { render } from "@testing-library/react";
import { CgmSummaryStats } from "@/components/dashboard/cgm-summary-stats";
import type { GlucoseStats } from "@/lib/api";

const stats: GlucoseStats = {
  mean_glucose: 180,
  std_dev: 36,
  cv_pct: 20,
  gmi: 7.0,
  cgm_active_pct: 90,
  readings_count: 288,
  period_minutes: 1440,
};

describe("CgmSummaryStats glucose unit", () => {
  it("shows mean + SD in mg/dL by default", () => {
    const { container } = render(
      <CgmSummaryStats
        stats={stats}
        isLoading={false}
        period="24h"
        onPeriodChange={jest.fn()}
      />
    );
    expect(container.textContent).toContain("180"); // mean
    expect(container.textContent).toContain("36"); // SD
    expect(container.textContent).toContain("mg/dL");
  });

  it("converts mean + SD to mmol (CV%/GMI stay percentages)", () => {
    const { container } = render(
      <CgmSummaryStats
        stats={stats}
        isLoading={false}
        period="24h"
        onPeriodChange={jest.fn()}
        unit="mmol"
      />
    );
    expect(container.textContent).toContain("10.0"); // mean 180 mg/dL
    expect(container.textContent).toContain("2.0"); // SD 36 mg/dL -> 2.0 mmol
    expect(container.textContent).toContain("mmol/L");
    // CV% and GMI are percentages, never converted.
    expect(container.textContent).toContain("20.0%");
    expect(container.textContent).toContain("7.0%");
  });
});
