import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  ApiError,
  generateTelegramCode,
  getTelegramBotConfig,
  getTelegramStatus,
  removeTelegramBotToken,
  saveTelegramBotToken,
  unlinkTelegram,
} from "@/lib/api";
import { ConfirmationProvider } from "@/compositions/ConfirmationProvider";
import { TelegramSettings } from "./TelegramSettings";

const mockRouterReplace = jest.fn();
const mockRouter = { replace: mockRouterReplace };

jest.mock("next/navigation", () => ({
  usePathname: () => "/settings/alarms-notification",
  useRouter: () => mockRouter,
}));

jest.mock("@/lib/api", () => ({
  ...jest.requireActual("@/lib/api"),
  generateTelegramCode: jest.fn(),
  getTelegramBotConfig: jest.fn(),
  getTelegramStatus: jest.fn(),
  removeTelegramBotToken: jest.fn(),
  saveTelegramBotToken: jest.fn(),
  sendTelegramTestMessage: jest.fn(),
  unlinkTelegram: jest.fn(),
}));

const mockGetTelegramBotConfig = jest.mocked(getTelegramBotConfig);
const mockGetTelegramStatus = jest.mocked(getTelegramStatus);
const mockGenerateTelegramCode = jest.mocked(generateTelegramCode);
const mockRemoveTelegramBotToken = jest.mocked(removeTelegramBotToken);
const mockSaveTelegramBotToken = jest.mocked(saveTelegramBotToken);
const mockUnlinkTelegram = jest.mocked(unlinkTelegram);

function renderTelegramSettingsPage(onLinkStatusChange?: () => void) {
  return render(
    <ConfirmationProvider>
      <TelegramSettings onLinkStatusChange={onLinkStatusChange} />
    </ConfirmationProvider>,
  );
}

describe("TelegramSettingsPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("redirects instead of showing an unlinked state after a 401", async () => {
    mockGetTelegramBotConfig.mockResolvedValue({
      bot_username: null,
      can_manage: true,
      configured: false,
      configured_at: null,
    });
    mockGetTelegramStatus.mockRejectedValue(
      new ApiError(401, "Session expired"),
    );

    renderTelegramSettingsPage();

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith(
        "/login?expired=true&redirect=%2Fsettings%2Falarms-notification",
      );
    });
  });

  it("does not install countdown or polling intervals for an expired code", async () => {
    jest.useFakeTimers();
    const setIntervalSpy = jest.spyOn(global, "setInterval");
    try {
      mockGetTelegramBotConfig.mockResolvedValue({
        bot_username: "lumose_bot",
        can_manage: true,
        configured: true,
        configured_at: "2026-08-01T10:00:00.000Z",
      });
      mockGetTelegramStatus.mockResolvedValue({
        bot_username: "lumose_bot",
        link: null,
        linked: false,
      });
      mockGenerateTelegramCode.mockResolvedValue({
        bot_username: "lumose_bot",
        code: "EXPIRED",
        expires_at: new Date(Date.now() - 1_000).toISOString(),
      });

      renderTelegramSettingsPage();
      fireEvent.click(
        await screen.findByRole("button", {
          name: /generate code/i,
        }),
      );

      expect(
        await screen.findByText(
          "Verification code expired. Please generate a new one.",
        ),
      ).toBeInTheDocument();
      expect(setIntervalSpy).not.toHaveBeenCalled();

      await act(async () => {
        jest.advanceTimersByTime(3_000);
      });
      expect(mockGetTelegramStatus).toHaveBeenCalledTimes(1);
      expect(setIntervalSpy).not.toHaveBeenCalled();
    } finally {
      setIntervalSpy.mockRestore();
      jest.useRealTimers();
    }
  });

  it("does not show bot management after a caregiver disconnects", async () => {
    const onLinkStatusChange = jest.fn();
    mockGetTelegramBotConfig.mockResolvedValue({
      bot_username: "lumose_bot",
      can_manage: false,
      configured: true,
      configured_at: "2026-08-01T10:00:00.000Z",
    });
    mockGetTelegramStatus.mockResolvedValue({
      bot_username: "lumose_bot",
      linked: true,
      link: {
        chat_id: 123,
        id: "telegram-link-id",
        is_verified: true,
        linked_at: "2026-08-01T10:00:00.000Z",
        username: "regular_user",
      },
    });
    mockUnlinkTelegram.mockResolvedValue({
      message: "Telegram account disconnected.",
      success: true,
    });

    renderTelegramSettingsPage(onLinkStatusChange);

    fireEvent.click(
      await screen.findByRole("button", { name: /disconnect telegram/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /yes, disconnect/i }));

    expect(
      await screen.findByText("Telegram account disconnected."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /connect with the existing bot/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Existing bot" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Bot username")).not.toBeInTheDocument();
    expect(
      screen.getByText("Existing Telegram bot available"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /remove existing bot/i }),
    ).not.toBeInTheDocument();
    expect(onLinkStatusChange).toHaveBeenCalledTimes(1);
  });

  it("hides bot setup from a non-administrator when no bot is configured", async () => {
    mockGetTelegramBotConfig.mockResolvedValue({
      bot_username: null,
      can_manage: false,
      configured: false,
      configured_at: null,
    });
    mockGetTelegramStatus.mockRejectedValue(
      new ApiError(503, "Telegram bot is not configured"),
    );

    renderTelegramSettingsPage();

    expect(
      await screen.findByText(/telegram bot not configured/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /add a new telegram bot/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i),
    ).not.toBeInTheDocument();
  });

  it("refreshes the delivery channel after an administrator adds a bot", async () => {
    const onLinkStatusChange = jest.fn();
    mockGetTelegramBotConfig.mockResolvedValue({
      bot_username: null,
      can_manage: true,
      configured: false,
      configured_at: null,
    });
    mockGetTelegramStatus.mockResolvedValue({
      bot_username: "lumose_bot",
      link: null,
      linked: false,
    });
    mockSaveTelegramBotToken.mockResolvedValue({
      bot_username: "lumose_bot",
      valid: true,
    });

    renderTelegramSettingsPage(onLinkStatusChange);

    fireEvent.change(
      await screen.findByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i),
      { target: { value: "123456789:test-token" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: /validate and add bot/i }),
    );

    await waitFor(() => {
      expect(onLinkStatusChange).toHaveBeenCalledTimes(1);
    });
  });

  it("redirects when loading bot configuration returns a 401", async () => {
    mockGetTelegramBotConfig.mockRejectedValue(
      new ApiError(401, "Session expired"),
    );
    mockGetTelegramStatus.mockRejectedValue(
      new ApiError(401, "Session expired"),
    );

    renderTelegramSettingsPage();

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith(
        "/login?expired=true&redirect=%2Fsettings%2Falarms-notification",
      );
    });
    expect(
      screen.queryByText("Unable to load Telegram bot configuration."),
    ).not.toBeInTheDocument();
  });

  it("reports when polling confirms a linked Telegram account", async () => {
    jest.useFakeTimers();
    const onLinkStatusChange = jest.fn();

    try {
      mockGetTelegramBotConfig.mockResolvedValue({
        bot_username: "lumose_bot",
        can_manage: true,
        configured: true,
        configured_at: "2026-08-01T10:00:00.000Z",
      });
      mockGetTelegramStatus
        .mockResolvedValueOnce({
          bot_username: "lumose_bot",
          link: null,
          linked: false,
        })
        .mockResolvedValueOnce({
          bot_username: "lumose_bot",
          linked: true,
          link: {
            chat_id: 123,
            id: "telegram-link-id",
            is_verified: true,
            linked_at: "2026-08-01T10:00:00.000Z",
            username: "regular_user",
          },
        })
        .mockResolvedValue({
          bot_username: "lumose_bot",
          link: null,
          linked: false,
        });
      mockGenerateTelegramCode.mockResolvedValue({
        bot_username: "lumose_bot",
        code: "FRESH1",
        expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
      });

      renderTelegramSettingsPage(onLinkStatusChange);

      fireEvent.click(
        await screen.findByRole("button", {
          name: /generate code/i,
        }),
      );
      await screen.findByText("/start FRESH1");

      await act(async () => {
        jest.advanceTimersByTime(3_000);
      });

      expect(onLinkStatusChange).toHaveBeenCalledTimes(1);
      expect(
        await screen.findByText("Telegram account linked successfully!"),
      ).toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  it("lets an administrator remove an existing bot before adding a new one", async () => {
    mockGetTelegramBotConfig
      .mockResolvedValueOnce({
        bot_username: "lumose_bot",
        can_manage: true,
        configured: true,
        configured_at: "2026-08-01T10:00:00.000Z",
      })
      .mockResolvedValueOnce({
        bot_username: null,
        can_manage: true,
        configured: false,
        configured_at: null,
      });
    mockGetTelegramStatus.mockResolvedValue({
      bot_username: "lumose_bot",
      link: null,
      linked: false,
    });
    mockRemoveTelegramBotToken.mockResolvedValue(undefined);

    renderTelegramSettingsPage();

    expect(
      await screen.findByText("Existing Telegram bot available"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Existing bot" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /remove existing bot/i }),
    );

    expect(
      await screen.findByRole("heading", { name: /remove existing bot/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/disconnect every linked telegram account/i),
    ).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Remove bot for everyone" }),
      );
    });

    await waitFor(() => {
      expect(mockRemoveTelegramBotToken).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByRole("heading", { name: /add a new telegram bot/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/you can now add a new bot/i),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/ABCdefGhIJKlmNoPQRsTUVwxyz/i),
    ).toBeInTheDocument();
  });

  it("shows the environment bot that becomes active after database removal", async () => {
    mockGetTelegramBotConfig
      .mockResolvedValueOnce({
        bot_username: "database_bot",
        can_manage: true,
        configured: true,
        configured_at: "2026-08-01T10:00:00.000Z",
      })
      .mockResolvedValueOnce({
        bot_username: "environment_bot",
        can_manage: true,
        configured: true,
        configured_at: null,
      });
    mockGetTelegramStatus
      .mockResolvedValueOnce({
        bot_username: "database_bot",
        link: null,
        linked: false,
      })
      .mockResolvedValueOnce({
        bot_username: "environment_bot",
        link: null,
        linked: false,
      });
    mockRemoveTelegramBotToken.mockResolvedValue(undefined);

    renderTelegramSettingsPage();

    fireEvent.click(
      await screen.findByRole("button", { name: /remove existing bot/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove bot for everyone" }),
    );

    expect(await screen.findByText("Managed outside Lumose")).toBeInTheDocument();
    expect(
      screen.getByText(/@environment_bot remains configured/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /add a new telegram bot/i }),
    ).not.toBeInTheDocument();
  });

  it("shows one refresh error after bot removal succeeds", async () => {
    const onLinkStatusChange = jest.fn();
    mockGetTelegramBotConfig
      .mockResolvedValueOnce({
        bot_username: "database_bot",
        can_manage: true,
        configured: true,
        configured_at: "2026-08-01T10:00:00.000Z",
      })
      .mockRejectedValueOnce(new Error("Request failed"));
    mockGetTelegramStatus.mockResolvedValue({
      bot_username: "database_bot",
      link: null,
      linked: false,
    });
    mockRemoveTelegramBotToken.mockResolvedValue(undefined);

    renderTelegramSettingsPage(onLinkStatusChange);

    fireEvent.click(
      await screen.findByRole("button", { name: /remove existing bot/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove bot for everyone" }),
    );

    expect(
      await screen.findByText("Unable to load Telegram bot configuration."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/bot removed, but the current telegram configuration/i),
    ).not.toBeInTheDocument();
    expect(onLinkStatusChange).toHaveBeenCalledTimes(1);
  });
});
