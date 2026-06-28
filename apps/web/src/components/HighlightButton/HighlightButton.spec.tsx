import { fireEvent, render, screen } from "@testing-library/react";
import { HighlightButton } from "./HighlightButton";

describe("HighlightButton", () => {
  it("renders the accent highlight styling with default button behavior", () => {
    render(<HighlightButton>Connect</HighlightButton>);

    const button = screen.getByRole("button", { name: "Connect" });

    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("bg-accent");
    expect(button).toHaveClass("rounded-button");
    expect(button).not.toHaveClass("active:bg-accent-active");
    expect(button).not.toHaveClass("active:text-foreground-inverse");
    expect(button).toHaveClass("h-10");
  });

  it("renders disabled styling when disabled", () => {
    render(<HighlightButton disabled>Connect</HighlightButton>);

    const button = screen.getByRole("button", { name: "Connect" });

    expect(button).toBeDisabled();
    expect(button).toHaveClass("disabled:opacity-50");
    expect(button).toHaveClass("disabled:cursor-not-allowed");
    expect(button).not.toHaveClass("disabled:pointer-events-none");
  });

  it("forwards click handlers", () => {
    const onClick = jest.fn();

    render(<HighlightButton onClick={onClick}>Save</HighlightButton>);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
