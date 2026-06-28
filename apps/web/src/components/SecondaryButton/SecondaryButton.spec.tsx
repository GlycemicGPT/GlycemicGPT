import { fireEvent, render, screen } from "@testing-library/react";
import { Icon } from "@/base/Icon";
import { SecondaryButton } from "./SecondaryButton";

describe("SecondaryButton", () => {
  it("renders through the Base button with smaller muted styling", () => {
    render(<SecondaryButton>Cancel</SecondaryButton>);

    const button = screen.getByRole("button", { name: "Cancel" });

    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("h-8");
    expect(button).toHaveClass("font_metric_caption");
    expect(button).toHaveClass("whitespace-nowrap");
    expect(button).toHaveClass("rounded-button");
    expect(button).toHaveClass("border-border-default");
    expect(button).toHaveClass("bg-surface-primary");
    expect(button).toHaveClass("text-foreground-primary");
    expect(button).toHaveClass("hover:bg-surface-secondary");
    expect(button).not.toHaveClass("active:bg-surface-inverse");
    expect(button).not.toHaveClass("active:text-foreground-inverse");
  });

  it("renders disabled styling when disabled", () => {
    render(<SecondaryButton disabled>Cancel</SecondaryButton>);

    const button = screen.getByRole("button", { name: "Cancel" });

    expect(button).toBeDisabled();
    expect(button).toHaveClass("disabled:opacity-50");
    expect(button).toHaveClass("disabled:cursor-not-allowed");
    expect(button).not.toHaveClass("disabled:pointer-events-none");
  });

  it("scales icons down in the icon size", () => {
    render(
      <SecondaryButton ariaLabel="Approve" size="icon">
        <Icon decorative icon="thumbsup" />
      </SecondaryButton>,
    );

    const button = screen.getByRole("button", { name: "Approve" });

    expect(button).toHaveClass("[&>svg]:h-4");
    expect(button).toHaveClass("[&>svg]:w-4");
  });

  it("forwards click handlers", () => {
    const onClick = jest.fn();

    render(<SecondaryButton onClick={onClick}>Cancel</SecondaryButton>);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
