import { STATIC_ASSET_ICON_SPRITE_PATH } from "@/lib/staticAssets";
import { fireEvent, render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { useUserContext } from "@/providers/user-provider";
import { useMealIntelligence } from "@/hooks/use-meal-intelligence";
import { getUnreadInsightsCount } from "@/lib/api";
import { Sidebar } from "./Sidebar";

jest.mock("next/navigation", () => ({
  usePathname: jest.fn(() => "/dashboard"),
}));

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

jest.mock("@/providers/user-provider", () => {
  return {
    useUserContext: jest.fn(),
  };
});

jest.mock("@/hooks/use-meal-intelligence", () => ({
  useMealIntelligence: jest.fn(),
}));

jest.mock("@/lib/api", () => ({
  getUnreadInsightsCount: jest.fn(() => Promise.reject(new Error("offline"))),
  logoutUser: jest.fn(() => Promise.resolve()),
}));

const mockUseUserContext = useUserContext as jest.MockedFunction<
  typeof useUserContext
>;
const mockUseMealIntelligence = useMealIntelligence as jest.MockedFunction<
  typeof useMealIntelligence
>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;
const mockGetUnreadInsightsCount =
  getUnreadInsightsCount as jest.MockedFunction<typeof getUnreadInsightsCount>;

function renderSidebar() {
  return render(<Sidebar />);
}

beforeEach(() => {
  mockUsePathname.mockReturnValue("/dashboard");
  mockGetUnreadInsightsCount.mockRejectedValue(new Error("offline"));
  window.localStorage.clear();
  window.matchMedia = jest.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    addListener: jest.fn(),
    removeListener: jest.fn(),
    dispatchEvent: jest.fn(),
  }));
  mockUseUserContext.mockReturnValue({
    error: null,
    isLoading: false,
    refreshUser: jest.fn(),
    user: {
      created_at: "2026-01-01T00:00:00.000Z",
      disclaimer_acknowledged: true,
      disclaimer_version: "2026-01",
      display_name: "Daniel",
      email: "daniel@example.com",
      email_verified: true,
      id: "user-1",
      is_active: true,
      role: "diabetic",
    },
  });
  mockUseMealIntelligence.mockReturnValue({
    enabled: true,
    isLoading: false,
  });
});

describe("Sidebar", () => {
  it("links the logo to the dashboard", () => {
    renderSidebar();

    const logoLink = screen.getByRole("link", { name: "Lumose" });

    expect(logoLink).toHaveAttribute("href", "/dashboard");
    expect(logoLink).toHaveClass(
      "focus-visible:ring-2",
      "focus-visible:ring-border-active",
    );
  });

  it("collapses desktop navigation and swaps the toggle icon", () => {
    const { container } = renderSidebar();

    const sidebar = container.querySelector("aside");
    const collapseButton = screen.getByRole("button", {
      name: "Collapse sidebar",
    });

    expect(sidebar).toHaveClass("lg:w-64");
    expect(sidebar).toHaveAttribute("data-collapsed", "false");
    expect(collapseButton).toHaveAttribute("aria-expanded", "true");
    expect(collapseButton).toHaveClass("before:right-px");
    expect(collapseButton).not.toHaveClass("hover:bg-surface-primary");
    expect(collapseButton.querySelector("use")).toHaveAttribute(
      "href",
      `${STATIC_ASSET_ICON_SPRITE_PATH}#sidebar-collapse`,
    );

    fireEvent.click(collapseButton);

    const expandButton = screen.getByRole("button", {
      name: "Expand sidebar",
    });

    expect(sidebar).toHaveClass("lg:w-20");
    expect(sidebar).toHaveAttribute("data-collapsed", "true");
    expect(expandButton).toHaveAttribute("aria-expanded", "false");
    expect(expandButton).not.toHaveClass("mx-auto");
    expect(expandButton.querySelector("use")).toHaveAttribute(
      "href",
      `${STATIC_ASSET_ICON_SPRITE_PATH}#sidebar-expand`,
    );
  });

  it("fades logo and link text when collapsed", () => {
    renderSidebar();

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));

    const logo = screen.getByRole("img", { name: "Lumose" });
    const logoIcons = logo.querySelectorAll("svg");
    const logoIcon = logoIcons[0];
    const wordmarkIcon = logoIcons[1];
    const logoText = wordmarkIcon.parentElement;
    const activeLink = screen.getByRole("link", { name: "Dashboard" });
    const activeLinkText = screen.getByText("Dashboard");

    expect(logoText).toHaveClass(
      "lg:h-auto",
      "max-w-0",
      "opacity-0",
      "transition-[max-width,opacity]",
      "duration-200",
    );
    expect(logoText).toHaveClass("whitespace-nowrap");
    expect(wordmarkIcon).toHaveClass("w-[135px]", "h-auto", "ml-1.5", "mt-0.5");
    expect(wordmarkIcon.querySelector("use")).toHaveAttribute(
      "href",
      `${STATIC_ASSET_ICON_SPRITE_PATH}#logo-text`,
    );
    expect(screen.queryByText("Lumose")).not.toBeInTheDocument();
    expect(screen.queryByText("Glucose Monitoring")).not.toBeInTheDocument();
    expect(logoIcon).toHaveClass("w-[33px]", "h-auto");
    expect(logoIcon).not.toHaveClass("text-accent");
    expect(logoIcon.querySelector("use")).not.toBeInTheDocument();
    expect(logoIcon.querySelectorAll("path")).toHaveLength(3);
    expect(logoIcon.querySelector("linearGradient")).toBeInTheDocument();
    expect(activeLink).toHaveClass("gap-0", "pl-[22px]", "pr-0");
    expect(activeLink).not.toHaveClass("justify-center");
    expect(activeLinkText).toHaveClass("max-w-0", "opacity-0");
  });

  it("uses the open book icon for the Knowledge Base link", () => {
    renderSidebar();

    const knowledgeBaseLink = screen.getByRole("link", {
      name: "Knowledge Base",
    });

    expect(knowledgeBaseLink.querySelector("use")).toHaveAttribute(
      "href",
      `${STATIC_ASSET_ICON_SPRITE_PATH}#book-open`,
    );
  });

  it("keeps alert configuration out of the app navigation", () => {
    const { container } = renderSidebar();

    expect(
      container.querySelector('a[href="/dashboard/alerts"]'),
    ).not.toBeInTheDocument();
  });

  it("uses the chat bubbles icon for the AI Chat link", () => {
    renderSidebar();

    const aiChatLink = screen.getByRole("link", {
      name: "AI Chat",
    });

    expect(aiChatLink.querySelector("use")).toHaveAttribute(
      "href",
      `${STATIC_ASSET_ICON_SPRITE_PATH}#chat-bubbles`,
    );
  });

  it("uses the chart indicator radius and highlight colors for unread briefs", async () => {
    mockGetUnreadInsightsCount.mockResolvedValue(1);
    renderSidebar();

    const badge = await screen.findByLabelText("1 unread");

    expect(badge).toHaveClass(
      "h-5",
      "min-w-5",
      "rounded-panel",
      "bg-accent",
      "text-accent-foreground",
    );
    expect(badge).not.toHaveClass("rounded-pill", "bg-signal-error-fill");
  });

  it("keeps the logo fixed and prevents collapsed horizontal overflow", () => {
    const { container } = renderSidebar();

    const sidebar = container.querySelector("aside");
    const header = container.querySelector("aside > div");
    const nav = container.querySelector("nav");
    const appNavigationPanel = container.querySelector(
      '[data-navigation-panel="app"]',
    );

    expect(sidebar).toHaveClass("overflow-x-hidden");
    expect(header).toHaveClass(
      "h-dashboard-header-height",
      "justify-start",
      "px-[23.5px]",
      "after:inset-x-2",
      "after:border-border-default",
    );
    expect(header).not.toHaveClass("border-b");
    expect(nav).toHaveClass("overflow-hidden");
    expect(appNavigationPanel).toHaveClass(
      "overflow-x-hidden",
      "overflow-y-auto",
      "px-2",
    );

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));

    expect(header).toHaveClass(
      "h-dashboard-header-height",
      "justify-start",
      "px-[23.5px]",
      "after:inset-x-2",
    );
    expect(appNavigationPanel).toHaveClass("px-2");
    expect(
      screen.queryByRole("radiogroup", { name: "Theme selection" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the icon rail stable while expanding and collapsing", () => {
    const { container } = renderSidebar();

    const appNavigationPanel = container.querySelector(
      '[data-navigation-panel="app"]',
    );
    const activeLink = screen.getByRole("link", { name: "Dashboard" });
    const collapseButton = screen.getByRole("button", {
      name: "Collapse sidebar",
    });

    expect(appNavigationPanel).toHaveClass("px-2");
    expect(activeLink).toHaveClass("pl-[22px]");
    expect(collapseButton).not.toHaveClass("mx-auto");

    fireEvent.click(collapseButton);

    const collapsedActiveLink = screen.getByRole("link", {
      name: "Dashboard",
    });
    const expandButton = screen.getByRole("button", {
      name: "Expand sidebar",
    });

    expect(appNavigationPanel).toHaveClass("px-2");
    expect(collapsedActiveLink).toHaveClass("gap-0", "pl-[22px]", "pr-0");
    expect(collapsedActiveLink).not.toHaveClass("justify-center");
    expect(expandButton).not.toHaveClass("mx-auto");
  });

  it("keeps the sidebar mounted while transitioning to settings links", () => {
    const { container, rerender } = renderSidebar();
    const logo = screen.getByRole("img", {
      name: "Lumose",
    });

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    mockUsePathname.mockReturnValue("/settings/account");
    rerender(<Sidebar />);

    expect(screen.getByRole("img", { name: "Lumose" })).toBe(logo);
    expect(screen.getByRole("link", { name: "Lumose" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
    expect(container.querySelector("aside")).toHaveAttribute(
      "data-collapsed",
      "false",
    );
    expect(container.querySelector("aside")).toHaveClass("lg:w-64");
    expect(
      screen.queryByRole("button", { name: "Collapse sidebar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Expand sidebar" }),
    ).not.toBeInTheDocument();
    const settingsNavigationLinks = container.querySelector(
      '[data-navigation-mode="settings"]',
    );
    const appNavigationPanel = container.querySelector(
      '[data-navigation-panel="app"]',
    );
    const settingsNavigationPanel = container.querySelector(
      '[data-navigation-panel="settings"]',
    );
    expect(settingsNavigationLinks).toBeInTheDocument();
    expect(appNavigationPanel).toHaveAttribute("aria-hidden", "true");
    expect(appNavigationPanel).toHaveAttribute("inert");
    expect(appNavigationPanel).toHaveClass(
      "-translate-x-full",
      "pointer-events-none",
      "duration-300",
    );
    expect(settingsNavigationPanel).toHaveAttribute("aria-hidden", "false");
    expect(settingsNavigationPanel).not.toHaveAttribute("inert");
    expect(settingsNavigationPanel).toHaveClass(
      "translate-x-0",
      "duration-300",
      "ease-in-out",
    );
    expect(
      screen.getByRole("link", { name: "Go back to app" }),
    ).toHaveAttribute("href", "/dashboard");
    const backToAppLink = screen.getByRole("link", {
      name: "Go back to app",
    });
    const backToAppRegion = backToAppLink.parentElement;
    expect(backToAppLink).toHaveClass("text-foreground-primary");
    expect(backToAppLink).not.toHaveClass("rounded-panel");
    expect(backToAppLink.parentElement).toHaveClass(
      "h-dashboard-header-height",
      "border-b",
      "border-border-default",
    );
    expect(settingsNavigationPanel).toHaveClass("pb-4");
    expect(backToAppLink.querySelector("svg")).toHaveClass("rotate-180");
    expect(backToAppLink.querySelector("use")).toHaveAttribute(
      "href",
      `${STATIC_ASSET_ICON_SPRITE_PATH}#chevron`,
    );
    expect(screen.getByRole("link", { name: "Account" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Appearance" })).toHaveAttribute(
      "href",
      "/settings/appearance",
    );
    expect(
      screen.getByRole("link", { name: "Data & Privacy" }),
    ).toHaveAttribute("href", "/settings/data-privacy");
    expect(
      screen.queryByRole("radiogroup", { name: "Theme selection" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Dashboard" }),
    ).not.toBeInTheDocument();

    mockUsePathname.mockReturnValue("/dashboard");
    rerender(<Sidebar />);

    expect(container.querySelector('[data-navigation-mode="app"]')).toBe(
      settingsNavigationLinks,
    );
    expect(backToAppRegion).toBeInTheDocument();
    expect(backToAppRegion).toHaveClass(
      "h-dashboard-header-height",
      "border-border-default",
    );
    expect(
      screen.queryByRole("link", { name: "Go back to app" }),
    ).not.toBeInTheDocument();
    expect(appNavigationPanel).toHaveAttribute("aria-hidden", "false");
    expect(appNavigationPanel).not.toHaveAttribute("inert");
    expect(appNavigationPanel).toHaveClass("translate-x-0");
    expect(appNavigationPanel).not.toHaveClass("pointer-events-none");
    expect(settingsNavigationPanel).toHaveAttribute("aria-hidden", "true");
    expect(settingsNavigationPanel).toHaveAttribute("inert");
    expect(settingsNavigationPanel).toHaveClass(
      "translate-x-full",
      "pointer-events-none",
    );
    expect(container.querySelector("aside")).toHaveAttribute(
      "data-collapsed",
      "false",
    );
    expect(
      screen.getByRole("button", { name: "Collapse sidebar" }),
    ).toBeInTheDocument();
  });
});
