import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ThemeProvider, useTheme } from "@/providers/theme-provider";

function ThemeProbe() {
  const { resolvedTheme, setTheme, theme } = useTheme();

  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved-theme">{resolvedTheme}</span>
      <button type="button" onClick={() => setTheme("dark")}>
        Dark
      </button>
      <button type="button" onClick={() => setTheme("light")}>
        Light
      </button>
    </div>
  );
}

describe("ThemeProvider", () => {
  const matchMedia = jest.fn();

  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = "";
    matchMedia.mockReturnValue({
      addEventListener: jest.fn(),
      matches: false,
      removeEventListener: jest.fn(),
    });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: matchMedia,
    });
  });

  it("applies the stored dark theme to the html element", async () => {
    localStorage.setItem("glycemicgpt-theme", "dark");
    document.documentElement.className = "light";

    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(document.documentElement).toHaveClass("dark");
      expect(document.documentElement).not.toHaveClass("light");
    });
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    expect(screen.getByTestId("resolved-theme")).toHaveTextContent("dark");
  });

  it("persists light and dark theme changes", async () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Dark" }));

    await waitFor(() => {
      expect(document.documentElement).toHaveClass("dark");
    });
    expect(localStorage.getItem("glycemicgpt-theme")).toBe("dark");

    fireEvent.click(screen.getByRole("button", { name: "Light" }));

    await waitFor(() => {
      expect(document.documentElement).toHaveClass("light");
      expect(document.documentElement).not.toHaveClass("dark");
    });
    expect(localStorage.getItem("glycemicgpt-theme")).toBe("light");
  });
});
