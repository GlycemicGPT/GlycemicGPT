/**
 * Story 15.4: Header Component Tests
 *
 * Tests logout functionality, user info display, and loading states.
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock next/link
jest.mock("next/link", () => {
  return function MockLink({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  };
});

// Mock sidebar's MobileNav
jest.mock("@/components/layout/sidebar", () => ({
  MobileNav: () => <div data-testid="mobile-nav" />,
}));

// Mock ThemeToggle
jest.mock("@/components/ui/theme-toggle", () => ({
  ThemeToggle: () => <div data-testid="theme-toggle" />,
}));

// Mock logoutUser
const mockLogoutUser = jest.fn();
jest.mock("@/lib/api", () => ({
  logoutUser: (...args: unknown[]) => mockLogoutUser(...args),
}));

// Mock useUserContext
const mockUseUserContext = jest.fn();
jest.mock("@/providers/user-provider", () => ({
  useUserContext: () => mockUseUserContext(),
}));

// Mock lucide-react icons
jest.mock("lucide-react", () => ({
  User: ({ className }: { className?: string }) => (
    <span data-testid="user-icon" className={className} />
  ),
  LogOut: ({ className }: { className?: string }) => (
    <span data-testid="logout-icon" className={className} />
  ),
  Settings: ({ className }: { className?: string }) => (
    <span data-testid="settings-icon" className={className} />
  ),
  ChevronDown: ({ className }: { className?: string }) => (
    <span data-testid="chevron-icon" className={className} />
  ),
  Activity: ({ className }: { className?: string }) => (
    <span data-testid="activity-icon" className={className} />
  ),
  Loader2: ({ className }: { className?: string }) => (
    <span data-testid="loader-icon" className={className} />
  ),
}));

import { Header } from "@/components/layout/header";

// Save and mock window.location
const originalLocation = window.location;

beforeEach(() => {
  jest.clearAllMocks();
  mockUseUserContext.mockReturnValue({
    user: null,
    isLoading: true,
    error: null,
  });
  Object.defineProperty(window, "location", {
    writable: true,
    value: { ...originalLocation, href: "http://localhost:3000/dashboard" },
  });
});

afterAll(() => {
  Object.defineProperty(window, "location", {
    writable: true,
    value: originalLocation,
  });
});

function openDropdown() {
  const trigger = screen.getByRole("button", { expanded: false });
  return userEvent.click(trigger);
}

describe("Header - User Info Display", () => {
  it("shows 'Account' as fallback when user is loading", () => {
    mockUseUserContext.mockReturnValue({
      user: null,
      isLoading: true,
      error: null,
    });

    render(<Header />);
    expect(screen.getByText("Account")).toBeInTheDocument();
  });

  it("shows user email when available", () => {
    mockUseUserContext.mockReturnValue({
      user: { email: "test@example.com", display_name: null },
      isLoading: false,
      error: null,
    });

    render(<Header />);
    expect(screen.getByText("test@example.com")).toBeInTheDocument();
  });

  it("shows display name when available (preferred over email)", () => {
    mockUseUserContext.mockReturnValue({
      user: { email: "test@example.com", display_name: "John Doe" },
      isLoading: false,
      error: null,
    });

    render(<Header />);
    expect(screen.getByText("John Doe")).toBeInTheDocument();
    expect(screen.queryByText("test@example.com")).not.toBeInTheDocument();
  });

  it("shows 'Account' when user is null", () => {
    mockUseUserContext.mockReturnValue({
      user: null,
      isLoading: false,
      error: "Failed",
    });

    render(<Header />);
    expect(screen.getByText("Account")).toBeInTheDocument();
  });
});

describe("Header - Logout", () => {
  beforeEach(() => {
    mockUseUserContext.mockReturnValue({
      user: { email: "test@example.com", display_name: null },
      isLoading: false,
      error: null,
    });
  });

  it("calls logoutUser and redirects to /login on sign out", async () => {
    mockLogoutUser.mockResolvedValue(undefined);

    render(<Header />);
    await openDropdown();

    const signOutButton = screen.getByRole("button", { name: /sign out/i });
    await userEvent.click(signOutButton);

    await waitFor(() => {
      expect(mockLogoutUser).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(window.location.href).toBe("/login");
    });
  });

  it("redirects to /login even if logout API fails", async () => {
    mockLogoutUser.mockRejectedValue(new Error("Network error"));

    render(<Header />);
    await openDropdown();

    const signOutButton = screen.getByRole("button", { name: /sign out/i });
    await userEvent.click(signOutButton);

    await waitFor(() => {
      expect(window.location.href).toBe("/login");
    });
  });

  it("shows loading state on sign out button during logout", async () => {
    // Make logout hang so we can observe the loading state
    let resolveLogout: () => void;
    mockLogoutUser.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveLogout = resolve;
      })
    );

    render(<Header />);
    await openDropdown();

    const signOutButton = screen.getByRole("button", { name: /sign out/i });
    await userEvent.click(signOutButton);

    // Should show "Signing out..." text
    await waitFor(() => {
      expect(screen.getByText("Signing out...")).toBeInTheDocument();
    });

    // Should show loader icon
    expect(screen.getByTestId("loader-icon")).toBeInTheDocument();

    // Button should be disabled
    const disabledButton = screen.getByRole("button", {
      name: /signing out/i,
    });
    expect(disabledButton).toBeDisabled();

    // Resolve to clean up
    resolveLogout!();
  });

  it("disables sign out button during logout to prevent double-clicks", async () => {
    let resolveLogout: () => void;
    mockLogoutUser.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveLogout = resolve;
      })
    );

    render(<Header />);
    await openDropdown();

    const signOutButton = screen.getByRole("button", { name: /sign out/i });
    await userEvent.click(signOutButton);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /signing out/i })
      ).toBeDisabled();
    });

    resolveLogout!();
  });
});

describe("Header - Dropdown menu", () => {
  it("shows settings link in dropdown", async () => {
    mockUseUserContext.mockReturnValue({
      user: { email: "test@example.com", display_name: null },
      isLoading: false,
      error: null,
    });

    render(<Header />);
    await openDropdown();

    const settingsLink = screen.getByRole("link", { name: /settings/i });
    expect(settingsLink).toHaveAttribute("href", "/dashboard/settings");
  });
});
