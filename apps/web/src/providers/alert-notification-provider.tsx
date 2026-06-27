"use client";

/**
 * Story 6.3: Alert Notification Provider
 *
 * Orchestrates tiered alert delivery: toast notifications,
 * audio alerts, and browser notifications. Manages user
 * preferences via localStorage.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { AlertToast } from "@/components/dashboard/alert-toast";
import type { AlertEventData } from "@/hooks/use-glucose-stream";
import { useGlucoseUnit } from "@/hooks/use-glucose-unit";
import { formatAlertSummary } from "@/lib/alert-utils";
import { playAlertSound } from "@/lib/audio";
import { showBrowserNotification } from "@/lib/browser-notifications";
import { GlucoseStreamProvider } from "./glucose-stream-provider";

const PREFS_KEY = "glycemicgpt-alert-preferences";
const DISMISSED_KEY = "glycemicgpt-dismissed-alerts";
const MAX_VISIBLE_TOASTS = 5;
const MAX_DISMISSED_IDS = 500;

/** Severity priority for toast eviction (higher = more important) */
const SEVERITY_PRIORITY: Record<string, number> = {
  info: 0,
  warning: 1,
  urgent: 2,
  emergency: 3,
};

export interface AlertPreferences {
  soundEnabled: boolean;
  browserNotificationsEnabled: boolean;
}

const DEFAULT_PREFERENCES: AlertPreferences = {
  soundEnabled: true,
  browserNotificationsEnabled: false,
};

export interface AlertNotificationContextValue {
  preferences: AlertPreferences;
  setPreferences: (prefs: AlertPreferences) => void;
}

const AlertNotificationContext =
  createContext<AlertNotificationContextValue | null>(null);

function loadPreferences(): AlertPreferences {
  if (typeof window === "undefined") return DEFAULT_PREFERENCES;
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        soundEnabled:
          typeof parsed.soundEnabled === "boolean"
            ? parsed.soundEnabled
            : DEFAULT_PREFERENCES.soundEnabled,
        browserNotificationsEnabled:
          typeof parsed.browserNotificationsEnabled === "boolean"
            ? parsed.browserNotificationsEnabled
            : DEFAULT_PREFERENCES.browserNotificationsEnabled,
      };
    }
  } catch {
    // Corrupted localStorage - use defaults
  }
  return DEFAULT_PREFERENCES;
}

function savePreferences(prefs: AlertPreferences): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // Storage full or unavailable
  }
}

function getDismissedAlerts(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = sessionStorage.getItem(DISMISSED_KEY);
    if (raw) {
      const ids: string[] = JSON.parse(raw);
      // Cap to prevent unbounded growth
      return new Set(ids.slice(-MAX_DISMISSED_IDS));
    }
  } catch {
    // Ignore
  }
  return new Set();
}

function addDismissedAlert(id: string): void {
  try {
    const dismissed = getDismissedAlerts();
    dismissed.add(id);
    // Cap the persisted set
    const ids = [...dismissed].slice(-MAX_DISMISSED_IDS);
    sessionStorage.setItem(DISMISSED_KEY, JSON.stringify(ids));
  } catch {
    // Storage full or unavailable
  }
}

export interface AlertNotificationProviderProps {
  children: ReactNode;
}

export function AlertNotificationProvider({
  children,
}: AlertNotificationProviderProps) {
  const [preferences, setPreferencesState] =
    useState<AlertPreferences>(DEFAULT_PREFERENCES);
  const [toasts, setToasts] = useState<AlertEventData[]>([]);
  // Eagerly initialize dismissed set to avoid race with SSE alerts (Fix #4)
  const dismissedRef = useRef<Set<string>>(getDismissedAlerts());

  // Viewer's glucose unit. The dashboard SSE only streams the viewer's OWN
  // alerts, so viewer == owner and rendering toast/notification glucose in this
  // unit is correct. Kept in a ref so the alert callback reads the latest value
  // without re-subscribing to the stream.
  const unit = useGlucoseUnit();
  const unitRef = useRef(unit);
  useEffect(() => {
    unitRef.current = unit;
  }, [unit]);

  // Load preferences from localStorage on mount
  useEffect(() => {
    setPreferencesState(loadPreferences());
  }, []);

  const setPreferences = useCallback((prefs: AlertPreferences) => {
    setPreferencesState(prefs);
    savePreferences(prefs);
  }, []);

  const handleDismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    addDismissedAlert(id);
    dismissedRef.current.add(id);
  }, []);

  // Use ref to access latest preferences without causing re-subscriptions
  const prefsRef = useRef(preferences);
  useEffect(() => {
    prefsRef.current = preferences;
  }, [preferences]);

  const handleAlertReceived = useCallback((alert: AlertEventData) => {
    // Skip if already dismissed this session
    if (dismissedRef.current.has(alert.id)) return;

    // Add toast with severity-based eviction (Fix #9)
    setToasts((prev) => {
      if (prev.some((t) => t.id === alert.id)) return prev;
      const next = [...prev, alert];
      if (next.length > MAX_VISIBLE_TOASTS) {
        // Evict the lowest-severity toast (not the oldest)
        const sorted = [...next].sort(
          (a, b) =>
            (SEVERITY_PRIORITY[a.severity] ?? 0) -
            (SEVERITY_PRIORITY[b.severity] ?? 0)
        );
        // Remove the least severe toast
        const evictId = sorted[0].id;
        return next.filter((t) => t.id !== evictId);
      }
      return next;
    });

    // Play sound if enabled
    if (prefsRef.current.soundEnabled) {
      playAlertSound(alert.severity);
    }

    // Show browser notification for urgent/emergency if enabled
    if (
      prefsRef.current.browserNotificationsEnabled &&
      (alert.severity === "urgent" || alert.severity === "emergency")
    ) {
      showBrowserNotification(
        alert.severity,
        formatAlertSummary(alert, unitRef.current)
      );
    }
  }, []);

  const contextValue: AlertNotificationContextValue = {
    preferences,
    setPreferences,
  };

  return (
    <AlertNotificationContext.Provider value={contextValue}>
      <GlucoseStreamProvider onAlertReceived={handleAlertReceived}>
        {children}
        {/* Toast container - always rendered for stable aria-live region (Fix #7, #16) */}
        <div
          className="fixed top-4 right-4 z-50 flex flex-col gap-3"
          aria-live="assertive"
          aria-label="Alert notifications"
        >
          {toasts.map((alert) => (
            <AlertToast
              key={alert.id}
              alert={alert}
              onDismiss={handleDismiss}
              unit={unit}
            />
          ))}
        </div>
      </GlucoseStreamProvider>
    </AlertNotificationContext.Provider>
  );
}

/**
 * Hook to access alert notification preferences.
 *
 * @throws Error if used outside of AlertNotificationProvider
 */
export function useAlertNotifications(): AlertNotificationContextValue {
  const context = useContext(AlertNotificationContext);

  if (!context) {
    throw new Error(
      "useAlertNotifications must be used within an AlertNotificationProvider"
    );
  }

  return context;
}
