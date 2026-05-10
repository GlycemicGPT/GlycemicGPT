"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useReducer,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronRight,
  Eye,
  EyeOff,
  Link2,
  Loader2,
  Wifi,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import {
  applyNightscoutOnboarding,
  createNightscoutConnection,
  evaluateNightscoutConnection,
  getNightscoutOnboardingDerivation,
  syncNightscoutConnection,
  type NightscoutApiVersion,
  type NightscoutApplyOnboardingRequest,
  type NightscoutApplyOnboardingResponse,
  type NightscoutAuthType,
  type NightscoutDiscoveryReport,
  type OnboardingDerivation,
  type OnboardingScheduleFieldDerivation,
  type OnboardingScheduleSegment,
} from "@/lib/api";

// ----------------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------------

// Mirrors the backend `INITIAL_SYNC_WINDOW_DAYS_OPTIONS`. 0 means
// "All available history" (the connection's existing default-window
// behavior applies). Wizard default: 7d -- a sensible first-look
// window. Power users can pick 90d / All.
const SYNC_WINDOW_OPTIONS: readonly { days: number; label: string }[] = [
  { days: 1, label: "1 day" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 0, label: "All" },
];

const DEFAULT_SYNC_WINDOW_DAYS = 7;

// Step labels used in the progress stepper. Order is load-bearing.
const STEPS = [
  { id: "credentials", label: "Credentials" },
  { id: "evaluating", label: "Reading" },
  { id: "review", label: "Review" },
  { id: "applying", label: "Importing" },
  { id: "done", label: "Done" },
] as const;
type StepId = (typeof STEPS)[number]["id"];

const GLUCOSE_DOMAIN_IMPORT_FIELDS = [
  "target_low",
  "target_high",
  "isf_schedule",
] as const;

// ----------------------------------------------------------------------------
// Reducer state
// ----------------------------------------------------------------------------

interface ImportFlags {
  target_low: boolean;
  target_high: boolean;
  dia_hours: boolean;
  basal_schedule: boolean;
  carb_ratio_schedule: boolean;
  isf_schedule: boolean;
}

interface OverrideValues {
  // Strings so the input controls behave naturally; parsed at submit.
  target_low: string;
  target_high: string;
  dia_hours: string;
}

interface CredentialForm {
  name: string;
  base_url: string;
  credential: string;
  auth_type: NightscoutAuthType;
  api_version: NightscoutApiVersion;
}

interface WizardState {
  step: StepId;
  form: CredentialForm;
  formError: string | null;
  isCreating: boolean;
  credentialVisible: boolean;
  // Step 2
  connectionId: string | null;
  derivation: OnboardingDerivation | null;
  discovery: NightscoutDiscoveryReport | null;
  evaluateError: string | null;
  isEvaluating: boolean;
  evaluatePhase: "idle" | "evaluating" | "syncing" | "deriving";
  // Step 3
  imports: ImportFlags;
  overrides: OverrideValues;
  initialSyncWindowDays: number;
  confirmUnitsUnknown: boolean;
  // Step 4
  isApplying: boolean;
  applyError: string | null;
  applyResult: NightscoutApplyOnboardingResponse | null;
  // Bumped on retry. Effect's dep list includes this so a retry
  // re-fires the same evaluate() chain without needing to clear /
  // re-set `connectionId`.
  evaluateAttempt: number;
}

const INITIAL_STATE: WizardState = {
  step: "credentials",
  form: {
    name: "",
    base_url: "",
    credential: "",
    auth_type: "auto",
    api_version: "auto",
  },
  formError: null,
  isCreating: false,
  credentialVisible: false,
  connectionId: null,
  derivation: null,
  discovery: null,
  evaluateError: null,
  isEvaluating: false,
  evaluatePhase: "idle",
  imports: {
    target_low: false,
    target_high: false,
    dia_hours: false,
    basal_schedule: false,
    carb_ratio_schedule: false,
    isf_schedule: false,
  },
  overrides: { target_low: "", target_high: "", dia_hours: "" },
  initialSyncWindowDays: DEFAULT_SYNC_WINDOW_DAYS,
  confirmUnitsUnknown: false,
  isApplying: false,
  applyError: null,
  applyResult: null,
  evaluateAttempt: 0,
};

type Action =
  | { type: "form/update"; patch: Partial<CredentialForm> }
  | { type: "form/toggleCredentialVisible" }
  | { type: "form/submitStart" }
  | { type: "form/submitError"; message: string }
  | { type: "form/submitSuccess"; connectionId: string }
  | { type: "evaluate/start"; phase: "evaluating" | "syncing" | "deriving" }
  | { type: "evaluate/retry" }
  | {
      type: "evaluate/success";
      derivation: OnboardingDerivation;
      discovery: NightscoutDiscoveryReport;
    }
  | { type: "evaluate/error"; message: string }
  | { type: "imports/toggle"; field: keyof ImportFlags }
  | { type: "overrides/update"; field: keyof OverrideValues; value: string }
  | { type: "syncWindow/set"; days: number }
  | { type: "unitsConfirm/toggle" }
  | { type: "apply/start" }
  | { type: "apply/success"; result: NightscoutApplyOnboardingResponse }
  | { type: "apply/error"; message: string };

function seedImportsFromDerivation(d: OnboardingDerivation): ImportFlags {
  // Per AC: a field's "Use this?" checkbox defaults to its
  // `default_checked` -- which is true iff the user is at platform
  // default OR the proposal matches current (a no-op). Customized
  // users see the row off by default.
  return {
    target_low: d.target_low.default_checked && d.target_low.proposed_value !== null,
    target_high:
      d.target_high.default_checked && d.target_high.proposed_value !== null,
    dia_hours: d.dia_hours.default_checked && d.dia_hours.proposed_value !== null,
    basal_schedule:
      d.basal_schedule.default_checked &&
      (d.basal_schedule.proposed_segments?.length ?? 0) > 0,
    carb_ratio_schedule:
      d.carb_ratio_schedule.default_checked &&
      (d.carb_ratio_schedule.proposed_segments?.length ?? 0) > 0,
    isf_schedule:
      d.isf_schedule.default_checked &&
      (d.isf_schedule.proposed_segments?.length ?? 0) > 0,
  };
}

function reducer(state: WizardState, action: Action): WizardState {
  switch (action.type) {
    case "form/update":
      return { ...state, form: { ...state.form, ...action.patch }, formError: null };
    case "form/toggleCredentialVisible":
      return { ...state, credentialVisible: !state.credentialVisible };
    case "form/submitStart":
      return { ...state, isCreating: true, formError: null };
    case "form/submitError":
      return { ...state, isCreating: false, formError: action.message };
    case "form/submitSuccess":
      return {
        ...state,
        isCreating: false,
        connectionId: action.connectionId,
        step: "evaluating",
      };
    case "evaluate/start":
      return {
        ...state,
        isEvaluating: true,
        evaluateError: null,
        evaluatePhase: action.phase,
      };
    case "evaluate/retry":
      return {
        ...state,
        evaluateError: null,
        evaluateAttempt: state.evaluateAttempt + 1,
      };
    case "evaluate/success":
      return {
        ...state,
        isEvaluating: false,
        evaluatePhase: "idle",
        derivation: action.derivation,
        discovery: action.discovery,
        imports: seedImportsFromDerivation(action.derivation),
        step: "review",
      };
    case "evaluate/error":
      return {
        ...state,
        isEvaluating: false,
        evaluatePhase: "idle",
        evaluateError: action.message,
      };
    case "imports/toggle":
      return {
        ...state,
        imports: { ...state.imports, [action.field]: !state.imports[action.field] },
      };
    case "overrides/update":
      return {
        ...state,
        overrides: { ...state.overrides, [action.field]: action.value },
      };
    case "syncWindow/set":
      return { ...state, initialSyncWindowDays: action.days };
    case "unitsConfirm/toggle":
      return { ...state, confirmUnitsUnknown: !state.confirmUnitsUnknown };
    case "apply/start":
      return { ...state, isApplying: true, applyError: null, step: "applying" };
    case "apply/success":
      return {
        ...state,
        isApplying: false,
        applyResult: action.result,
        step: "done",
      };
    case "apply/error":
      // Stay on the review step so the user can correct + retry.
      return {
        ...state,
        isApplying: false,
        applyError: action.message,
        step: "review",
      };
    default:
      return state;
  }
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function formatTime(startMinutes: number): string {
  const h = Math.floor(startMinutes / 60);
  const m = startMinutes % 60;
  const period = h < 12 ? "AM" : "PM";
  const displayHour = h % 12 || 12;
  return `${displayHour}:${m.toString().padStart(2, "0")} ${period}`;
}

function parseOverride(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

function anyGlucoseDomainImported(imports: ImportFlags): boolean {
  return GLUCOSE_DOMAIN_IMPORT_FIELDS.some((f) => imports[f]);
}

// ----------------------------------------------------------------------------
// Wizard
// ----------------------------------------------------------------------------

export function NightscoutOnboardingWizard() {
  const router = useRouter();
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  // Kick the evaluate + derive chain when we enter step 2. Using
  // ref-as-cache-key so React-strict-mode double-mount in dev
  // doesn't fire two identical evaluate POSTs back-to-back, while
  // a Retry click (which bumps `evaluateAttempt`) still re-fires.
  const evaluateStartedFor = useRef<string | null>(null);
  useEffect(() => {
    if (state.step !== "evaluating") return;
    if (!state.connectionId) return;
    const key = `${state.connectionId}#${state.evaluateAttempt}`;
    if (evaluateStartedFor.current === key) return;
    evaluateStartedFor.current = key;

    // Cancellation flag: a Retry click (which bumps
    // `evaluateAttempt`) or an unmount must stop the in-flight chain
    // from dispatching to stale state. The async helpers don't take
    // AbortSignal today, so we gate every dispatch on the flag.
    let cancelled = false;

    const run = async () => {
      try {
        dispatch({ type: "evaluate/start", phase: "evaluating" });
        const discovery = await evaluateNightscoutConnection(state.connectionId!);
        if (cancelled) return;
        if (!discovery.status_ok) {
          dispatch({
            type: "evaluate/error",
            message:
              discovery.error ||
              "Couldn't read your Nightscout instance. Check the URL and credential.",
          });
          return;
        }
        // The derivation read pulls from `nightscout_profile_snapshots`,
        // which the discovery report does NOT populate. Kick a manual
        // sync after evaluate so the snapshot (and the connection's
        // initial entries) land before we ask the backend to derive
        // proposals. Apply-onboarding's first sync will then be near-
        // idempotent because the cursor has already advanced.
        dispatch({ type: "evaluate/start", phase: "syncing" });
        try {
          await syncNightscoutConnection(state.connectionId!);
        } catch (syncErr) {
          // Don't abort the wizard if sync fails -- derive can still
          // return `has_profile=False` and the review step renders
          // banners for that case. Log to console for triage.
          console.warn(
            "wizard: initial sync failed (continuing to derive)",
            syncErr
          );
        }
        if (cancelled) return;
        dispatch({ type: "evaluate/start", phase: "deriving" });
        const derivation = await getNightscoutOnboardingDerivation(
          state.connectionId!
        );
        if (cancelled) return;
        dispatch({ type: "evaluate/success", derivation, discovery });
      } catch (err) {
        if (cancelled) return;
        dispatch({
          type: "evaluate/error",
          message:
            err instanceof Error ? err.message : "Failed to evaluate connection",
        });
      }
    };
    void run();

    return () => {
      cancelled = true;
    };
  }, [state.step, state.connectionId, state.evaluateAttempt]);

  // Step 1 submit
  const onCreate = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      if (state.isCreating) return;
      const { name, base_url, credential } = state.form;
      if (!name.trim() || !base_url.trim() || !credential.trim()) {
        dispatch({
          type: "form/submitError",
          message: "Name, base URL, and credential are all required.",
        });
        return;
      }
      dispatch({ type: "form/submitStart" });
      try {
        const created = await createNightscoutConnection({
          name: name.trim(),
          base_url: base_url.trim(),
          credential: state.form.credential,
          auth_type: state.form.auth_type,
          api_version: state.form.api_version,
        });
        if (!created.test.ok) {
          dispatch({
            type: "form/submitError",
            message:
              created.test.error ||
              "Connection saved but the test request failed. Double-check the URL and credential.",
          });
          return;
        }
        dispatch({
          type: "form/submitSuccess",
          connectionId: created.connection.id,
        });
      } catch (err) {
        dispatch({
          type: "form/submitError",
          message:
            err instanceof Error ? err.message : "Failed to create connection.",
        });
      }
    },
    [state.form, state.isCreating]
  );

  // Step 3 → 4 submit
  const onApply = useCallback(async () => {
    if (!state.connectionId || !state.derivation) return;
    if (state.isApplying) return;

    // Server-side validation duplicates this -- we gate client-side
    // for instant feedback rather than waiting on a 409 round-trip.
    if (state.derivation.units_unknown) {
      if (anyGlucoseDomainImported(state.imports) && !state.confirmUnitsUnknown) {
        dispatch({
          type: "apply/error",
          message:
            "Confirm your Nightscout units before importing glucose-domain values.",
        });
        return;
      }
    }

    const overrideTargetLow = state.imports.target_low
      ? parseOverride(state.overrides.target_low)
      : null;
    const overrideTargetHigh = state.imports.target_high
      ? parseOverride(state.overrides.target_high)
      : null;
    const overrideDia = state.imports.dia_hours
      ? parseOverride(state.overrides.dia_hours)
      : null;

    const body: NightscoutApplyOnboardingRequest = {
      import_target_low: state.imports.target_low,
      import_target_high: state.imports.target_high,
      import_dia_hours: state.imports.dia_hours,
      import_basal_schedule: state.imports.basal_schedule,
      import_carb_ratio_schedule: state.imports.carb_ratio_schedule,
      import_isf_schedule: state.imports.isf_schedule,
      override_target_low: overrideTargetLow,
      override_target_high: overrideTargetHigh,
      override_dia_hours: overrideDia,
      initial_sync_window_days: state.initialSyncWindowDays,
      confirm_units_unknown: state.confirmUnitsUnknown,
    };

    dispatch({ type: "apply/start" });
    try {
      const result = await applyNightscoutOnboarding(state.connectionId, body);
      dispatch({ type: "apply/success", result });
    } catch (err) {
      dispatch({
        type: "apply/error",
        message: err instanceof Error ? err.message : "Apply failed.",
      });
    }
  }, [
    state.connectionId,
    state.derivation,
    state.imports,
    state.overrides,
    state.initialSyncWindowDays,
    state.confirmUnitsUnknown,
    state.isApplying,
  ]);

  return (
    <div
      className="min-h-screen bg-slate-50 dark:bg-slate-950"
      data-testid="nightscout-wizard"
    >
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
        <WizardHeader currentStep={state.step} />
        <div className="mt-6">
          {state.step === "credentials" && (
            <CredentialsStep
              form={state.form}
              error={state.formError}
              isCreating={state.isCreating}
              credentialVisible={state.credentialVisible}
              onUpdate={(patch) => dispatch({ type: "form/update", patch })}
              onToggleCredentialVisible={() =>
                dispatch({ type: "form/toggleCredentialVisible" })
              }
              onSubmit={onCreate}
            />
          )}
          {state.step === "evaluating" && (
            <EvaluatingStep
              phase={state.evaluatePhase}
              error={state.evaluateError}
              onRetry={() => dispatch({ type: "evaluate/retry" })}
              onCancel={() => router.push("/dashboard/settings/integrations")}
            />
          )}
          {state.step === "review" && state.derivation && (
            <ReviewStep
              derivation={state.derivation}
              discovery={state.discovery}
              imports={state.imports}
              overrides={state.overrides}
              initialSyncWindowDays={state.initialSyncWindowDays}
              confirmUnitsUnknown={state.confirmUnitsUnknown}
              applyError={state.applyError}
              onToggleImport={(field) =>
                dispatch({ type: "imports/toggle", field })
              }
              onUpdateOverride={(field, value) =>
                dispatch({ type: "overrides/update", field, value })
              }
              onSyncWindowChange={(days) =>
                dispatch({ type: "syncWindow/set", days })
              }
              onConfirmUnitsToggle={() =>
                dispatch({ type: "unitsConfirm/toggle" })
              }
              onApply={onApply}
              isApplying={state.isApplying}
            />
          )}
          {state.step === "applying" && <ApplyingStep />}
          {state.step === "done" && state.applyResult && (
            <DoneStep
              result={state.applyResult}
              onGoToIntegrations={() =>
                router.push("/dashboard/settings/integrations")
              }
              onGoToDashboard={() => router.push("/dashboard")}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------
// Header / stepper
// ----------------------------------------------------------------------------

function WizardHeader({ currentStep }: { currentStep: StepId }) {
  const currentIndex = STEPS.findIndex((s) => s.id === currentStep);
  return (
    <div>
      <div className="flex items-center gap-3 text-slate-700 dark:text-slate-200">
        <Wifi className="h-5 w-5 text-blue-500" />
        <h1 className="text-xl font-semibold">Connect Nightscout</h1>
      </div>
      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
        Read your existing Nightscout profile and pre-fill your GlycemicGPT
        settings so you don&apos;t start from a blank dashboard.
      </p>
      <ol
        className="mt-5 flex items-center gap-2 text-xs"
        aria-label="Wizard progress"
      >
        {STEPS.map((step, idx) => {
          const reached = idx <= currentIndex;
          const isCurrent = idx === currentIndex;
          return (
            <li
              key={step.id}
              className="flex items-center gap-2"
              aria-current={isCurrent ? "step" : undefined}
            >
              <span
                className={clsx(
                  "inline-flex h-6 w-6 items-center justify-center rounded-full font-semibold",
                  reached
                    ? "bg-blue-600 text-white"
                    : "bg-slate-200 dark:bg-slate-800 text-slate-500"
                )}
              >
                {idx + 1}
              </span>
              <span
                className={clsx(
                  "font-medium",
                  isCurrent
                    ? "text-slate-700 dark:text-slate-200"
                    : "text-slate-500 dark:text-slate-400"
                )}
              >
                {step.label}
              </span>
              {idx < STEPS.length - 1 && (
                <span
                  aria-hidden="true"
                  className="h-px w-6 bg-slate-200 dark:bg-slate-800"
                />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ----------------------------------------------------------------------------
// Step 1 — credentials
// ----------------------------------------------------------------------------

interface CredentialsStepProps {
  form: CredentialForm;
  error: string | null;
  isCreating: boolean;
  credentialVisible: boolean;
  onUpdate: (patch: Partial<CredentialForm>) => void;
  onToggleCredentialVisible: () => void;
  onSubmit: (e: FormEvent) => void;
}

function CredentialsStep({
  form,
  error,
  isCreating,
  credentialVisible,
  onUpdate,
  onToggleCredentialVisible,
  onSubmit,
}: CredentialsStepProps) {
  // useId so this form can theoretically render twice on the same
  // page without colliding `for`/`id` pairs (e.g. if the wizard is
  // ever portaled into a "preview" pane or rendered in a dev story).
  const reactId = useId();
  const nameId = `${reactId}-name`;
  const urlId = `${reactId}-url`;
  const credId = `${reactId}-cred`;
  const authTypeId = `${reactId}-auth`;
  const apiVerId = `${reactId}-apiver`;
  return (
    <form
      onSubmit={onSubmit}
      className="bg-white dark:bg-slate-900 rounded-lg p-5 border border-slate-200 dark:border-slate-800"
      aria-label="Nightscout credentials"
      data-testid="wizard-step-credentials"
    >
      <h2 className="text-base font-medium text-slate-700 dark:text-slate-200">
        Your Nightscout instance
      </h2>
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
        We&apos;ll test the connection before reading your profile.
      </p>
      <div className="mt-4 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field id={nameId} label="Name">
            <input
              id={nameId}
              type="text"
              value={form.name}
              onChange={(e) => onUpdate({ name: e.target.value })}
              disabled={isCreating}
              placeholder="e.g. Home Loop"
              data-testid="wizard-ns-name"
              className={inputCls}
            />
          </Field>
          <Field id={urlId} label="Nightscout URL">
            <input
              id={urlId}
              type="url"
              value={form.base_url}
              onChange={(e) => onUpdate({ base_url: e.target.value })}
              disabled={isCreating}
              placeholder="https://my-ns.example.com"
              autoComplete="off"
              data-testid="wizard-ns-url"
              className={inputCls}
            />
          </Field>
        </div>
        <Field id={credId} label="API_SECRET or bearer token">
          <div className="relative">
            <input
              id={credId}
              type={credentialVisible ? "text" : "password"}
              value={form.credential}
              onChange={(e) => onUpdate({ credential: e.target.value })}
              disabled={isCreating}
              autoComplete="off"
              spellCheck={false}
              data-1p-ignore=""
              data-lpignore="true"
              data-testid="wizard-ns-credential"
              className={clsx(inputCls, "pr-10")}
            />
            <button
              type="button"
              onClick={onToggleCredentialVisible}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              aria-label={
                credentialVisible ? "Hide credential" : "Show credential"
              }
            >
              {credentialVisible ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Use your Nightscout API_SECRET (the longer config string) or a
            bearer token issued by your deployment.
          </p>
        </Field>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field id={authTypeId} label="Credential type">
            <select
              id={authTypeId}
              value={form.auth_type}
              onChange={(e) =>
                onUpdate({ auth_type: e.target.value as NightscoutAuthType })
              }
              disabled={isCreating}
              className={inputCls}
            >
              <option value="auto">Auto-detect</option>
              <option value="secret">API_SECRET</option>
              <option value="token">Bearer token</option>
            </select>
          </Field>
          <Field id={apiVerId} label="API version">
            <select
              id={apiVerId}
              value={form.api_version}
              onChange={(e) =>
                onUpdate({
                  api_version: e.target.value as NightscoutApiVersion,
                })
              }
              disabled={isCreating}
              className={inputCls}
            >
              <option value="auto">Auto-detect</option>
              <option value="v1">v1</option>
              <option value="v3">v3</option>
            </select>
          </Field>
        </div>
      </div>
      {error && (
        <div
          className="mt-3 bg-red-500/10 rounded-lg p-2 px-3 text-xs text-red-400 flex items-center gap-2"
          role="alert"
          data-testid="wizard-credentials-error"
        >
          <AlertTriangle className="h-3 w-3 shrink-0" />
          {error}
        </div>
      )}
      <div className="mt-5 flex items-center justify-between">
        <Link
          href="/dashboard/settings/integrations"
          className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 inline-flex items-center gap-1"
        >
          <ArrowLeft className="h-3 w-3" /> Cancel
        </Link>
        <button
          type="submit"
          disabled={isCreating}
          data-testid="wizard-credentials-submit"
          className={clsx(
            "px-4 py-2 rounded-lg text-sm font-medium",
            "bg-blue-600 text-white hover:bg-blue-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "transition-colors flex items-center gap-2"
          )}
        >
          {isCreating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Link2 className="h-4 w-4" />
          )}
          Connect &amp; continue
        </button>
      </div>
    </form>
  );
}

// ----------------------------------------------------------------------------
// Step 2 — evaluating
// ----------------------------------------------------------------------------

interface EvaluatingStepProps {
  phase: "idle" | "evaluating" | "syncing" | "deriving";
  error: string | null;
  onRetry: () => void;
  onCancel: () => void;
}

function EvaluatingStep({ phase, error, onRetry, onCancel }: EvaluatingStepProps) {
  if (error) {
    return (
      <div
        className="bg-white dark:bg-slate-900 rounded-lg p-5 border border-red-500/30"
        data-testid="wizard-step-evaluating"
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
          <div className="flex-1">
            <h2 className="text-base font-medium text-slate-700 dark:text-slate-200">
              We couldn&apos;t read your Nightscout instance
            </h2>
            <p className="text-sm text-red-400 mt-1" data-testid="wizard-eval-error">
              {error}
            </p>
            <p className="text-xs text-slate-500 mt-3">
              Your connection was saved -- you can fix the URL/credential from
              the integrations page, or retry this step.
            </p>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            onClick={onCancel}
            className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 inline-flex items-center gap-1"
          >
            <ArrowLeft className="h-3 w-3" /> Back to integrations
          </button>
          <button
            type="button"
            onClick={onRetry}
            data-testid="wizard-eval-retry"
            className="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const label =
    phase === "deriving"
      ? "Building proposals…"
      : phase === "syncing"
        ? "Importing your initial profile…"
        : "Reading your Nightscout profile…";
  return (
    <div
      className="bg-white dark:bg-slate-900 rounded-lg p-8 border border-slate-200 dark:border-slate-800 flex flex-col items-center justify-center text-center"
      data-testid="wizard-step-evaluating"
    >
      <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
      <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">
        {label}
      </p>
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
        This usually takes a few seconds.
      </p>
    </div>
  );
}

// ----------------------------------------------------------------------------
// Step 3 — review
// ----------------------------------------------------------------------------

interface ReviewStepProps {
  derivation: OnboardingDerivation;
  discovery: NightscoutDiscoveryReport | null;
  imports: ImportFlags;
  overrides: OverrideValues;
  initialSyncWindowDays: number;
  confirmUnitsUnknown: boolean;
  applyError: string | null;
  onToggleImport: (field: keyof ImportFlags) => void;
  onUpdateOverride: (field: keyof OverrideValues, value: string) => void;
  onSyncWindowChange: (days: number) => void;
  onConfirmUnitsToggle: () => void;
  onApply: () => void;
  isApplying: boolean;
}

function ReviewStep({
  derivation,
  discovery,
  imports,
  overrides,
  initialSyncWindowDays,
  confirmUnitsUnknown,
  applyError,
  onToggleImport,
  onUpdateOverride,
  onSyncWindowChange,
  onConfirmUnitsToggle,
  onApply,
  isApplying,
}: ReviewStepProps) {
  const needsUnitsConfirm = useMemo(
    () => derivation.units_unknown && anyGlucoseDomainImported(imports),
    [derivation.units_unknown, imports]
  );
  const anyImportChecked = useMemo(
    () =>
      imports.target_low ||
      imports.target_high ||
      imports.dia_hours ||
      imports.basal_schedule ||
      imports.carb_ratio_schedule ||
      imports.isf_schedule,
    [imports]
  );
  // Mirror the per-row "did the user type something that won't
  // parse?" check at the top level so Apply can't be clicked while
  // any active override is invalid. Schedules don't take overrides
  // so they're not part of this check.
  const hasInvalidOverride = useMemo(() => {
    const check = (
      flag: boolean,
      proposed: number | null,
      raw: string
    ): boolean =>
      flag &&
      proposed !== null &&
      raw.trim() !== "" &&
      parseOverride(raw) === null;
    return (
      check(imports.target_low, derivation.target_low.proposed_value, overrides.target_low) ||
      check(imports.target_high, derivation.target_high.proposed_value, overrides.target_high) ||
      check(imports.dia_hours, derivation.dia_hours.proposed_value, overrides.dia_hours)
    );
  }, [imports, overrides, derivation]);

  const applyBlocked =
    !anyImportChecked ||
    hasInvalidOverride ||
    (needsUnitsConfirm && !confirmUnitsUnknown);

  return (
    <div
      className="bg-white dark:bg-slate-900 rounded-lg p-5 border border-slate-200 dark:border-slate-800"
      data-testid="wizard-step-review"
    >
      <h2 className="text-base font-medium text-slate-700 dark:text-slate-200">
        Review what we found
      </h2>
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
        Uncheck anything you don&apos;t want to import. Overrides replace the
        Nightscout value with what you type.
      </p>

      {discovery && (
        <div className="mt-3 text-xs text-slate-500 dark:text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
          {discovery.entry_count_estimate > 0 && (
            <span>~{discovery.entry_count_estimate.toLocaleString()} entries</span>
          )}
          {discovery.uploaders_detected.length > 0 && (
            <span>
              Uploader{discovery.uploaders_detected.length === 1 ? "" : "s"}:{" "}
              {discovery.uploaders_detected.join(", ")}
            </span>
          )}
          {discovery.server_version && (
            <span>Server {discovery.server_version}</span>
          )}
          {discovery.active_pump_loop && (
            <span>Loop: {discovery.active_pump_loop}</span>
          )}
        </div>
      )}

      {derivation.units_converted && (
        <Banner
          tone="info"
          title="Units converted from mmol/L"
          body="Your Nightscout profile uses mmol/L. We've converted glucose values to mg/dL for storage."
          testId="wizard-banner-units-converted"
        />
      )}

      {derivation.units_unknown && (
        <Banner
          tone="warn"
          title="Couldn't detect glucose units"
          body="Your Nightscout profile didn't report units we recognize. Confirm below before importing target ranges or ISF."
          testId="wizard-banner-units-unknown"
        />
      )}

      {!derivation.has_profile && (
        <Banner
          tone="warn"
          title="No profile detected"
          body="Your Nightscout doesn't have a default profile we can read. You can still import the connection's first sync; settings stay at platform defaults."
          testId="wizard-banner-no-profile"
        />
      )}

      <div className="mt-5 space-y-2">
        <NumericRow
          label="Target low"
          unitsHint="mg/dL"
          checked={imports.target_low}
          onToggle={() => onToggleImport("target_low")}
          current={derivation.target_low.current_value}
          proposed={derivation.target_low.proposed_value}
          override={overrides.target_low}
          onOverrideChange={(v) => onUpdateOverride("target_low", v)}
          field="target_low"
        />
        <NumericRow
          label="Target high"
          unitsHint="mg/dL"
          checked={imports.target_high}
          onToggle={() => onToggleImport("target_high")}
          current={derivation.target_high.current_value}
          proposed={derivation.target_high.proposed_value}
          override={overrides.target_high}
          onOverrideChange={(v) => onUpdateOverride("target_high", v)}
          field="target_high"
        />
        <NumericRow
          label="DIA"
          unitsHint="hours"
          checked={imports.dia_hours}
          onToggle={() => onToggleImport("dia_hours")}
          current={derivation.dia_hours.current_value}
          proposed={derivation.dia_hours.proposed_value}
          override={overrides.dia_hours}
          onOverrideChange={(v) => onUpdateOverride("dia_hours", v)}
          field="dia_hours"
        />
        <ScheduleRow
          label="Basal schedule"
          unitsHint="U/hr"
          checked={imports.basal_schedule}
          onToggle={() => onToggleImport("basal_schedule")}
          derivation={derivation.basal_schedule}
          field="basal_schedule"
        />
        <ScheduleRow
          label="Carb ratio schedule"
          unitsHint="g/U"
          checked={imports.carb_ratio_schedule}
          onToggle={() => onToggleImport("carb_ratio_schedule")}
          derivation={derivation.carb_ratio_schedule}
          field="carb_ratio_schedule"
        />
        <ScheduleRow
          label="ISF schedule"
          unitsHint="mg/dL per U"
          checked={imports.isf_schedule}
          onToggle={() => onToggleImport("isf_schedule")}
          derivation={derivation.isf_schedule}
          field="isf_schedule"
        />
      </div>

      <div className="mt-5">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
          Import history for
        </span>
        <p className="text-xs text-slate-500 mt-0.5">
          How far back to pull your first sync.
        </p>
        <SyncWindowRadioGroup
          value={initialSyncWindowDays}
          onChange={onSyncWindowChange}
        />
      </div>

      {needsUnitsConfirm && (
        <label
          className="mt-4 flex items-start gap-2 text-xs text-slate-700 dark:text-slate-200 cursor-pointer"
          data-testid="wizard-confirm-units-unknown"
        >
          <input
            type="checkbox"
            checked={confirmUnitsUnknown}
            onChange={onConfirmUnitsToggle}
            className="mt-0.5"
          />
          <span>
            I confirm my Nightscout glucose values are in <strong>mg/dL</strong>
            . If they&apos;re actually mmol/L, importing them will corrupt my
            targets and ISF.
          </span>
        </label>
      )}

      {applyError && (
        <div
          className="mt-4 bg-red-500/10 rounded-lg p-2 px-3 text-xs text-red-400 flex items-center gap-2"
          role="alert"
          data-testid="wizard-apply-error"
        >
          <AlertTriangle className="h-3 w-3 shrink-0" />
          {applyError}
        </div>
      )}

      {applyBlocked && !applyError && (
        <p
          className="mt-3 text-xs text-slate-500 dark:text-slate-400"
          data-testid="wizard-apply-blocked-hint"
        >
          {!anyImportChecked
            ? "Check at least one setting above to enable Apply."
            : hasInvalidOverride
              ? "Fix the highlighted override before continuing."
              : "Confirm your Nightscout units before continuing."}
        </p>
      )}

      <div className="mt-5 flex items-center justify-between">
        <Link
          href="/dashboard/settings/integrations"
          className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 inline-flex items-center gap-1"
        >
          <ArrowLeft className="h-3 w-3" /> Cancel
        </Link>
        <button
          type="button"
          onClick={onApply}
          disabled={applyBlocked || isApplying}
          data-testid="wizard-apply"
          className={clsx(
            "px-4 py-2 rounded-lg text-sm font-medium",
            "bg-blue-600 text-white hover:bg-blue-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "transition-colors flex items-center gap-2"
          )}
        >
          {isApplying ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Check className="h-4 w-4" />
          )}
          Apply &amp; import
        </button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------
// Sync-window radio group (roving tabindex + arrow-key nav per ARIA APG)
// ----------------------------------------------------------------------------

interface SyncWindowRadioGroupProps {
  value: number;
  onChange: (days: number) => void;
}

function SyncWindowRadioGroup({ value, onChange }: SyncWindowRadioGroupProps) {
  // Roving tabindex: only the selected (or first) option is tab-able;
  // arrow keys move focus + selection per WAI-ARIA Authoring Practices
  // for radio groups. Without this, keyboard users tab through every
  // chip individually (and screen readers don't announce them as a
  // grouped choice).
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const currentIndex = Math.max(
    0,
    SYNC_WINDOW_OPTIONS.findIndex((o) => o.days === value)
  );

  const moveTo = (idx: number) => {
    const len = SYNC_WINDOW_OPTIONS.length;
    const next = ((idx % len) + len) % len;
    onChange(SYNC_WINDOW_OPTIONS[next].days);
    refs.current[next]?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent, idx: number) => {
    switch (e.key) {
      case "ArrowRight":
      case "ArrowDown":
        e.preventDefault();
        moveTo(idx + 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        e.preventDefault();
        moveTo(idx - 1);
        break;
      case "Home":
        e.preventDefault();
        moveTo(0);
        break;
      case "End":
        e.preventDefault();
        moveTo(SYNC_WINDOW_OPTIONS.length - 1);
        break;
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label="Initial sync window"
      className="mt-2 flex flex-wrap gap-2"
    >
      {SYNC_WINDOW_OPTIONS.map((opt, idx) => {
        const selected = opt.days === value;
        return (
          <button
            key={opt.days}
            ref={(el) => {
              refs.current[idx] = el;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={idx === currentIndex ? 0 : -1}
            onClick={() => onChange(opt.days)}
            onKeyDown={(e) => onKeyDown(e, idx)}
            data-testid={`wizard-sync-window-${opt.days}`}
            className={clsx(
              "px-3 py-1 rounded-full text-xs font-medium border transition-colors",
              selected
                ? "border-blue-500/50 bg-blue-500/10 text-blue-400"
                : "border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// ----------------------------------------------------------------------------
// Diff-table rows
// ----------------------------------------------------------------------------

interface NumericRowProps {
  label: string;
  unitsHint: string;
  checked: boolean;
  onToggle: () => void;
  current: number | null;
  proposed: number | null;
  override: string;
  onOverrideChange: (value: string) => void;
  field: string;
}

function NumericRow({
  label,
  unitsHint,
  checked,
  onToggle,
  current,
  proposed,
  override,
  onOverrideChange,
  field,
}: NumericRowProps) {
  const noProposal = proposed === null;
  // Empty override = "use the Nightscout proposal". Non-empty
  // override that doesn't parse to a positive number is a real
  // user-entered value the wizard would silently drop (parseOverride
  // returns null) -- flag it visibly so the user doesn't end up with
  // the NS proposal believing their typed value won.
  const overrideInvalid =
    checked && !noProposal && override.trim() !== "" && parseOverride(override) === null;
  const errorId = `wiz-${field}-override-error`;
  return (
    <div
      className={clsx(
        "rounded-lg border p-3 flex flex-wrap items-center gap-3",
        noProposal
          ? "border-slate-200 dark:border-slate-800 opacity-60"
          : overrideInvalid
            ? "border-red-500/40"
            : "border-slate-200 dark:border-slate-800"
      )}
      data-testid={`wizard-row-${field}`}
    >
      <label className="flex items-center gap-2 flex-1 min-w-0 cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          disabled={noProposal}
          data-testid={`wizard-import-${field}`}
          className="shrink-0"
        />
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
          {label}
        </span>
      </label>
      <div className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-3">
        <span>
          Currently: <strong>{formatNumber(current)}</strong>
        </span>
        <span aria-hidden="true">→</span>
        <span>
          Nightscout:{" "}
          <strong data-testid={`wizard-proposed-${field}`}>
            {noProposal ? "—" : formatNumber(proposed)}
          </strong>
        </span>
      </div>
      <div className="flex items-center gap-1">
        <input
          type="number"
          step="any"
          min="0"
          inputMode="decimal"
          value={override}
          onChange={(e) => onOverrideChange(e.target.value)}
          disabled={!checked || noProposal}
          placeholder={
            proposed !== null
              ? `Use ${formatNumber(proposed).toString()}`
              : ""
          }
          aria-label={`Override ${label}`}
          aria-invalid={overrideInvalid || undefined}
          aria-describedby={overrideInvalid ? errorId : undefined}
          data-testid={`wizard-override-${field}`}
          className={clsx(
            "w-28 rounded-md border px-2 py-1 text-xs",
            "bg-white dark:bg-slate-800",
            overrideInvalid
              ? "border-red-500/60"
              : "border-slate-300 dark:border-slate-700",
            "text-slate-700 dark:text-slate-200",
            "focus:outline-none focus:ring-2 focus:ring-blue-500",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        />
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {unitsHint}
        </span>
      </div>
      {overrideInvalid && (
        <p
          id={errorId}
          className="basis-full text-xs text-red-400"
          role="alert"
          data-testid={`wizard-override-error-${field}`}
        >
          Enter a positive number, or clear the field to use Nightscout&apos;s
          value.
        </p>
      )}
    </div>
  );
}

interface ScheduleRowProps {
  label: string;
  unitsHint: string;
  checked: boolean;
  onToggle: () => void;
  derivation: OnboardingScheduleFieldDerivation;
  field: string;
}

function ScheduleRow({
  label,
  unitsHint,
  checked,
  onToggle,
  derivation,
  field,
}: ScheduleRowProps) {
  const proposed = derivation.proposed_segments;
  const current = derivation.current_segments;
  const noProposal = !proposed || proposed.length === 0;
  // Disclosure state is managed by us (not a native <details>)
  // because putting a checkbox inside <summary> caused the segment
  // preview to toggle on every checkbox click in Safari -- the
  // input click target is part of <summary>'s click region and
  // bubbling control isn't reliable across engines. A plain
  // <button> for the disclosure trigger keeps the checkbox click
  // strictly local.
  const [isOpen, setIsOpen] = useState(false);
  const panelId = `wiz-${field}-segments-panel`;

  return (
    <div
      className={clsx(
        "rounded-lg border",
        noProposal
          ? "border-slate-200 dark:border-slate-800 opacity-60"
          : "border-slate-200 dark:border-slate-800"
      )}
      data-testid={`wizard-row-${field}`}
    >
      <div className="flex flex-wrap items-center gap-3 p-3">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={checked}
            onChange={onToggle}
            disabled={noProposal}
            data-testid={`wizard-import-${field}`}
            className="shrink-0"
          />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {label}
          </span>
        </label>
        <div className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-3 flex-1 min-w-0">
          <span>
            Currently:{" "}
            <strong>
              {current && current.length > 0
                ? `${current.length} segment${current.length === 1 ? "" : "s"}`
                : "—"}
            </strong>
          </span>
          <span aria-hidden="true">→</span>
          <span>
            Nightscout:{" "}
            <strong data-testid={`wizard-proposed-${field}`}>
              {noProposal
                ? "—"
                : `${proposed!.length} segment${proposed!.length === 1 ? "" : "s"}`}
            </strong>
          </span>
        </div>
        {!noProposal && (
          <button
            type="button"
            onClick={() => setIsOpen((v) => !v)}
            aria-expanded={isOpen}
            aria-controls={panelId}
            data-testid={`wizard-toggle-segments-${field}`}
            className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 inline-flex items-center gap-0.5"
          >
            {isOpen ? "Hide" : "Preview"}
            <ChevronRight
              className={clsx(
                "h-3 w-3 transition-transform",
                isOpen && "rotate-90"
              )}
            />
          </button>
        )}
      </div>
      {!noProposal && isOpen && (
        <div id={panelId} className="px-3 pb-3 -mt-1">
          <div className="rounded-md bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 overflow-hidden">
            <table className="w-full text-xs">
              <thead className="text-slate-500 dark:text-slate-400">
                <tr>
                  <th className="text-left px-3 py-1 font-medium">Time</th>
                  <th className="text-right px-3 py-1 font-medium">
                    Value ({unitsHint})
                  </th>
                </tr>
              </thead>
              <tbody className="text-slate-700 dark:text-slate-200">
                {proposed!.map((seg: OnboardingScheduleSegment) => (
                  <tr
                    key={seg.start_minutes}
                    className="border-t border-slate-200 dark:border-slate-800"
                  >
                    <td className="px-3 py-1 font-mono">
                      {formatTime(seg.start_minutes)}
                    </td>
                    <td className="px-3 py-1 text-right font-mono">
                      {formatNumber(seg.value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function formatNumber(v: number | null): string {
  if (v === null || v === undefined) return "—";
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2).replace(/\.?0+$/, "");
}

// ----------------------------------------------------------------------------
// Step 4 — applying
// ----------------------------------------------------------------------------

function ApplyingStep() {
  return (
    <div
      className="bg-white dark:bg-slate-900 rounded-lg p-8 border border-slate-200 dark:border-slate-800 flex flex-col items-center justify-center text-center"
      data-testid="wizard-step-applying"
    >
      <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
      <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">
        Saving settings and importing your first sync…
      </p>
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
        This can take up to 20 seconds.
      </p>
    </div>
  );
}

// ----------------------------------------------------------------------------
// Step 5 — done
// ----------------------------------------------------------------------------

interface DoneStepProps {
  result: NightscoutApplyOnboardingResponse;
  onGoToIntegrations: () => void;
  onGoToDashboard: () => void;
}

function DoneStep({
  result,
  onGoToIntegrations,
  onGoToDashboard,
}: DoneStepProps) {
  // Only render setting-domain fields. The backend's `applied` map
  // also surfaces non-setting flags like `initial_sync_window_days`
  // (which is a connection-level config, not a settings import);
  // listing it under "We imported:" would mislead the user into
  // thinking it's a glucose / insulin setting.
  const appliedFields = useMemo(
    () =>
      Object.entries(result.applied).filter(
        ([k, v]) => v === true && SETTING_FIELD_LABELS[k] !== undefined
      ),
    [result.applied]
  );
  const syncOk = result.first_sync_status === "ok";
  const syncTimeout = result.first_sync_status === "timeout";

  return (
    <div
      className="bg-white dark:bg-slate-900 rounded-lg p-5 border border-slate-200 dark:border-slate-800"
      data-testid="wizard-step-done"
    >
      <div className="flex items-center gap-2 text-green-500">
        <Check className="h-5 w-5" />
        <h2 className="text-base font-medium text-slate-700 dark:text-slate-200">
          Connected
        </h2>
      </div>

      {appliedFields.length > 0 ? (
        <div className="mt-3">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            We imported:
          </p>
          <ul
            className="mt-1 space-y-1"
            data-testid="wizard-done-applied-list"
          >
            {appliedFields.map(([field]) => (
              <li
                key={field}
                className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200"
              >
                <Check className="h-3 w-3 text-green-500" />
                <span>{labelForField(field)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">
          No settings were imported. Your connection is saved -- you can sync
          data without changing any settings.
        </p>
      )}

      <div className="mt-4">
        {syncOk && result.sync_result && (
          <SyncStatusLine result={result} />
        )}
        {syncTimeout && (
          <p
            className="text-xs text-amber-400 flex items-center gap-1"
            data-testid="wizard-sync-timeout"
          >
            <AlertTriangle className="h-3 w-3" /> Your first sync is still
            running -- check the integrations page in a moment.
          </p>
        )}
        {result.first_sync_status === "error" && (
          <p
            className="text-xs text-red-400 flex items-center gap-1"
            data-testid="wizard-sync-error"
          >
            <X className="h-3 w-3" /> Settings saved, but the first sync hit an
            error: {result.first_sync_error || "unknown error"}
          </p>
        )}
        {result.first_sync_status === "skipped" && (
          <p className="text-xs text-slate-500">First sync was skipped.</p>
        )}
      </div>

      <div className="mt-5 flex flex-wrap gap-2 justify-end">
        <button
          type="button"
          onClick={onGoToIntegrations}
          className="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
          data-testid="wizard-done-back-integrations"
        >
          Back to integrations
        </button>
        <button
          type="button"
          onClick={onGoToDashboard}
          className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-500"
          data-testid="wizard-done-dashboard"
        >
          Go to dashboard
        </button>
      </div>
    </div>
  );
}

function SyncStatusLine({
  result,
}: {
  result: NightscoutApplyOnboardingResponse;
}) {
  if (!result.sync_result) return null;
  const sr = result.sync_result;
  const inserted =
    sr.entries_inserted +
    sr.treatments_inserted_pump +
    sr.treatments_inserted_glucose +
    sr.devicestatuses_inserted;
  return (
    <p
      className="text-xs text-green-400 flex items-center gap-1"
      data-testid="wizard-sync-ok"
    >
      <Check className="h-3 w-3" /> Imported {inserted.toLocaleString()} record
      {inserted === 1 ? "" : "s"} in {sr.duration_ms}ms.
    </p>
  );
}

const SETTING_FIELD_LABELS: Record<string, string> = {
  target_low: "Target low",
  target_high: "Target high",
  dia_hours: "DIA",
  basal_schedule: "Basal schedule",
  carb_ratio_schedule: "Carb ratio schedule",
  isf_schedule: "ISF schedule",
};

function labelForField(field: string): string {
  return SETTING_FIELD_LABELS[field] ?? field;
}

// ----------------------------------------------------------------------------
// Small primitives
// ----------------------------------------------------------------------------

const inputCls = clsx(
  "w-full rounded-lg border px-3 py-2 text-sm",
  "bg-white dark:bg-slate-800",
  "border-slate-300 dark:border-slate-700",
  "text-slate-700 dark:text-slate-200",
  "placeholder:text-slate-400 dark:placeholder:text-slate-500",
  "focus:outline-none focus:ring-2 focus:ring-blue-500",
  "disabled:opacity-50 disabled:cursor-not-allowed"
);

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
      >
        {label}
      </label>
      {children}
    </div>
  );
}

function Banner({
  tone,
  title,
  body,
  testId,
}: {
  tone: "info" | "warn";
  title: string;
  body: string;
  testId: string;
}) {
  return (
    <div
      className={clsx(
        "mt-4 rounded-lg p-3 text-xs border",
        tone === "info"
          ? "bg-blue-500/5 border-blue-500/30 text-blue-300"
          : "bg-amber-500/5 border-amber-500/30 text-amber-300"
      )}
      // Warning banners are safety-critical (units-unknown corrupts
      // glucose targets if user picks wrong); promote to `alert` so
      // assistive tech interrupts. Info banners stay `status`.
      role={tone === "warn" ? "alert" : "status"}
      data-testid={testId}
    >
      <p className="font-medium text-sm">{title}</p>
      <p className="mt-1 opacity-90">{body}</p>
    </div>
  );
}
