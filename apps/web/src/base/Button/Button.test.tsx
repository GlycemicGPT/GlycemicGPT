import { fireEvent, render, screen } from "@testing-library/react";
import { Button } from "./Button";

describe("Button", () => {
  it("renders a button with default type and accessible name", () => {
    render(<Button ariaLabel="Open panel">Open</Button>);

    const button = screen.getByRole("button", { name: "Open panel" });

    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveTextContent("Open");
    expect(button).not.toHaveClass("bg-surface-page");
  });

  it("supports merged classes without owning visual styles", () => {
    render(
      <Button className="px-8 custom-class">
        Save
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Save" });

    expect(button).toHaveClass("px-8");
    expect(button).toHaveClass("custom-class");
  });

  it("forwards click events unless disabled", () => {
    const onClick = jest.fn();

    render(
      <Button disabled onClick={onClick}>
        Save
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Save" });
    fireEvent.click(button);

    expect(button).toBeDisabled();
    expect(onClick).not.toHaveBeenCalled();
  });
});
