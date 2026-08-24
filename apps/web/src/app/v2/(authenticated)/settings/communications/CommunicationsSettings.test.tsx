import { render, screen, waitFor } from "@testing-library/react";
import { ApiError, getTelegramStatus } from "@/lib/api";

import { CommunicationsSettings } from "./CommunicationsSettings";

const mockRouter = { replace: jest.fn() };

jest.mock("next/navigation", () => ({
  usePathname: () => "/settings/alarms-notification",
  useRouter: () => mockRouter,
}));

jest.mock("@/lib/api", () => ({
  ...jest.requireActual("@/lib/api"),
  getTelegramStatus: jest.fn(),
}));

const mockGetTelegramStatus = jest.mocked(getTelegramStatus);

describe("CommunicationsSettings", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("refreshes the Telegram badge when the linked account changes", async () => {
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
      });

    const { rerender } = render(
      <CommunicationsSettings telegramStatusRefreshKey={0} />,
    );

    expect(await screen.findByText("Bot Available")).toBeInTheDocument();
    expect(
      screen.getByText(
        "@lumose_bot is ready. Link your Telegram account to receive notifications.",
      ),
    ).toBeInTheDocument();

    rerender(<CommunicationsSettings telegramStatusRefreshKey={1} />);

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Linked as @regular_user")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockGetTelegramStatus).toHaveBeenCalledTimes(2);
    });
  });

  it("clears a stale linked badge when the shared bot is removed", async () => {
    mockGetTelegramStatus
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
      .mockRejectedValueOnce(
        new ApiError(503, "Telegram bot is not configured"),
      );

    const { rerender } = render(
      <CommunicationsSettings telegramStatusRefreshKey={0} />,
    );

    expect(await screen.findByText("Connected")).toBeInTheDocument();

    rerender(<CommunicationsSettings telegramStatusRefreshKey={1} />);

    expect(await screen.findByText("Not Configured")).toBeInTheDocument();
    expect(screen.queryByText("Connected")).not.toBeInTheDocument();
  });

  it("does not report an available bot without a username", async () => {
    mockGetTelegramStatus.mockResolvedValue({
      bot_username: "",
      link: null,
      linked: false,
    });

    render(<CommunicationsSettings />);

    expect(await screen.findByText("Status Unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Bot Available")).not.toBeInTheDocument();
  });
});
