/**
 * Story 15.1: Login Page Tests
 */
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

import LoginPage from "@/app/login/page";

describe("Login Page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockReturnValue(null);
    // Default: not authenticated on mount → form is shown
    mockGetCurrentUser.mockRejectedValue(new Error("Not authenticated"));
    // Default: post-login verification succeeds (cookie saved)
    mockVerifySessionCookie.mockResolvedValue(200);
  });

  it("renders email and password fields", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
  });

  it("renders Sign In heading and button", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /sign in/i })
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("renders Register link", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByRole("link", { name: /register/i })).toHaveAttribute(
        "href",
        "/register"
      );
    });
  });

  it("renders Back to home link", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /back to home/i })
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
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "test@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockLoginUser).toHaveBeenCalledWith("test@test.com", "TestPass123");
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
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "test@test.com"
    );
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
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "bad@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "WrongPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Invalid email or password"
      );
    });
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
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "test@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/signing in/i)).toBeInTheDocument();
    });

    expect(
      screen.getByRole("button", { name: /signing in/i })
    ).toBeDisabled();
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
      key === "redirect" ? "/dashboard/settings" : null
    );
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "test@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard/settings");
    });
  });

  it("ignores redirect parameter with external URL", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "redirect" ? "https://evil.com" : null
    );
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "test@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("shows expired session banner when expired=true", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "expired" ? "true" : null
    );

    render(<LoginPage />);
    await waitFor(() => {
      expect(
        screen.getByText(/your session has expired/i)
      ).toBeInTheDocument();
    });
  });

  it("does not show expired banner without parameter", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/your session has expired/i)
    ).not.toBeInTheDocument();
  });

  it("ignores redirect parameter with path-prefix attack", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "redirect" ? "/dashboardevil" : null
    );
    mockLoginUser.mockResolvedValue({
      message: "Login successful",
      user: { id: "1", email: "test@test.com" },
      disclaimer_required: false,
    });

    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "test@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("redirects authenticated users using redirect parameter", async () => {
    mockGet.mockImplementation((key: string) =>
      key === "redirect" ? "/dashboard/settings" : null
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
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "bad@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "WrongPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "An unexpected error occurred"
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
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "test@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /did not store the session cookie/i
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
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "test@test.com"
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /could not verify your session/i
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
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    });

    await userEvent.type(
      screen.getByLabelText(/email address/i),
      "  test@test.com  "
    );
    await userEvent.type(screen.getByLabelText(/^password$/i), "TestPass123");

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockLoginUser).toHaveBeenCalledWith(
        "test@test.com",
        "TestPass123"
      );
    });
  });
});
