/**
 * Caregiver dashboard renders each patient's glucose in the PATIENT's own unit
 * (never the viewing caregiver's), while the glucose color / status bands stay
 * computed from the raw mg/dL value. Guards the per-patient (overview cards) vs
 * selected-patient (detail view) unit resolution and the mg/dL-banding contract.
 */

import { render, screen } from "@testing-library/react";
import {
  listLinkedPatients,
  getCaregiverPatientStatus,
  type CaregiverPatientStatus,
} from "@/lib/api";

jest.mock("@/lib/api");

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/dashboard/caregiver",
}));

// The viewer is a caregiver; the page must render PATIENT units, not a viewer
// unit, so it deliberately does NOT call useGlucoseUnit.
jest.mock("@/providers", () => ({
  useUserContext: () => ({
    user: { id: "cg1", email: "cg@example.com", role: "caregiver" },
    isLoading: false,
    error: null,
  }),
}));

// Chat card is gated off below; stub the markdown renderer so importing the
// page never pulls heavy markdown deps into jsdom.
jest.mock("@/components/ui/markdown-content", () => ({
  MarkdownContent: () => null,
}));

import CaregiverDashboardPage from "@/app/dashboard/caregiver/page";

const mockListPatients = listLinkedPatients as jest.Mock;
const mockGetStatus = getCaregiverPatientStatus as jest.Mock;

function makeStatus(
  patientId: string,
  email: string,
  unit: "mmol" | "mgdl",
  valueMgdl: number
): CaregiverPatientStatus {
  return {
    patient_id: patientId,
    patient_email: email,
    glucose: {
      value: valueMgdl,
      trend: "Flat",
      trend_rate: null,
      reading_timestamp: "2026-06-21T12:00:00Z",
      minutes_ago: 2,
      is_stale: false,
    },
    iob: null,
    permissions: {
      can_view_glucose: true,
      can_view_history: true,
      can_view_iob: false,
      can_view_ai_suggestions: false,
      can_receive_alerts: true,
    },
    glucose_unit: unit,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("caregiver overview — per-patient unit, mg/dL color bands", () => {
  it("renders two patients with the SAME stored value in each patient's own unit", async () => {
    // Same canonical 90 mg/dL for both; only the display unit differs.
    mockListPatients.mockResolvedValue({
      count: 2,
      patients: [
        { patient_id: "A", patient_email: "amy@example.com", linked_at: "" },
        { patient_id: "B", patient_email: "bob@example.com", linked_at: "" },
      ],
    });
    mockGetStatus.mockImplementation((id: string) =>
      Promise.resolve(
        id === "A"
          ? makeStatus("A", "amy@example.com", "mmol", 90)
          : makeStatus("B", "bob@example.com", "mgdl", 90)
      )
    );

    render(<CaregiverDashboardPage />);

    // Patient A: 90 mg/dL renders as 5.0 mmol/L; patient B as 90 mg/dL — proving
    // per-patient resolution, not one shared/viewer unit.
    const aValue = await screen.findByText("5.0");
    expect(screen.getByText("90")).toBeInTheDocument();
    expect(screen.getByText("mmol/L")).toBeInTheDocument();
    expect(screen.getByText("mg/dL")).toBeInTheDocument();

    // The band reads the RAW mg/dL value: 90 mg/dL is in-range (green). A naive
    // band of the displayed "5.0" would be < 70 -> red, so green proves the band
    // is unaffected by the display unit.
    expect(aValue).toHaveClass("text-green-400");
    expect(screen.getByText("90")).toHaveClass("text-green-400");
  });
});

describe("caregiver detail — selected patient unit, mg/dL color band", () => {
  it("renders the selected patient in their unit and bands a low value by mg/dL", async () => {
    // Single patient auto-selects into the detail view. 75 mg/dL is in the
    // low-warning band (yellow); the displayed 4.2 mmol naively banded would be
    // < 70 -> red, so yellow proves the detail view also bands on raw mg/dL.
    mockListPatients.mockResolvedValue({
      count: 1,
      patients: [{ patient_id: "A", patient_email: "amy@example.com", linked_at: "" }],
    });
    mockGetStatus.mockResolvedValue(makeStatus("A", "amy@example.com", "mmol", 75));

    render(<CaregiverDashboardPage />);

    const value = await screen.findByText("4.2"); // 75 mg/dL -> 4.2 mmol/L
    expect(screen.getByText("mmol/L")).toBeInTheDocument();
    expect(value).toHaveClass("text-yellow-400");
  });
});
