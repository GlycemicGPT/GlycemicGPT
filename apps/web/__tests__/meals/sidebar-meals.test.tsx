/**
 * Tests the flag-gated Meals nav item: present only when meal intelligence is
 * enabled, hidden while the probe is loading or when disabled, and never for
 * caregivers.
 */

import { render, screen } from "@testing-library/react";

jest.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

jest.mock("next/link", () => {
  const Link = ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  );
  Link.displayName = "Link";
  return Link;
});

jest.mock("next/image", () => {
  const NextImage = (props: Record<string, unknown>) => {
    // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
    return <img {...props} />;
  };
  NextImage.displayName = "NextImage";
  return { __esModule: true, default: NextImage };
});

const mockUser = jest.fn();
const mockMeal = jest.fn();
jest.mock("@/providers", () => ({
  useUserContext: () => mockUser(),
  useMealIntelligenceContext: () => mockMeal(),
}));

jest.mock("@/lib/api", () => ({
  __esModule: true,
  getUnreadInsightsCount: jest.fn().mockResolvedValue(0),
}));

import { Sidebar } from "@/components/layout/sidebar";

describe("Sidebar Meals nav gating", () => {
  beforeEach(() => {
    mockUser.mockReset();
    mockMeal.mockReset();
    mockUser.mockReturnValue({ user: { role: "diabetic" } });
  });

  it("shows the Meals item when meal intelligence is enabled", async () => {
    mockMeal.mockReturnValue({ enabled: true, isLoading: false });
    render(<Sidebar />);
    const meals = await screen.findByText("Meals");
    expect(meals.closest("a")).toHaveAttribute("href", "/dashboard/meals");
  });

  it("hides the Meals item while the flag probe is still loading", () => {
    mockMeal.mockReturnValue({ enabled: null, isLoading: true });
    render(<Sidebar />);
    expect(screen.queryByText("Meals")).not.toBeInTheDocument();
  });

  it("hides the Meals item when meal intelligence is disabled", () => {
    mockMeal.mockReturnValue({ enabled: false, isLoading: false });
    render(<Sidebar />);
    expect(screen.queryByText("Meals")).not.toBeInTheDocument();
  });

  it("never shows the Meals item for a caregiver", () => {
    mockUser.mockReturnValue({ user: { role: "caregiver" } });
    mockMeal.mockReturnValue({ enabled: true, isLoading: false });
    render(<Sidebar />);
    expect(screen.queryByText("Meals")).not.toBeInTheDocument();
  });
});
