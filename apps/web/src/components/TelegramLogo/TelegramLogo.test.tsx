import { render, screen } from "@testing-library/react";

import { TelegramLogo } from "./TelegramLogo";

const telegramPlanePath =
  "M22.987 10.209c.124-.806-.642-1.441-1.358-1.127L7.365 15.345c-.514.225-.476 1.003.056 1.173l2.942.937c.562.179 1.17.086 1.66-.253l6.632-4.582c.2-.138.418.147.247.323l-4.774 4.922c-.463.477-.371 1.286.186 1.636l5.345 3.351c.6.376 1.37-.001 1.483-.726z";

describe("TelegramLogo", () => {
  it("owns its gradient and Telegram geometry", () => {
    const { container } = render(<TelegramLogo />);
    const logo = screen.getByRole("img", { name: "Telegram" });
    const gradient = container.querySelector("linearGradient");
    const circle = container.querySelector("circle");
    const plane = container.querySelector("path");
    const stops = container.querySelectorAll("stop");

    expect(logo).toHaveAttribute("viewBox", "0 0 32 32");
    expect(container.querySelector("use")).not.toBeInTheDocument();
    expect(gradient).toHaveAttribute("gradientUnits", "userSpaceOnUse");
    expect(gradient).toHaveAttribute("x1", "16");
    expect(gradient).toHaveAttribute("x2", "16");
    expect(gradient).toHaveAttribute("y1", "2");
    expect(gradient).toHaveAttribute("y2", "30");
    expect(stops[0]).toHaveAttribute(
      "stop-color",
      "var(--color-brand-telegram-gradient-start)",
    );
    expect(stops[1]).toHaveAttribute(
      "stop-color",
      "var(--color-brand-telegram-gradient-end)",
    );
    expect(circle).toHaveAttribute("fill", `url(#${gradient?.id})`);
    expect(plane).toHaveAttribute(
      "fill",
      "var(--color-brand-telegram-foreground)",
    );
    expect(plane).toHaveAttribute("d", telegramPlanePath);
  });

  it("creates unique gradient references for multiple logos", () => {
    const { container } = render(
      <>
        <TelegramLogo decorative />
        <TelegramLogo decorative />
      </>,
    );
    const gradients = container.querySelectorAll("linearGradient");
    const circles = container.querySelectorAll("circle");

    expect(gradients[0].id).not.toBe(gradients[1].id);
    expect(circles[0]).toHaveAttribute("fill", `url(#${gradients[0].id})`);
    expect(circles[1]).toHaveAttribute("fill", `url(#${gradients[1].id})`);
  });

  it("supports decorative rendering and class overrides", () => {
    const { container } = render(
      <TelegramLogo className="h-8 w-8" decorative />,
    );
    const logo = container.querySelector("svg");

    expect(logo).toHaveAttribute("aria-hidden", "true");
    expect(logo).not.toHaveAttribute("aria-label");
    expect(logo).not.toHaveAttribute("role");
    expect(logo).toHaveClass("h-8", "w-8");
    expect(logo).not.toHaveClass("h-6", "w-6");
  });
});
