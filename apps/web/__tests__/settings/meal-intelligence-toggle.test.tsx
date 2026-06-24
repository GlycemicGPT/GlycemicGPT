/**
 * The profile settings Meal Intelligence toggle must persist via the dedicated
 * endpoint and refresh the shared user context so the "Meals" nav and meal
 * surfaces appear/disappear immediately.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ProfilePage from "@/app/dashboard/settings/profile/page";
import { getCurrentUser, updateMealIntelligence } from "@/lib/api";

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
});
