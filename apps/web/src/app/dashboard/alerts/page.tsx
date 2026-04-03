"use client";

/**
 * Alerts & Thresholds Page
 *
 * Story 6.1: Alert Threshold Configuration
 * Story 6.2: Predictive Alert Engine - Active alerts display
 * Story 6.3: Notification Preferences
 * Story 6.6: Escalation Timing Configuration
 *
 * Allows users to configure glucose and IoB alert thresholds,
 * view active predictive alerts with acknowledgment,
 * manage notification preferences (sound, browser notifications),
 * and configure escalation timing for emergency contacts.
 *
 * Accessibility: labeled inputs, error alerts, keyboard navigation.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Bell,
  Save,
  RotateCcw,
  Loader2,
  AlertTriangle,
  Check,
  Volume2,
  BellRing,
  Clock,
} from "lucide-react";
import clsx from "clsx";
import {
  getAlertThresholds,
  updateAlertThresholds,
  getActiveAlerts,
  acknowledgeAlert,
  getEscalationConfig,
  updateEscalationConfig,
  type AlertThresholdUpdate,
  type PredictiveAlert,
  type EscalationConfigUpdate,
} from "@/lib/api";
import { useAlertNotifications } from "@/providers";
import { requestNotificationPermission } from "@/lib/browser-notifications";
import { AlertCard } from "@/components/dashboard/alert-card";

const DEFAULTS = {
  low_warning: 70,
  urgent_low: 55,
  high_warning: 180,
  urgent_high: 250,
  iob_warning: 3.0,
};

interface ThresholdFieldConfig {
  key: keyof AlertThresholdUpdate;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  description: string;
  color: string;
}

const THRESHOLD_FIELDS: ThresholdFieldConfig[] = [
  {
    key: "urgent_low",
    label: "Urgent Low",
    unit: "mg/dL",
    min: 30,
    max: 80,
    step: 1,
    description: "Critical low glucose alert",
    color: "text-red-400",
  },
  {
    key: "low_warning",
    label: "Low Warning",
    unit: "mg/dL",
    min: 40,
    max: 100,
    step: 1,
    description: "Low glucose warning",
    color: "text-amber-400",
  },
  {
    key: "high_warning",
    label: "High Warning",
    unit: "mg/dL",
    min: 120,
    max: 300,
    step: 1,
    description: "High glucose warning",
    color: "text-amber-400",
  },
  {
    key: "urgent_high",
    label: "Urgent High",
    unit: "mg/dL",
    min: 150,
    max: 400,
    step: 1,
    description: "Critical high glucose alert",
    color: "text-red-400",
  },
  {
    key: "iob_warning",
    label: "IoB Warning",
    unit: "units",
    min: 0.5,
    max: 20,
    step: 0.1,
    description: "Insulin on Board warning threshold",
    color: "text-purple-400",
  },
];

const ESCALATION_DEFAULTS = {
  reminder_delay_minutes: 5,
  primary_contact_delay_minutes: 10,
  all_contacts_delay_minutes: 20,
};

export default function AlertsPage() {
  const [formValues, setFormValues] = useState<AlertThresholdUpdate>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [activeAlerts, setActiveAlerts] = useState<PredictiveAlert[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(true);
  const [acknowledgingId, setAcknowledgingId] = useState<string | null>(null);

  // Story 6.3: Notification preferences
  const { preferences, setPreferences } = useAlertNotifications();

  // Story 6.6: Escalation timing
  const [escalationValues, setEscalationValues] =
    useState<EscalationConfigUpdate>({});
  const [escalationLoading, setEscalationLoading] = useState(true);
  const [escalationSaving, setEscalationSaving] = useState(false);
  const [escalationError, setEscalationError] = useState<string | null>(null);
  const [escalationSuccess, setEscalationSuccess] = useState(false);
  const [escalationHasChanges, setEscalationHasChanges] = useState(false);

  const fetchAlerts = useCallback(async () => {
    try {
      const data = await getActiveAlerts();
      setActiveAlerts(data.alerts);
    } catch {
      // Silently fail for alerts - user may not be authenticated yet
      setActiveAlerts([]);
    } finally {
      setAlertsLoading(false);
    }
  }, []);

  const handleAcknowledge = async (alertId: string) => {
    setAcknowledgingId(alertId);
    try {
      await acknowledgeAlert(alertId);
      setActiveAlerts((prev) => prev.filter((a) => a.id !== alertId));
    } catch {
      // Refresh alerts from server to get current state
      await fetchAlerts();
    } finally {
      setAcknowledgingId(null);
    }
  };

  const fetchThresholds = useCallback(async () => {
    try {
      setError(null);
      const data = await getAlertThresholds();
      setFormValues({
        low_warning: data.low_warning,
        urgent_low: data.urgent_low,
        high_warning: data.high_warning,
        urgent_high: data.urgent_high,
        iob_warning: data.iob_warning,
      });
      setHasChanges(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setError(
          err instanceof Error ? err.message : "Failed to load thresholds"
        );
      }
      // Show defaults on any error so inputs aren't empty
      setFormValues({ ...DEFAULTS });
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchEscalationConfig = useCallback(async () => {
    try {
      const data = await getEscalationConfig();
      setEscalationValues({
        reminder_delay_minutes: data.reminder_delay_minutes,
        primary_contact_delay_minutes: data.primary_contact_delay_minutes,
        all_contacts_delay_minutes: data.all_contacts_delay_minutes,
      });
      setEscalationHasChanges(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setEscalationError(
          err instanceof Error
            ? err.message
            : "Failed to load escalation config"
        );
      }
      setEscalationValues({ ...ESCALATION_DEFAULTS });
    } finally {
      setEscalationLoading(false);
    }
  }, []);

  const handleEscalationChange = (
    key: keyof EscalationConfigUpdate,
    value: string
  ) => {
    if (value === "") {
      setEscalationValues((prev) => ({ ...prev, [key]: undefined }));
      setEscalationHasChanges(true);
      setEscalationSuccess(false);
      setEscalationError(null);
      return;
    }

    const numValue = parseInt(value, 10);
    if (isNaN(numValue)) return;

    setEscalationValues((prev) => ({ ...prev, [key]: numValue }));
    setEscalationHasChanges(true);
    setEscalationSuccess(false);
    setEscalationError(null);
  };

  const handleEscalationSave = async () => {
    setEscalationSuccess(false);

    const r =
      escalationValues.reminder_delay_minutes ??
      ESCALATION_DEFAULTS.reminder_delay_minutes;
    const p =
      escalationValues.primary_contact_delay_minutes ??
      ESCALATION_DEFAULTS.primary_contact_delay_minutes;
    const a =
      escalationValues.all_contacts_delay_minutes ??
      ESCALATION_DEFAULTS.all_contacts_delay_minutes;

    // Validate bounds
    if (r < 2 || r > 60) {
      setEscalationError("First Reminder must be between 2 and 60 minutes");
      return;
    }
    if (p < 2 || p > 120) {
      setEscalationError(
        "Primary Contact Alert must be between 2 and 120 minutes"
      );
      return;
    }
    if (a < 2 || a > 240) {
      setEscalationError(
        "All Contacts Alert must be between 2 and 240 minutes"
      );
      return;
    }

    // Validate tier ordering
    if (r >= p) {
      setEscalationError(
        `Reminder (${r} min) must be less than Primary Contact (${p} min)`
      );
      return;
    }
    if (p >= a) {
      setEscalationError(
        `Primary Contact (${p} min) must be less than All Contacts (${a} min)`
      );
      return;
    }

    setEscalationSaving(true);
    setEscalationError(null);

    try {
      const data = await updateEscalationConfig(escalationValues);
      setEscalationValues({
        reminder_delay_minutes: data.reminder_delay_minutes,
        primary_contact_delay_minutes: data.primary_contact_delay_minutes,
        all_contacts_delay_minutes: data.all_contacts_delay_minutes,
      });
      setEscalationHasChanges(false);
      setEscalationSuccess(true);
    } catch (err) {
      setEscalationError(
        err instanceof Error ? err.message : "Failed to save escalation config"
      );
    } finally {
      setEscalationSaving(false);
    }
  };

  const handleEscalationReset = () => {
    setEscalationValues({ ...ESCALATION_DEFAULTS });
    setEscalationHasChanges(true);
    setEscalationSuccess(false);
    setEscalationError(null);
  };

  useEffect(() => {
    fetchThresholds();
    fetchEscalationConfig();
    fetchAlerts();

    // Poll for new alerts every 60 seconds
    const interval = setInterval(fetchAlerts, 60000);
    return () => clearInterval(interval);
  }, [fetchThresholds, fetchEscalationConfig, fetchAlerts]);

  const handleChange = (key: keyof AlertThresholdUpdate, value: string) => {
    const numValue = parseFloat(value);
    if (isNaN(numValue)) return;

    setFormValues((prev) => ({ ...prev, [key]: numValue }));
    setHasChanges(true);
    setSaveSuccess(false);
  };

  const handleSave = async () => {
    // Client-side ordering validation
    const ul = formValues.urgent_low ?? DEFAULTS.urgent_low;
    const lw = formValues.low_warning ?? DEFAULTS.low_warning;
    const hw = formValues.high_warning ?? DEFAULTS.high_warning;
    const uh = formValues.urgent_high ?? DEFAULTS.urgent_high;

    if (ul >= lw) {
      setError(`Urgent Low (${ul}) must be less than Low Warning (${lw})`);
      return;
    }
    if (lw >= hw) {
      setError(`Low Warning (${lw}) must be less than High Warning (${hw})`);
      return;
    }
    if (hw >= uh) {
      setError(`High Warning (${hw}) must be less than Urgent High (${uh})`);
      return;
    }

    setIsSaving(true);
    setError(null);
    setSaveSuccess(false);

    try {
      const data = await updateAlertThresholds(formValues);
      setFormValues({
        low_warning: data.low_warning,
        urgent_low: data.urgent_low,
        high_warning: data.high_warning,
        urgent_high: data.urgent_high,
        iob_warning: data.iob_warning,
      });
      setHasChanges(false);
      setSaveSuccess(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to save thresholds"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    setFormValues({ ...DEFAULTS });
    setHasChanges(true);
    setSaveSuccess(false);
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold">Alerts & Thresholds</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Configure your glucose and insulin alert thresholds
        </p>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading thresholds"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading thresholds...</p>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div
          className="bg-red-500/10 rounded-xl p-4 border border-red-500/20"
          role="alert"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
            <p className="text-sm text-red-400">{error}</p>
          </div>
        </div>
      )}

      {/* Success state */}
      {saveSuccess && (
        <div
          className="bg-green-500/10 rounded-xl p-4 border border-green-500/20"
          role="status"
        >
          <div className="flex items-center gap-2">
            <Check className="h-4 w-4 text-green-400 shrink-0" />
            <p className="text-sm text-green-400">
              Thresholds saved successfully. Changes take effect immediately.
            </p>
          </div>
        </div>
      )}

      {/* Threshold configuration form */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-amber-500/10 rounded-lg">
              <Bell className="h-5 w-5 text-amber-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Alert Thresholds</h2>
              <p className="text-xs text-slate-500">
                Alerts trigger when glucose or IoB crosses these thresholds
              </p>
            </div>
          </div>

          <div className="space-y-5">
            {/* Glucose thresholds section */}
            <div>
              <h3 className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-3">
                Glucose Thresholds
              </h3>
              <div className="grid gap-4 sm:grid-cols-2">
                {THRESHOLD_FIELDS.filter((f) => f.unit === "mg/dL").map(
                  (field) => (
                    <div key={field.key}>
                      <label
                        htmlFor={field.key}
                        className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                      >
                        <span className={field.color}>{field.label}</span>
                      </label>
                      <p className="text-xs text-slate-500 mb-2">
                        {field.description}
                      </p>
                      <div className="flex items-center gap-2">
                        <input
                          id={field.key}
                          type="number"
                          min={field.min}
                          max={field.max}
                          step={field.step}
                          value={formValues[field.key] ?? ""}
                          onChange={(e) =>
                            handleChange(field.key, e.target.value)
                          }
                          className={clsx(
                            "w-full rounded-lg border px-3 py-2 text-sm",
                            "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200",
                            "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                            "placeholder:text-slate-500"
                          )}
                          aria-describedby={`${field.key}-range`}
                        />
                        <span className="text-xs text-slate-500 shrink-0">
                          {field.unit}
                        </span>
                      </div>
                      <p
                        id={`${field.key}-range`}
                        className="text-xs text-slate-600 mt-1"
                      >
                        Range: {field.min}–{field.max} {field.unit}
                      </p>
                    </div>
                  )
                )}
              </div>
            </div>

            {/* IoB threshold section */}
            <div>
              <h3 className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-3">
                Insulin on Board
              </h3>
              {THRESHOLD_FIELDS.filter((f) => f.unit === "units").map(
                (field) => (
                  <div key={field.key} className="max-w-xs">
                    <label
                      htmlFor={field.key}
                      className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                    >
                      <span className={field.color}>{field.label}</span>
                    </label>
                    <p className="text-xs text-slate-500 mb-2">
                      {field.description}
                    </p>
                    <div className="flex items-center gap-2">
                      <input
                        id={field.key}
                        type="number"
                        min={field.min}
                        max={field.max}
                        step={field.step}
                        value={formValues[field.key] ?? ""}
                        onChange={(e) =>
                          handleChange(field.key, e.target.value)
                        }
                        className={clsx(
                          "w-full rounded-lg border px-3 py-2 text-sm",
                          "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200",
                          "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                          "placeholder:text-slate-500"
                        )}
                        aria-describedby={`${field.key}-range`}
                      />
                      <span className="text-xs text-slate-500 shrink-0">
                        {field.unit}
                      </span>
                    </div>
                    <p
                      id={`${field.key}-range`}
                      className="text-xs text-slate-600 mt-1"
                    >
                      Range: {field.min}–{field.max} {field.unit}
                    </p>
                  </div>
                )
              )}
            </div>
          </div>

          {/* Action buttons */}
          <div
            className="flex items-center gap-3 mt-6 pt-4 border-t border-slate-200 dark:border-slate-800"
            role="group"
            aria-label="Threshold actions"
          >
            <button
              onClick={handleSave}
              disabled={isSaving || !hasChanges}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-blue-600 text-white hover:bg-blue-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
              aria-label="Save threshold changes"
            >
              {isSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Save className="h-4 w-4" aria-hidden="true" />
              )}
              {isSaving ? "Saving..." : "Save Changes"}
            </button>
            <button
              onClick={handleReset}
              disabled={isSaving}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
              aria-label="Reset thresholds to defaults"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Reset to Defaults
            </button>
          </div>
        </div>
      )}

      {/* Active alerts section */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-red-500/10 rounded-lg">
            <AlertTriangle className="h-5 w-5 text-red-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Active Alerts</h2>
            <p className="text-xs text-slate-500">
              Predictive and threshold-based alerts
            </p>
          </div>
          {activeAlerts.length > 0 && (
            <span className="ml-auto text-xs bg-red-500/20 text-red-400 px-2 py-1 rounded-full">
              {activeAlerts.length} active
            </span>
          )}
        </div>

        {alertsLoading && (
          <div
            className="text-center py-4"
            role="status"
            aria-label="Loading alerts"
          >
            <Loader2 className="h-5 w-5 text-slate-500 dark:text-slate-400 animate-spin mx-auto" />
          </div>
        )}

        {!alertsLoading && activeAlerts.length === 0 && (
          <div className="flex items-center gap-3 py-4">
            <div className="h-3 w-3 rounded-full bg-green-500" />
            <span className="text-slate-600 dark:text-slate-300">No active alerts</span>
          </div>
        )}

        {!alertsLoading && activeAlerts.length > 0 && (
          <div className="space-y-3">
            {activeAlerts.map((alert) => (
              <AlertCard
                key={alert.id}
                alert={alert}
                onAcknowledge={handleAcknowledge}
                isAcknowledging={acknowledgingId === alert.id}
              />
            ))}
          </div>
        )}
      </div>

      {/* Story 6.3: Notification Preferences */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-blue-500/10 rounded-lg">
            <BellRing className="h-5 w-5 text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Notification Preferences</h2>
            <p className="text-xs text-slate-500">
              Control how you receive alert notifications
            </p>
          </div>
        </div>

        <div className="space-y-4">
          {/* Sound toggle */}
          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              id="pref-sound"
              type="checkbox"
              checked={preferences.soundEnabled}
              onChange={(e) =>
                setPreferences({
                  ...preferences,
                  soundEnabled: e.target.checked,
                })
              }
              className="h-4 w-4 rounded border-slate-300 dark:border-slate-600 bg-slate-100 dark:bg-slate-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
              aria-describedby="pref-sound-desc"
            />
            <Volume2
              className="h-4 w-4 text-slate-500 dark:text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-300"
              aria-hidden="true"
            />
            <div>
              <span className="text-sm text-slate-600 dark:text-slate-300 group-hover:text-slate-700 dark:group-hover:text-slate-200">
                Alert sounds
              </span>
              <p id="pref-sound-desc" className="text-xs text-slate-500">
                Play audio tones when alerts are received
              </p>
            </div>
          </label>

          {/* Browser notifications toggle */}
          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              id="pref-browser-notif"
              type="checkbox"
              checked={preferences.browserNotificationsEnabled}
              onChange={async (e) => {
                if (e.target.checked) {
                  const permission = await requestNotificationPermission();
                  setPreferences({
                    ...preferences,
                    browserNotificationsEnabled: permission === "granted",
                  });
                } else {
                  setPreferences({
                    ...preferences,
                    browserNotificationsEnabled: false,
                  });
                }
              }}
              className="h-4 w-4 rounded border-slate-300 dark:border-slate-600 bg-slate-100 dark:bg-slate-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
              aria-describedby="pref-browser-notif-desc"
            />
            <Bell
              className="h-4 w-4 text-slate-500 dark:text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-300"
              aria-hidden="true"
            />
            <div>
              <span className="text-sm text-slate-600 dark:text-slate-300 group-hover:text-slate-700 dark:group-hover:text-slate-200">
                Browser notifications
              </span>
              <p id="pref-browser-notif-desc" className="text-xs text-slate-500">
                Show OS-level notifications for urgent and emergency alerts
              </p>
            </div>
          </label>
        </div>
      </div>

      {/* Story 6.6: Escalation Timing */}
      {escalationLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading escalation timing"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading escalation timing...</p>
        </div>
      )}
      {!escalationLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-orange-500/10 rounded-lg">
              <Clock className="h-5 w-5 text-orange-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Escalation Timing</h2>
              <p className="text-xs text-slate-500">
                Configure how long before alerts escalate to emergency contacts
              </p>
            </div>
          </div>

          {escalationError && (
            <div
              className="bg-red-500/10 rounded-lg p-3 border border-red-500/20 mb-4"
              role="alert"
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
                <p className="text-sm text-red-400">{escalationError}</p>
              </div>
            </div>
          )}

          {escalationSuccess && (
            <div
              className="bg-green-500/10 rounded-lg p-3 border border-green-500/20 mb-4"
              role="status"
            >
              <div className="flex items-center gap-2">
                <Check className="h-4 w-4 text-green-400 shrink-0" />
                <p className="text-sm text-green-400">
                  Escalation timing saved successfully.
                </p>
              </div>
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label
                htmlFor="reminder_delay"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                <span className="text-amber-400">First Reminder</span>
              </label>
              <p className="text-xs text-slate-500 mb-2">
                Time before a reminder is sent to you
              </p>
              <div className="flex items-center gap-2 max-w-xs">
                <input
                  id="reminder_delay"
                  type="number"
                  min={2}
                  max={60}
                  step={1}
                  value={escalationValues.reminder_delay_minutes ?? ""}
                  onChange={(e) =>
                    handleEscalationChange(
                      "reminder_delay_minutes",
                      e.target.value
                    )
                  }
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "placeholder:text-slate-500"
                  )}
                  aria-describedby="reminder-range"
                />
                <span className="text-xs text-slate-500 shrink-0">min</span>
              </div>
              <p id="reminder-range" className="text-xs text-slate-600 mt-1">
                Range: 2–60 minutes
              </p>
            </div>

            <div>
              <label
                htmlFor="primary_contact_delay"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                <span className="text-orange-400">Primary Contact Alert</span>
              </label>
              <p className="text-xs text-slate-500 mb-2">
                Time before your primary emergency contact is notified
              </p>
              <div className="flex items-center gap-2 max-w-xs">
                <input
                  id="primary_contact_delay"
                  type="number"
                  min={2}
                  max={120}
                  step={1}
                  value={
                    escalationValues.primary_contact_delay_minutes ?? ""
                  }
                  onChange={(e) =>
                    handleEscalationChange(
                      "primary_contact_delay_minutes",
                      e.target.value
                    )
                  }
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "placeholder:text-slate-500"
                  )}
                  aria-describedby="primary-range"
                />
                <span className="text-xs text-slate-500 shrink-0">min</span>
              </div>
              <p id="primary-range" className="text-xs text-slate-600 mt-1">
                Range: 2–120 minutes
              </p>
            </div>

            <div>
              <label
                htmlFor="all_contacts_delay"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                <span className="text-red-400">All Contacts Alert</span>
              </label>
              <p className="text-xs text-slate-500 mb-2">
                Time before all emergency contacts are notified
              </p>
              <div className="flex items-center gap-2 max-w-xs">
                <input
                  id="all_contacts_delay"
                  type="number"
                  min={2}
                  max={240}
                  step={1}
                  value={escalationValues.all_contacts_delay_minutes ?? ""}
                  onChange={(e) =>
                    handleEscalationChange(
                      "all_contacts_delay_minutes",
                      e.target.value
                    )
                  }
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "placeholder:text-slate-500"
                  )}
                  aria-describedby="all-contacts-range"
                />
                <span className="text-xs text-slate-500 shrink-0">min</span>
              </div>
              <p
                id="all-contacts-range"
                className="text-xs text-slate-600 mt-1"
              >
                Range: 2–240 minutes
              </p>
            </div>
          </div>

          <div
            className="flex items-center gap-3 mt-6 pt-4 border-t border-slate-200 dark:border-slate-800"
            role="group"
            aria-label="Escalation timing actions"
          >
            <button
              onClick={handleEscalationSave}
              disabled={escalationSaving || !escalationHasChanges}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-blue-600 text-white hover:bg-blue-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
              aria-label="Save escalation timing"
            >
              {escalationSaving ? (
                <Loader2
                  className="h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Save className="h-4 w-4" aria-hidden="true" />
              )}
              {escalationSaving ? "Saving..." : "Save Changes"}
            </button>
            <button
              onClick={handleEscalationReset}
              disabled={escalationSaving}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
              aria-label="Reset escalation timing to defaults"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Reset to Defaults
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
