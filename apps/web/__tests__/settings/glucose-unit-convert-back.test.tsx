/**
 * Wiring tests: the safety-limits, glucose-range, and alert-threshold forms must
 * convert mmol entries back to INTEGER mg/dL and clamp to the canonical bound
 * before they leave the browser. The conversion math is unit-tested in
 * glucose-units.test; these prove the input forms actually call it on save (so a
 * refactor that dropped the clamp/convert would fail here).
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import SafetyLimitsPage from "@/app/dashboard/settings/safety-limits/page";
import GlucoseRangePage from "@/app/dashboard/settings/glucose-range/page";
import AlertSettingsPage from "@/app/dashboard/settings/alerts/page";
import {
  getSafetyLimits,
  getSafetyLimitsDefaults,
  updateSafetyLimits,
  getTargetGlucoseRange,
  updateTargetGlucoseRange,
  getAlertThresholds,
  updateAlertThresholds,
  getEscalationConfig,
  updateEscalationConfig,
} from "@/lib/api";

jest.mock("@/lib/api");

// Force mmol display so entries are in mmol and must convert back to mg/dL.
jest.mock("@/hooks/use-glucose-unit", () => ({
  useGlucoseUnit: () => "mmol",
}));

// safety-limits gates on the user role via the shared context.
jest.mock("@/providers", () => ({
  useUserContext: () => ({
    user: { id: "u1", role: "diabetic" },
    isLoading: false,
    error: null,
    refreshUser: jest.fn(),
  }),
}));

const mockGetSafety = getSafetyLimits as jest.Mock;
const mockGetSafetyDefaults = getSafetyLimitsDefaults as jest.Mock;
const mockUpdateSafety = updateSafetyLimits as jest.Mock;
const mockGetRange = getTargetGlucoseRange as jest.Mock;
const mockUpdateRange = updateTargetGlucoseRange as jest.Mock;
const mockGetThresholds = getAlertThresholds as jest.Mock;
const mockUpdateThresholds = updateAlertThresholds as jest.Mock;
const mockGetEscalation = getEscalationConfig as jest.Mock;
const mockUpdateEscalation = updateEscalationConfig as jest.Mock;

const SAFETY_DEFAULTS = {
  min_glucose_mgdl: 20,
  max_glucose_mgdl: 500,
  max_basal_rate_milliunits: 15000,
  max_bolus_dose_milliunits: 25000,
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe("safety-limits convert-back + clamp (medical safety)", () => {
  it("sends integer mg/dL clamped to the bound when entering the displayed mmol max", async () => {
    // Loaded max 450 mg/dL renders as 25.0 mmol; the user raises it to the
    // displayed ceiling 27.8 mmol, which round-trips to 501 and must clamp to 500.
    mockGetSafety.mockResolvedValue({
      id: "s1",
      min_glucose_mgdl: 70, // 3.9 mmol
      max_glucose_mgdl: 450, // 25.0 mmol
      max_basal_rate_milliunits: 15000,
      max_bolus_dose_milliunits: 25000,
      updated_at: "",
    });
    mockGetSafetyDefaults.mockResolvedValue(SAFETY_DEFAULTS);
    mockUpdateSafety.mockResolvedValue({
      id: "s1",
      min_glucose_mgdl: 70,
      max_glucose_mgdl: 500,
      max_basal_rate_milliunits: 15000,
      max_bolus_dose_milliunits: 25000,
      updated_at: "",
    });

    render(<SafetyLimitsPage />);

    const maxInput = await screen.findByLabelText(/Maximum Glucose/i);
    fireEvent.change(maxInput, { target: { value: "27.8" } });

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));
    // Confirmation dialog -> confirm
    fireEvent.click(await screen.findByRole("button", { name: /^confirm$/i }));

    await waitFor(() => expect(mockUpdateSafety).toHaveBeenCalledTimes(1));
    const payload = mockUpdateSafety.mock.calls[0][0];
    // Max clamped from 501 -> 500 (never crosses the ceiling); min stays 70.
    expect(payload.max_glucose_mgdl).toBe(500);
    expect(payload.min_glucose_mgdl).toBe(70);
    // Everything on the wire is an integer mg/dL within the 20-500 invariant.
    expect(Number.isInteger(payload.max_glucose_mgdl)).toBe(true);
    expect(Number.isInteger(payload.min_glucose_mgdl)).toBe(true);
    expect(payload.max_glucose_mgdl).toBeLessThanOrEqual(500);
    expect(payload.min_glucose_mgdl).toBeGreaterThanOrEqual(20);
  });
});

describe("alert-thresholds convert-back (integer mg/dL on the wire)", () => {
  it("converts an mmol urgent-high entry to integer mg/dL on save", async () => {
    mockGetThresholds.mockResolvedValue({
      id: "t1",
      low_warning: 70, // 3.9 mmol
      urgent_low: 55, // 3.1 mmol
      high_warning: 180, // 10.0 mmol
      urgent_high: 250, // 13.9 mmol
      iob_warning: 3.0,
      updated_at: "",
    });
    mockGetEscalation.mockResolvedValue({
      reminder_delay_minutes: 5,
      primary_contact_delay_minutes: 10,
      all_contacts_delay_minutes: 20,
    });
    mockUpdateThresholds.mockResolvedValue({
      id: "t1",
      low_warning: 70,
      urgent_low: 56,
      high_warning: 180,
      urgent_high: 252,
      iob_warning: 3.0,
      updated_at: "",
    });
    mockUpdateEscalation.mockResolvedValue({
      reminder_delay_minutes: 5,
      primary_contact_delay_minutes: 10,
      all_contacts_delay_minutes: 20,
    });

    render(<AlertSettingsPage />);

    const urgentHigh = await screen.findByLabelText(/Urgent High/i);
    fireEvent.change(urgentHigh, { target: { value: "14.0" } });

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockUpdateThresholds).toHaveBeenCalledTimes(1));
    const payload = mockUpdateThresholds.mock.calls[0][0];
    // 14.0 mmol -> 252 mg/dL (round(14 * 18.0156)).
    expect(payload.urgent_high).toBe(252);
    // The four glucose thresholds are integers within the 20-500 invariant.
    for (const k of [
      "low_warning",
      "urgent_low",
      "high_warning",
      "urgent_high",
    ]) {
      expect(Number.isInteger(payload[k])).toBe(true);
      expect(payload[k]).toBeGreaterThanOrEqual(20);
      expect(payload[k]).toBeLessThanOrEqual(500);
    }
    // IoB stays in insulin units (never glucose-converted).
    expect(payload.iob_warning).toBe(3.0);
  });
});

describe("glucose-range convert-back (integer mg/dL on the wire)", () => {
  it("converts an mmol urgent-high entry to integer mg/dL on save", async () => {
    mockGetRange.mockResolvedValue({
      urgent_low: 55, // 3.1 mmol
      low_target: 70, // 3.9 mmol
      high_target: 180, // 10.0 mmol
      urgent_high: 250, // 13.9 mmol
    });
    mockUpdateRange.mockResolvedValue({
      urgent_low: 55,
      low_target: 70,
      high_target: 180,
      urgent_high: 252,
    });

    render(<GlucoseRangePage />);

    const urgentHigh = await screen.findByLabelText(/Urgent High/i);
    fireEvent.change(urgentHigh, { target: { value: "14.0" } });

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockUpdateRange).toHaveBeenCalledTimes(1));
    const payload = mockUpdateRange.mock.calls[0][0];
    // 14.0 mmol -> 252 mg/dL (round(14 * 18.0156)).
    expect(payload.urgent_high).toBe(252);
    // All four thresholds are integers within the 20-500 invariant.
    for (const k of ["urgent_low", "low_target", "high_target", "urgent_high"]) {
      expect(Number.isInteger(payload[k])).toBe(true);
      expect(payload[k]).toBeGreaterThanOrEqual(20);
      expect(payload[k]).toBeLessThanOrEqual(500);
    }
  });
});
