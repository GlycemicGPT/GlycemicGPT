/**
 * Story 15.1: Login Page Tests
 */
import { STATIC_ASSET_ICON_SPRITE_PATH } from "@/lib/staticAssets";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock next/navigation
const mockReplace = jest.fn();
const mockGet = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => ({ get: mockGet }),
}));

// Mock next/image
jest.mock("next/image", () => ({
  __esModule: true,
  default: (props: Record<string, unknown>) => {
    const { priority, ...rest } = props;
    return <img {...rest} data-priority={priority ? "true" : undefined} />;
  },
}));

// Mock API functions
const mockLoginUser = jest.fn();
const mockGetCurrentUser = jest.fn();
const mockVerifySessionCookie = jest.fn();
jest.mock("@/lib/api", () => ({
  loginUser: (...args: unknown[]) => mockLoginUser(...args),
  getCurrentUser: (...args: unknown[]) => mockGetCurrentUser(...args),
  verifySessionCookie: (...args: unknown[]) => mockVerifySessionCookie(...args),
}));

import LoginPage from "@/app/v2/login/page";

describe("V2 Login Page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockReturnValue(null);
    // Default: not authenticated on mount → form is shown
    mockGetCurrentUser.mockRejectedValue(new Error("Not authenticated"));
    // Default: post-login verification succeeds (cookie saved)
    mockVerifySessionCookie.mockResolvedValue(200);
  });

  it("uses the branded loading logo while checking the session", () => {
    mockGetCurrentUser.mockReturnValue(new Promise(() => {}));
    const { container } = render(<LoginPage />);

    expect(screen.getByRole("status", { name: "Loading sign in" })).toHaveClass(
      "h-12",
      "w-12",
      "mx-auto",
      "mb-3",
    );
    expect(container.querySelectorAll("[role='status'] svg path")).toHaveLength(
      6,
    );
    expect(
      container.querySelector("[role='status'] use"),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector(".lumose-loading-logo-flow"),
    ).toBeInTheDocument();
  });

  it("renders email and password fields", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
  });

  it("reveals field errors only after submit and hides them when corrected", async () => {
    render(<LoginPage />);
    const emailInput = await screen.findByLabelText("Email");
    const passwordInput = screen.getByLabelText("Password");
    const submitButton = screen.getByRole("button", { name: "Sign In" });

    fireEvent.change(emailInput, { target: { value: "invalid" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(submitButton);

    expect(
      screen.getByText("Enter a valid email address."),
    ).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(emailInput).toHaveAttribute("aria-invalid", "true");
    expect(passwordInput).toHaveAttribute("aria-invalid", "true");
    expect(mockLoginUser).not.toHaveBeenCalled();

    fireEvent.change(emailInput, {
      target: { value: "daniel@example.com" },
    });
    fireEvent.change(passwordInput, { target: { value: "Password1" } });

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    fireEvent.change(emailInput, { target: { value: "invalid" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(submitButton);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a valid email address.",
    );
    expect(mockLoginUser).not.toHaveBeenCalled();
  });

  it("renders Sign In heading and button", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /sign in/i }),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: /sign in/i }),
    ).toBeInTheDocument();
  });

  it("renders the combined Lumose brand and new form controls", async () => {
    const { container } = render(<LoginPage />);

    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Lumose" })).toBeInTheDocument();
    });

    const heading = screen.getByRole("heading", { name: "Sign In" });
    const panelIndex = screen.getByText("01");
    const logo = screen.getByRole("img", { name: "Lumose" });
    const emailInput = screen.getByLabelText("Email");
    const passwordInput = screen.getByLabelText("Password");
    const signInButton = screen.getByRole("button", { name: "Sign In" });
    const registerLink = screen.getByRole("link", {
      name: "Register",
    });
    const registerCopy = registerLink.parentElement;
    const backToHomeCopy = screen.getByRole("link", {
      name: "Back to home",
    }).parentElement;

    expect(
      screen.queryByText("Welcome back to GlycemicGPT"),
    ).not.toBeInTheDocument();
    expect(logo.querySelector("linearGradient")).toBeInTheDocument();
    expect(logo.querySelector("use")).not.toBeInTheDocument();
    expect(logo).toHaveClass("h-auto", "w-full");
    expect(logo.parentElement).toHaveClass("py-12");
    expect(logo.parentElement).not.toHaveClass("my-8");
    expect(heading.parentElement).toHaveClass("bg-surface-elevated");
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
    expect(heading).not.toHaveClass("font_poppins", "font_header_3");
    expect(
      heading.compareDocumentPosition(logo) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText("Email")).toHaveClass("font_metric_label");
    expect(emailInput).toHaveClass(
      "font_poppins",
      "font_ui_input",
      "border-border-default",
      "bg-surface-primary",
      "text-foreground-primary",
    );
    expect(passwordInput).toHaveClass("font_poppins", "font_ui_input");
    expect(signInButton).toHaveClass(
      "font_poppins",
      "font_body_2",
      "bg-accent",
      "text-accent-foreground",
    );
    expect(registerCopy).toHaveClass(
      "font_poppins",
      "font_body_3",
      "text-foreground-primary/[0.65]",
    );
    expect(registerLink).toHaveClass(
      "text-foreground-primary",
      "underline",
      "decoration-accent",
    );
    expect(backToHomeCopy).toHaveClass(
      "font_poppins",
      "font_body_4",
      "text-foreground-primary/[0.65]",
    );
  });

  it("renders Register link", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByRole("link", { name: /register/i })).toHaveAttribute(
        "href",
        "/register",
      );
    });
  });

  it("renders Back to home link", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /back to home/i }),
      ).toHaveAttribute("href", "/");
    });
  });

  it("calls loginUser with correct payload on submit", async () => {
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "test@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockLoginUser).toHaveBeenCalledWith(
        "test@test.com",
        "TestPass123",
      );
    });
  });

  it("redirects to dashboard on successful login", async () => {
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "test@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("displays error message on failed login", async () => {
    mockLoginUser.mockRejectedValue(new Error("Invalid email or password"));

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "bad@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "WrongPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Invalid email or password",
      );
    });
    const alert = screen.getByRole("alert");
    expect(alert).not.toHaveClass("border");
    expect(
      alert.querySelector(`use[href="${STATIC_ASSET_ICON_SPRITE_PATH}#alert"]`),
    ).toBeInTheDocument();
  });

  it("toggles password visibility", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    });

    const passwordInput = screen.getByLabelText(/^password$/i);
    expect(passwordInput).toHaveAttribute("type", "password");

    const toggleButton = screen.getByRole("button", {
      name: /show password/i,
    });
    fireEvent.click(toggleButton);

    expect(passwordInput).toHaveAttribute("type", "text");

    const hideButton = screen.getByRole("button", { name: /hide password/i });
    fireEvent.click(hideButton);

    expect(passwordInput).toHaveAttribute("type", "password");
  });

  it("shows loading state during submission", async () => {
    // Never resolve to keep the loading state
    mockLoginUser.mockReturnValue(new Promise(() => {}));

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "test@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/signing in/i)).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();
  });

  it("redirects authenticated users to dashboard", async () => {
    mockGetCurrentUser.mockResolvedValue({
      id: "1",
      email: "test@test.com",
    });

    render(<LoginPage />);

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("uses redirect parameter when present and valid", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "redirect" ? "/dashboard/settings" : null,
    );
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "test@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard/settings");
    });
  });

  it("uses a settings redirect with its query parameters", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "redirect"
        ? "/settings/connections?tab=insulin-pumps&connection=tandem"
        : null,
    );
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await userEvent.type(
      await screen.findByLabelText("Email"),
      "test@test.com",
    );
    await userEvent.type(screen.getByLabelText("Password"), "TestPass123");
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        "/settings/connections?tab=insulin-pumps&connection=tandem",
      );
    });
  });

  it("ignores redirect parameter with external URL", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "redirect" ? "https://evil.com" : null,
    );
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "test@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("shows expired session banner when expired=true", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "expired" ? "true" : null,
    );

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByText(/your session has expired/i)).toBeInTheDocument();
    });
  });

  it("does not show expired banner without parameter", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/your session has expired/i),
    ).not.toBeInTheDocument();
  });

  it("ignores redirect parameter with path-prefix attack", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "redirect" ? "/dashboardevil" : null,
    );
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "test@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("redirects authenticated users using redirect parameter", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "redirect" ? "/dashboard/settings" : null,
    );
    mockGetCurrentUser.mockResolvedValue({
      id: "1",
      email: "test@test.com",
    });

    render(<LoginPage />);

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard/settings");
    });
  });

  it("displays fallback error for non-Error rejections", async () => {
    mockLoginUser.mockRejectedValue("string error");

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "bad@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "WrongPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "An unexpected error occurred",
      );
    });
  });

  it("shows deployment-misconfig banner and does not navigate when session cookie is dropped (401)", async () => {
    // Symptom seen by self-hosters on plain-HTTP deploys: login API returns
    // 200, but the browser drops the Secure cookie, so /api/auth/me 401s.
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });
    mockVerifySessionCookie.mockResolvedValue(401);

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "test@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /did not store the session cookie/i,
      );
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/COOKIE_SECURE/);
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("shows generic verification error on non-401 failure (does not misattribute to cookie issue)", async () => {
    // A transient 5xx or proxy error must NOT show the cookie-misconfig
    // banner — that would create false-positive support reports.
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });
    mockVerifySessionCookie.mockResolvedValue(502);

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(screen.getByLabelText(/^email$/i), "test@test.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /could not verify your session/i,
      );
    });
    expect(screen.getByRole("alert")).toHaveTextContent("502");
    expect(screen.getByRole("alert")).not.toHaveTextContent(/COOKIE_SECURE/);
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("trims whitespace from email before submission", async () => {
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/^email$/i),
      "  test@test.com  ",
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockLoginUser).toHaveBeenCalledWith(
        "test@test.com",
        "TestPass123",
      );
    });
  });
});
