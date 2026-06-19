"use client";

/**
 * MealIntelligenceProvider -- shares a single meal-feature availability probe.
 *
 * Wraps `useMealIntelligence` in a context so the sidebar (desktop + mobile) and
 * the meals pages read one probe instead of each firing their own. Modelled on
 * `user-provider.tsx`: a non-null default + a no-throw hook.
 */

import { createContext, useContext } from "react";
import {
  useMealIntelligence,
  type UseMealIntelligenceReturn,
} from "@/hooks/use-meal-intelligence";

const MealIntelligenceContext = createContext<UseMealIntelligenceReturn>({
  enabled: null,
  isLoading: true,
});

export function MealIntelligenceProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const value = useMealIntelligence();

  return (
    <MealIntelligenceContext.Provider value={value}>
      {children}
    </MealIntelligenceContext.Provider>
  );
}

export function useMealIntelligenceContext(): UseMealIntelligenceReturn {
  return useContext(MealIntelligenceContext);
}
