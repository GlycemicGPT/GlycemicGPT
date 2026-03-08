"use client";

/**
 * Stories 8.3 & 8.5: Caregiver Dashboard View
 *
 * Read-only dashboard for caregivers to view their linked patients'
 * glucose status. Data is filtered by permissions set by each patient.
 *
 * Story 8.5: Multi-patient card grid with drill-down detail view.
 * When multiple patients are linked, shows a summary card for each.
 * Tapping a card reveals the full detail view (glucose, IoB, AI chat).
 * Auto-refreshes every 60 seconds via REST polling.
 */

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  ChevronLeft,
  Clock,
  Syringe,
  Loader2,
  AlertTriangle,
  Eye,
  Lock,
  MessageSquare,
  RefreshCw,
  Send,
  Users,
} from "lucide-react";
import clsx from "clsx";
import {
  listLinkedPatients,
  getCaregiverPatientStatus,
  sendCaregiverChat,
  type LinkedPatient,
  type CaregiverPatientStatus,
  type CaregiverChatResponse,
} from "@/lib/api";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { useUserContext } from "@/providers";

const REFRESH_INTERVAL_MS = 60_000;

function getTrendArrow(trend: string): string {
  const arrows: Record<string, string> = {
    RisingQuickly: "\u2191\u2191",
    Rising: "\u2191",
    SlightlyRising: "\u2197",
    Flat: "\u2192",
    SlightlyFalling: "\u2198",
    Falling: "\u2193",
    FallingQuickly: "\u2193\u2193",
  };
  return arrows[trend] || "?";
}

function getGlucoseColor(value: number): string {
  if (value < 70) return "text-red-400";
  if (value < 80) return "text-yellow-400";
  if (value <= 180) return "text-green-400";
  if (value <= 250) return "text-yellow-400";
  return "text-red-400";
}

/**
 * Status dot color based on glucose value for patient overview cards.
 * Green = in range (70-180), Yellow = warning (55-69/181-250 or stale),
 * Red = critical (<55 or >250), Slate = no data available or not permitted.
 */
function getStatusDotColor(status: CaregiverPatientStatus | null): string {
  if (!status?.glucose || !status.permissions.can_view_glucose) {
    return "bg-slate-500"; // No data or no permission — grey indicates unavailable
  }
  if (status.glucose.is_stale) return "bg-yellow-400";
  const v = status.glucose.value;
  if (v < 55 || v > 250) return "bg-red-400";
  if (v < 70 || v > 180) return "bg-yellow-400";
  return "bg-green-400";
}

export default function CaregiverDashboardPage() {
  const router = useRouter();
  const { user, isLoading: isUserLoading } = useUserContext();
  const [patients, setPatients] = useState<LinkedPatient[]>([]);
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(
    null
  );
  const [status, setStatus] = useState<CaregiverPatientStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // Story 8.5: Multi-patient overview state
  const [patientStatuses, setPatientStatuses] = useState<
    Map<string, CaregiverPatientStatus>
  >(new Map());
  const [isLoadingStatuses, setIsLoadingStatuses] = useState(false);

  // Story 8.4: AI chat state
  const [chatMessage, setChatMessage] = useState("");
  const [chatResponse, setChatResponse] =
    useState<CaregiverChatResponse | null>(null);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // Whether we're in multi-patient mode (show grid overview)
  const isMultiPatient = patients.length > 1;
  const showOverview = isMultiPatient && !selectedPatientId;

  // Redirect non-caregivers away from this page
  useEffect(() => {
    if (!isUserLoading && user && user.role !== "caregiver") {
      router.replace("/dashboard");
    }
  }, [user, isUserLoading, router]);

  // Load linked patients on mount
  useEffect(() => {
    async function loadPatients() {
      try {
        const data = await listLinkedPatients();
        setPatients(data.patients);
        // Single patient: auto-select for direct detail view
        // Multiple patients: stay on overview (selectedPatientId stays null)
        if (data.patients.length === 1) {
          setSelectedPatientId(data.patients[0].patient_id);
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load patients"
        );
      } finally {
        setIsLoading(false);
      }
    }
    loadPatients();
  }, []);

  // Story 8.5: Fetch all patient statuses in parallel for overview cards
  const fetchAllStatuses = useCallback(
    async (showRefreshing = false) => {
      if (patients.length <= 1) return;

      if (showRefreshing) setIsRefreshing(true);
      setIsLoadingStatuses(true);

      const results = await Promise.allSettled(
        patients.map((p) => getCaregiverPatientStatus(p.patient_id))
      );

      // Merge: keep previous successful data for patients whose fetch failed
      setPatientStatuses((prev) => {
        const merged = new Map(prev);
        let failCount = 0;
        results.forEach((result, idx) => {
          if (result.status === "fulfilled") {
            merged.set(patients[idx].patient_id, result.value);
          } else {
            failCount++;
          }
        });
        if (failCount > 0 && failCount < patients.length) {
          setError(
            `Failed to refresh ${failCount} of ${patients.length} patients`
          );
        } else if (failCount === patients.length) {
          setError("Failed to fetch patient statuses");
        } else {
          setError(null);
        }
        return merged;
      });

      setLastRefresh(new Date());
      setIsLoadingStatuses(false);
      setIsRefreshing(false);
    },
    [patients]
  );

  // Fetch single patient status (for detail view)
  const fetchStatus = useCallback(
    async (showRefreshing = false) => {
      if (!selectedPatientId) return;

      if (showRefreshing) setIsRefreshing(true);
      try {
        const data = await getCaregiverPatientStatus(selectedPatientId);
        setStatus(data);
        setError(null);
        setLastRefresh(new Date());
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to fetch status"
        );
      } finally {
        setIsRefreshing(false);
      }
    },
    [selectedPatientId]
  );

  // Story 8.4: AI chat handler
  const handleChatSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!selectedPatientId || !chatMessage.trim() || isChatLoading) return;

      setIsChatLoading(true);
      setChatError(null);
      try {
        const result = await sendCaregiverChat(
          selectedPatientId,
          chatMessage.trim()
        );
        setChatResponse(result);
        setChatMessage("");
      } catch (err) {
        setChatError(
          err instanceof Error ? err.message : "Failed to get AI response"
        );
      } finally {
        setIsChatLoading(false);
      }
    },
    [selectedPatientId, chatMessage, isChatLoading]
  );

  // Fetch status and reset chat when patient changes
  useEffect(() => {
    if (selectedPatientId) {
      fetchStatus();
      setChatMessage("");
      setChatResponse(null);
      setChatError(null);
    }
  }, [selectedPatientId, fetchStatus]);

  // Fetch all statuses when patients load (for multi-patient overview)
  useEffect(() => {
    if (patients.length > 1) {
      fetchAllStatuses();
    }
  }, [patients, fetchAllStatuses]);

  // Auto-refresh every 60 seconds
  useEffect(() => {
    if (patients.length === 0) return;

    const interval = setInterval(() => {
      if (selectedPatientId) {
        fetchStatus();
      } else if (patients.length > 1) {
        fetchAllStatuses();
      }
    }, REFRESH_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [patients, selectedPatientId, fetchStatus, fetchAllStatuses]);

  // Handle selecting a patient from the overview grid
  const handleSelectPatient = (patientId: string) => {
    setSelectedPatientId(patientId);
  };

  // Handle going back to overview
  const handleBackToOverview = () => {
    setSelectedPatientId(null);
    setStatus(null);
    setChatMessage("");
    setChatResponse(null);
    setChatError(null);
    // Refresh overview data (may be stale after time in detail view)
    fetchAllStatuses();
  };

  if (isLoading) {
    return (
      <main id="main-content" className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold">Caregiver Dashboard</h1>
          <p className="text-slate-500 dark:text-slate-400">Loading patient data</p>
        </div>
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading dashboard"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading dashboard...</p>
        </div>
      </main>
    );
  }

  if (patients.length === 0) {
    return (
      <main id="main-content" className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold">Caregiver Dashboard</h1>
          <p className="text-slate-500 dark:text-slate-400">Monitor your patient&apos;s glucose</p>
        </div>
        <div className="bg-white dark:bg-slate-900 rounded-xl p-8 border border-slate-200 dark:border-slate-800 text-center">
          <Users className="h-10 w-10 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400 mb-1">No patients linked</p>
          <p className="text-xs text-slate-500">
            Ask your patient to send you an invitation link from the
            GlycemicGPT web app.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main id="main-content" className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          {showOverview ? (
            <>
              <h1 className="text-2xl font-bold">Caregiver Dashboard</h1>
              <p className="text-slate-500 dark:text-slate-400">
                Monitoring {patients.length} patients
              </p>
            </>
          ) : (
            <div className="flex items-center gap-3">
              {isMultiPatient && (
                <button
                  type="button"
                  onClick={handleBackToOverview}
                  className="p-1.5 rounded-lg text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                  aria-label="Back to all patients"
                >
                  <ChevronLeft className="h-5 w-5" />
                </button>
              )}
              <div>
                <h1 className="text-2xl font-bold">Caregiver Dashboard</h1>
                <p className="text-slate-500 dark:text-slate-400">
                  Monitor your patient&apos;s glucose
                </p>
              </div>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs px-2 py-1 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <Eye className="h-3 w-3 inline mr-1" />
            Read-only
          </span>
          <button
            type="button"
            onClick={() =>
              showOverview
                ? fetchAllStatuses(true)
                : fetchStatus(true)
            }
            disabled={isRefreshing}
            className="p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
            aria-label="Refresh data"
          >
            <RefreshCw
              className={clsx("h-4 w-4", isRefreshing && "animate-spin")}
            />
          </button>
        </div>
      </div>

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

      {/* Story 8.5: Multi-patient card grid (overview mode) */}
      {showOverview && (
        <>
          {isLoadingStatuses && patientStatuses.size === 0 ? (
            <div
              className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
              role="status"
              aria-label="Loading patient statuses"
            >
              <Loader2 className="h-6 w-6 text-blue-400 animate-spin mx-auto mb-2" />
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Loading patient statuses...
              </p>
            </div>
          ) : (
            <div
              className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
              aria-live="polite"
              aria-atomic="false"
            >
              {patients.map((patient) => {
                const ps = patientStatuses.get(patient.patient_id) || null;
                const dotColor = getStatusDotColor(ps);
                const g =
                  ps?.permissions.can_view_glucose && ps?.glucose
                    ? ps.glucose
                    : null;

                return (
                  <button
                    key={patient.patient_id}
                    type="button"
                    onClick={() => handleSelectPatient(patient.patient_id)}
                    className="bg-white dark:bg-slate-900 rounded-xl p-5 border border-slate-200 dark:border-slate-800 text-left hover:border-blue-500/40 hover:bg-slate-50 dark:hover:bg-slate-900/80 transition-all cursor-pointer group"
                    aria-label={`View details for ${patient.patient_email}`}
                  >
                    {/* Patient name + status dot */}
                    <div className="flex items-center gap-2 mb-3">
                      <span
                        className={clsx(
                          "h-2.5 w-2.5 rounded-full shrink-0",
                          dotColor
                        )}
                        aria-hidden="true"
                      />
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
                        {patient.patient_email}
                      </span>
                    </div>

                    {/* Glucose value + trend */}
                    {g ? (
                      <div className="space-y-1">
                        <div className="flex items-baseline gap-2">
                          <span
                            className={clsx(
                              "text-3xl font-bold",
                              getGlucoseColor(g.value)
                            )}
                          >
                            {g.value}
                          </span>
                          <span className="text-sm text-slate-500 dark:text-slate-400">mg/dL</span>
                          <span className="text-lg">
                            {getTrendArrow(g.trend)}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 text-xs text-slate-500">
                          <Clock className="h-3 w-3" />
                          <span>
                            {g.minutes_ago < 1
                              ? "Just now"
                              : `${g.minutes_ago}m ago`}
                          </span>
                          {g.is_stale && (
                            <span className="text-yellow-400 ml-1">
                              Stale
                            </span>
                          )}
                        </div>
                      </div>
                    ) : ps?.permissions.can_view_glucose === false ? (
                      <div className="flex items-center gap-1.5 text-slate-500">
                        <Lock className="h-3.5 w-3.5" />
                        <span className="text-xs">Not permitted</span>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">No data</p>
                    )}

                    {/* Tap hint */}
                    <p className="text-xs text-slate-600 dark:text-slate-400 mt-3 group-hover:text-slate-500 dark:group-hover:text-slate-400 transition-colors">
                      Tap to view details
                    </p>
                  </button>
                );
              })}
            </div>
          )}

          {lastRefresh && (
            <p className="text-xs text-slate-500 text-center">
              Last updated{" "}
              {lastRefresh.toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          )}
        </>
      )}

      {/* Detail view loading spinner (drill-down transition) */}
      {!showOverview && !status && selectedPatientId && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading patient details"
        >
          <Loader2 className="h-6 w-6 text-blue-400 animate-spin mx-auto mb-2" />
          <p className="text-sm text-slate-500 dark:text-slate-400">Loading patient details...</p>
        </div>
      )}

      {/* Patient detail view (single patient or drill-down from grid) */}
      {!showOverview && status && (
        <>
          {/* Patient info bar */}
          <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Users className="h-4 w-4" />
            <span>
              Viewing data for{" "}
              <span className="text-blue-400">{status.patient_email}</span>
            </span>
            {lastRefresh && (
              <span className="text-xs text-slate-500 ml-auto">
                Updated{" "}
                {lastRefresh.toLocaleTimeString(undefined, {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
          </div>

          {/* Glucose Card */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-blue-500/10 rounded-lg">
                <Activity className="h-5 w-5 text-blue-400" />
              </div>
              <h2 className="text-lg font-semibold">Current Glucose</h2>
            </div>

            {status.permissions.can_view_glucose ? (
              status.glucose ? (
                <div className="space-y-3">
                  <div className="flex items-baseline gap-3">
                    <span
                      className={clsx(
                        "text-5xl font-bold",
                        getGlucoseColor(status.glucose.value)
                      )}
                    >
                      {status.glucose.value}
                    </span>
                    <span className="text-2xl text-slate-500 dark:text-slate-400">mg/dL</span>
                    <span className="text-2xl">
                      {getTrendArrow(status.glucose.trend)}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-slate-500">
                    <span className="flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5" />
                      {status.glucose.minutes_ago < 1
                        ? "Just now"
                        : `${status.glucose.minutes_ago}m ago`}
                    </span>
                    {status.glucose.is_stale && (
                      <span className="text-yellow-400 text-xs">
                        Data may be stale
                      </span>
                    )}
                    {status.glucose.trend_rate !== null && (
                      <span>
                        {status.glucose.trend_rate > 0 ? "+" : ""}
                        {status.glucose.trend_rate.toFixed(1)} mg/dL/min
                      </span>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-slate-500 text-sm">
                  No glucose data available
                </p>
              )
            ) : (
              <div className="flex items-center gap-2 text-slate-500">
                <Lock className="h-4 w-4" />
                <p className="text-sm">Glucose data not permitted</p>
              </div>
            )}
          </div>

          {/* IoB Card */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-purple-500/10 rounded-lg">
                <Syringe className="h-5 w-5 text-purple-400" />
              </div>
              <h2 className="text-lg font-semibold">Insulin on Board</h2>
            </div>

            {status.permissions.can_view_iob ? (
              status.iob ? (
                <div className="space-y-2">
                  <p className="text-3xl font-bold text-purple-400">
                    {status.iob.current_iob.toFixed(2)}{" "}
                    <span className="text-base text-slate-500 dark:text-slate-400">U</span>
                  </p>
                  {status.iob.is_stale && (
                    <p className="text-yellow-400 text-xs">
                      Data may be stale
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-slate-500 text-sm">
                  No IoB data available
                </p>
              )
            ) : (
              <div className="flex items-center gap-2 text-slate-500">
                <Lock className="h-4 w-4" />
                <p className="text-sm">IoB data not permitted</p>
              </div>
            )}
          </div>

          {/* AI Chat Card - Story 8.4 */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-cyan-500/10 rounded-lg">
                <MessageSquare className="h-5 w-5 text-cyan-400" />
              </div>
              <h2 className="text-lg font-semibold">
                Ask AI About Your Patient
              </h2>
            </div>

            {status.permissions.can_view_ai_suggestions ? (
              <div className="space-y-4">
                <div aria-live="polite" aria-atomic="true">
                  {chatResponse && (
                    <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 space-y-3">
                      <MarkdownContent content={chatResponse.response} className="text-slate-700 dark:text-slate-200" />
                      <p className="text-xs text-amber-400/70 italic">
                        {chatResponse.disclaimer}
                      </p>
                    </div>
                  )}
                </div>

                {chatError && (
                  <div className="flex items-center gap-2 text-sm text-red-400">
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    <p>{chatError}</p>
                  </div>
                )}

                <form onSubmit={handleChatSubmit} className="flex gap-2">
                  <input
                    type="text"
                    value={chatMessage}
                    onChange={(e) => setChatMessage(e.target.value)}
                    placeholder='Ask about your patient, e.g. "How are they doing?"'
                    maxLength={2000}
                    disabled={isChatLoading}
                    className="flex-1 bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 rounded-lg px-3 py-2 text-sm border border-slate-300 dark:border-slate-700 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-50"
                    aria-label="Ask AI about your patient"
                  />
                  <button
                    type="submit"
                    disabled={isChatLoading || !chatMessage.trim()}
                    className="px-4 py-2 rounded-lg bg-cyan-600 text-white text-sm font-medium hover:bg-cyan-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    aria-label="Send question"
                  >
                    {isChatLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </button>
                </form>

                <div className="flex flex-wrap gap-2">
                  {[
                    "How is my patient doing?",
                    "Should I be worried?",
                  ].map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => setChatMessage(q)}
                      disabled={isChatLoading}
                      className="text-xs px-3 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200 transition-colors disabled:opacity-50"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-slate-500">
                <Lock className="h-4 w-4" />
                <p className="text-sm">AI suggestions not permitted</p>
              </div>
            )}
          </div>

          {/* Permissions summary */}
          <div className="bg-slate-50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
            <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">
              Your access permissions
            </h3>
            <div className="flex flex-wrap gap-2">
              {[
                {
                  key: "can_view_glucose" as const,
                  label: "Glucose",
                },
                {
                  key: "can_view_history" as const,
                  label: "History",
                },
                { key: "can_view_iob" as const, label: "IoB" },
                {
                  key: "can_view_ai_suggestions" as const,
                  label: "AI Insights",
                },
                {
                  key: "can_receive_alerts" as const,
                  label: "Alerts",
                },
              ].map((perm) => (
                <span
                  key={perm.key}
                  className={clsx(
                    "text-xs px-2 py-1 rounded-full",
                    status.permissions[perm.key]
                      ? "bg-green-500/10 text-green-400"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-500"
                  )}
                >
                  {status.permissions[perm.key] ? (
                    <Eye className="h-3 w-3 inline mr-1" />
                  ) : (
                    <Lock className="h-3 w-3 inline mr-1" />
                  )}
                  {perm.label}
                </span>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Info card */}
      <div className="bg-slate-50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
        <p className="text-xs text-slate-500">
          This is a read-only view. Data access is controlled by the patient.
          Data refreshes automatically every 60 seconds.
        </p>
      </div>
    </main>
  );
}
