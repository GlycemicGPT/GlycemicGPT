/**
 * Story 11.3: Wire Daily Briefs Web Delivery
 *
 * Tests for the unread badge on sidebar, briefs page filter tabs,
 * and the getUnreadInsightsCount API function.
 */

import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

// Mock next/navigation
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  usePathname: () => "/dashboard/briefs",
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

// Mock next/image
jest.mock("next/image", () => {
  return function MockImage(props: { alt: string; [key: string]: unknown }) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img alt={props.alt} />;
  };
});

// Mock providers
jest.mock("@/providers", () => ({
  useUserContext: () => ({ user: { role: "diabetic" } }),
}));

// Mock API functions
const mockGetUnreadInsightsCount = jest.fn();
const mockGetInsightDetail = jest.fn();

jest.mock("@/lib/api", () => ({
  getUnreadInsightsCount: (...args: unknown[]) =>
    mockGetUnreadInsightsCount(...args),
  getInsightDetail: (...args: unknown[]) => mockGetInsightDetail(...args),
  getApiBaseUrl: () => "",
  apiFetch: (url: string, options?: RequestInit) => global.fetch(url, { ...options, credentials: "include" }),
}));

// Mock fetch for insights list
const originalFetch = global.fetch;
const mockFetch = jest.fn();

import { Sidebar } from "@/components/layout/sidebar";
import BriefsPage from "@/app/dashboard/briefs/page";

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  global.fetch = mockFetch;
  mockGetUnreadInsightsCount.mockResolvedValue(0);
  mockFetch.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ insights: [], total: 0 }),
  });
});

afterEach(() => {
  jest.runOnlyPendingTimers();
  jest.useRealTimers();
  global.fetch = originalFetch;
});

describe("Sidebar unread badge", () => {
  it("shows unread badge when count > 0", async () => {
    mockGetUnreadInsightsCount.mockResolvedValue(5);

    await act(async () => {
      render(<Sidebar />);
    });

    await waitFor(() => {
      expect(screen.getByText("5")).toBeInTheDocument();
    });
  });

  it("does not show badge when count is 0", async () => {
    mockGetUnreadInsightsCount.mockResolvedValue(0);

    await act(async () => {
      render(<Sidebar />);
    });

    // Wait for fetch to complete
    await waitFor(() => {
      expect(mockGetUnreadInsightsCount).toHaveBeenCalled();
    });

    expect(screen.queryByLabelText(/unread/i)).not.toBeInTheDocument();
  });

  it("shows 99+ for large counts", async () => {
    mockGetUnreadInsightsCount.mockResolvedValue(150);

    await act(async () => {
      render(<Sidebar />);
    });

    await waitFor(() => {
      expect(screen.getByText("99+")).toBeInTheDocument();
    });
  });

  it("has aria-label with unread count", async () => {
    mockGetUnreadInsightsCount.mockResolvedValue(3);

    await act(async () => {
      render(<Sidebar />);
    });

    await waitFor(() => {
      expect(screen.getByLabelText("3 unread")).toBeInTheDocument();
    });
  });

  it("silently handles fetch errors", async () => {
    mockGetUnreadInsightsCount.mockRejectedValue(new Error("Network error"));

    await act(async () => {
      render(<Sidebar />);
    });

    // Should not show badge and should not throw
    await waitFor(() => {
      expect(mockGetUnreadInsightsCount).toHaveBeenCalled();
    });

    expect(screen.queryByLabelText(/unread/i)).not.toBeInTheDocument();
  });

  it("shows Daily Briefs nav item", async () => {
    await act(async () => {
      render(<Sidebar />);
    });

    expect(screen.getByText("Daily Briefs")).toBeInTheDocument();
  });
});

describe("Briefs page filter tabs", () => {
  const mockInsights = [
    {
      id: "brief-1",
      analysis_type: "daily_brief",
      title: "Daily Brief - Jan 15, 2026",
      content: "Your glucose was stable today.",
      created_at: "2026-01-15T12:00:00Z",
      status: "pending",
    },
    {
      id: "brief-2",
      analysis_type: "daily_brief",
      title: "Daily Brief - Jan 14, 2026",
      content: "Your glucose had some highs.",
      created_at: "2026-01-14T12:00:00Z",
      status: "acknowledged",
    },
    {
      id: "meal-1",
      analysis_type: "meal_analysis",
      title: "Meal Pattern Analysis - 3 spikes",
      content: "Post-meal spikes detected.",
      created_at: "2026-01-15T10:00:00Z",
      status: "pending",
    },
  ];

  beforeEach(() => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ insights: mockInsights, total: 3 }),
    });
  });

  it("shows All Insights tab by default", async () => {
    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("AI Insights")).toBeInTheDocument();
    });

    expect(screen.getByRole("tab", { name: /all insights/i })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("shows Daily Briefs filter tab with count", async () => {
    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(
        screen.getByRole("tab", { name: /daily briefs/i })
      ).toBeInTheDocument();
    });
  });

  it("shows all insights when All tab is selected", async () => {
    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(
        screen.getByText("Daily Brief - Jan 15, 2026")
      ).toBeInTheDocument();
    });

    expect(
      screen.getByText("Meal Pattern Analysis - 3 spikes")
    ).toBeInTheDocument();
  });

  it("filters to only daily briefs when Daily Briefs tab is clicked", async () => {
    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(
        screen.getByRole("tab", { name: /daily briefs/i })
      ).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /daily briefs/i }));
    });

    // Header should change
    expect(
      screen.getByRole("heading", { name: "Daily Briefs" })
    ).toBeInTheDocument();
    expect(
      screen.getByText("AI-generated daily summaries of your glucose data")
    ).toBeInTheDocument();

    // Briefs should be visible
    expect(
      screen.getByText("Daily Brief - Jan 15, 2026")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Daily Brief - Jan 14, 2026")
    ).toBeInTheDocument();

    // Meal analysis should NOT be visible
    expect(
      screen.queryByText("Meal Pattern Analysis - 3 spikes")
    ).not.toBeInTheDocument();
  });

  it("shows pending badge on Daily Briefs tab when there are unread briefs", async () => {
    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      // The pending brief count badge (1 pending brief)
      expect(screen.getByText("1")).toBeInTheDocument();
    });
  });

  it("switches back to all insights when All tab is clicked", async () => {
    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(
        screen.getByRole("tab", { name: /daily briefs/i })
      ).toBeInTheDocument();
    });

    // Switch to daily briefs
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /daily briefs/i }));
    });

    // Switch back to all
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /all insights/i }));
    });

    expect(screen.getByText("AI Insights")).toBeInTheDocument();
    expect(
      screen.getByText("Meal Pattern Analysis - 3 spikes")
    ).toBeInTheDocument();
  });

  it("shows filtered empty state when no daily briefs exist", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        insights: [
          {
            id: "meal-1",
            analysis_type: "meal_analysis",
            title: "Meal Analysis",
            content: "content",
            created_at: "2026-01-15T10:00:00Z",
            status: "pending",
          },
        ],
        total: 1,
      }),
    });

    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(
        screen.getByRole("tab", { name: /daily briefs/i })
      ).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /daily briefs/i }));
    });

    expect(screen.getByText("No Daily Briefs Yet")).toBeInTheDocument();
  });
});

describe("Briefs page loading and error states", () => {
  it("shows loading state", async () => {
    mockFetch.mockReturnValue(new Promise(() => {}));

    await act(async () => {
      render(<BriefsPage />);
    });

    expect(screen.getByText("Loading insights...")).toBeInTheDocument();
  });

  it("shows error state on fetch failure", async () => {
    mockFetch.mockRejectedValue(new Error("Network error"));

    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });

  it("shows empty state when no insights", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ insights: [], total: 0 }),
    });

    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("No Insights Yet")).toBeInTheDocument();
    });
  });

  it("does not show filter tabs when no insights", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ insights: [], total: 0 }),
    });

    await act(async () => {
      render(<BriefsPage />);
    });

    await waitFor(() => {
      expect(screen.getByText("No Insights Yet")).toBeInTheDocument();
    });

    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});
