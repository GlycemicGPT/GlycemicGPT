import { STATIC_ASSET_ICON_SPRITE_PATH } from "@/lib/staticAssets";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  changePassword,
  getCurrentUser,
  getSessionTimeout,
  updateGlucoseUnit,
  updateMealIntelligence,
  updateProfile,
  updateSessionTimeout,
  type CurrentUserResponse,
  type SessionTimeoutResponse,
} from "@/lib/api";
import { useNotifications } from "@/compositions/NotificationsProvider";
import { useUserContext } from "@/providers/user-provider";
import AccountPage from "../account/page";
import { ProfileSettings } from "./ProfileSettings";
import ProfilePage from "./page";

const mockRouterReplace = jest.fn();
const mockRouter = { replace: mockRouterReplace };

jest.mock("next/navigation", () => ({
  usePathname: () => "/settings/account",
  useRouter: () => mockRouter,
}));

jest.mock("@/lib/api", () => ({
  changePassword: jest.fn(),
  getCurrentUser: jest.fn(),
  getSessionTimeout: jest.fn(),
  updateGlucoseUnit: jest.fn(),
  updateMealIntelligence: jest.fn(),
  updateProfile: jest.fn(),
  updateSessionTimeout: jest.fn(),
}));

jest.mock("@/providers/user-provider", () => ({
  useUserContext: jest.fn(),
}));

jest.mock("@/compositions/NotificationsProvider", () => ({
  useNotifications: jest.fn(),
}));

const mockChangePassword = changePassword as jest.MockedFunction<
  typeof changePassword
>;
const mockGetCurrentUser = getCurrentUser as jest.MockedFunction<
  typeof getCurrentUser
>;
const mockUpdateGlucoseUnit = updateGlucoseUnit as jest.MockedFunction<
  typeof updateGlucoseUnit
>;
const mockUpdateMealIntelligence =
  updateMealIntelligence as jest.MockedFunction<typeof updateMealIntelligence>;
const mockGetSessionTimeout = getSessionTimeout as jest.MockedFunction<
  typeof getSessionTimeout
>;
const mockUpdateSessionTimeout =
  updateSessionTimeout as jest.MockedFunction<typeof updateSessionTimeout>;
const mockUpdateProfile = updateProfile as jest.MockedFunction<
  typeof updateProfile
>;
const mockUseUserContext = useUserContext as jest.MockedFunction<
  typeof useUserContext
>;
const mockUseNotifications = useNotifications as jest.MockedFunction<
  typeof useNotifications
>;

const PROFILE: CurrentUserResponse = {
  created_at: "2025-04-18T10:00:00.000Z",
  disclaimer_acknowledged: true,
  disclaimer_version: "2025-01",
  display_name: "Daniel",
  email: "daniel@example.com",
  email_verified: true,
  glucose_unit: "mgdl",
  id: "user-1",
  is_active: true,
  meal_intelligence_enabled: true,
  role: "diabetic",
};

const SESSION_TIMEOUT: SessionTimeoutResponse = {
  max_minutes: 10080,
  min_minutes: 15,
  minutes: 1440,
  presets: [15, 60, 360, 720, 1440, 10080],
};

const refreshUser = jest.fn();
const notifySuccess = jest.fn();

async function renderLoadedProfile() {
  render(<ProfilePage />);
  await screen.findByText(PROFILE.email);
}

async function renderLoadedPreference(section: "glucose" | "meal") {
  render(<ProfileSettings sections={[section]} />);
  if (section === "glucose") {
    await screen.findByRole("combobox", { name: "Glucose display unit" });
  } else {
    await screen.findByRole("switch");
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGetCurrentUser.mockResolvedValue(PROFILE);
  mockUpdateGlucoseUnit.mockResolvedValue({ glucose_unit: "mmol" });
  mockUpdateMealIntelligence.mockResolvedValue({ enabled: false });
  // Pending by default so account-view tests that don't exercise the session
  // control never trigger its async state update (act warnings); the session
  // tests below resolve it explicitly.
  mockGetSessionTimeout.mockReturnValue(new Promise(() => undefined));
  mockUpdateSessionTimeout.mockResolvedValue({
    ...SESSION_TIMEOUT,
    minutes: 15,
  });
  mockChangePassword.mockResolvedValue({ message: "Password changed" });
  mockUseUserContext.mockReturnValue({
    error: null,
    isLoading: false,
    refreshUser,
    user: PROFILE,
  });
  mockUseNotifications.mockReturnValue({
    notify: jest.fn(),
    notifyError: jest.fn(),
    notifySuccess,
    notifyWarning: jest.fn(),
    preferences: {
      browserNotificationsEnabled: false,
      soundEnabled: false,
    },
    setPreferences: jest.fn(),
  });
});

describe("ProfilePage", () => {
  it("adds spacious padding around account section separators", async () => {
    render(<AccountPage />);
    await screen.findByText(PROFILE.email);

    const accountDetails = screen.getByText(PROFILE.email).closest("dl");
    expect(accountDetails?.parentElement?.parentElement).toHaveClass(
      "space-y-32",
    );

    for (const sectionName of ["Personal Information", "Password"]) {
      expect(screen.getByRole("region", { name: sectionName })).toHaveClass(
        "before:-top-16",
      );
    }
  });

  it("announces loading while the profile request is pending", () => {
    mockGetCurrentUser.mockReturnValue(new Promise(() => undefined));

    render(<ProfilePage />);

    expect(
      screen.getByRole("status", { name: "Loading profile..." }),
    ).toHaveTextContent("Loading profile...");
  });

  it("loads and renders the current account details", async () => {
    await renderLoadedProfile();

    expect(mockGetCurrentUser).toHaveBeenCalledTimes(1);
    const accountHeading = screen.getByRole("heading", {
      level: 1,
      name: "Account",
    });
    const accountIcon = accountHeading
      .closest("header")
      ?.querySelector(`use[href="${STATIC_ASSET_ICON_SPRITE_PATH}#person"]`)
      ?.closest("svg");

    expect(accountIcon).toHaveClass("h-20", "w-20", "text-accent");
    expect(accountIcon).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Diabetic")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Display Name/)).toHaveValue("Daniel");
    expect(screen.getByLabelText(/^Display Name/)).not.toHaveAttribute(
      "maxLength",
    );
    expect(
      screen.queryByText(/Display name must|Use only letters/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Glucose display unit" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 2, name: "Preferences" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Current Password")).toBeInTheDocument();
    expect(screen.getByLabelText("New Password")).toBeInTheDocument();
    expect(screen.getByLabelText("Confirm New Password")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Current Password").closest("section"),
    ).toHaveClass("pb-[40vh]");
    expect(
      screen.getByRole("button", { name: "Change Password" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();

    const accountDetails = screen.getByText(PROFILE.email).closest("dl");
    expect(accountDetails?.parentElement).toHaveClass(
      "rounded-panel",
      "bg-surface-elevated",
      "p-6",
    );
    expect(
      screen.queryByRole("heading", { level: 2, name: "Account Information" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("These account details cannot be changed here."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Set a name to personalize your experience."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Email")).toHaveClass("text-foreground-primary");

    for (const sectionName of ["Personal Information", "Password"]) {
      expect(screen.getByRole("region", { name: sectionName })).toHaveClass(
        "before:border-t",
        "before:border-border-default",
      );
    }
  });

  it("redirects an expired session back through login", async () => {
    mockGetCurrentUser.mockRejectedValue(
      new Error("401: Authentication required"),
    );

    render(<ProfilePage />);

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith(
        "/login?expired=true&redirect=%2Fsettings%2Faccount",
      );
    });
  });

  it("saves a trimmed display name with the existing profile payload", async () => {
    let resolveUpdate: (profile: CurrentUserResponse) => void = () => {};
    mockUpdateProfile.mockReturnValue(
      new Promise((resolve) => {
        resolveUpdate = resolve;
      }),
    );
    await renderLoadedProfile();

    fireEvent.change(screen.getByLabelText(/^Display Name/), {
      target: { value: "  Dani-42 Name  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Saved" }),
    ).not.toBeInTheDocument();

    await act(async () => {
      resolveUpdate({ ...PROFILE, display_name: "Dani-42 Name" });
    });

    await waitFor(() => {
      expect(mockUpdateProfile).toHaveBeenCalledWith({
        display_name: "Dani-42 Name",
      });
      expect(refreshUser).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByRole("button", { name: "Saved" })).toBeDisabled();
    expect(
      screen.queryByText("Display name updated successfully"),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^Display Name/)).toHaveValue("Dani-42 Name");

    fireEvent.change(screen.getByLabelText(/^Display Name/), {
      target: { value: "@" },
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled();
  });

  it("reveals all current display name requirements after an invalid save", async () => {
    await renderLoadedProfile();
    const input = screen.getByLabelText(/^Display Name/);
    const saveButton = screen.getByRole("button", { name: "Save Changes" });

    fireEvent.change(input, { target: { value: "<" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(saveButton);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Display name must be at least 2 characters.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Use only letters, numbers, spaces, and hyphens.",
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(mockUpdateProfile).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "<a" } });
    expect(
      screen
        .getByText("Display name must be at least 2 characters.")
        .closest("li"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Use only letters, numbers, spaces, and hyphens.",
    );

    fireEvent.change(input, { target: { value: "D".repeat(21) } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(saveButton);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Display name must be 20 characters or fewer.",
    );
    expect(screen.getAllByRole("alert")).toHaveLength(1);

    fireEvent.change(input, { target: { value: "Dani-42" } });
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    fireEvent.change(input, { target: { value: "<" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(saveButton);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Display name must be at least 2 characters.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Use only letters, numbers, spaces, and hyphens.",
    );
  });

  it("does not reveal a corrected error again until another save attempt", async () => {
    await renderLoadedProfile();
    const input = screen.getByLabelText(/^Display Name/);
    const saveButton = screen.getByRole("button", { name: "Save Changes" });

    fireEvent.change(input, { target: { value: "<" } });
    fireEvent.click(saveButton);

    expect(screen.getAllByRole("listitem")).toHaveLength(2);

    fireEvent.change(input, { target: { value: "<a" } });
    expect(
      screen
        .getByText("Display name must be at least 2 characters.")
        .closest("li"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Use only letters, numbers, spaces, and hyphens.",
    );

    fireEvent.change(input, { target: { value: "<" } });
    expect(
      screen
        .getByText("Display name must be at least 2 characters.")
        .closest("li"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Use only letters, numbers, spaces, and hyphens.",
    );
    expect(screen.getAllByRole("alert")).toHaveLength(1);

    fireEvent.click(saveButton);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Display name must be at least 2 characters.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Use only letters, numbers, spaces, and hyphens.",
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(mockUpdateProfile).not.toHaveBeenCalled();
  });

  it("animates an additional error revealed by a later save attempt", async () => {
    const animationFrames: FrameRequestCallback[] = [];
    const requestAnimationFrameSpy = jest
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback) => {
        animationFrames.push(callback);
        return animationFrames.length;
      });
    const cancelAnimationFrameSpy = jest
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation();

    try {
      await renderLoadedProfile();
      const input = screen.getByLabelText(/^Display Name/);
      const saveButton = screen.getByRole("button", { name: "Save Changes" });

      fireEvent.change(input, { target: { value: "<a" } });
      fireEvent.click(saveButton);

      act(() => {
        while (animationFrames.length > 0) {
          animationFrames.shift()?.(0);
        }
      });

      fireEvent.change(input, { target: { value: "<" } });
      expect(
        screen.queryByText("Display name must be at least 2 characters."),
      ).not.toBeInTheDocument();

      fireEvent.click(saveButton);

      const addedErrorTransition = screen
        .getByText("Display name must be at least 2 characters.")
        .closest("li")?.firstElementChild;

      expect(addedErrorTransition).toHaveClass(
        "grid-rows-[0fr]",
        "-translate-y-2",
        "opacity-0",
      );

      act(() => {
        while (animationFrames.length > 0) {
          animationFrames.shift()?.(0);
        }
      });

      expect(addedErrorTransition).toHaveClass(
        "grid-rows-[1fr]",
        "translate-y-0",
        "opacity-100",
      );
      expect(mockUpdateProfile).not.toHaveBeenCalled();
    } finally {
      requestAnimationFrameSpy.mockRestore();
      cancelAnimationFrameSpy.mockRestore();
    }
  });

  it("shows display name save failures beside the field", async () => {
    mockUpdateProfile.mockRejectedValue(
      new Error("Display name is unavailable"),
    );
    await renderLoadedProfile();

    fireEvent.change(screen.getByLabelText(/^Display Name/), {
      target: { value: "Taken" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Display name is unavailable",
    );
    expect(screen.getByLabelText(/^Display Name/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled();
  });

  it("saves glucose unit changes immediately and refreshes user context", async () => {
    await renderLoadedPreference("glucose");

    fireEvent.change(
      screen.getByRole("combobox", { name: "Glucose display unit" }),
      { target: { value: "mmol" } },
    );

    await waitFor(() => {
      expect(mockUpdateGlucoseUnit).toHaveBeenCalledWith("mmol");
      expect(refreshUser).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByRole("combobox", { name: "Glucose display unit" }),
    ).toHaveValue("mmol");
    expect(screen.getByText("Glucose unit set to mmol/L")).toBeInTheDocument();
  });

  it("saves Meal Intelligence changes immediately and refreshes user context", async () => {
    await renderLoadedPreference("meal");

    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() => {
      expect(mockUpdateMealIntelligence).toHaveBeenCalledWith(false);
      expect(refreshUser).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByRole("switch")).not.toBeChecked();
    expect(notifySuccess).toHaveBeenCalledWith("Meal Intelligence disabled");
    expect(
      screen.queryByText("Meal Intelligence disabled"),
    ).not.toBeInTheDocument();
  });

  it("can present a preference as a settings section heading", async () => {
    render(
      <ProfileSettings embedded preferenceLabelAs="h2" sections={["meal"]} />,
    );

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Meal Intelligence",
      }),
    ).toHaveClass("font_header_3");
  });

  it("validates matching passwords before using the existing password payload", async () => {
    await renderLoadedProfile();

    fireEvent.change(screen.getByLabelText("Current Password"), {
      target: { value: "OldPassword1" },
    });
    fireEvent.change(screen.getByLabelText("New Password"), {
      target: { value: "NewPassword1" },
    });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), {
      target: { value: "DifferentPassword1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change Password" }));

    expect(
      await screen.findByText("New passwords do not match."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Confirm New Password")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(mockChangePassword).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Confirm New Password"), {
      target: { value: "NewPassword1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change Password" }));

    await waitFor(() => {
      expect(mockChangePassword).toHaveBeenCalledWith({
        current_password: "OldPassword1",
        new_password: "NewPassword1",
      });
    });
    expect(
      await screen.findByRole("button", { name: "Password Changed" }),
    ).toBeDisabled();
    expect(
      screen.queryByText("Password changed successfully"),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Current Password")).toHaveValue("");
    expect(screen.getByLabelText("New Password")).toHaveValue("");
    expect(screen.getByLabelText("Confirm New Password")).toHaveValue("");
  });

  it("clears stale success feedback before password validation", async () => {
    render(<ProfileSettings sections={["account", "glucose"]} />);
    await screen.findByText(PROFILE.email);

    fireEvent.change(
      screen.getByRole("combobox", { name: "Glucose display unit" }),
      { target: { value: "mmol" } },
    );
    expect(await screen.findByText("Glucose unit set to mmol/L")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Current Password"), {
      target: { value: "current" },
    });
    fireEvent.change(screen.getByLabelText("New Password"), {
      target: { value: "weak" },
    });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), {
      target: { value: "weak" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change Password" }));

    await waitFor(() => {
      expect(
        screen.queryByText("Glucose unit set to mmol/L"),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText("Include at least one uppercase letter."),
      ).toBeVisible();
    });
  });

  it("reveals password requirements only after save and hides corrected errors", async () => {
    await renderLoadedProfile();

    const currentPasswordInput = screen.getByLabelText("Current Password");
    const newPasswordInput = screen.getByLabelText("New Password");
    const confirmPasswordInput = screen.getByLabelText("Confirm New Password");

    fireEvent.change(currentPasswordInput, {
      target: { value: "OldPassword1" },
    });
    fireEvent.change(newPasswordInput, {
      target: { value: "password" },
    });
    fireEvent.change(confirmPasswordInput, {
      target: { value: "password" },
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Include at least one uppercase letter."),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Change Password" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Include at least one uppercase letter.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Include at least one number.",
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(mockChangePassword).not.toHaveBeenCalled();

    fireEvent.change(newPasswordInput, {
      target: { value: "Password" },
    });
    expect(
      screen.getByText("Include at least one uppercase letter.").closest("li"),
    ).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Include at least one number.",
    );

    fireEvent.change(newPasswordInput, {
      target: { value: "Password1" },
    });
    fireEvent.change(confirmPasswordInput, {
      target: { value: "Password1" },
    });
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    fireEvent.change(newPasswordInput, {
      target: { value: "password1" },
    });
    fireEvent.change(confirmPasswordInput, {
      target: { value: "password1" },
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Change Password" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Include at least one uppercase letter.",
    );
    expect(mockChangePassword).not.toHaveBeenCalled();
  });

  it("shows an incorrect current password error beside its field", async () => {
    mockChangePassword.mockRejectedValue(
      new Error("Current password is incorrect"),
    );
    await renderLoadedProfile();

    const currentPasswordInput = screen.getByLabelText("Current Password");
    const newPasswordInput = screen.getByLabelText("New Password");

    fireEvent.change(currentPasswordInput, {
      target: { value: "IncorrectPassword1" },
    });
    fireEvent.change(newPasswordInput, {
      target: { value: "NewPassword1" },
    });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), {
      target: { value: "NewPassword1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change Password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Current password is incorrect",
    );
    expect(currentPasswordInput).toHaveAttribute("aria-invalid", "true");
    expect(currentPasswordInput).toHaveAttribute(
      "aria-describedby",
      "current-password-error",
    );
    expect(screen.queryByText("Could not save")).not.toBeInTheDocument();

    fireEvent.change(newPasswordInput, {
      target: { value: "AnotherPassword1" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Current password is incorrect",
    );

    fireEvent.change(currentPasswordInput, {
      target: { value: "CorrectedPassword1" },
    });
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(currentPasswordInput).toHaveAttribute("aria-invalid", "false");
    });
  });

  it("shows offline feedback and retries the profile request", async () => {
    mockGetCurrentUser.mockRejectedValueOnce(new Error("Network unavailable"));
    let resolveRetry: ((value: CurrentUserResponse) => void) | undefined;
    mockGetCurrentUser.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRetry = resolve;
      }),
    );
    render(<ProfilePage />);

    const retry = await screen.findByRole("button", {
      name: "Retry connection",
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Profile management is unavailable",
    );

    fireEvent.click(retry);

    expect(screen.getByRole("button", { name: "Retrying..." })).toBeDisabled();
    expect(
      screen.getByRole("status", { name: "Loading profile..." }),
    ).toBeVisible();

    resolveRetry?.(PROFILE);

    expect(await screen.findByText(PROFILE.email)).toBeInTheDocument();
    expect(mockGetCurrentUser).toHaveBeenCalledTimes(2);
  });

  it("renders the session length control with the current value on the account view", async () => {
    mockGetSessionTimeout.mockResolvedValue(SESSION_TIMEOUT);
    render(<ProfileSettings sections={["account"]} />);

    const select = await screen.findByRole("combobox", {
      name: "Session length",
    });
    expect(mockGetSessionTimeout).toHaveBeenCalledTimes(1);
    // 1440 minutes from the mocked preference -> the "24 hours" preset.
    expect(select).toHaveValue("1440");
  });

  it("saves a new session length and reflects it, applying at next sign-in", async () => {
    mockGetSessionTimeout.mockResolvedValue(SESSION_TIMEOUT);
    render(<ProfileSettings sections={["account"]} />);

    fireEvent.change(
      await screen.findByRole("combobox", { name: "Session length" }),
      { target: { value: "15" } },
    );

    await waitFor(() => {
      expect(mockUpdateSessionTimeout).toHaveBeenCalledWith(15);
    });
    // Applies at next login, so the shared user context is never refreshed.
    expect(refreshUser).not.toHaveBeenCalled();
    expect(
      screen.getByRole("combobox", { name: "Session length" }),
    ).toHaveValue("15");
    expect(notifySuccess).toHaveBeenCalledWith(
      "Session length set to 15 minutes",
    );
  });
});
