import { fireEvent, render, screen } from "@testing-library/react";
import { Checkbox } from "./Checkbox";

describe("Checkbox", () => {
  it("renders a labelled checkbox and reports checked changes", () => {
    const onCheckedChange = jest.fn();

    render(
      <Checkbox
        checked={false}
        label="Show source"
        onCheckedChange={onCheckedChange}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Show source" }));

    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it("toggles the native checkbox state on user interaction when uncontrolled", () => {
    render(<Checkbox label="Show source" />);

    const checkbox = screen.getByRole("checkbox", { name: "Show source" });

    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();

    fireEvent.click(checkbox);
    expect(checkbox).not.toBeChecked();
  });

  it("reflects defaultChecked as the initial checked state", () => {
    render(<Checkbox defaultChecked label="Show source" />);

    expect(screen.getByRole("checkbox", { name: "Show source" })).toBeChecked();
  });

  it("wires the hidden input as the peer that drives the visual indicator", () => {
    render(<Checkbox label="Show source" />);

    const checkbox = screen.getByRole("checkbox", { name: "Show source" });
    const indicator = screen.getByText("Show source").previousElementSibling;

    expect(checkbox).toHaveClass("peer", "sr-only");
    expect(indicator).toHaveAttribute("aria-hidden", "true");
    expect(checkbox.nextElementSibling).toBe(indicator);
  });

  it("aligns the visual checkbox with the first line of wrapped label text", () => {
    render(<Checkbox checked={false} label="Long label text that wraps across lines" />);

    const label = screen.getByText("Long label text that wraps across lines");

    expect(label.closest("label")).toHaveClass("items-start");
    expect(label.previousElementSibling).toHaveClass("mt-1", "shrink-0");
  });

  it("applies disabled state to the input and wrapper", () => {
    render(<Checkbox checked disabled label="Disabled option" labelClassName="custom-label" />);

    expect(screen.getByRole("checkbox", { name: "Disabled option" })).toBeDisabled();
    expect(screen.getByText("Disabled option").closest("label")).toHaveClass(
      "cursor-not-allowed",
      "custom-label",
    );
  });
});
