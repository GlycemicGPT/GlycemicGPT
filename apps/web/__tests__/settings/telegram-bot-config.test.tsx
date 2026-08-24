/**
 * Tests for Telegram Bot Token Configuration (Story 12.3)
 *
 * Verifies:
 * 1. Bot Setup section renders with token input and validate button
 * 2. Bot configured state shows username and "Configured" badge
 * 3. Token input has show/hide toggle
 * 4. Validate Token button is disabled when input is empty or offline
 * 5. Account linking section is disabled when bot is not configured
 * 6. "Bot not configured" warning appears when bot is not set up
 * 7. Remove Bot Token confirmation flow works
 * 8. Offline state disables all actions
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

const mockGetTelegramBotConfig = jest.fn();
const mockGetTelegramStatus = jest.fn();
const mockSaveTelegramBotToken = jest.fn();
const mockRemoveTelegramBotToken = jest.fn();
const mockGenerateTelegramCode = jest.fn();
const mockSendTelegramTestMessage = jest.fn();
const mockUnlinkTelegram = jest.fn();

jest.mock("../../src/lib/api", () => ({
  __esModule: true,
  ApiError: jest.requireActual("../../src/lib/api").ApiError,
  getTelegramBotConfig: (...args: unknown[]) =>
    mockGetTelegramBotConfig(...args),
  getTelegramStatus: (...args: unknown[]) => mockGetTelegramStatus(...args),
  saveTelegramBotToken: (...args: unknown[]) =>
    mockSaveTelegramBotToken(...args),
  removeTelegramBotToken: (...args: unknown[]) =>
    mockRemoveTelegramBotToken(...args),
  generateTelegramCode: (...args: unknown[]) =>
    mockGenerateTelegramCode(...args),
  sendTelegramTestMessage: (...args: unknown[]) =>
    mockSendTelegramTestMessage(...args),
  unlinkTelegram: (...args: unknown[]) => mockUnlinkTelegram(...args),
}));

import { ApiError } from "../../src/lib/api";
import TelegramSettingsPage from "../../src/app/dashboard/settings/telegram/page";

describe("Story 12.3: Telegram Bot Token Configuration", () => {
  beforeEach(() => {
    mockGetTelegramBotConfig.mockReset();
    mockGetTelegramStatus.mockReset();
    mockSaveTelegramBotToken.mockReset();
    mockRemoveTelegramBotToken.mockReset();
    mockGenerateTelegramCode.mockReset();
    mockSendTelegramTestMessage.mockReset();
    mockUnlinkTelegram.mockReset();
  });

  describe("when bot is NOT configured", () => {
    beforeEach(() => {
      mockGetTelegramBotConfig.mockResolvedValue({
        configured: false,
        can_manage: true,
        bot_username: null,
        configured_at: null,
      });
      mockGetTelegramStatus.mockRejectedValue(
        new ApiError(503, "Telegram bot is not configured")
      );
    });

    it("renders Bot Setup section with instructions", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /bot setup/i })
        ).toBeInTheDocument();
      });

      expect(
        await screen.findByText(/a telegram bot token is required/i)
      ).toBeInTheDocument();
      // @BotFather appears in both description and instructions
      const botFatherRefs = screen.getAllByText(/@BotFather/);
      expect(botFatherRefs.length).toBeGreaterThanOrEqual(1);
    });

    it("shows token input field", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
        ).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i);
      expect(input).toHaveAttribute("type", "password");
    });

    it("has show/hide toggle for token input", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
        ).toBeInTheDocument();
      });

      const input = screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i);
      expect(input).toHaveAttribute("type", "password");

      const toggleBtn = screen.getByRole("button", { name: /show token/i });
      await act(async () => {
        fireEvent.click(toggleBtn);
      });

      expect(input).toHaveAttribute("type", "text");

      const hideBtn = screen.getByRole("button", { name: /hide token/i });
      await act(async () => {
        fireEvent.click(hideBtn);
      });

      expect(input).toHaveAttribute("type", "password");
    });

    it("shows Validate Token button disabled when input is empty", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /validate bot token/i })
        ).toBeInTheDocument();
      });

      expect(
        screen.getByRole("button", { name: /validate bot token/i })
      ).toBeDisabled();
    });

    it("enables Validate Token button when token is entered", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.change(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i),
          { target: { value: "123456:ABC-DEF" } }
        );
      });

      expect(
        screen.getByRole("button", { name: /validate bot token/i })
      ).toBeEnabled();
    });

    it("does not disable token setup when the bot is simply unconfigured", async () => {
      mockGetTelegramStatus.mockRejectedValue(
        new ApiError(503, "Telegram bot is not configured")
      );

      render(<TelegramSettingsPage />);

      const input = await screen.findByPlaceholderText(
        /ABCdefGhIJKlmNoPQRsTUVwxyz/i
      );

      expect(input).toBeEnabled();
      expect(
        screen.queryByText(
          "Unable to connect to server. Telegram settings are unavailable."
        )
      ).not.toBeInTheDocument();
    });

    it("shows bot not configured warning", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            /telegram bot not configured\. an administrator must set up the bot token first/i
          )
        ).toBeInTheDocument();
      });
    });

    it("disables account linking Generate Code button", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /generate verification code/i })
        ).toBeInTheDocument();
      });

      expect(
        screen.getByRole("button", { name: /generate verification code/i })
      ).toBeDisabled();
    });
  });

  describe("when user cannot manage the bot", () => {
    it("hides bot setup when the bot is unconfigured", async () => {
      mockGetTelegramBotConfig.mockResolvedValue({
        configured: false,
        can_manage: false,
        bot_username: null,
        configured_at: null,
      });
      mockGetTelegramStatus.mockRejectedValue(
        new ApiError(503, "Telegram bot is not configured")
      );

      render(<TelegramSettingsPage />);

      await screen.findByRole("heading", {
        name: /connect your telegram account/i,
      });
      expect(
        screen.queryByRole("heading", { name: /bot setup/i })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /validate bot token/i })
      ).not.toBeInTheDocument();
    });

    it("hides configured bot metadata", async () => {
      mockGetTelegramBotConfig.mockResolvedValue({
        configured: true,
        can_manage: false,
        bot_username: "GlycemicGPTBot",
        configured_at: "2026-01-15T12:00:00Z",
      });
      mockGetTelegramStatus.mockResolvedValue({
        linked: false,
        bot_username: "GlycemicGPTBot",
      });

      render(<TelegramSettingsPage />);

      await screen.findByRole("heading", {
        name: /connect your telegram account/i,
      });
      expect(screen.queryByText("Configured")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: /bot setup/i })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /remove bot token/i })
      ).not.toBeInTheDocument();
    });
  });

  describe("when bot IS configured", () => {
    beforeEach(() => {
      mockGetTelegramBotConfig.mockResolvedValue({
        configured: true,
        can_manage: true,
        bot_username: "GlycemicGPTBot",
        configured_at: "2026-01-15T12:00:00Z",
      });
      mockGetTelegramStatus.mockResolvedValue({
        linked: false,
        bot_username: "GlycemicGPTBot",
      });
    });

    it("shows Configured badge", async () => {
      render(<TelegramSettingsPage />);

      // Wait for the page to load by checking for a known element
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });

      expect(screen.getByText("Configured")).toBeInTheDocument();
    });

    it("shows bot username", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });

      // Username appears in both bot config card and account linking instructions
      const usernameElements = screen.getAllByText("@GlycemicGPTBot");
      expect(usernameElements.length).toBeGreaterThanOrEqual(1);
    });

    it("shows Remove Bot Token button", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });
    });

    it("hides bot removal when the bot is managed by the server environment", async () => {
      mockGetTelegramBotConfig.mockResolvedValue({
        configured: true,
        can_manage: true,
        bot_username: "EnvironmentBot",
        configured_at: null,
      });
      mockGetTelegramStatus.mockResolvedValue({
        linked: false,
        bot_username: "EnvironmentBot",
      });

      render(<TelegramSettingsPage />);

      expect(await screen.findAllByText("@EnvironmentBot")).not.toHaveLength(0);
      expect(
        screen.queryByRole("button", { name: /remove bot token/i })
      ).not.toBeInTheDocument();
    });

    it("does NOT show bot not configured warning", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });

      expect(
        screen.queryByText(/telegram bot not configured/i)
      ).not.toBeInTheDocument();
    });

    it("enables Generate Code button for account linking", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /generate verification code/i })
        ).toBeEnabled();
      });
    });
  });

  describe("validate token flow", () => {
    beforeEach(() => {
      mockGetTelegramBotConfig.mockResolvedValue({
        configured: false,
        can_manage: true,
        bot_username: null,
        configured_at: null,
      });
      mockGetTelegramStatus.mockRejectedValue(
        new ApiError(503, "Telegram bot is not configured")
      );
    });

    it("calls saveTelegramBotToken on Validate click", async () => {
      mockSaveTelegramBotToken.mockResolvedValue({
        valid: true,
        bot_username: "MyTestBot",
      });

      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.change(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i),
          { target: { value: "123456:ABC-DEF" } }
        );
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /validate bot token/i })
        );
      });

      await waitFor(() => {
        expect(mockSaveTelegramBotToken).toHaveBeenCalledWith("123456:ABC-DEF");
      });
    });

    it("shows success message after valid token", async () => {
      mockSaveTelegramBotToken.mockResolvedValue({
        valid: true,
        bot_username: "MyTestBot",
      });
      // After validation, re-fetch status
      mockGetTelegramStatus
        .mockRejectedValueOnce(
          new ApiError(503, "Telegram bot is not configured")
        )
        .mockResolvedValue({
          linked: false,
          bot_username: "MyTestBot",
        });

      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.change(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i),
          { target: { value: "123456:ABC-DEF" } }
        );
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /validate bot token/i })
        );
      });

      await waitFor(() => {
        expect(
          screen.getByText(/bot token validated/i)
        ).toBeInTheDocument();
      });
    });

    it("shows error message on invalid token", async () => {
      mockSaveTelegramBotToken.mockRejectedValue(
        new Error("Invalid bot token")
      );

      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.change(
          screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i),
          { target: { value: "bad-token" } }
        );
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /validate bot token/i })
        );
      });

      await waitFor(() => {
        expect(screen.getByText("Invalid bot token")).toBeInTheDocument();
      });
    });
  });

  describe("remove bot token flow", () => {
    beforeEach(() => {
      mockGetTelegramBotConfig.mockResolvedValue({
        configured: true,
        can_manage: true,
        bot_username: "GlycemicGPTBot",
        configured_at: "2026-01-15T12:00:00Z",
      });
      mockGetTelegramStatus.mockResolvedValue({
        linked: false,
        bot_username: "GlycemicGPTBot",
      });
    });

    it("shows confirmation on Remove Bot Token click", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove bot token/i })
        );
      });

      expect(
        screen.getByText(/removing the bot token will disable/i)
      ).toBeInTheDocument();
      expect(screen.getByText("Yes, Remove")).toBeInTheDocument();
    });

    it("calls removeTelegramBotToken on confirm", async () => {
      mockRemoveTelegramBotToken.mockResolvedValue(undefined);

      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove bot token/i })
        );
      });

      await act(async () => {
        fireEvent.click(screen.getByText("Yes, Remove"));
      });

      await waitFor(() => {
        expect(mockRemoveTelegramBotToken).toHaveBeenCalled();
      });
    });

    it("dismisses confirmation on Cancel click", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove bot token/i })
        );
      });

      expect(screen.getByText("Yes, Remove")).toBeInTheDocument();

      await act(async () => {
        fireEvent.click(screen.getByText("Cancel"));
      });

      expect(screen.queryByText("Yes, Remove")).not.toBeInTheDocument();
    });

    it("transitions back to unconfigured state after successful removal", async () => {
      mockRemoveTelegramBotToken.mockResolvedValue(undefined);
      // After removal, bot config re-check returns not configured
      mockGetTelegramBotConfig
        .mockResolvedValueOnce({
          configured: true,
          can_manage: true,
          bot_username: "GlycemicGPTBot",
          configured_at: "2026-01-15T12:00:00Z",
        })
        .mockResolvedValueOnce({
          configured: false,
          can_manage: true,
          bot_username: null,
          configured_at: null,
        });
      mockGetTelegramStatus.mockRejectedValue(
        new ApiError(503, "Telegram bot is not configured")
      );

      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove bot token/i })
        );
      });

      await act(async () => {
        fireEvent.click(screen.getByText("Yes, Remove"));
      });

      await waitFor(() => {
        expect(screen.getByText(/bot token removed/i)).toBeInTheDocument();
      });

      // Should now show the token input form (unconfigured state)
      expect(
        screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
      ).toBeInTheDocument();
      // Configured badge should be gone
      expect(screen.queryByText("Configured")).not.toBeInTheDocument();
    });

    it("dismisses confirmation and shows error on removal failure", async () => {
      mockRemoveTelegramBotToken.mockRejectedValue(
        new Error("Permission denied")
      );

      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /remove bot token/i })
        ).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /remove bot token/i })
        );
      });

      await act(async () => {
        fireEvent.click(screen.getByText("Yes, Remove"));
      });

      await waitFor(() => {
        expect(screen.getByText("Permission denied")).toBeInTheDocument();
      });

      // Confirmation dialog should be dismissed
      expect(screen.queryByText("Yes, Remove")).not.toBeInTheDocument();
      // Should still show configured state (not reverted)
      expect(screen.getByText("Configured")).toBeInTheDocument();
    });
  });

  describe("offline state", () => {
    beforeEach(() => {
      mockGetTelegramBotConfig.mockRejectedValue(
        new Error("NetworkError: Failed to fetch")
      );
      mockGetTelegramStatus.mockRejectedValue(
        new Error("NetworkError: Failed to fetch")
      );
    });

    it("shows offline banner", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByText(/unable to connect to server/i)
        ).toBeInTheDocument();
      });
      expect(
        screen.queryByText(/telegram bot not configured/i)
      ).not.toBeInTheDocument();
    });

    it("retries a failed bot configuration request", async () => {
      mockGetTelegramBotConfig
        .mockRejectedValueOnce(new Error("NetworkError: Failed to fetch"))
        .mockResolvedValue({
          configured: false,
          can_manage: true,
          bot_username: null,
          configured_at: null,
        });

      render(<TelegramSettingsPage />);

      expect(
        await screen.findByText("Unable to load Telegram bot configuration.")
      ).toBeInTheDocument();

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      });

      expect(
        await screen.findByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
      ).toBeInTheDocument();
      expect(mockGetTelegramBotConfig).toHaveBeenCalledTimes(2);
    });

    it("hides Validate Token button when permissions cannot be loaded", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.queryByRole("button", { name: /validate bot token/i })
        ).not.toBeInTheDocument();
      });
    });

    it("hides token input when permissions cannot be loaded", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.queryByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i)
        ).not.toBeInTheDocument();
      });
    });
  });

  describe("page header and navigation", () => {
    beforeEach(() => {
      mockGetTelegramBotConfig.mockResolvedValue({
        configured: false,
        can_manage: true,
        bot_username: null,
        configured_at: null,
      });
      mockGetTelegramStatus.mockRejectedValue(
        new ApiError(503, "Telegram bot is not configured")
      );
    });

    it("renders page heading", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /telegram/i, level: 1 })
        ).toBeInTheDocument();
      });
    });

    it("shows Back to Communications link", async () => {
      render(<TelegramSettingsPage />);

      await waitFor(() => {
        const backLink = screen.getByText(/back to communications/i);
        expect(backLink.closest("a")).toHaveAttribute(
          "href",
          "/dashboard/settings/communications"
        );
      });
    });
  });
});
