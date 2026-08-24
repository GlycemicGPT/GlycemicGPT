import { render, screen } from "@testing-library/react";

import { LumoseLogoTextIcon } from "./LumoseLogoTextIcon";

describe("LumoseLogoTextIcon", () => {
  it("owns its wordmark, logo geometry, and semantic gradient", () => {
    const { container } = render(<LumoseLogoTextIcon />);
    const logo = screen.getByRole("img", { name: "Lumose" });
    const gradient = container.querySelector("linearGradient");
    const stops = container.querySelectorAll("stop");
    const logoGroup = container.querySelector("g");
    const gradientPaths = logoGroup?.querySelectorAll("path");

    expect(logo).toHaveAttribute("viewBox", "0 0 342.06 54.91");
    expect(container.querySelector("use")).not.toBeInTheDocument();
    expect(container.querySelector("polygon")).toHaveAttribute(
      "fill",
      "currentColor",
    );
    expect(container.querySelectorAll("svg > path")).toHaveLength(4);
    expect(logoGroup).toHaveAttribute(
      "transform",
      "translate(183.98 7.42) scale(0.1952)",
    );
    expect(gradientPaths).toHaveLength(3);
    gradientPaths?.forEach((path) => {
      expect(path).toHaveAttribute("fill", `url(#${gradient?.id})`);
    });
    expect(stops[0]).toHaveAttribute(
      "stop-color",
      "var(--color-brand-gradient-start)",
    );
    expect(stops[1]).toHaveAttribute(
      "stop-color",
      "var(--color-brand-gradient-middle)",
    );
    expect(stops[2]).toHaveAttribute(
      "stop-color",
      "var(--color-brand-gradient-end)",
    );
  });

  it("creates unique gradient references for multiple logos", () => {
    const { container } = render(
      <>
        <LumoseLogoTextIcon decorative />
        <LumoseLogoTextIcon decorative />
      </>,
    );
    const gradients = container.querySelectorAll("linearGradient");
    const groups = container.querySelectorAll("svg > g");

    expect(gradients[0].id).not.toBe(gradients[1].id);
    expect(groups[0].querySelector("path")).toHaveAttribute(
      "fill",
      `url(#${gradients[0].id})`,
    );
    expect(groups[1].querySelector("path")).toHaveAttribute(
      "fill",
      `url(#${gradients[1].id})`,
    );
  });

  it("supports decorative rendering and class overrides", () => {
    const { container } = render(
      <LumoseLogoTextIcon className="h-10 w-64" decorative />,
    );
    const logo = container.querySelector("svg");

    expect(logo).toHaveAttribute("aria-hidden", "true");
    expect(logo).not.toHaveAttribute("aria-label");
    expect(logo).not.toHaveAttribute("role");
    expect(logo).toHaveClass("h-10", "w-64");
    expect(logo).not.toHaveClass("h-auto", "w-52");
  });
});
