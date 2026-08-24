import { render, screen } from "@testing-library/react";
import { LumoseLogoIcon } from "./LumoseLogoIcon";

describe("LumoseLogoIcon", () => {
  it("renders the shared logo geometry with the semantic gradient color", () => {
    const { container } = render(<LumoseLogoIcon />);
    const logo = screen.getByRole("img", { name: "Lumose logo" });
    const gradient = container.querySelector("linearGradient");
    const stops = container.querySelectorAll("stop");
    const paths = container.querySelectorAll("svg > path");

    expect(logo).toHaveAttribute("viewBox", "0 0 268.88 243.31");
    expect(gradient).toHaveAttribute("gradientUnits", "userSpaceOnUse");
    expect(gradient).toHaveAttribute("x1", "268.88");
    expect(gradient).toHaveAttribute("y1", "0");
    expect(gradient).toHaveAttribute("x2", "0");
    expect(gradient).toHaveAttribute("y2", "243.31");
    expect(stops).toHaveLength(3);
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
    expect(stops[0]).not.toHaveAttribute("stop-opacity");
    expect(stops[1]).not.toHaveAttribute("stop-opacity");
    expect(stops[2]).not.toHaveAttribute("stop-opacity");
    expect(container.querySelector("use")).not.toBeInTheDocument();
    expect(paths).toHaveLength(3);
    paths.forEach((path) => {
      expect(path).toHaveAttribute("fill", `url(#${gradient?.id})`);
    });
  });

  it("creates unique gradient references for multiple logos", () => {
    const { container } = render(
      <>
        <LumoseLogoIcon decorative />
        <LumoseLogoIcon decorative />
      </>,
    );
    const gradients = container.querySelectorAll("linearGradient");
    const logos = container.querySelectorAll("svg");

    expect(gradients[0].id).not.toBe(gradients[1].id);
    expect(logos[0].querySelector("path")).toHaveAttribute(
      "fill",
      `url(#${gradients[0].id})`,
    );
    expect(logos[1].querySelector("path")).toHaveAttribute(
      "fill",
      `url(#${gradients[1].id})`,
    );
  });

  it("supports decorative rendering and class overrides", () => {
    const { container } = render(
      <LumoseLogoIcon className="h-8 w-8" decorative />,
    );
    const logo = container.querySelector("svg");

    expect(logo).toHaveAttribute("aria-hidden", "true");
    expect(logo).not.toHaveAttribute("aria-label");
    expect(logo).not.toHaveAttribute("role");
    expect(logo).toHaveClass("h-8", "w-8");
    expect(logo).not.toHaveClass("h-10", "w-10");
  });
});
