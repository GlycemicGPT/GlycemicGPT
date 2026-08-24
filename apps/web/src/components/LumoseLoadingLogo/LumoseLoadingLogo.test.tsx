import { render, screen } from "@testing-library/react";
import { LumoseLoadingLogo } from "./LumoseLoadingLogo";

describe("LumoseLoadingLogo", () => {
  it("uses the theme mapped brand color", () => {
    render(<LumoseLoadingLogo label="Loading content" />);

    expect(screen.getByRole("status", { name: "Loading content" })).toHaveClass(
      "h-12",
      "w-12",
      "text-brand-gradient-middle",
    );
  });

  it("uses the shared logo geometry for its base and animated paint", () => {
    const { container } = render(<LumoseLoadingLogo />);
    const paths = container.querySelectorAll("svg path");
    const animatedGradients = container.querySelectorAll(
      ".lumose-loading-logo-flow",
    );
    const filteredGroup = container.querySelector("g[filter]");

    expect(container.querySelector("use")).not.toBeInTheDocument();
    expect(paths).toHaveLength(6);
    expect(animatedGradients).toHaveLength(1);
    expect(animatedGradients[0]).toHaveAttribute(
      "gradientUnits",
      "userSpaceOnUse",
    );
    for (const stop of container.querySelectorAll("stop")) {
      expect(stop).toHaveAttribute(
        "stop-color",
        "var(--color-brand-highlight)",
      );
    }
    expect(container.querySelector('g[fill="currentColor"]')).toHaveAttribute(
      "fill-opacity",
      "0.42",
    );
    expect(filteredGroup).toHaveAttribute(
      "filter",
      `url(#${container.querySelector("filter")?.id})`,
    );
  });

  it("adds semantic shadow, accent glow, and color brightening", () => {
    const { container } = render(<LumoseLoadingLogo />);
    const shadowColor = container.querySelector("feFlood");
    const glow = container.querySelector('feGaussianBlur[in="SourceGraphic"]');
    const colorChannels = container.querySelectorAll(
      "feComponentTransfer feFuncR, feComponentTransfer feFuncG, feComponentTransfer feFuncB",
    );

    expect(shadowColor).toHaveAttribute(
      "flood-color",
      "var(--color-surface-fixed-dark)",
    );
    expect(shadowColor).toHaveAttribute("flood-opacity", "0.52");
    expect(glow).toHaveAttribute("stdDeviation", "4");
    expect(colorChannels).toHaveLength(3);
    for (const channel of colorChannels) {
      expect(channel).toHaveAttribute("slope", "1.24");
      expect(channel).toHaveAttribute("intercept", "0.04");
    }
  });

  it("creates unique paint references for multiple loaders", () => {
    const { container } = render(
      <>
        <LumoseLoadingLogo />
        <LumoseLoadingLogo />
      </>,
    );
    const gradients = container.querySelectorAll("linearGradient");
    const filters = container.querySelectorAll("filter");

    expect(gradients[0].id).not.toBe(gradients[1].id);
    expect(filters[0].id).not.toBe(filters[1].id);
  });

  it("supports size class overrides", () => {
    render(<LumoseLoadingLogo className="h-16 w-16" />);

    const loader = screen.getByRole("status", { name: "Loading" });
    expect(loader).toHaveClass("h-16", "w-16");
    expect(loader).not.toHaveClass("h-12", "w-12");
  });
});
