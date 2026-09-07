import type { ReactNode } from "react";
import type {
  HistorySelection,
  HistoryWindow,
} from "@/lib/glucose/history-selection";
import type { TimeRange } from "@/lib/glucose/time-ranges";

export interface DashboardTimeRangeContextValue {
  selection: HistorySelection;
  currentWindow: HistoryWindow | null;
  label: string;
  timeZone: string;
  setSelection: (selection: HistorySelection) => void;
  /** Advance a rolling preset to now without changing a historical selection. */
  refreshWindow: () => void;
}

export interface DashboardTimeRangeProviderProps {
  children: ReactNode;
  defaultRange?: TimeRange;
}
