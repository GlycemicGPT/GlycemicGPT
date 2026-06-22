/**
 * Story 53.10: GlucoseUnitSeedNotice tests.
 *
 * The one-time smart-default notice must appear ONLY for a still-seed-owned
 * non-mgdl preference, never for an mg/dL default or an explicit user choice,
 * and dismissing it must acknowledge the seed server-side so it doesn't recur.
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("lucide-react", () => ({
  Info: ({ className }: { className?: string }) => (
    <span data-testid="info-icon" className={className} />
  ),
  X: ({ className }: { className?: string }) => (
    <span data-testid="x-icon" className={className} />
  ),
}));

jest.mock("next/link", () => ({
  __esModule: true,
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

const mockUseUserContext = jest.fn();
jest.mock("@/providers", () => ({
  useUserContext: () => mockUseUserContext(),
}));

const mockAcknowledgeGlucoseUnitSeed = jest.fn();
jest.mock("@/lib/api", () => ({
  acknowledgeGlucoseUnitSeed: (...args: unknown[]) =>
    mockAcknowledgeGlucoseUnitSeed(...args),
}));

import { GlucoseUnitSeedNotice } from "@/components/dashboard/glucose-unit-seed-notice";

function mockUser(user: Record<string, unknown> | null, refreshUser = jest.fn()) {
  mockUseUserContext.mockReturnValue({
    user,
    isLoading: false,
    error: null,
    refreshUser,
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockAcknowledgeGlucoseUnitSeed.mockResolvedValue(undefined);
});

describe("GlucoseUnitSeedNotice - visibility gate", () => {
  it("shows the notice for a seed-owned mmol preference", () => {
    mockUser({ glucose_unit: "mmol", glucose_unit_source: "seed" });
    render(<GlucoseUnitSeedNotice />);
    expect(
      screen.getByTestId("glucose-unit-seed-notice")
    ).toBeInTheDocument();
    expect(
      screen.getByText(/We set your glucose unit to mmol\/L/)
    ).toBeInTheDocument();
  });

  it("does NOT show for an mg/dL-defaulted account (even if seed-owned)", () => {
    mockUser({ glucose_unit: "mgdl", glucose_unit_source: "seed" });
    render(<GlucoseUnitSeedNotice />);
    expect(
      screen.queryByTestId("glucose-unit-seed-notice")
    ).not.toBeInTheDocument();
  });

  it("does NOT show once the user has explicitly chosen (source=user)", () => {
    mockUser({ glucose_unit: "mmol", glucose_unit_source: "user" });
    render(<GlucoseUnitSeedNotice />);
    expect(
      screen.queryByTestId("glucose-unit-seed-notice")
    ).not.toBeInTheDocument();
  });

  it("does NOT show when the source field is absent (deploy skew)", () => {
    mockUser({ glucose_unit: "mmol" });
    render(<GlucoseUnitSeedNotice />);
    expect(
      screen.queryByTestId("glucose-unit-seed-notice")
    ).not.toBeInTheDocument();
  });

  it("does NOT show while the user is null", () => {
    mockUser(null);
    render(<GlucoseUnitSeedNotice />);
    expect(
      screen.queryByTestId("glucose-unit-seed-notice")
    ).not.toBeInTheDocument();
  });
});

describe("GlucoseUnitSeedNotice - dismiss", () => {
  it("acknowledges the seed and refreshes the user, then hides", async () => {
    const refreshUser = jest.fn().mockResolvedValue(undefined);
    mockUser({ glucose_unit: "mmol", glucose_unit_source: "seed" }, refreshUser);

    render(<GlucoseUnitSeedNotice />);
    await userEvent.click(
      screen.getByRole("button", { name: "Dismiss glucose unit notice" })
    );

    await waitFor(() => {
      expect(mockAcknowledgeGlucoseUnitSeed).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(refreshUser).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.queryByTestId("glucose-unit-seed-notice")
    ).not.toBeInTheDocument();
  });

  it("still hides when the acknowledge call fails (best-effort)", async () => {
    mockAcknowledgeGlucoseUnitSeed.mockRejectedValue(new Error("network"));
    mockUser({ glucose_unit: "mmol", glucose_unit_source: "seed" });

    render(<GlucoseUnitSeedNotice />);
    await userEvent.click(
      screen.getByRole("button", { name: "Dismiss glucose unit notice" })
    );

    await waitFor(() => {
      expect(
        screen.queryByTestId("glucose-unit-seed-notice")
      ).not.toBeInTheDocument();
    });
  });
});
