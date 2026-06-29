import { fireEvent, render, screen } from "@testing-library/react";
import { Input } from "./Input";

describe("Input", () => {
  it("renders as a text input by default and forwards changes", () => {
    const onChange = jest.fn();

    render(<Input aria-label="Title" onChange={onChange} value="Text" />);

    const input = screen.getByRole("textbox", { name: "Title" });
    fireEvent.change(input, { target: { value: "Notes" } });

    expect(input).toHaveAttribute("type", "text");
    expect(onChange).toHaveBeenCalled();
  });

  it("supports disabled state and custom classes", () => {
    render(<Input aria-label="Token" className="custom-input" disabled />);

    const input = screen.getByLabelText("Token");

    expect(input).toBeDisabled();
    expect(input).toHaveClass("custom-input");
  });

  it("does not apply visual styling by default", () => {
    render(<Input aria-label="unstyled" />);

    expect(screen.getByLabelText("unstyled")).not.toHaveClass("font_ui_input");
  });
});
