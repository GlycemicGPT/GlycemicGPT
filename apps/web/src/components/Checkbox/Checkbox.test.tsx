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

  it("renders checked visual state from the checked prop", () => {
    render(<Checkbox checked label="Show source" />);

    expect(screen.getByText("Show source").previousElementSibling).toHaveClass(
      "bg-accent",
      "text-accent-foreground",
      "group-hover:bg-accent-hover",
    );
  });

  it("renders inactive and hover visual states when unchecked", () => {
    render(<Checkbox checked={false} label="Show source" />);

    expect(screen.getByText("Show source").previousElementSibling).toHaveClass(
      "border-border-default",
      "bg-surface-primary",
      "text-transparent",
      "group-hover:border-border-hover",
      "group-hover:bg-surface-secondary",
    );
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
    expect(screen.getByText("Disabled option").previousElementSibling).toHaveClass(
      "border-border-disabled",
    );
    expect(screen.getByText("Disabled option").previousElementSibling).not.toHaveClass(
      "group-hover:bg-accent-hover",
    );
  });
});
