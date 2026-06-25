/**
 * useMealIntelligence derives meal-feature availability from the shared user
 * context: null while loading, the boolean once resolved, and an absent field
 * (deploy skew against an older API) defaults to true so the feature stays
 * visible. The sidebar "Meals" nav and meal surfaces gate on this.
 */

import { renderHook } from "@testing-library/react";
import { useMealIntelligence } from "@/hooks/use-meal-intelligence";

const mockUserContext = jest.fn();
jest.mock("@/providers", () => ({
  useUserContext: () => mockUserContext(),
}));

describe("useMealIntelligence", () => {
  it("returns enabled=null while the user is loading", () => {
    mockUserContext.mockReturnValue({ user: null, isLoading: true });
    const { result } = renderHook(() => useMealIntelligence());
    expect(result.current).toEqual({ enabled: null, isLoading: true });
  });

  it("defaults an absent field to true (deploy-skew against an older API)", () => {
    mockUserContext.mockReturnValue({ user: { id: "u1" }, isLoading: false });
    const { result } = renderHook(() => useMealIntelligence());
    expect(result.current.enabled).toBe(true);
  });

  it("reflects an explicit false", () => {
    mockUserContext.mockReturnValue({
      user: { id: "u1", meal_intelligence_enabled: false },
      isLoading: false,
    });
    const { result } = renderHook(() => useMealIntelligence());
    expect(result.current.enabled).toBe(false);
  });

  it("reflects an explicit true", () => {
    mockUserContext.mockReturnValue({
      user: { id: "u1", meal_intelligence_enabled: true },
      isLoading: false,
    });
    const { result } = renderHook(() => useMealIntelligence());
    expect(result.current.enabled).toBe(true);
  });
});
