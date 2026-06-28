import { fireEvent, render, screen } from "@testing-library/react";
import { TextInput } from "./TextInput";

describe("TextInput", () => {
  it("renders an accessible label and placeholder", () => {
    render(
      <TextInput
        label="Glucose target"
        onChange={jest.fn()}
        placeholder="112 mg/dL"
      />,
    );

    const input = screen.getByRole("textbox", { name: "Glucose target" });

    expect(input).toHaveAttribute("placeholder", "112 mg/dL");
    expect(input).toHaveClass("bg-surface-primary");
    expect(input).toHaveClass("placeholder:text-foreground-secondary");
  });

  it("connects error text to the input", () => {
    render(
      <TextInput
        errorMessage="Enter a value between 70 and 180 mg/dL."
        id="glucose-target"
        label="Glucose target"
      />,
    );

    const input = screen.getByRole("textbox", { name: "Glucose target" });
    const error = screen.getByText("Enter a value between 70 and 180 mg/dL.");

    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", "glucose-target-error");
    expect(error).toHaveAttribute("id", "glucose-target-error");
    expect(error).toHaveClass("text-signal-error-text");
  });

  it("preserves described by references and forwards change handlers", () => {
    const onChange = jest.fn();

    render(
      <>
        <p id="glucose-help">Use your configured target range.</p>
        <TextInput
          aria-describedby="glucose-help"
          id="glucose-target"
          label="Glucose target"
          onChange={onChange}
        />
      </>,
    );

    const input = screen.getByRole("textbox", { name: "Glucose target" });
    fireEvent.change(input, { target: { value: "120" } });

    expect(input).toHaveAttribute("aria-describedby", "glucose-help");
    expect(onChange).toHaveBeenCalled();
  });
});
