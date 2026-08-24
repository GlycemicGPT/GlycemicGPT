import { fireEvent, render, screen } from "@testing-library/react";
import { useUserContext } from "@/providers/user-provider";

import AccountPage from "./account/page";
import AISettingsPage from "./ai/page";
import AlarmsNotificationSettingsPage from "./alarms-notification/page";
import CareAndSharingSettingsPage from "./care-sharing/page";
import ConnectionsSettingsPage from "./connections/page";
import DataPrivacySettingsPage from "./data-privacy/page";
import HealthSettingsPage from "./health/page";

jest.mock("@/providers/user-provider", () => ({
  useUserContext: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
  }),
}));

jest.mock("./profile/ProfileSettings", () => ({
  ProfileSettings: ({ sections }: { sections: string[] }) => (
    <div>Profile sections: {sections.join(", ")}</div>
  ),
}));

jest.mock("./glucose-range/page", () => ({
  __esModule: true,
  default: () => <div>Glucose range settings</div>,
}));

jest.mock("./integrations/IntegrationsSettings", () => ({
  __esModule: true,
  default: () => <div>Connection settings</div>,
}));

jest.mock("./ai-provider/page", () => ({
  __esModule: true,
  default: () => <div>AI provider settings</div>,
}));

jest.mock("./research-sources/page", () => ({
  __esModule: true,
  default: () => <div>Research source settings</div>,
}));

jest.mock("./insulin/page", () => ({
  __esModule: true,
  default: () => <div>Insulin settings</div>,
}));

jest.mock("./emergency-contacts/page", () => ({
  __esModule: true,
  default: () => <div>Emergency contact settings</div>,
}));

jest.mock("./caregivers/CaregiversSettings", () => ({
  CaregiversSettings: ({
    onManagePermissions,
  }: {
    onManagePermissions?: (caregiverId: string) => void;
  }) => (
    <div>
      Caregiver access settings
      <button onClick={() => onManagePermissions?.("caregiver-1")}>
        Manage caregiver permissions
      </button>
    </div>
  ),
}));

jest.mock(
  "./caregivers/[linkId]/permissions/CaregiverPermissionsSettings",
  () => ({
    CaregiverPermissionsSettings: () => (
      <div>Caregiver permission settings</div>
    ),
  }),
);

jest.mock("./data/page", () => ({
  __esModule: true,
  default: () => <div>Data management settings</div>,
}));

jest.mock("./safety-limits/page", () => ({
  __esModule: true,
  default: () => <div>Safety limit settings</div>,
}));

jest.mock("./alerts/page", () => ({
  __esModule: true,
  default: () => <div>Alert settings</div>,
}));

jest.mock("./brief-delivery/page", () => ({
  __esModule: true,
  default: () => <div>Daily brief settings</div>,
}));

jest.mock("./communications/CommunicationsSettings", () => ({
  CommunicationsSettings: ({
    telegramStatusRefreshKey,
  }: {
    telegramStatusRefreshKey?: number;
  }) => (
    <div>
      Delivery channel settings
      <span>Telegram status refresh {telegramStatusRefreshKey}</span>
    </div>
  ),
}));

jest.mock("./telegram/TelegramSettings", () => ({
  __esModule: true,
  TelegramSettings: ({
    onLinkStatusChange,
  }: {
    onLinkStatusChange?: () => void;
  }) => (
    <div>
      Telegram settings
      <button onClick={onLinkStatusChange}>Report Telegram link change</button>
    </div>
  ),
}));

const mockUseUserContext = useUserContext as jest.MockedFunction<
  typeof useUserContext
>;

beforeEach(() => {
  mockUseUserContext.mockReturnValue({
    error: null,
    isLoading: false,
    refreshUser: jest.fn(),
    user: {
      created_at: "2026-01-01T00:00:00.000Z",
      disclaimer_acknowledged: true,
      disclaimer_version: "2026-01",
      display_name: "Daniel",
      email: "daniel@example.com",
      email_verified: true,
      id: "user-1",
      is_active: true,
      role: "diabetic",
    },
  });
});

describe("consolidated settings pages", () => {
  it("keeps Account focused on account settings", () => {
    render(<AccountPage />);

    expect(screen.getByText("Profile sections: account")).toBeInTheDocument();
  });

  it("groups glucose display, ranges, insulin action, and safety limits", () => {
    render(<HealthSettingsPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Glucose & Insulin" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Profile sections: glucose")).toBeInTheDocument();
    expect(screen.getByText("Glucose range settings")).toBeInTheDocument();
    expect(screen.getByText("Insulin settings")).toBeInTheDocument();
    expect(screen.getByText("Safety limit settings")).toBeInTheDocument();
  });

  it("groups every supported connection source", async () => {
    render(
      await ConnectionsSettingsPage({
        searchParams: Promise.resolve({}),
      }),
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "Connections" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Connection settings")).toBeInTheDocument();
  });

  it("groups meal intelligence, provider, and research settings", () => {
    render(<AISettingsPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "AI & Insight" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Control AI assisted meal analysis and carbohydrate estimates.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Profile sections: meal")).toBeInTheDocument();
    expect(screen.getByText("AI provider settings")).toBeInTheDocument();
    expect(screen.getByText("Research source settings")).toBeInTheDocument();
  });

  it("groups patient alerts, briefs, delivery channels, and Telegram", () => {
    render(<AlarmsNotificationSettingsPage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Alarms & Notifications",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Alert settings")).toBeInTheDocument();
    expect(screen.getByText("Daily brief settings")).toBeInTheDocument();
    expect(screen.getByText("Delivery channel settings")).toBeInTheDocument();
    expect(screen.getByText("Telegram settings")).toBeInTheDocument();
  });

  it("refreshes delivery channel status when the Telegram link changes", () => {
    render(<AlarmsNotificationSettingsPage />);

    expect(screen.getByText("Telegram status refresh 0")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Report Telegram link change" }),
    );

    expect(screen.getByText("Telegram status refresh 1")).toBeInTheDocument();
  });

  it("limits caregiver notifications to delivery channels", () => {
    mockUseUserContext.mockReturnValue({
      ...mockUseUserContext(),
      user: {
        ...mockUseUserContext().user!,
        role: "caregiver",
      },
    });

    render(<AlarmsNotificationSettingsPage />);

    expect(screen.queryByText("Alert settings")).not.toBeInTheDocument();
    expect(screen.queryByText("Daily brief settings")).not.toBeInTheDocument();
    expect(screen.getByText("Delivery channel settings")).toBeInTheDocument();
    expect(screen.getByText("Telegram settings")).toBeInTheDocument();
  });

  it("groups emergency contacts and caregiver access", () => {
    render(<CareAndSharingSettingsPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Care & Sharing" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Emergency contact settings")).toBeInTheDocument();
    expect(screen.getByText("Caregiver access settings")).toBeInTheDocument();
  });

  it("focuses the caregiver permissions heading when it opens", () => {
    render(<CareAndSharingSettingsPage />);

    fireEvent.click(
      screen.getByRole("button", { name: "Manage caregiver permissions" }),
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "Caregiver Permissions" }),
    ).toHaveFocus();
  });

  it("groups retention, export, and deletion under data management", () => {
    render(<DataPrivacySettingsPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Data & Privacy" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Data management settings")).toBeInTheDocument();
  });
});
