import { fireEvent, render, screen } from "@testing-library/react";
import { PrimaryButton } from "./PrimaryButton";

describe("PrimaryButton", () => {
  it("renders through the Base button with default button behavior", () => {
    render(<PrimaryButton>Connect</PrimaryButton>);

    const button = screen.getByRole("button", { name: "Connect" });

    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("bg-surface-inverse");
    expect(button).toHaveClass("text-foreground-inverse");
    expect(button).toHaveClass("rounded-button");
    expect(button).not.toHaveClass("active:bg-surface-secondary");
    expect(button).not.toHaveClass("active:text-foreground-primary");
    expect(button).toHaveClass("h-10");
  });

  it("renders disabled styling when disabled", () => {
    render(<PrimaryButton disabled>Connect</PrimaryButton>);

    const button = screen.getByRole("button", { name: "Connect" });

    expect(button).toBeDisabled();
    expect(button).toHaveClass("disabled:opacity-50");
    expect(button).toHaveClass("disabled:cursor-not-allowed");
    expect(button).not.toHaveClass("disabled:pointer-events-none");
  });

  it("forwards click handlers", () => {
    const onClick = jest.fn();

    render(<PrimaryButton onClick={onClick}>Save</PrimaryButton>);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
