"use client";

/**
 * Story 10.3: Alert Settings Page
 *
 * Allows users to configure alert thresholds (glucose & IoB) and
 * escalation timing (reminder, primary contact, all contacts delays).
 */

import { useState, useEffect, useCallback } from "react";
import {
  Bell,
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  RotateCcw,
  Clock,
  Activity,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";
import {
  getAlertThresholds,
  updateAlertThresholds,
  getEscalationConfig,
  updateEscalationConfig,
  type AlertThresholdResponse,
  type EscalationConfigResponse,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

const THRESHOLD_DEFAULTS = {
  low_warning: 70,
  urgent_low: 55,
  high_warning: 180,
  urgent_high: 250,
  iob_warning: 3.0,
};

const ESCALATION_DEFAULTS = {
  reminder_delay_minutes: 5,
  primary_contact_delay_minutes: 10,
  all_contacts_delay_minutes: 20,
};

export default function AlertSettingsPage() {
  const [thresholds, setThresholds] =
    useState<AlertThresholdResponse | null>(null);
  const [escalation, setEscalation] =
    useState<EscalationConfigResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isOffline, setIsOffline] = useState(false);

  // Threshold form state
  const [lowWarning, setLowWarning] = useState("70");
  const [urgentLow, setUrgentLow] = useState("55");
  const [highWarning, setHighWarning] = useState("180");
  const [urgentHigh, setUrgentHigh] = useState("250");
  const [iobWarning, setIobWarning] = useState("3.0");

  // Escalation form state
  const [reminderDelay, setReminderDelay] = useState("5");
  const [primaryDelay, setPrimaryDelay] = useState("10");
  const [allContactsDelay, setAllContactsDelay] = useState("20");

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [thresholdData, escalationData] = await Promise.all([
        getAlertThresholds(),
        getEscalationConfig(),
      ]);

      setThresholds(thresholdData);
      setLowWarning(String(thresholdData.low_warning));
      setUrgentLow(String(thresholdData.urgent_low));
      setHighWarning(String(thresholdData.high_warning));
      setUrgentHigh(String(thresholdData.urgent_high));
      setIobWarning(String(thresholdData.iob_warning));

      setEscalation(escalationData);
      setReminderDelay(String(escalationData.reminder_delay_minutes));
      setPrimaryDelay(String(escalationData.primary_contact_delay_minutes));
      setAllContactsDelay(String(escalationData.all_contacts_delay_minutes));
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
      // Use defaults as baseline so the form is still functional
      setThresholds({
        ...THRESHOLD_DEFAULTS,
      } as AlertThresholdResponse);
      setLowWarning(String(THRESHOLD_DEFAULTS.low_warning));
      setUrgentLow(String(THRESHOLD_DEFAULTS.urgent_low));
      setHighWarning(String(THRESHOLD_DEFAULTS.high_warning));
      setUrgentHigh(String(THRESHOLD_DEFAULTS.urgent_high));
      setIobWarning(String(THRESHOLD_DEFAULTS.iob_warning));

      setEscalation({
        ...ESCALATION_DEFAULTS,
      } as EscalationConfigResponse);
      setReminderDelay(String(ESCALATION_DEFAULTS.reminder_delay_minutes));
      setPrimaryDelay(
        String(ESCALATION_DEFAULTS.primary_contact_delay_minutes)
      );
      setAllContactsDelay(
        String(ESCALATION_DEFAULTS.all_contacts_delay_minutes)
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-clear success message after 5 seconds
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  // --- Validation ---
  const lowWarn = parseFloat(lowWarning);
  const urgLow = parseFloat(urgentLow);
  const highWarn = parseFloat(highWarning);
  const urgHigh = parseFloat(urgentHigh);
  const iobWarn = parseFloat(iobWarning);
  const remDelay = parseInt(reminderDelay, 10);
  const priDelay = parseInt(primaryDelay, 10);
  const allDelay = parseInt(allContactsDelay, 10);

  const thresholdsValid =
    !isNaN(urgLow) &&
    !isNaN(lowWarn) &&
    !isNaN(highWarn) &&
    !isNaN(urgHigh) &&
    !isNaN(iobWarn) &&
    urgLow >= 30 &&
    urgLow <= 80 &&
    lowWarn >= 40 &&
    lowWarn <= 100 &&
    highWarn >= 120 &&
    highWarn <= 300 &&
    urgHigh >= 150 &&
    urgHigh <= 400 &&
    iobWarn >= 0.5 &&
    iobWarn <= 20 &&
    urgLow < lowWarn &&
    highWarn < urgHigh;

  const escalationValid =
    !isNaN(remDelay) &&
    !isNaN(priDelay) &&
    !isNaN(allDelay) &&
    remDelay >= 2 &&
    remDelay <= 60 &&
    priDelay >= 2 &&
    priDelay <= 120 &&
    allDelay >= 2 &&
    allDelay <= 240 &&
    remDelay < priDelay &&
    priDelay < allDelay;

  const isValid = thresholdsValid && escalationValid;

  const thresholdsChanged =
    thresholds !== null &&
    (parseFloat(lowWarning) !== thresholds.low_warning ||
      parseFloat(urgentLow) !== thresholds.urgent_low ||
      parseFloat(highWarning) !== thresholds.high_warning ||
      parseFloat(urgentHigh) !== thresholds.urgent_high ||
      parseFloat(iobWarning) !== thresholds.iob_warning);

  const escalationChanged =
    escalation !== null &&
    (parseInt(reminderDelay, 10) !== escalation.reminder_delay_minutes ||
      parseInt(primaryDelay, 10) !==
        escalation.primary_contact_delay_minutes ||
      parseInt(allContactsDelay, 10) !==
        escalation.all_contacts_delay_minutes);

  const hasChanges = thresholdsChanged || escalationChanged;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid || !hasChanges) return;

    setIsSaving(true);
    setError(null);
    setSuccess(null);

    const results = await Promise.allSettled([
      thresholdsChanged
        ? updateAlertThresholds({
            low_warning: lowWarn,
            urgent_low: urgLow,
            high_warning: highWarn,
            urgent_high: urgHigh,
            iob_warning: iobWarn,
          })
        : Promise.resolve(thresholds!),
      escalationChanged
        ? updateEscalationConfig({
            reminder_delay_minutes: remDelay,
            primary_contact_delay_minutes: priDelay,
            all_contacts_delay_minutes: allDelay,
          })
        : Promise.resolve(escalation!),
    ]);

    // Update state for whichever calls succeeded
    if (results[0].status === "fulfilled") {
      setThresholds(results[0].value);
    }
    if (results[1].status === "fulfilled") {
      setEscalation(results[1].value);
    }

    // Report errors for any failures
    const errors: string[] = [];
    if (results[0].status === "rejected") {
      errors.push(
        results[0].reason instanceof Error
          ? results[0].reason.message
          : "Failed to update thresholds"
      );
    }
    if (results[1].status === "rejected") {
      errors.push(
        results[1].reason instanceof Error
          ? results[1].reason.message
          : "Failed to update escalation config"
      );
    }

    if (errors.length > 0) {
      setError(errors.join(". "));
    } else {
      setSuccess("Alert settings updated successfully");
    }

    setIsSaving(false);
  };

  const handleReset = async () => {
    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const [updatedThresholds, updatedEscalation] = await Promise.all([
        updateAlertThresholds({ ...THRESHOLD_DEFAULTS }),
        updateEscalationConfig({ ...ESCALATION_DEFAULTS }),
      ]);

      setThresholds(updatedThresholds);
      setLowWarning(String(THRESHOLD_DEFAULTS.low_warning));
      setUrgentLow(String(THRESHOLD_DEFAULTS.urgent_low));
      setHighWarning(String(THRESHOLD_DEFAULTS.high_warning));
      setUrgentHigh(String(THRESHOLD_DEFAULTS.urgent_high));
      setIobWarning(String(THRESHOLD_DEFAULTS.iob_warning));

      setEscalation(updatedEscalation);
      setReminderDelay(String(ESCALATION_DEFAULTS.reminder_delay_minutes));
      setPrimaryDelay(
        String(ESCALATION_DEFAULTS.primary_contact_delay_minutes)
      );
      setAllContactsDelay(
        String(ESCALATION_DEFAULTS.all_contacts_delay_minutes)
      );

      setSuccess("Alert settings reset to defaults");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reset alert settings"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const isAtDefaults =
    thresholds?.low_warning === THRESHOLD_DEFAULTS.low_warning &&
    thresholds?.urgent_low === THRESHOLD_DEFAULTS.urgent_low &&
    thresholds?.high_warning === THRESHOLD_DEFAULTS.high_warning &&
    thresholds?.urgent_high === THRESHOLD_DEFAULTS.urgent_high &&
    thresholds?.iob_warning === THRESHOLD_DEFAULTS.iob_warning &&
    escalation?.reminder_delay_minutes ===
      ESCALATION_DEFAULTS.reminder_delay_minutes &&
    escalation?.primary_contact_delay_minutes ===
      ESCALATION_DEFAULTS.primary_contact_delay_minutes &&
    escalation?.all_contacts_delay_minutes ===
      ESCALATION_DEFAULTS.all_contacts_delay_minutes;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <Link
          href="/dashboard/settings"
          className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mb-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </Link>
        <h1 className="text-2xl font-bold">Alert Settings</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Configure alert thresholds and escalation timing
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner onRetry={fetchData} isRetrying={isLoading} />
      )}

      {/* Error state */}
      {error && (
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
      {success && (
        <div
          className="bg-green-500/10 rounded-xl p-4 border border-green-500/20"
          role="status"
        >
          <div className="flex items-center gap-2">
            <Check className="h-4 w-4 text-green-400 shrink-0" />
            <p className="text-sm text-green-400">{success}</p>
          </div>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading alert settings"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading alert settings...</p>
        </div>
      )}

      {!isLoading && (
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Alert Thresholds Section */}
          <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-red-500/10 rounded-lg">
                <Activity className="h-5 w-5 text-red-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Alert Thresholds</h2>
                <p className="text-xs text-slate-500">
                  Set glucose and insulin thresholds that trigger alerts
                </p>
              </div>
            </div>

            {/* Low glucose thresholds */}
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400">
                Low Glucose Alerts
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="urgent-low"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    Urgent Low (mg/dL)
                  </label>
                  <input
                    id="urgent-low"
                    type="number"
                    min={30}
                    max={80}
                    step={1}
                    value={urgentLow}
                    onChange={(e) => setUrgentLow(e.target.value)}
                    disabled={isSaving}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="urgent-low-hint"
                  />
                  <p
                    id="urgent-low-hint"
                    className="text-xs text-slate-500 mt-1"
                  >
                    Range: 30-80. Default: 55 mg/dL
                  </p>
                </div>

                <div>
                  <label
                    htmlFor="low-warning"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    Low Warning (mg/dL)
                  </label>
                  <input
                    id="low-warning"
                    type="number"
                    min={40}
                    max={100}
                    step={1}
                    value={lowWarning}
                    onChange={(e) => setLowWarning(e.target.value)}
                    disabled={isSaving}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="low-warning-hint"
                  />
                  <p
                    id="low-warning-hint"
                    className="text-xs text-slate-500 mt-1"
                  >
                    Range: 40-100. Default: 70 mg/dL
                  </p>
                </div>
              </div>

              {/* Validation hint for low thresholds */}
              {!isNaN(urgLow) &&
                !isNaN(lowWarn) &&
                urgLow >= lowWarn && (
                  <p className="text-xs text-amber-400" role="alert">
                    Urgent Low must be less than Low Warning
                  </p>
                )}
            </div>

            {/* High glucose thresholds */}
            <div className="space-y-4 mt-6">
              <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400">
                High Glucose Alerts
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="high-warning"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    High Warning (mg/dL)
                  </label>
                  <input
                    id="high-warning"
                    type="number"
                    min={120}
                    max={300}
                    step={1}
                    value={highWarning}
                    onChange={(e) => setHighWarning(e.target.value)}
                    disabled={isSaving}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="high-warning-hint"
                  />
                  <p
                    id="high-warning-hint"
                    className="text-xs text-slate-500 mt-1"
                  >
                    Range: 120-300. Default: 180 mg/dL
                  </p>
                </div>

                <div>
                  <label
                    htmlFor="urgent-high"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    Urgent High (mg/dL)
                  </label>
                  <input
                    id="urgent-high"
                    type="number"
                    min={150}
                    max={400}
                    step={1}
                    value={urgentHigh}
                    onChange={(e) => setUrgentHigh(e.target.value)}
                    disabled={isSaving}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="urgent-high-hint"
                  />
                  <p
                    id="urgent-high-hint"
                    className="text-xs text-slate-500 mt-1"
                  >
                    Range: 150-400. Default: 250 mg/dL
                  </p>
                </div>
              </div>

              {/* Validation hint for high thresholds */}
              {!isNaN(highWarn) &&
                !isNaN(urgHigh) &&
                highWarn >= urgHigh && (
                  <p className="text-xs text-amber-400" role="alert">
                    High Warning must be less than Urgent High
                  </p>
                )}
            </div>

            {/* IoB threshold */}
            <div className="space-y-4 mt-6">
              <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400">
                Insulin on Board
              </h3>
              <div className="max-w-xs">
                <label
                  htmlFor="iob-warning"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  IoB Warning (units)
                </label>
                <input
                  id="iob-warning"
                  type="number"
                  min={0.5}
                  max={20}
                  step={0.1}
                  value={iobWarning}
                  onChange={(e) => setIobWarning(e.target.value)}
                  disabled={isSaving}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="iob-warning-hint"
                />
                <p
                  id="iob-warning-hint"
                  className="text-xs text-slate-500 mt-1"
                >
                  Range: 0.5-20.0 units. Default: 3.0 units
                </p>
              </div>
            </div>

            {/* Threshold preview */}
            {thresholdsValid && (
              <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50 mt-6">
                <p className="text-xs text-slate-500 mb-2">
                  Threshold Preview
                </p>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <span className="text-red-400">Urgent Low:</span>{" "}
                    <span className="text-slate-200">
                      &lt; {urgLow} mg/dL
                    </span>
                  </div>
                  <div>
                    <span className="text-amber-400">Low Warning:</span>{" "}
                    <span className="text-slate-200">
                      &lt; {lowWarn} mg/dL
                    </span>
                  </div>
                  <div>
                    <span className="text-amber-400">High Warning:</span>{" "}
                    <span className="text-slate-200">
                      &gt; {highWarn} mg/dL
                    </span>
                  </div>
                  <div>
                    <span className="text-red-400">Urgent High:</span>{" "}
                    <span className="text-slate-200">
                      &gt; {urgHigh} mg/dL
                    </span>
                  </div>
                  <div className="col-span-2">
                    <span className="text-amber-400">IoB Warning:</span>{" "}
                    <span className="text-slate-200">
                      &gt; {iobWarn} units
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Escalation Timing Section */}
          <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-amber-500/10 rounded-lg">
                <Clock className="h-5 w-5 text-amber-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Escalation Timing</h2>
                <p className="text-xs text-slate-500">
                  Configure delays before alerts escalate to contacts
                </p>
              </div>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label
                    htmlFor="reminder-delay"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    Reminder (minutes)
                  </label>
                  <input
                    id="reminder-delay"
                    type="number"
                    min={2}
                    max={60}
                    step={1}
                    value={reminderDelay}
                    onChange={(e) => setReminderDelay(e.target.value)}
                    disabled={isSaving}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="reminder-hint"
                  />
                  <p id="reminder-hint" className="text-xs text-slate-500 mt-1">
                    2-60 min. Default: 5 min
                  </p>
                </div>

                <div>
                  <label
                    htmlFor="primary-delay"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    Primary Contact (minutes)
                  </label>
                  <input
                    id="primary-delay"
                    type="number"
                    min={2}
                    max={120}
                    step={1}
                    value={primaryDelay}
                    onChange={(e) => setPrimaryDelay(e.target.value)}
                    disabled={isSaving}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="primary-hint"
                  />
                  <p id="primary-hint" className="text-xs text-slate-500 mt-1">
                    2-120 min. Default: 10 min
                  </p>
                </div>

                <div>
                  <label
                    htmlFor="all-contacts-delay"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    All Contacts (minutes)
                  </label>
                  <input
                    id="all-contacts-delay"
                    type="number"
                    min={2}
                    max={240}
                    step={1}
                    value={allContactsDelay}
                    onChange={(e) => setAllContactsDelay(e.target.value)}
                    disabled={isSaving}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    aria-describedby="all-contacts-hint"
                  />
                  <p
                    id="all-contacts-hint"
                    className="text-xs text-slate-500 mt-1"
                  >
                    2-240 min. Default: 20 min
                  </p>
                </div>
              </div>

              {/* Validation hint for escalation ordering */}
              {!isNaN(remDelay) &&
                !isNaN(priDelay) &&
                !isNaN(allDelay) &&
                !(remDelay < priDelay && priDelay < allDelay) && (
                  <p className="text-xs text-amber-400" role="alert">
                    Delays must increase: Reminder &lt; Primary Contact &lt; All
                    Contacts
                  </p>
                )}

              {/* Escalation preview */}
              {escalationValid && (
                <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50 mt-2">
                  <p className="text-xs text-slate-500 mb-2">
                    Escalation Flow
                  </p>
                  <div className="flex items-center gap-2 text-sm flex-wrap">
                    <span className="text-slate-500 dark:text-slate-400">Alert triggered</span>
                    <span className="text-slate-600">&rarr;</span>
                    <span className="text-blue-400">
                      Reminder at {remDelay}m
                    </span>
                    <span className="text-slate-600">&rarr;</span>
                    <span className="text-amber-400">
                      Primary contact at {priDelay}m
                    </span>
                    <span className="text-slate-600">&rarr;</span>
                    <span className="text-red-400">
                      All contacts at {allDelay}m
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={isSaving || !hasChanges || !isValid || isOffline}
              title={isOffline ? "Cannot save while disconnected" : undefined}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-blue-600 text-white hover:bg-blue-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isSaving ? (
                <Loader2
                  className="h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Check className="h-4 w-4" aria-hidden="true" />
              )}
              {isSaving ? "Saving..." : "Save Changes"}
            </button>

            <button
              type="button"
              onClick={handleReset}
              disabled={isSaving || isAtDefaults || isOffline}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Reset to Defaults
            </button>
          </div>
        </form>
      )}

      {/* Info card */}
      <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
        <div className="flex items-start gap-2">
          <Bell className="h-4 w-4 text-slate-500 mt-0.5 shrink-0" />
          <p className="text-xs text-slate-500">
            Alert thresholds determine when you receive glucose and insulin
            warnings. Escalation timing controls how quickly unacknowledged
            alerts are forwarded to your emergency contacts. Consult your
            healthcare provider before adjusting these values.
          </p>
        </div>
      </div>
    </div>
  );
}
