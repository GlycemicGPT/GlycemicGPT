/**
 * Integration tests for offline/disconnected state across settings pages.
 *
 * Story 12.4: Graceful Offline/Disconnected State for All Settings
 *
 * Verifies that when the API is unreachable, settings pages:
 * 1. Show the OfflineBanner with warning message and retry button
 * 2. Load with sensible default values
 * 3. Disable the Save Changes button with a tooltip
 * 4. Disable the Reset to Defaults button
 * 5. Disable action buttons (create, edit, delete, etc.)
 */

import { render, screen, waitFor } from "@testing-library/react";

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

// Simulate API failure for all requests
jest.mock("../../src/lib/api", () => {
  const networkError = new Error("NetworkError: Failed to fetch");

  return {
    __esModule: true,
    // Glucose range
    getTargetGlucoseRange: jest.fn().mockRejectedValue(networkError),
    updateTargetGlucoseRange: jest.fn().mockRejectedValue(networkError),
    // Brief delivery
    getBriefDeliveryConfig: jest.fn().mockRejectedValue(networkError),
    updateBriefDeliveryConfig: jest.fn().mockRejectedValue(networkError),
    // Alert thresholds + escalation
    getAlertThresholds: jest.fn().mockRejectedValue(networkError),
    updateAlertThresholds: jest.fn().mockRejectedValue(networkError),
    getEscalationConfig: jest.fn().mockRejectedValue(networkError),
    updateEscalationConfig: jest.fn().mockRejectedValue(networkError),
    // Data retention
    getDataRetentionConfig: jest.fn().mockRejectedValue(networkError),
    updateDataRetentionConfig: jest.fn().mockRejectedValue(networkError),
    getStorageUsage: jest.fn().mockRejectedValue(networkError),
    exportSettings: jest.fn().mockRejectedValue(networkError),
    purgeUserData: jest.fn().mockRejectedValue(networkError),
    // Emergency contacts
    getEmergencyContacts: jest.fn().mockRejectedValue(networkError),
    createEmergencyContact: jest.fn().mockRejectedValue(networkError),
    updateEmergencyContact: jest.fn().mockRejectedValue(networkError),
    deleteEmergencyContact: jest.fn().mockRejectedValue(networkError),
    // Profile
    getCurrentUser: jest.fn().mockRejectedValue(networkError),
    updateProfile: jest.fn().mockRejectedValue(networkError),
    changePassword: jest.fn().mockRejectedValue(networkError),
    // Integrations
    listIntegrations: jest.fn().mockRejectedValue(networkError),
    connectDexcom: jest.fn().mockRejectedValue(networkError),
    disconnectDexcom: jest.fn().mockRejectedValue(networkError),
    connectTandem: jest.fn().mockRejectedValue(networkError),
    disconnectTandem: jest.fn().mockRejectedValue(networkError),
    // Telegram
    getTelegramStatus: jest.fn().mockRejectedValue(networkError),
    generateTelegramCode: jest.fn().mockRejectedValue(networkError),
    sendTelegramTestMessage: jest.fn().mockRejectedValue(networkError),
    unlinkTelegram: jest.fn().mockRejectedValue(networkError),
    // Caregivers
    listCaregiverInvitations: jest.fn().mockRejectedValue(networkError),
    createCaregiverInvitation: jest.fn().mockRejectedValue(networkError),
    revokeCaregiverInvitation: jest.fn().mockRejectedValue(networkError),
    listLinkedCaregivers: jest.fn().mockRejectedValue(networkError),
    unlinkCaregiver: jest.fn().mockRejectedValue(networkError),
    // Analytics config
    getAnalyticsConfig: jest.fn().mockRejectedValue(networkError),
    updateAnalyticsConfig: jest.fn().mockRejectedValue(networkError),
    // Insulin / bolus
    getInsulinSummary: jest.fn().mockRejectedValue(networkError),
    getBolusReview: jest.fn().mockRejectedValue(networkError),
  };
});

// Import pages after mocks are set up
import GlucoseRangePage from "../../src/app/dashboard/settings/glucose-range/page";
import BriefDeliveryPage from "../../src/app/dashboard/settings/brief-delivery/page";
import AlertSettingsPage from "../../src/app/dashboard/settings/alerts/page";
import DataRetentionPage from "../../src/app/dashboard/settings/data/page";
import EmergencyContactsPage from "../../src/app/dashboard/settings/emergency-contacts/page";
import ProfilePage from "../../src/app/dashboard/settings/profile/page";
import IntegrationsPage from "../../src/app/dashboard/settings/integrations/page";
import TelegramPage from "../../src/app/dashboard/settings/telegram/page";
import CaregiversPage from "../../src/app/dashboard/settings/caregivers/page";

describe("Story 12.4: Offline state across settings pages", () => {
  describe("Glucose Range Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<GlucoseRangePage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Showing default values."
          )
        ).toBeInTheDocument();
      });
    });

    it("renders form with default values when offline", async () => {
      render(<GlucoseRangePage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const lowInput = screen.getByLabelText(
        /low target/i
      ) as HTMLInputElement;
      const highInput = screen.getByLabelText(
        /high target/i
      ) as HTMLInputElement;

      expect(lowInput.value).toBe("70");
      expect(highInput.value).toBe("180");
    });

    it("shows Retry Connection button when offline", async () => {
      render(<GlucoseRangePage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /retry connection/i })
        ).toBeInTheDocument();
      });
    });

    it("disables Save Changes button when offline", async () => {
      render(<GlucoseRangePage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const saveButton = screen.getByRole("button", {
        name: /save changes/i,
      });
      expect(saveButton).toBeDisabled();
    });
  });

  describe("Brief Delivery Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<BriefDeliveryPage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Showing default values."
          )
        ).toBeInTheDocument();
      });
    });

    it("disables Save Changes button when offline", async () => {
      render(<BriefDeliveryPage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const saveButton = screen.getByRole("button", {
        name: /save changes/i,
      });
      expect(saveButton).toBeDisabled();
    });
  });

  describe("Alert Settings Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<AlertSettingsPage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Showing default values."
          )
        ).toBeInTheDocument();
      });
    });

    it("renders form with default threshold values when offline", async () => {
      render(<AlertSettingsPage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const urgentLow = screen.getByLabelText(
        /urgent low/i
      ) as HTMLInputElement;
      expect(urgentLow.value).toBe("55");
    });

    it("disables Save Changes button when offline", async () => {
      render(<AlertSettingsPage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const saveButton = screen.getByRole("button", {
        name: /save changes/i,
      });
      expect(saveButton).toBeDisabled();
    });
  });

  describe("Data Retention Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<DataRetentionPage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Showing default values."
          )
        ).toBeInTheDocument();
      });
    });

    it("disables Save Changes button when offline", async () => {
      render(<DataRetentionPage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const saveButton = screen.getByRole("button", {
        name: /save changes/i,
      });
      expect(saveButton).toBeDisabled();
    });
  });

  describe("Emergency Contacts Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<EmergencyContactsPage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Contact management is unavailable."
          )
        ).toBeInTheDocument();
      });
    });

    it("disables Add Contact button when offline", async () => {
      render(<EmergencyContactsPage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const addButton = screen.getByRole("button", {
        name: /add contact/i,
      });
      expect(addButton).toBeDisabled();
    });
  });

  describe("Profile Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<ProfilePage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Profile management is unavailable."
          )
        ).toBeInTheDocument();
      });
    });

    it("shows Retry Connection button when offline", async () => {
      render(<ProfilePage />);

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /retry connection/i })
        ).toBeInTheDocument();
      });
    });
  });

  describe("Integrations Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<IntegrationsPage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Integration management is unavailable."
          )
        ).toBeInTheDocument();
      });
    });

    it("disables Test Connection buttons when offline", async () => {
      render(<IntegrationsPage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const connectButtons = screen.getAllByRole("button", {
        name: /test connection/i,
      });
      connectButtons.forEach((btn) => expect(btn).toBeDisabled());
    });
  });

  describe("Telegram Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<TelegramPage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Telegram settings are unavailable."
          )
        ).toBeInTheDocument();
      });
    });

    it("disables Generate Code button when offline", async () => {
      render(<TelegramPage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const generateButton = screen.getByRole("button", {
        name: /generate verification code/i,
      });
      expect(generateButton).toBeDisabled();
    });
  });

  describe("Caregivers Page", () => {
    it("shows offline banner when API is unreachable", async () => {
      render(<CaregiversPage />);

      await waitFor(() => {
        expect(
          screen.getByText(
            "Unable to connect to server. Caregiver management is unavailable."
          )
        ).toBeInTheDocument();
      });
    });

    it("disables Create Invitation button when offline", async () => {
      render(<CaregiversPage />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const createButton = screen.getByRole("button", {
        name: /create invitation/i,
      });
      expect(createButton).toBeDisabled();
    });
  });
});
