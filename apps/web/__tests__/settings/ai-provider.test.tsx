/**
 * Tests for AI Provider Configuration Page (Story 14.3)
 *
 * Verifies:
 * 1. Page renders with heading and back link
 * 2. Loading state shows spinner
 * 3. Not configured: shows setup form with 5 provider options in 3 categories
 * 4. Configured: shows current config with status badge, masked key, test/remove buttons
 * 5. Provider selection across categories
 * 6. API key input has show/hide toggle
 * 7. Save button disabled when required fields empty or offline
 * 8. Save calls configureAIProvider with correct payload including base_url
 * 9. Test Connection calls testAIProvider
 * 10. Remove flow: confirmation dialog, calls deleteAIProvider
 * 11. Error and success banners display correctly
 * 12. Offline state disables all actions
 * 13. Dynamic form fields based on selected provider
 */

import {
  render,
  screen,
  waitFor,
  act,
  fireEvent,
} from "@testing-library/react";

// Mock next/link
jest.mock("next/link", () => {
  return ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  );
});

// Mock next/navigation
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const mockGetAIProvider = jest.fn();
const mockConfigureAIProvider = jest.fn();
const mockTestAIProvider = jest.fn();
const mockDeleteAIProvider = jest.fn();
const mockStartSubscriptionAuth = jest.fn();
const mockSubmitSubscriptionToken = jest.fn();
const mockGetSubscriptionAuthStatus = jest.fn();
const mockRevokeSubscriptionAuth = jest.fn();
const mockGetSidecarHealth = jest.fn();

jest.mock("../../src/lib/api", () => ({
  __esModule: true,
  getAIProvider: (...args: unknown[]) => mockGetAIProvider(...args),
  configureAIProvider: (...args: unknown[]) =>
    mockConfigureAIProvider(...args),
  testAIProvider: (...args: unknown[]) => mockTestAIProvider(...args),
  deleteAIProvider: (...args: unknown[]) => mockDeleteAIProvider(...args),
  startSubscriptionAuth: (...args: unknown[]) => mockStartSubscriptionAuth(...args),
  submitSubscriptionToken: (...args: unknown[]) => mockSubmitSubscriptionToken(...args),
  getSubscriptionAuthStatus: (...args: unknown[]) => mockGetSubscriptionAuthStatus(...args),
  revokeSubscriptionAuth: (...args: unknown[]) => mockRevokeSubscriptionAuth(...args),
  getSidecarHealth: (...args: unknown[]) => mockGetSidecarHealth(...args),
}));

import AIProviderPage from "../../src/app/dashboard/settings/ai-provider/page";

describe("Story 14.3: AI Provider Configuration Page", () => {
  beforeEach(() => {
    mockGetAIProvider.mockReset();
    mockConfigureAIProvider.mockReset();
    mockTestAIProvider.mockReset();
    mockDeleteAIProvider.mockReset();
    mockStartSubscriptionAuth.mockReset();
    mockSubmitSubscriptionToken.mockReset();
    mockGetSubscriptionAuthStatus.mockReset();
    mockRevokeSubscriptionAuth.mockReset();
    mockGetSidecarHealth.mockReset();
    // Default: sidecar unavailable (most tests don't need it)
    mockGetSidecarHealth.mockRejectedValue(new Error("unavailable"));
    mockGetSubscriptionAuthStatus.mockRejectedValue(new Error("unavailable"));
  });

  describe("page header and navigation", () => {
    beforeEach(() => {
      mockGetAIProvider.mockRejectedValue(
        new Error("No AI provider configured: 404")
      );
    });

    it("renders page heading", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /ai provider/i, level: 1 })
        ).toBeInTheDocument();
      });
    });

    it("shows Back to Settings link", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        const backLink = screen.getByText(/back to settings/i);
        expect(backLink.closest("a")).toHaveAttribute(
          "href",
          "/dashboard/settings"
        );
      });
    });
  });

  describe("loading state", () => {
    it("shows loading spinner before API resolves", async () => {
      let resolve: (v: unknown) => void;
      mockGetAIProvider.mockReturnValue(
        new Promise((r) => {
          resolve = r;
        })
      );

      render(<AIProviderPage />);

      expect(
        screen.getByRole("status", {
          name: /loading ai provider configuration/i,
        })
      ).toBeInTheDocument();

      // Resolve to prevent act warnings
      await act(async () => {
        resolve!({
          provider_type: "claude_api",
          status: "connected",
          masked_api_key: "sk-...xY7z",
          base_url: null,
          created_at: "2026-01-01",
          updated_at: "2026-01-01",
        });
      });
    });
  });

  describe("when provider is NOT configured", () => {
    beforeEach(() => {
      mockGetAIProvider.mockRejectedValue(
        new Error("No AI provider configured: 404")
      );
    });

    it("shows setup form with provider selection categories", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /set up ai provider/i })
        ).toBeInTheDocument();
      });

      // Check for all 3 categories
      expect(screen.getByText("Subscription Plans")).toBeInTheDocument();
      expect(screen.getByText("Pay-Per-Token APIs")).toBeInTheDocument();
      expect(screen.getByText("Self-Hosted")).toBeInTheDocument();
    });

    it("shows all 5 provider options", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /set up ai provider/i })
        ).toBeInTheDocument();
      });

      expect(
        screen.getByRole("button", { name: /select claude subscription/i })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /select chatgpt subscription/i })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /select claude api/i })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /select openai api/i })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /select custom openai-compatible/i })
      ).toBeInTheDocument();
    });

    it("shows BYOAI description", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByText(/glycemicgpt uses your own ai/i)
        ).toBeInTheDocument();
      });
    });

    it("shows API key input field", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /set up ai provider/i })
        ).toBeInTheDocument();
      });

      const input = document.getElementById("api-key");
      expect(input).toBeInTheDocument();
      expect(input).toHaveAttribute("type", "password");
    });

    it("has show/hide toggle for API key", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /set up ai provider/i })
        ).toBeInTheDocument();
      });

      const input = document.getElementById("api-key")!;
      expect(input).toHaveAttribute("type", "password");

      const toggleBtn = screen.getByRole("button", { name: /show api key/i });
      await act(async () => {
        fireEvent.click(toggleBtn);
      });

      expect(input).toHaveAttribute("type", "text");

      const hideBtn = screen.getByRole("button", { name: /hide api key/i });
      await act(async () => {
        fireEvent.click(hideBtn);
      });

      expect(input).toHaveAttribute("type", "password");
    });

    it("shows Save button disabled when API key empty for API provider", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /save and validate/i })
        ).toBeInTheDocument();
      });

      // Default provider is claude_api which requires API key
      expect(
        screen.getByRole("button", { name: /save and validate/i })
      ).toBeDisabled();
    });

    it("enables Save button when API key is entered", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(document.getElementById("api-key")).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.change(document.getElementById("api-key")!, {
          target: { value: "test-claude-key-123" },
        });
      });

      expect(
        screen.getByRole("button", { name: /save and validate/i })
      ).toBeEnabled();
    });

    it("shows model name field", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(screen.getByLabelText(/model name/i)).toBeInTheDocument();
      });
    });

    it("does NOT show current configuration section", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /set up ai provider/i })
        ).toBeInTheDocument();
      });

      expect(
        screen.queryByRole("heading", { name: /current configuration/i })
      ).not.toBeInTheDocument();
    });

    it("shows sidecar auth UI when subscription provider is selected", async () => {
      mockGetSidecarHealth.mockResolvedValue({ available: false, status: "unreachable" });
      mockGetSubscriptionAuthStatus.mockResolvedValue({ sidecar_available: false });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /set up ai provider/i })
        ).toBeInTheDocument();
      });

      // Default is claude_api - no sidecar status indicator
      expect(screen.queryByText(/ai sidecar:/i)).not.toBeInTheDocument();

      // Switch to Claude Subscription
      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /select claude subscription/i })
        );
      });

      // Should show sidecar status indicator (with colon: "AI Sidecar:")
      await waitFor(() => {
        expect(screen.getByText(/ai sidecar:/i)).toBeInTheDocument();
      });

      // Should NOT show base-url field (subscription uses sidecar, not manual URL)
      expect(document.getElementById("base-url")).not.toBeInTheDocument();
    });

    it("hides Save button for subscription providers", async () => {
      mockGetSidecarHealth.mockResolvedValue({ available: false, status: "unreachable" });
      mockGetSubscriptionAuthStatus.mockResolvedValue({ sidecar_available: false });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /set up ai provider/i })
        ).toBeInTheDocument();
      });

      // Switch to Claude Subscription
      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /select claude subscription/i })
        );
      });

      // Save & Validate button should not be shown for subscription providers
      await waitFor(() => {
        expect(
          screen.queryByRole("button", { name: /save and validate/i })
        ).not.toBeInTheDocument();
      });
    });
  });

  describe("when provider IS configured", () => {
    const configuredResponse = {
      provider_type: "claude_api" as const,
      status: "connected" as const,
      model_name: null,
      base_url: null,
      masked_api_key: "sk-...xY7z",
      last_validated_at: "2026-01-15T12:00:00Z",
      last_error: null,
      created_at: "2026-01-15T12:00:00Z",
      updated_at: "2026-01-15T12:00:00Z",
    };

    beforeEach(() => {
      mockGetAIProvider.mockResolvedValue(configuredResponse);
    });

    it("shows Current Configuration section", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /current configuration/i })
        ).toBeInTheDocument();
      });
    });

    it("shows Connected status badge", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(screen.getByText("Connected")).toBeInTheDocument();
      });
    });

    it("shows provider name and masked key", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /current configuration/i })
        ).toBeInTheDocument();
      });

      // Provider name appears in both config card and selection button
      const providerElements = screen.getAllByText("Claude API (Anthropic)");
      expect(providerElements.length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("sk-...xY7z")).toBeInTheDocument();
    });

    it("shows Test Connection button", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /test connection/i })
        ).toBeInTheDocument();
      });
    });

    it("shows Remove AI Provider button", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove ai provider/i })
        ).toBeInTheDocument();
      });
    });

    it("shows Update Configuration form heading", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /update configuration/i })
        ).toBeInTheDocument();
      });
    });

    it("shows Update button instead of Save", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /update ai provider/i })
        ).toBeInTheDocument();
      });
    });

    it("shows error status with last error message", async () => {
      mockGetAIProvider.mockResolvedValue({
        ...configuredResponse,
        status: "error",
        last_error: "Invalid API key: authentication failed",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(screen.getByText("Error")).toBeInTheDocument();
      });

      expect(
        screen.getByText("Invalid API key: authentication failed")
      ).toBeInTheDocument();
    });

    it("shows model name when configured", async () => {
      mockGetAIProvider.mockResolvedValue({
        ...configuredResponse,
        model_name: "claude-sonnet-4-5-20250929",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByText("claude-sonnet-4-5-20250929")
        ).toBeInTheDocument();
      });
    });

    it("shows base_url when configured with subscription provider", async () => {
      mockGetAIProvider.mockResolvedValue({
        ...configuredResponse,
        provider_type: "claude_subscription",
        base_url: "http://localhost:3456/v1",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByText("http://localhost:3456/v1")
        ).toBeInTheDocument();
      });

      // Should show provider label
      const providerElements = screen.getAllByText("Claude Subscription");
      expect(providerElements.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("save flow", () => {
    beforeEach(() => {
      mockGetAIProvider.mockRejectedValue(
        new Error("No AI provider configured: 404")
      );
    });

    it("calls configureAIProvider with correct payload for API provider", async () => {
      mockConfigureAIProvider.mockResolvedValue({
        provider_type: "claude_api",
        status: "connected",
        model_name: null,
        base_url: null,
        masked_api_key: "sk-...test",
        last_validated_at: "2026-01-15T12:00:00Z",
        last_error: null,
        created_at: "2026-01-15T12:00:00Z",
        updated_at: "2026-01-15T12:00:00Z",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(document.getElementById("api-key")).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.change(document.getElementById("api-key")!, {
          target: { value: "test-claude-key-456" },
        });
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /save and validate/i })
        );
      });

      await waitFor(() => {
        expect(mockConfigureAIProvider).toHaveBeenCalledWith({
          provider_type: "claude_api",
          api_key: "test-claude-key-456",
          model_name: null,
          base_url: null,
          // Empty "Max response tokens" input sends null (= use the
          // per-context default). See issue #554 / PR #600.
          max_response_tokens: null,
        });
      });
    });

    it("shows Sign in button for subscription provider when sidecar is available", async () => {
      mockGetSidecarHealth.mockResolvedValue({ available: true, status: "ok" });
      mockGetSubscriptionAuthStatus.mockResolvedValue({
        sidecar_available: true,
        claude: { authenticated: false },
        codex: { authenticated: false },
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /set up ai provider/i })
        ).toBeInTheDocument();
      });

      // Select Claude Subscription
      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /select claude subscription/i })
        );
      });

      // Should show Sign in button
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /sign in with claude/i })
        ).toBeInTheDocument();
      });
    });

    it("shows success message after save", async () => {
      mockConfigureAIProvider.mockResolvedValue({
        provider_type: "claude_api",
        status: "connected",
        model_name: null,
        base_url: null,
        masked_api_key: "sk-...myky",
        last_validated_at: "2026-01-15T12:00:00Z",
        last_error: null,
        created_at: "2026-01-15T12:00:00Z",
        updated_at: "2026-01-15T12:00:00Z",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(document.getElementById("api-key")).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.change(document.getElementById("api-key")!, {
          target: { value: "test-claude-key-456" },
        });
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /save and validate/i })
        );
      });

      await waitFor(() => {
        expect(
          screen.getByText(/ai provider configured successfully/i)
        ).toBeInTheDocument();
      });
    });

    it("shows error message on save failure", async () => {
      mockConfigureAIProvider.mockRejectedValue(
        new Error("Invalid API key: authentication failed")
      );

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(document.getElementById("api-key")).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.change(document.getElementById("api-key")!, {
          target: { value: "bad-key" },
        });
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /save and validate/i })
        );
      });

      await waitFor(() => {
        expect(
          screen.getByText("Invalid API key: authentication failed")
        ).toBeInTheDocument();
      });
    });

    it("sends model name when provided", async () => {
      mockConfigureAIProvider.mockResolvedValue({
        provider_type: "openai_api",
        status: "connected",
        model_name: "gpt-4o-mini",
        base_url: null,
        masked_api_key: "sk-...test",
        last_validated_at: "2026-01-15T12:00:00Z",
        last_error: null,
        created_at: "2026-01-15T12:00:00Z",
        updated_at: "2026-01-15T12:00:00Z",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(document.getElementById("api-key")).toBeInTheDocument();
      });

      // Switch to OpenAI API
      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /select openai api/i })
        );
      });

      await act(async () => {
        fireEvent.change(document.getElementById("api-key")!, {
          target: { value: "test-openai-key-789" },
        });
      });

      await act(async () => {
        fireEvent.change(screen.getByLabelText(/model name/i), {
          target: { value: "gpt-4o-mini" },
        });
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /save and validate/i })
        );
      });

      await waitFor(() => {
        expect(mockConfigureAIProvider).toHaveBeenCalledWith({
          provider_type: "openai_api",
          api_key: "test-openai-key-789",
          model_name: "gpt-4o-mini",
          base_url: null,
          max_response_tokens: null,
        });
      });
    });
  });

  describe("test connection flow", () => {
    beforeEach(() => {
      mockGetAIProvider.mockResolvedValue({
        provider_type: "claude_api",
        status: "connected",
        model_name: null,
        base_url: null,
        masked_api_key: "sk-...xY7z",
        last_validated_at: "2026-01-15T12:00:00Z",
        last_error: null,
        created_at: "2026-01-15T12:00:00Z",
        updated_at: "2026-01-15T12:00:00Z",
      });
    });

    it("calls testAIProvider on click", async () => {
      mockTestAIProvider.mockResolvedValue({
        success: true,
        message: "AI provider configured successfully",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /test connection/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /test connection/i })
        );
      });

      await waitFor(() => {
        expect(mockTestAIProvider).toHaveBeenCalled();
      });
    });

    it("shows success on successful test", async () => {
      mockTestAIProvider.mockResolvedValue({
        success: true,
        message: "AI provider configured successfully",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /test connection/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /test connection/i })
        );
      });

      await waitFor(() => {
        expect(
          screen.getByText(/ai provider configured successfully/i)
        ).toBeInTheDocument();
      });
    });

    it("shows error on failed test", async () => {
      mockTestAIProvider.mockResolvedValue({
        success: false,
        message: "API key expired",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /test connection/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /test connection/i })
        );
      });

      await waitFor(() => {
        expect(screen.getByText("API key expired")).toBeInTheDocument();
      });
    });
  });

  describe("remove flow", () => {
    beforeEach(() => {
      mockGetAIProvider.mockResolvedValue({
        provider_type: "claude_api",
        status: "connected",
        model_name: null,
        base_url: null,
        masked_api_key: "sk-...xY7z",
        last_validated_at: "2026-01-15T12:00:00Z",
        last_error: null,
        created_at: "2026-01-15T12:00:00Z",
        updated_at: "2026-01-15T12:00:00Z",
      });
    });

    it("shows confirmation on Remove click", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove ai provider/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove ai provider/i })
        );
      });

      expect(
        screen.getByText(/removing the ai provider will disable/i)
      ).toBeInTheDocument();
      expect(screen.getByText("Yes, Remove")).toBeInTheDocument();
    });

    it("calls deleteAIProvider on confirm", async () => {
      mockDeleteAIProvider.mockResolvedValue({
        message: "AI provider configuration removed successfully",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove ai provider/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove ai provider/i })
        );
      });

      await act(async () => {
        fireEvent.click(screen.getByText("Yes, Remove"));
      });

      await waitFor(() => {
        expect(mockDeleteAIProvider).toHaveBeenCalled();
      });
    });

    it("transitions to unconfigured state after removal", async () => {
      mockDeleteAIProvider.mockResolvedValue({
        message: "AI provider configuration removed successfully",
      });

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove ai provider/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove ai provider/i })
        );
      });

      await act(async () => {
        fireEvent.click(screen.getByText("Yes, Remove"));
      });

      await waitFor(() => {
        expect(
          screen.getByText(/ai provider configuration removed/i)
        ).toBeInTheDocument();
      });

      // Should show setup form
      expect(
        screen.getByRole("heading", { name: /set up ai provider/i })
      ).toBeInTheDocument();
      // Current configuration should be gone
      expect(
        screen.queryByRole("heading", { name: /current configuration/i })
      ).not.toBeInTheDocument();
    });

    it("dismisses confirmation and shows error on removal failure", async () => {
      mockDeleteAIProvider.mockRejectedValue(
        new Error("Permission denied")
      );

      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove ai provider/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove ai provider/i })
        );
      });

      await act(async () => {
        fireEvent.click(screen.getByText("Yes, Remove"));
      });

      await waitFor(() => {
        expect(screen.getByText("Permission denied")).toBeInTheDocument();
      });

      // Confirmation should be dismissed
      expect(screen.queryByText("Yes, Remove")).not.toBeInTheDocument();
      // Should still show configured state
      expect(screen.getByText("Connected")).toBeInTheDocument();
    });

    it("dismisses confirmation on Cancel", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove ai provider/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove ai provider/i })
        );
      });

      expect(screen.getByText("Yes, Remove")).toBeInTheDocument();

      await act(async () => {
        fireEvent.click(screen.getByText("Cancel"));
      });

      expect(screen.queryByText("Yes, Remove")).not.toBeInTheDocument();
    });
  });

  describe("offline state", () => {
    beforeEach(() => {
      mockGetAIProvider.mockRejectedValue(
        new Error("NetworkError: Failed to fetch")
      );
    });

    it("shows offline banner", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByText(/unable to connect to server/i)
        ).toBeInTheDocument();
      });
    });

    it("disables Save button when offline", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /save and validate/i })
        ).toBeInTheDocument();
      });

      expect(
        screen.getByRole("button", { name: /save and validate/i })
      ).toBeDisabled();
    });

    it("disables API key input when offline", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(document.getElementById("api-key")).toBeInTheDocument();
      });

      expect(document.getElementById("api-key")!).toBeDisabled();
    });

    it("disables provider selection when offline", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /select claude api/i })
        ).toBeInTheDocument();
      });

      expect(
        screen.getByRole("button", { name: /select claude api/i })
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: /select openai api/i })
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: /select claude subscription/i })
      ).toBeDisabled();
    });

    it("clears offline banner when retry succeeds", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByText(/unable to connect to server/i)
        ).toBeInTheDocument();
      });

      // First call was initial load (failed). Now mock success for retry.
      mockGetAIProvider.mockRejectedValueOnce(
        new Error("No AI provider configured: 404")
      );

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /retry connection/i })
        );
      });

      await waitFor(() => {
        expect(
          screen.queryByText(/unable to connect to server/i)
        ).not.toBeInTheDocument();
      });
    });

    it("calls getAIProvider again on retry", async () => {
      render(<AIProviderPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /retry connection/i })
        ).toBeInTheDocument();
      });

      // Initial call was 1
      expect(mockGetAIProvider).toHaveBeenCalledTimes(1);

      // Retry still fails
      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /retry connection/i })
        );
      });

      await waitFor(() => {
        expect(mockGetAIProvider).toHaveBeenCalledTimes(2);
      });
    });
  });
});
