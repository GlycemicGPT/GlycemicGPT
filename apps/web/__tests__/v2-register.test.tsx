import { STATIC_ASSET_ICON_SPRITE_PATH } from "@/lib/staticAssets";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const mockReplace = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

const mockRegisterUser = jest.fn();
const mockLoginUser = jest.fn();
const mockGetCurrentUser = jest.fn();
jest.mock("@/lib/api", () => ({
  getCurrentUser: (...args: unknown[]) => mockGetCurrentUser(...args),
  loginUser: (...args: unknown[]) => mockLoginUser(...args),
  registerUser: (...args: unknown[]) => mockRegisterUser(...args),
}));

import RegisterPage from "@/app/v2/register/page";

describe("V2 Registration Page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetCurrentUser.mockRejectedValue(new Error("Not authenticated"));
    mockRegisterUser.mockResolvedValue({
      disclaimer_required: true,
      email: "daniel@example.com",
      id: "user-1",
      message: "Registration successful",
      role: "diabetic",
    });
    mockLoginUser.mockResolvedValue({
      disclaimer_required: true,
      message: "Login successful",
      user: { email: "daniel@example.com", id: "user-1" },
    });
  });

  it("uses the branded loading logo while checking the session", () => {
    mockGetCurrentUser.mockReturnValue(new Promise(() => {}));
    render(<RegisterPage />);

    const loadingLogo = screen.getByRole("status", {
      name: "Loading registration",
    });
    expect(loadingLogo).toHaveClass("h-12", "w-12", "mx-auto", "mb-3");
    expect(loadingLogo).toHaveAttribute("aria-live", "polite");
  });

  async function renderRegistrationForm() {
    const { container } = render(<RegisterPage />);
    return {
      confirmPasswordInput: await screen.findByLabelText("Confirm Password"),
      container,
      emailInput: screen.getByLabelText("Email"),
      passwordInput: screen.getByLabelText("Password"),
      submitButton: screen.getByRole("button", { name: "Create Account" }),
    };
  }

  it("uses the shared semantic panel, branding, and action icons", async () => {
    const { container, submitButton } = await renderRegistrationForm();
    const heading = screen.getByRole("heading", { name: "Register" });
    const panelIndex = screen.getByText("02");
    const logo = screen.getByRole("img", { name: "Lumose" });
    const signInLink = screen.getByRole("link", { name: "Sign in" });
    const signInCopy = signInLink.parentElement;
    const backToHomeCopy = screen.getByRole("link", {
      name: "Back to home",
    }).parentElement;

    expect(container.querySelector("main")).toHaveClass(
      "bg-surface-page",
      "text-foreground-primary",
    );
    expect(heading.parentElement).toHaveClass(
      "rounded-panel",
      "border-border-default",
      "bg-surface-elevated",
    );
    expect(heading).toHaveClass(
      "font_metric_label",
      "absolute",
      "left-2",
      "top-2",
      "text-foreground-primary/[0.65]",
    );
    expect(panelIndex).toHaveClass(
      "font_metric_label",
      "absolute",
      "right-2",
      "top-2",
      "text-foreground-primary/[0.65]",
    );
    expect(panelIndex).toHaveAttribute("aria-hidden", "true");
    expect(logo).toHaveClass("h-auto", "w-full");
    expect(logo.parentElement).toHaveClass("py-12");
    expect(logo.parentElement).not.toHaveClass("my-8");
    expect(submitButton).toHaveClass(
      "font_poppins",
      "font_body_2",
      "bg-accent",
      "text-accent-foreground",
      "rounded-button",
    );
    expect(
      submitButton.querySelector(
        `use[href="${STATIC_ASSET_ICON_SPRITE_PATH}#person-add"]`,
      ),
    ).toBeInTheDocument();
    expect(signInCopy).toHaveClass(
      "font_poppins",
      "font_body_3",
      "text-foreground-primary/[0.65]",
    );
    expect(signInLink).toHaveClass(
      "text-foreground-primary",
      "underline",
      "decoration-accent",
    );
    expect(backToHomeCopy).toHaveClass(
      "font_poppins",
      "font_body_4",
      "text-foreground-primary/[0.65]",
    );
    expect(container.innerHTML).not.toMatch(
      /(?:bg|border|text)-(?:blue|slate)-/,
    );
  });

  it("renders shared text inputs without showing requirements initially", async () => {
    const { confirmPasswordInput, emailInput, passwordInput, submitButton } =
      await renderRegistrationForm();

    expect(emailInput).toHaveClass(
      "font_poppins",
      "font_ui_input",
      "border-border-default",
      "bg-surface-primary",
    );
    expect(passwordInput).toHaveClass("font_poppins");
    expect(confirmPasswordInput).toHaveClass("font_poppins");
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(confirmPasswordInput).toHaveAttribute("type", "password");
    expect(submitButton).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Password must be at least 8 characters."),
    ).not.toBeInTheDocument();
  });

  it("shows all current errors after submit and only hides corrected errors", async () => {
    const { confirmPasswordInput, emailInput, passwordInput, submitButton } =
      await renderRegistrationForm();

    fireEvent.change(emailInput, { target: { value: "invalid" } });
    fireEvent.change(passwordInput, { target: { value: "weak" } });
    fireEvent.change(confirmPasswordInput, {
      target: { value: "different" },
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(submitButton);

    expect(
      screen.getByText("Enter a valid email address."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Password must be at least 8 characters."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Include at least one uppercase letter."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Include at least one number."),
    ).toBeInTheDocument();
    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    expect(mockRegisterUser).not.toHaveBeenCalled();

    fireEvent.change(emailInput, {
      target: { value: "daniel@example.com" },
    });
    fireEvent.change(passwordInput, { target: { value: "Password1" } });
    fireEvent.change(confirmPasswordInput, {
      target: { value: "Password1" },
    });

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    fireEvent.change(passwordInput, { target: { value: "weak" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(submitButton);
    expect(
      screen.getByText("Password must be at least 8 characters.").closest("ul"),
    ).toHaveAttribute("role", "alert");
    expect(mockRegisterUser).not.toHaveBeenCalled();
  });

  it("submits trimmed valid values and preserves automatic login", async () => {
    const { confirmPasswordInput, emailInput, passwordInput, submitButton } =
      await renderRegistrationForm();

    fireEvent.change(emailInput, {
      target: { value: "  daniel@example.com  " },
    });
    fireEvent.change(passwordInput, { target: { value: "Password1" } });
    fireEvent.change(confirmPasswordInput, {
      target: { value: "Password1" },
    });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockRegisterUser).toHaveBeenCalledWith(
        "daniel@example.com",
        "Password1",
      );
      expect(mockLoginUser).toHaveBeenCalledWith(
        "daniel@example.com",
        "Password1",
      );
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("shows duplicate email failures beside the email field", async () => {
    mockRegisterUser.mockRejectedValue(
      new Error("An account with this email already exists"),
    );
    const { confirmPasswordInput, emailInput, passwordInput, submitButton } =
      await renderRegistrationForm();

    fireEvent.change(emailInput, {
      target: { value: "existing@example.com" },
    });
    fireEvent.change(passwordInput, { target: { value: "Password1" } });
    fireEvent.change(confirmPasswordInput, {
      target: { value: "Password1" },
    });
    fireEvent.click(submitButton);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An account with this email already exists",
    );
    expect(emailInput).toHaveAttribute("aria-invalid", "true");
    expect(emailInput).toHaveAttribute("aria-describedby", "email-error");

    fireEvent.change(passwordInput, { target: { value: "Password2" } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "An account with this email already exists",
    );

    fireEvent.change(emailInput, {
      target: { value: "another@example.com" },
    });
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  it("keeps generic registration failures at page level", async () => {
    mockRegisterUser.mockRejectedValue(new Error("Registration unavailable"));
    const { confirmPasswordInput, emailInput, passwordInput, submitButton } =
      await renderRegistrationForm();

    fireEvent.change(emailInput, {
      target: { value: "daniel@example.com" },
    });
    fireEvent.change(passwordInput, { target: { value: "Password1" } });
    fireEvent.change(confirmPasswordInput, {
      target: { value: "Password1" },
    });
    fireEvent.click(submitButton);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Registration unavailable",
    );
    const alert = screen.getByRole("alert");
    expect(alert).not.toHaveClass("border");
    expect(
      alert.querySelector(`use[href="${STATIC_ASSET_ICON_SPRITE_PATH}#alert"]`),
    ).toBeInTheDocument();
    expect(emailInput).toHaveAttribute("aria-invalid", "false");
    expect(passwordInput).toHaveAttribute("aria-invalid", "false");
  });

  it("keeps password visibility controls inside their fields", async () => {
    const { confirmPasswordInput, passwordInput } =
      await renderRegistrationForm();

    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(passwordInput).toHaveAttribute("type", "text");

    fireEvent.click(
      screen.getByRole("button", { name: "Show confirm password" }),
    );
    expect(confirmPasswordInput).toHaveAttribute("type", "text");
  });
});
