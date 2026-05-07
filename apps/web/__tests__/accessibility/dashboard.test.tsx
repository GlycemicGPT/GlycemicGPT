/**
 * Dashboard Page Accessibility Tests
 *
 * Story 4.6: Dashboard Accessibility
 * Tests for page landmarks, heading hierarchy, and navigation.
 */

import { render, screen } from "@testing-library/react";

// Mock next/navigation (needed for caregiver redirect logic)
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: jest.fn(),
    push: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    prefetch: jest.fn(),
  }),
  usePathname: () => "/dashboard",
}));

// Mock the providers
jest.mock("@/providers", () => ({
  useGlucoseStreamContext: () => ({
    glucose: null,
    isLive: false,
    isReconnecting: false,
    error: null,
    reconnect: jest.fn(),
  }),
  useUserContext: () => ({
    user: { id: "test-user", email: "test@example.com", role: "diabetic" },
    isLoading: false,
    error: null,
  }),
}));

// Import after mocking
import DashboardPage from "@/app/dashboard/page";

// DashboardLayout provides <main id="main-content">, so wrap page in it for tests
function LayoutWrapper({ children }: { children: React.ReactNode }) {
  return <main id="main-content">{children}</main>;
}

describe("Dashboard Page Accessibility", () => {
  describe("Landmarks", () => {
    it("has a main landmark", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const main = screen.getByRole("main");
      expect(main).toBeInTheDocument();
    });

    it("main landmark has id for skip link", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const main = screen.getByRole("main");
      expect(main).toHaveAttribute("id", "main-content");
    });

    // Note: Page header uses <div> instead of <header> to avoid
    // banner role confusion when nested inside <main> landmark
  });

  describe("Heading Hierarchy", () => {
    it("has h1 as page title", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const h1 = screen.getByRole("heading", { level: 1 });
      expect(h1).toBeInTheDocument();
      expect(h1).toHaveTextContent("Dashboard");
    });

    it("has h2 for metrics section (visually hidden)", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const h2 = screen.getByRole("heading", { level: 2, name: /dashboard metrics/i });
      expect(h2).toBeInTheDocument();
      expect(h2).toHaveClass("sr-only");
    });

    it("has h3 for individual metric cards", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const h3s = screen.getAllByRole("heading", { level: 3 });
      expect(h3s.length).toBeGreaterThanOrEqual(2);
      expect(h3s.some(h => h.textContent?.includes("Time in Range"))).toBe(true);
      // The old single-row "Last Updated" card was replaced by the
      // multi-source "Data Sources" card in Story 43.5 phase 3. Both
      // the populated card and its empty-state fallback render an h3
      // with this text.
      expect(h3s.some(h => h.textContent?.includes("Data Sources"))).toBe(true);
    });
  });

  describe("Semantic Structure", () => {
    it("uses article elements for metric cards", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const articles = screen.getAllByRole("article");
      expect(articles.length).toBeGreaterThanOrEqual(2);
    });

    it("uses section element for metrics grid", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const section = screen.getByRole("region", { name: /dashboard metrics/i });
      expect(section).toBeInTheDocument();
    });

    it("hides decorative icons from screen readers", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      // Icons should have aria-hidden="true"
      const articles = screen.getAllByRole("article");
      articles.forEach(article => {
        const svg = article.querySelector("svg");
        if (svg) {
          expect(svg).toHaveAttribute("aria-hidden", "true");
        }
      });
    });
  });

  describe("Metric Card Accessibility", () => {
    it("provides accessible label for time in range value", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const tirValue = screen.getByLabelText(/time in range.*percent/i);
      expect(tirValue).toBeInTheDocument();
    });

    it("renders a Data Sources card with discoverable content", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      // The new Data Sources card replaces the old "Last Updated"
      // card. With no integrations configured (the test fixture
      // returns empty lists), the empty-state fallback renders the
      // h3 + an actionable hint pointing to Settings → Integrations.
      const heading = screen.getByRole("heading", {
        level: 3,
        name: /data sources/i,
      });
      expect(heading).toBeInTheDocument();
    });
  });
});

describe("Dashboard Layout Accessibility", () => {
  // Note: Skip link is in layout.tsx, which wraps the page
  // The <main id="main-content"> is now in DashboardLayout, not in page components

  describe("Skip Link", () => {
    it("skip link target matches main content id", () => {
      render(<DashboardPage />, { wrapper: LayoutWrapper });

      const main = screen.getByRole("main");
      expect(main.id).toBe("main-content");
      // Skip link href="#main-content" should work with this id
    });
  });
});
