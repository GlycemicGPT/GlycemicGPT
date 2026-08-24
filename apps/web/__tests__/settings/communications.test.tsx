/**
 * Tests for the Communications Settings Hub page.
 *
 * Story 12.2: Redesign Communications Settings Hub
 *
 * Verifies:
 * 1. Page renders with correct heading and back link
 * 2. Telegram channel card shows connected/not connected status
 * 3. Future channels (Discord, Email) show as "Coming Soon"
 * 4. Offline banner appears when API is unreachable
 * 5. Telegram card links to the detailed Telegram settings page
 */

import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";

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

const mockGetTelegramStatus = jest.fn();

jest.mock("../../src/lib/api", () => ({
  __esModule: true,
  ApiError: jest.requireActual("../../src/lib/api").ApiError,
  getTelegramStatus: (...args: unknown[]) => mockGetTelegramStatus(...args),
}));

import { ApiError } from "../../src/lib/api";
import CommunicationsPage from "../../src/app/dashboard/settings/communications/page";

describe("Story 12.2: Communications Settings Hub", () => {
  beforeEach(() => {
    mockGetTelegramStatus.mockReset();
  });

  describe("when Telegram is not linked", () => {
    beforeEach(() => {
      mockGetTelegramStatus.mockResolvedValue({
        linked: false,
        bot_username: "GlycemicGPTBot",
      });
    });

    it("renders page heading and description", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /communications/i, level: 1 })
        ).toBeInTheDocument();
      });

      expect(
        screen.getByText(/configure notification channels/i)
      ).toBeInTheDocument();
    });

    it("shows Back to Settings link", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        const backLink = screen.getByText(/back to settings/i);
        expect(backLink.closest("a")).toHaveAttribute(
          "href",
          "/dashboard/settings"
        );
      });
    });

    it("shows Telegram channel as Not Connected", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(screen.getByText("Not Connected")).toBeInTheDocument();
      });

      expect(
        screen.getByText(/receive alerts and daily briefs via telegram bot/i)
      ).toBeInTheDocument();
    });

    it("links Telegram card to telegram settings", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(screen.getByText("Telegram")).toBeInTheDocument();
      });

      const telegramLink = screen.getByText("Telegram").closest("a");
      expect(telegramLink).toHaveAttribute(
        "href",
        "/dashboard/settings/telegram"
      );
    });
  });

  describe("when Telegram is linked", () => {
    beforeEach(() => {
      mockGetTelegramStatus.mockResolvedValue({
        linked: true,
        bot_username: "GlycemicGPTBot",
        link: {
          username: "testuser",
          linked_at: "2026-01-15T12:00:00Z",
        },
      });
    });

    it("shows Telegram channel as Connected", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(screen.getByText("Connected")).toBeInTheDocument();
      });
    });

    it("shows linked username", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(screen.getByText("Linked as @testuser")).toBeInTheDocument();
      });
    });
  });

  describe("loading state", () => {
    it("shows loading indicator before API resolves", async () => {
      let resolve: (v: unknown) => void;
      mockGetTelegramStatus.mockReturnValue(
        new Promise((r) => {
          resolve = r;
        })
      );

      render(<CommunicationsPage />);

      expect(
        screen.getByRole("status", { name: /loading communication channels/i })
      ).toBeInTheDocument();

      // Resolve the promise to prevent act warnings
      await act(async () => {
        resolve!({ linked: false, bot_username: "GlycemicGPTBot" });
      });
    });
  });

  describe("future channels", () => {
    beforeEach(() => {
      mockGetTelegramStatus.mockResolvedValue({
        linked: false,
        bot_username: "GlycemicGPTBot",
      });
    });

    it("shows Discord as coming soon", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(screen.getByText("Discord")).toBeInTheDocument();
      });

      const comingSoonBadges = screen.getAllByText("Coming Soon");
      expect(comingSoonBadges.length).toBeGreaterThanOrEqual(1);
    });

    it("shows Email as coming soon", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(screen.getByText("Email")).toBeInTheDocument();
      });
    });
  });

  describe("offline state", () => {
    beforeEach(() => {
      mockGetTelegramStatus.mockRejectedValue(
        new Error("NetworkError: Failed to fetch")
      );
    });

    it("shows offline banner when API is unreachable", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(
          screen.getByText(/unable to connect to server/i)
        ).toBeInTheDocument();
      });
    });

    it("shows Retry Connection button", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /retry connection/i })
        ).toBeInTheDocument();
      });
    });

    it("clicking Retry calls getTelegramStatus again", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /retry connection/i })
        ).toBeInTheDocument();
      });

      // First call was the initial load
      expect(mockGetTelegramStatus).toHaveBeenCalledTimes(1);

      // Retry still fails
      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: /retry connection/i })
        );
      });

      await waitFor(() => {
        expect(mockGetTelegramStatus).toHaveBeenCalledTimes(2);
      });
    });

    it("clears offline banner when retry succeeds", async () => {
      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(
          screen.getByText(/unable to connect to server/i)
        ).toBeInTheDocument();
      });

      // Next call succeeds
      mockGetTelegramStatus.mockResolvedValue({
        linked: false,
        bot_username: "GlycemicGPTBot",
      });

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
  });

  describe("401 error handling", () => {
    it("does not show offline banner on 401 errors", async () => {
      mockGetTelegramStatus.mockRejectedValue(
        new ApiError(401, "Session expired")
      );

      render(<CommunicationsPage />);

      // Wait for loading to complete
      await waitFor(() => {
        expect(
          screen.queryByRole("status", {
            name: /loading communication channels/i,
          })
        ).not.toBeInTheDocument();
      });

      expect(
        screen.queryByText(/unable to connect to server/i)
      ).not.toBeInTheDocument();
    });
  });

  describe("unconfigured bot handling", () => {
    it("does not show the offline banner when the server reports that the bot is not configured", async () => {
      mockGetTelegramStatus.mockRejectedValue(
        new ApiError(503, "Telegram bot is not configured")
      );

      render(<CommunicationsPage />);

      await waitFor(() => {
        expect(
          screen.queryByRole("status", {
            name: /loading communication channels/i,
          })
        ).not.toBeInTheDocument();
      });

      expect(
        screen.queryByText(/unable to connect to server/i)
      ).not.toBeInTheDocument();
    });
  });
});
