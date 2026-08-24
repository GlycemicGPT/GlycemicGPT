import { fireEvent, render, screen } from "@testing-library/react";
import { ThemeProvider } from "@/providers/theme-provider";
import { ThemeSwitcher } from "./ThemeSwitcher";

beforeEach(() => {
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
});

describe("ThemeSwitcher", () => {
  it("renders all theme choices as radio buttons", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="test-theme" />
      </ThemeProvider>,
    );

    expect(
      screen.getByRole("radiogroup", { name: "Theme selection" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Light theme" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Dark theme" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Dark theme 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Dark theme 2" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Dark theme 3" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("radio", { name: "System theme" }),
    ).not.toBeInTheDocument();
  });

  it("orders the primary themes before the dark variants", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="test-theme" />
      </ThemeProvider>,
    );

    expect(
      screen
        .getAllByRole("radio")
        .map((control) => control.getAttribute("aria-label")),
    ).toEqual([
      "Light theme",
      "Dark theme",
      "Dark theme 1",
      "Dark theme 2",
      "Dark theme 3",
    ]);
  });

  it("does not render a visual wrapper around the controls", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="test-theme" />
      </ThemeProvider>,
    );

    const switcher = screen.getByRole("radiogroup", {
      name: "Theme selection",
    });

    expect(switcher).toHaveClass("flex", "flex-col");
    expect(switcher).not.toHaveClass(
      "rounded-panel",
      "border",
      "border-border-default",
      "bg-surface-secondary",
      "p-[6px]",
    );
  });

  it("stores the selected theme when clicked", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="test-theme" />
      </ThemeProvider>,
    );

    fireEvent.click(screen.getByRole("radio", { name: "Dark theme" }));

    expect(window.localStorage.getItem("glycemicgpt-theme")).toBe("dark");
  });

  it("supports custom id prefixes", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="sidebar-theme" />
      </ThemeProvider>,
    );

    expect(screen.getByRole("radio", { name: "Light theme" })).toHaveAttribute(
      "id",
      "sidebar-theme-light",
    );
  });

  it("renders numbered variant controls with matching labels", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="test-theme" />
      </ThemeProvider>,
    );

    expect(
      screen.getByRole("radio", { name: "Dark theme 1" }),
    ).toHaveTextContent("1");
    expect(
      screen.getByRole("radio", { name: "Dark theme 2" }),
    ).toHaveTextContent("2");
    expect(
      screen.getByRole("radio", { name: "Dark theme 3" }),
    ).toHaveTextContent("3");
  });

  it("uses the navigation selected style for the active theme", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="test-theme" />
      </ThemeProvider>,
    );

    const darkTheme = screen.getByRole("radio", { name: "Dark theme" });

    fireEvent.click(darkTheme);

    const accentMarkers = darkTheme.querySelectorAll(
      "span[aria-hidden='true']",
    );

    expect(darkTheme).toHaveClass(
      "bg-surface-elevated",
      "text-foreground-primary",
    );
    expect(darkTheme).not.toHaveClass("bg-accent", "text-accent-foreground");
    expect(accentMarkers).toHaveLength(2);
    expect(accentMarkers[0]).toHaveClass("bg-accent", "opacity-100");
  });

  it("matches the dashboard navigation icon size", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="test-theme" />
      </ThemeProvider>,
    );

    const lightThemeIcon = screen
      .getByRole("radio", { name: "Light theme" })
      .querySelector("svg");

    expect(lightThemeIcon).toHaveClass("h-5", "w-5");
  });

  it("renders labeled theme previews for settings", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="settings-theme" variant="settings" />
      </ThemeProvider>,
    );

    const switcher = screen.getByRole("radiogroup", {
      name: "Theme selection",
    });
    const systemTheme = screen.getByRole("radio", { name: "System theme" });
    const lightTheme = screen.getByRole("radio", { name: "Light theme" });
    const systemPreview = systemTheme.querySelector(
      '[data-theme-preview="system"]',
    );
    const lightPreview = lightTheme.querySelector(
      '[data-theme-preview="light"]',
    );

    expect(switcher).toHaveClass("space-y-8");
    expect(switcher.firstElementChild).toHaveClass(
      "grid-cols-3",
      "gap-3",
      "sm:gap-5",
    );
    expect(
      screen
        .getAllByRole("radio")
        .map((control) => control.getAttribute("aria-label")),
    ).toEqual([
      "System theme",
      "Dark theme",
      "Light theme",
      "Dark theme 1",
      "Dark theme 2",
      "Dark theme 3",
    ]);
    expect(systemTheme).toHaveAttribute("aria-checked", "true");
    expect(lightTheme).toHaveAttribute("aria-checked", "false");
    expect(systemPreview?.querySelector(".theme-light")).toBeInTheDocument();
    expect(systemPreview?.querySelector(".theme-dark")).toBeInTheDocument();
    expect(systemPreview?.querySelectorAll("linearGradient")).toHaveLength(2);
    expect(systemPreview?.querySelector("use")).not.toBeInTheDocument();
    expect(lightTheme.querySelectorAll("linearGradient")).toHaveLength(1);
    expect(lightTheme.querySelector("use")).not.toBeInTheDocument();
    expect(
      lightTheme.querySelector('[data-theme-preview-panel="light"]'),
    ).toBeInTheDocument();
    expect(lightPreview).toHaveClass("aspect-square", "sm:aspect-[13/6]");
    expect(lightPreview?.textContent).toBe("");
    expect(lightPreview?.querySelector("svg")).toHaveClass("text-accent");
    expect(
      screen.getByRole("heading", { level: 3, name: "Additional themes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "Additional themes" })
        .nextElementSibling,
    ).toHaveClass("grid-cols-3", "gap-3", "sm:gap-5");
    expect(screen.getByRole("separator")).toHaveClass(
      "border-t",
      "border-border-default",
    );
    expect(screen.getByText("Light")).toHaveClass("font_nav_link");
  });

  it("stores the system theme preference when selected", () => {
    window.localStorage.setItem("glycemicgpt-theme", "dark");

    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="settings-theme" variant="settings" />
      </ThemeProvider>,
    );

    fireEvent.click(screen.getByRole("radio", { name: "System theme" }));

    expect(window.localStorage.getItem("glycemicgpt-theme")).toBe("system");
    expect(screen.getByRole("radio", { name: "System theme" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(document.documentElement).toHaveClass("light", "theme-light");
    expect(document.documentElement).not.toHaveClass(
      "theme-dark-1",
      "theme-dark-2",
      "theme-dark-3",
    );
  });

  it("falls back to system for a removed light theme preference", () => {
    window.localStorage.setItem("glycemicgpt-theme", "light-1");

    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="settings-theme" variant="settings" />
      </ThemeProvider>,
    );

    expect(screen.getByRole("radio", { name: "System theme" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(document.documentElement).toHaveClass("light", "theme-light");
  });

  it("keeps numbered badges absolute so icons stay centered", () => {
    render(
      <ThemeProvider>
        <ThemeSwitcher idPrefix="test-theme" />
      </ThemeProvider>,
    );

    const darkThemeVariant = screen.getByRole("radio", {
      name: "Dark theme 1",
    });
    const badge = Array.from(darkThemeVariant.querySelectorAll("span")).find(
      (span) => span.textContent === "1",
    );

    expect(darkThemeVariant).toHaveClass(
      "relative",
      "items-center",
      "justify-center",
    );
    expect(badge).toHaveClass("absolute", "right-3", "top-1/2");
  });
});
