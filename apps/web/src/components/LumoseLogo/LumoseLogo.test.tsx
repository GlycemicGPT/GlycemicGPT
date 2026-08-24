import { STATIC_ASSET_ICON_SPRITE_PATH } from "@/lib/staticAssets";
import { fireEvent, render, screen } from "@testing-library/react";

import { LumoseLogo } from "./LumoseLogo";

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

describe("LumoseLogo", () => {
  it("links the accessible logo to the dashboard", () => {
    render(<LumoseLogo />);

    const link = screen.getByRole("link", { name: "Lumose" });

    expect(link).toHaveAttribute("href", "/dashboard");
    expect(link).toHaveClass(
      "focus-visible:ring-2",
      "focus-visible:ring-border-active",
    );
    expect(link.querySelector("linearGradient")).toBeInTheDocument();
    expect(
      link.querySelectorAll("svg")[0].querySelectorAll("path"),
    ).toHaveLength(3);
    expect(link.querySelectorAll("use")).toHaveLength(1);
    expect(link.querySelector("use")).toHaveAttribute(
      "href",
      `${STATIC_ASSET_ICON_SPRITE_PATH}#logo-text`,
    );
  });

  it("hides the wordmark while preserving the logo link when collapsed", () => {
    render(<LumoseLogo collapsed />);

    const logo = screen.getByRole("img", { name: "Lumose" });
    const wordmarkContainer = logo.querySelectorAll("svg")[1].parentElement;

    expect(logo).toHaveClass("gap-0");
    expect(wordmarkContainer).toHaveClass(
      "h-0",
      "lg:h-auto",
      "max-w-0",
      "opacity-0",
      "transition-[max-width,opacity]",
      "duration-200",
      "motion-reduce:transition-none",
    );
  });

  it("emits clicks from the dashboard link", () => {
    const handleClick = jest.fn();
    render(<LumoseLogo onClick={handleClick} />);

    fireEvent.click(screen.getByRole("link", { name: "Lumose" }));

    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
