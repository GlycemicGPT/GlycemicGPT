"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import {
  formatTimeRangeLabel,
  resolveRawTimeRange,
  type RawTimeRangeInput,
} from "@/lib/glucose/time-range-expressions";
import type { HistorySelection, HistoryWindow } from "@/lib/glucose/history-selection";
import { GLUCOSE_TIME_RANGES, getTimeRangeHours, type TimeRange } from "@/lib/glucose/time-ranges";
import type {
  DashboardTimeRangeContextValue,
  DashboardTimeRangeProviderProps,
} from "./DashboardTimeRangeProvider.types";

const DashboardTimeRangeContext = createContext<DashboardTimeRangeContextValue | null>(null);

function getTimeZone(): string {
  if (typeof Intl === "undefined") {
    return "UTC";
  }

  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function getPresetRawTimeRange(range: TimeRange): RawTimeRangeInput {
  const hours = getTimeRangeHours(range) ?? 24;

  return {
    from: `now-${hours}h`,
    to: "now",
  };
}

export function getSelectionLabel(selection: HistorySelection, timeZone: string): string {
  if (selection.kind === "preset") {
    const preset = GLUCOSE_TIME_RANGES.find((range) => range.key === selection.range);
    return preset ? `Last ${preset.label}` : "Time range";
  }

  return selection.label ?? formatTimeRangeLabel(selection.window, timeZone);
}

function resolveSelectionWindow(selection: HistorySelection, timeZone: string, now: Date): HistoryWindow | null {
  if (selection.kind === "custom") {
    return selection.window;
  }

  return resolveRawTimeRange(getPresetRawTimeRange(selection.range), { timeZone, now })?.window ?? null;
}

export function DashboardTimeRangeProvider({
  children,
  defaultRange = "24h",
}: DashboardTimeRangeProviderProps) {
  const [{ selection, now }, setRange] = useState<{ selection: HistorySelection; now: Date }>(() => ({
    selection: { kind: "preset", range: defaultRange },
    now: new Date(),
  }));
  const [timeZone] = useState(getTimeZone);
  const setSelection = useCallback((selection: HistorySelection) => {
    setRange({ selection, now: new Date() });
  }, []);
  const refreshWindow = useCallback(() => {
    // Re-resolve rolling presets against now; historical selections stay fixed.
    setRange((current) => current.selection.kind === "preset"
      ? { ...current, now: new Date() }
      : current);
  }, []);

  const value = useMemo<DashboardTimeRangeContextValue>(() => ({
    selection,
    currentWindow: resolveSelectionWindow(selection, timeZone, now),
    label: getSelectionLabel(selection, timeZone),
    timeZone,
    setSelection,
    refreshWindow,
  }), [selection, timeZone, now, setSelection, refreshWindow]);

  return (
    <DashboardTimeRangeContext.Provider value={value}>
      {children}
    </DashboardTimeRangeContext.Provider>
  );
}

export function useDashboardTimeRange(): DashboardTimeRangeContextValue {
  const context = useContext(DashboardTimeRangeContext);

  if (!context) {
    throw new Error("useDashboardTimeRange must be used inside DashboardTimeRangeProvider");
  }

  return context;
}

export function useOptionalDashboardTimeRange(): DashboardTimeRangeContextValue | null {
  return useContext(DashboardTimeRangeContext);
}
