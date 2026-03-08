/**
 * Tests for the Sidebar Navigation component.
 *
 * Story 4.1: Dashboard Layout & Navigation
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { Sidebar, MobileNav } from "../../../src/components/layout/sidebar";

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

describe("Sidebar", () => {
  it("renders the logo", () => {
    render(<Sidebar />);
    expect(screen.getByText("GlycemicGPT")).toBeInTheDocument();
  });

  it("renders all navigation items", () => {
    render(<Sidebar />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Daily Briefs")).toBeInTheDocument();
    expect(screen.getByText("Alerts")).toBeInTheDocument();
    expect(screen.getByText("Reports")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders navigation links with correct hrefs", () => {
    render(<Sidebar />);
    expect(screen.getByText("Dashboard").closest("a")).toHaveAttribute(
      "href",
      "/dashboard"
    );
    expect(screen.getByText("Daily Briefs").closest("a")).toHaveAttribute(
      "href",
      "/dashboard/briefs"
    );
    expect(screen.getByText("Alerts").closest("a")).toHaveAttribute(
      "href",
      "/dashboard/alerts"
    );
    expect(screen.getByText("Reports").closest("a")).toHaveAttribute(
      "href",
      "/dashboard/reports"
    );
    expect(screen.getByText("Settings").closest("a")).toHaveAttribute(
      "href",
      "/dashboard/settings"
    );
  });

  it("displays 'Not medical advice' footer", () => {
    render(<Sidebar />);
    expect(screen.getByText("Not medical advice")).toBeInTheDocument();
  });

  it("highlights the active navigation item", () => {
    render(<Sidebar />);
    const dashboardLink = screen.getByText("Dashboard").closest("a");
    expect(dashboardLink).toHaveClass("bg-blue-600");
  });
});

describe("MobileNav", () => {
  it("renders the menu button", () => {
    render(<MobileNav />);
    expect(
      screen.getByRole("button", { name: /open navigation menu/i })
    ).toBeInTheDocument();
  });

  it("opens the mobile menu when button is clicked", () => {
    render(<MobileNav />);
    const menuButton = screen.getByRole("button", {
      name: /open navigation menu/i,
    });

    fireEvent.click(menuButton);

    // Menu should now be visible
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Daily Briefs")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /close navigation menu/i })
    ).toBeInTheDocument();
  });

  it("closes the mobile menu when close button is clicked", () => {
    render(<MobileNav />);
    const menuButton = screen.getByRole("button", {
      name: /open navigation menu/i,
    });

    // Open menu
    fireEvent.click(menuButton);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();

    // Close menu
    const closeButton = screen.getByRole("button", {
      name: /close navigation menu/i,
    });
    fireEvent.click(closeButton);

    // Menu should be closed (navigation items not visible)
    expect(screen.queryByText("Daily Briefs")).not.toBeInTheDocument();
  });

  it("closes the mobile menu when a navigation link is clicked", () => {
    render(<MobileNav />);
    const menuButton = screen.getByRole("button", {
      name: /open navigation menu/i,
    });

    // Open menu
    fireEvent.click(menuButton);

    // Click a navigation link
    fireEvent.click(screen.getByText("Settings"));

    // Menu should be closed
    expect(screen.queryByText("Daily Briefs")).not.toBeInTheDocument();
  });
});
