/**
 * Story 15.5: AuthDisclaimerGate Component Tests
 *
 * Tests disclaimer enforcement for authenticated users:
 * - Shows modal when disclaimer_acknowledged is false
 * - Renders children when disclaimer_acknowledged is true
 * - Loading state while user data is being fetched
 * - Acknowledgment flow (checkboxes, submit, refresh)
 * - Dashboard content blocked while disclaimer shown
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock framer-motion to render children directly
jest.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  motion: {
    div: ({
      children,
      className,
      role,
      "aria-modal": ariaModal,
      "aria-labelledby": ariaLabelledby,
      ...rest
    }: Record<string, unknown> & { children?: React.ReactNode }) => (
      <div
        className={className as string}
        role={role as string}
        aria-modal={ariaModal as boolean}
        aria-labelledby={ariaLabelledby as string}
      >
        {children}
      </div>
    ),
  },
}));

// Mock lucide-react icons
jest.mock("lucide-react", () => ({
  FlaskConical: ({ className }: { className?: string }) => (
    <span data-testid="flask-icon" className={className} />
  ),
  Brain: ({ className }: { className?: string }) => (
    <span data-testid="brain-icon" className={className} />
  ),
  ShieldOff: ({ className }: { className?: string }) => (
    <span data-testid="shield-icon" className={className} />
  ),
  Stethoscope: ({ className }: { className?: string }) => (
    <span data-testid="stethoscope-icon" className={className} />
  ),
  AlertTriangle: ({ className }: { className?: string }) => (
    <span data-testid="alert-icon" className={className} />
  ),
  Check: ({ className }: { className?: string }) => (
    <span data-testid="check-icon" className={className} />
  ),
  Cloud: ({ className }: { className?: string }) => (
    <span data-testid="cloud-icon" className={className} />
  ),
  Loader2: ({ className }: { className?: string }) => (
    <span data-testid="loader-icon" className={className} />
  ),
}));

// Mock useUserContext
const mockUseUserContext = jest.fn();
jest.mock("@/providers/user-provider", () => ({
  useUserContext: () => mockUseUserContext(),
}));

// Mock API functions
const mockAcknowledgeDisclaimerAuth = jest.fn();
const mockGetDisclaimerContent = jest.fn();
jest.mock("@/lib/api", () => ({
  acknowledgeDisclaimerAuth: (...args: unknown[]) =>
    mockAcknowledgeDisclaimerAuth(...args),
  getDisclaimerContent: (...args: unknown[]) =>
    mockGetDisclaimerContent(...args),
}));

import { AuthDisclaimerGate } from "@/components/auth-disclaimer-gate";

const mockDisclaimerContent = {
  version: "1.1",
  title: "Important Safety Information",
  warnings: [
    {
      icon: "flask",
      title: "Experimental Software",
      text: "This is experimental software.",
    },
    {
      icon: "cloud",
      title: "AI Data Processing",
      text: "BYOAI: cloud providers receive your data; local providers do not.",
    },
  ],
  checkboxes: [
    {
      id: "checkbox_experimental",
      label: "I understand this is experimental software",
    },
    {
      id: "checkbox_not_medical_advice",
      label: "I understand this is not medical advice",
    },
    {
      id: "checkbox_ai_data_flow",
      label: "I understand the AI data-flow implications",
    },
  ],
  button_text: "I Understand & Accept",
};

beforeEach(() => {
  jest.clearAllMocks();
  mockGetDisclaimerContent.mockResolvedValue(mockDisclaimerContent);
});

describe("AuthDisclaimerGate - Loading State", () => {
  it("shows loading spinner while user data is being fetched", () => {
    mockUseUserContext.mockReturnValue({
      user: null,
      isLoading: true,
      error: null,
      refreshUser: jest.fn(),
    });

    render(
      <AuthDisclaimerGate>
        <div data-testid="dashboard-content">Dashboard</div>
      </AuthDisclaimerGate>
    );

    expect(screen.getByTestId("loader-icon")).toBeInTheDocument();
    expect(screen.queryByTestId("dashboard-content")).not.toBeInTheDocument();
  });

  it("does not flash the disclaimer modal during loading", () => {
    mockUseUserContext.mockReturnValue({
      user: null,
      isLoading: true,
      error: null,
      refreshUser: jest.fn(),
    });

    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    expect(
      screen.queryByText("Important Safety Information")
    ).not.toBeInTheDocument();
  });
});

describe("AuthDisclaimerGate - Acknowledged User", () => {
  it("renders children when disclaimer_acknowledged is true", () => {
    mockUseUserContext.mockReturnValue({
      user: {
        id: "1",
        email: "test@example.com",
        disclaimer_acknowledged: true,
      },
      isLoading: false,
      error: null,
      refreshUser: jest.fn(),
    });

    render(
      <AuthDisclaimerGate>
        <div data-testid="dashboard-content">Dashboard</div>
      </AuthDisclaimerGate>
    );

    expect(screen.getByTestId("dashboard-content")).toBeInTheDocument();
    expect(
      screen.queryByText("Important Safety Information")
    ).not.toBeInTheDocument();
  });
});

describe("AuthDisclaimerGate - Unacknowledged User", () => {
  beforeEach(() => {
    mockUseUserContext.mockReturnValue({
      user: {
        id: "1",
        email: "test@example.com",
        disclaimer_acknowledged: false,
      },
      isLoading: false,
      error: null,
      refreshUser: jest.fn(),
    });
  });

  it("shows disclaimer modal when disclaimer_acknowledged is false", async () => {
    render(
      <AuthDisclaimerGate>
        <div data-testid="dashboard-content">Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByText("Important Safety Information")
      ).toBeInTheDocument();
    });
  });

  it("blocks dashboard content while disclaimer is shown", async () => {
    render(
      <AuthDisclaimerGate>
        <div data-testid="dashboard-content">Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByText("Important Safety Information")
      ).toBeInTheDocument();
    });

    expect(screen.queryByTestId("dashboard-content")).not.toBeInTheDocument();
  });

  it("renders all required checkboxes", async () => {
    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByText("I understand this is experimental software")
      ).toBeInTheDocument();
    });

    expect(
      screen.getByText("I understand this is not medical advice")
    ).toBeInTheDocument();
    expect(
      screen.getByText("I understand the AI data-flow implications")
    ).toBeInTheDocument();
  });

  it("disables the accept button until all checkboxes are checked", async () => {
    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "I Understand & Accept" })
      ).toBeInTheDocument();
    });

    const button = screen.getByRole("button", {
      name: "I Understand & Accept",
    });
    expect(button).toBeDisabled();

    const checkboxes = screen.getAllByRole("checkbox");
    // Check first
    await userEvent.click(checkboxes[0]);
    expect(button).toBeDisabled();

    // Check second -- still disabled (3rd is required)
    await userEvent.click(checkboxes[1]);
    expect(button).toBeDisabled();

    // Check third -- now enabled
    await userEvent.click(checkboxes[2]);
    expect(button).not.toBeDisabled();
  });

  it("keeps accept button disabled when no checkboxes are checked", async () => {
    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "I Understand & Accept" })
      ).toBeInTheDocument();
    });

    const button = screen.getByRole("button", {
      name: "I Understand & Accept",
    });
    expect(button).toBeDisabled();
  });

  it("re-disables accept button when a checkbox is unchecked", async () => {
    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "I Understand & Accept" })
      ).toBeInTheDocument();
    });

    const checkboxes = screen.getAllByRole("checkbox");
    const button = screen.getByRole("button", {
      name: "I Understand & Accept",
    });

    // Check all three
    await userEvent.click(checkboxes[0]);
    await userEvent.click(checkboxes[1]);
    await userEvent.click(checkboxes[2]);
    expect(button).not.toBeDisabled();

    // Uncheck one
    await userEvent.click(checkboxes[0]);
    expect(button).toBeDisabled();
  });
});

describe("AuthDisclaimerGate - Acknowledgment Flow", () => {
  it("calls acknowledgeDisclaimerAuth and refreshUser on accept", async () => {
    const mockRefreshUser = jest.fn().mockResolvedValue(undefined);
    mockAcknowledgeDisclaimerAuth.mockResolvedValue({
      success: true,
      message: "ok",
    });

    mockUseUserContext.mockReturnValue({
      user: {
        id: "1",
        email: "test@example.com",
        disclaimer_acknowledged: false,
      },
      isLoading: false,
      error: null,
      refreshUser: mockRefreshUser,
    });

    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "I Understand & Accept" })
      ).toBeInTheDocument();
    });

    // Check all required checkboxes
    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[0]);
    await userEvent.click(checkboxes[1]);
    await userEvent.click(checkboxes[2]);

    // Click accept
    const button = screen.getByRole("button", {
      name: "I Understand & Accept",
    });
    await userEvent.click(button);

    await waitFor(() => {
      expect(mockAcknowledgeDisclaimerAuth).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(mockRefreshUser).toHaveBeenCalledTimes(1);
    });
  });

  it("shows saving state during acknowledgment", async () => {
    let resolveAcknowledge: () => void;
    mockAcknowledgeDisclaimerAuth.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveAcknowledge = resolve;
      })
    );

    mockUseUserContext.mockReturnValue({
      user: {
        id: "1",
        email: "test@example.com",
        disclaimer_acknowledged: false,
      },
      isLoading: false,
      error: null,
      refreshUser: jest.fn(),
    });

    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "I Understand & Accept" })
      ).toBeInTheDocument();
    });

    // Check all required checkboxes
    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[0]);
    await userEvent.click(checkboxes[1]);
    await userEvent.click(checkboxes[2]);

    // Click accept
    await userEvent.click(
      screen.getByRole("button", { name: "I Understand & Accept" })
    );

    await waitFor(() => {
      expect(screen.getByText("Saving...")).toBeInTheDocument();
    });

    // Clean up
    resolveAcknowledge!();
  });

  it("shows error on API failure", async () => {
    mockAcknowledgeDisclaimerAuth.mockRejectedValue(
      new Error("Network error")
    );

    mockUseUserContext.mockReturnValue({
      user: {
        id: "1",
        email: "test@example.com",
        disclaimer_acknowledged: false,
      },
      isLoading: false,
      error: null,
      refreshUser: jest.fn(),
    });

    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "I Understand & Accept" })
      ).toBeInTheDocument();
    });

    // Check all required checkboxes
    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[0]);
    await userEvent.click(checkboxes[1]);
    await userEvent.click(checkboxes[2]);

    // Click accept
    await userEvent.click(
      screen.getByRole("button", { name: "I Understand & Accept" })
    );

    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });
});

describe("AuthDisclaimerGate - Fallback Content", () => {
  it("uses fallback content when API fails to load disclaimer", async () => {
    mockGetDisclaimerContent.mockRejectedValue(new Error("API error"));

    mockUseUserContext.mockReturnValue({
      user: {
        id: "1",
        email: "test@example.com",
        disclaimer_acknowledged: false,
      },
      isLoading: false,
      error: null,
      refreshUser: jest.fn(),
    });

    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(
        screen.getByText("Important Safety Information")
      ).toBeInTheDocument();
    });

    // Fallback should have all required checkboxes (v1.1 -> 3)
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  });
});

describe("AuthDisclaimerGate - No User", () => {
  it("renders children when user is null (auth redirect handles this)", () => {
    mockUseUserContext.mockReturnValue({
      user: null,
      isLoading: false,
      error: "Not authenticated",
      refreshUser: jest.fn(),
    });

    render(
      <AuthDisclaimerGate>
        <div data-testid="dashboard-content">Dashboard</div>
      </AuthDisclaimerGate>
    );

    // When user is null and not loading, render children
    // (middleware/apiFetch will handle the redirect)
    expect(screen.getByTestId("dashboard-content")).toBeInTheDocument();
  });
});

describe("AuthDisclaimerGate - Accessibility", () => {
  it("renders modal with proper ARIA attributes", async () => {
    mockUseUserContext.mockReturnValue({
      user: {
        id: "1",
        email: "test@example.com",
        disclaimer_acknowledged: false,
      },
      isLoading: false,
      error: null,
      refreshUser: jest.fn(),
    });

    render(
      <AuthDisclaimerGate>
        <div>Dashboard</div>
      </AuthDisclaimerGate>
    );

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "disclaimer-title");
  });
});
