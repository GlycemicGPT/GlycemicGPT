/**
 * Tests for the Dashboard Layout component.
 *
 * Story 4.1: Dashboard Layout & Navigation
 */

import { render, screen } from "@testing-library/react";
import { DashboardLayout } from "../../../src/components/layout/dashboard-layout";

// Mock next/navigation
jest.mock("next/navigation", () => ({
  usePathname: jest.fn(() => "/dashboard"),
}));

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

describe("DashboardLayout", () => {
  it("renders children content", () => {
    render(
      <DashboardLayout>
        <div data-testid="test-content">Test Content</div>
      </DashboardLayout>
    );

    expect(screen.getByTestId("test-content")).toBeInTheDocument();
    expect(screen.getByText("Test Content")).toBeInTheDocument();
  });

  it("renders the sidebar", () => {
    render(
      <DashboardLayout>
        <div>Content</div>
      </DashboardLayout>
    );

    // Sidebar should have navigation items
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Daily Briefs")).toBeInTheDocument();
  });

  it("renders the header", () => {
    render(
      <DashboardLayout>
        <div>Content</div>
      </DashboardLayout>
    );

    // Header should have account button
    expect(screen.getByText("Account")).toBeInTheDocument();
  });

  it("applies correct layout structure", () => {
    const { container } = render(
      <DashboardLayout>
        <div>Content</div>
      </DashboardLayout>
    );

    // Should have the main container with theme-aware background
    const mainContainer = container.firstChild;
    expect(mainContainer).toHaveClass("min-h-screen");
  });
});
