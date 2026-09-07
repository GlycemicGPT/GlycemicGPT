/**
 * The profile settings Meal Intelligence toggle must persist via the dedicated
 * endpoint and refresh the shared user context so the "Meals" nav and meal
 * surfaces appear/disappear immediately.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ProfilePage from "@/app/dashboard/settings/profile/page";
import { getCurrentUser, getSessionTimeout, updateMealIntelligence } from "@/lib/api";

jest.mock("@/lib/api");

const mockRefreshUser = jest.fn();
jest.mock("@/providers", () => ({
  useUserContext: () => ({
    user: { id: "u1", role: "diabetic" },
    isLoading: false,
    refreshUser: mockRefreshUser,
  }),
}));

const mockGetCurrentUser = getCurrentUser as jest.Mock;
const mockUpdateMeal = updateMealIntelligence as jest.Mock;

function userWith(mealEnabled: boolean) {
  return {
    id: "u1",
    email: "a@b.com",
    display_name: null,
    role: "diabetic",
    is_active: true,
    email_verified: true,
    disclaimer_acknowledged: true,
    disclaimer_version: "1",
    glucose_unit: "mgdl",
    meal_intelligence_enabled: mealEnabled,
    created_at: "2026-01-01T00:00:00Z",
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  (getSessionTimeout as jest.Mock).mockRejectedValue(new Error("NetworkError"));
  mockRefreshUser.mockResolvedValue(undefined);
});

it("renders the toggle on for an enabled user and disables it via the endpoint", async () => {
  mockGetCurrentUser.mockResolvedValue(userWith(true));
  mockUpdateMeal.mockResolvedValue({ enabled: false });

  render(<ProfilePage />);

  const toggle = await screen.findByRole("switch");
  expect(toggle).toHaveAttribute("aria-checked", "true");

  fireEvent.click(toggle);

  await waitFor(() => expect(mockUpdateMeal).toHaveBeenCalledWith(false));
  // Persisted state is reflected optimistically and the user context refreshes
  // so the Meals nav disappears.
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
  expect(mockRefreshUser).toHaveBeenCalled();
});

it("renders the toggle off for a disabled user and enables it via the endpoint", async () => {
  mockGetCurrentUser.mockResolvedValue(userWith(false));
  mockUpdateMeal.mockResolvedValue({ enabled: true });

  render(<ProfilePage />);

  const toggle = await screen.findByRole("switch");
  expect(toggle).toHaveAttribute("aria-checked", "false");

  fireEvent.click(toggle);

  await waitFor(() => expect(mockUpdateMeal).toHaveBeenCalledWith(true));
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  // The sidebar "Meals" nav reads from shared user context, so re-enabling must
  // refresh it too -- a regression that skipped this would hide the nav.
  expect(mockRefreshUser).toHaveBeenCalled();
});


it("renders deployment-specific session choices and the saved custom value", async () => {
  mockGetCurrentUser.mockResolvedValue(userWith(true));
  (getSessionTimeout as jest.Mock).mockResolvedValue({
    minutes: 45,
    min_minutes: 15,
    max_minutes: 60,
    presets: [15, 60],
  });
  render(<ProfilePage />);
  expect(await screen.findByRole("radio", { name: "45 minutes" })).toHaveAttribute(
    "aria-checked", "true",
  );
  expect(screen.getByRole("radio", { name: "15 minutes" })).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: "1 hour" })).toBeInTheDocument();
  expect(screen.queryByRole("radio", { name: "7 days" })).not.toBeInTheDocument();
});
