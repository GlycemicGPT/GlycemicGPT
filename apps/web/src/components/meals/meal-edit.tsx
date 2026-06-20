"use client";

/**
 * Interactive meal-correction surfaces for the detail view, bringing the web app
 * to mobile parity with the two things a user does when the AI is wrong:
 *
 *  - {@link MealCorrectionSection} corrects the carb *range*.
 *  - {@link MealIdentitySection} confirms/corrects *what the food is*.
 *
 * These are deliberately TWO separate actions (the Story 50.H2 split between
 * fixing carbs and confirming identity): correcting carbs never touches identity,
 * and confirming identity is what opens external grounding. Both fix a
 * description of the food, never a dose -- the corrected values are never fed to
 * IoB / treatment_safety / carb-ratio math, and the never-dose framing is the
 * server-cleared `safety_qualifier`, rendered verbatim.
 */

import { useCallback, useId, useState } from "react";
import { Check, Loader2, Pencil, X } from "lucide-react";
import {
  confirmFoodIdentity,
  correctFoodRecord,
  MealApiError,
  type FoodRecord,
} from "@/lib/api";
import {
  CARB_GRAMS_MAX,
  CARB_GRAMS_MIN,
  effectiveCarbRange,
  parseCarbInputs,
  prefillIdentity,
} from "@/lib/meal-format";
import { MealSafetyQualifier } from "@/components/meals/meal-ui";

/**
 * The shared explainer that confirming a food's identity opens external
 * grounding. Rendered identically by the prompt and the editor, so it lives in
 * one place rather than being copy-pasted across the two branches.
 */
function IdentityGroundingExplainer() {
  return (
    <p
      data-testid="meal-identity-grounding-explainer"
      className="text-xs text-slate-500 dark:text-slate-400"
    >
      Confirming opens a lookup against authoritative nutrition data (USDA, Open
      Food Facts, or a restaurant’s published facts).
    </p>
  );
}

/** Map a correction failure to friendly copy; surfaces the server detail otherwise. */
function describeCorrectionError(err: unknown): string {
  if (err instanceof MealApiError) {
    if (err.status === 404) return "This meal no longer exists.";
    const detail = err.detail.toLowerCase();
    if (detail.includes("exceed")) {
      return "The low value must not exceed the high value.";
    }
    if (
      detail.includes("less than or equal") ||
      detail.includes("greater than or equal") ||
      detail.includes("bound above") ||
      detail.includes("bound below") ||
      detail.includes("range")
    ) {
      return "Enter carb values between 0 and 1000 grams.";
    }
    return err.detail || "Couldn't save that correction. Try again.";
  }
  return "Couldn't save that correction. Try again.";
}

/** Map an identity failure to friendly copy; surfaces the server detail otherwise. */
function describeIdentityError(err: unknown): string {
  if (err instanceof MealApiError) {
    if (err.status === 404) return "This meal no longer exists.";
    return err.detail || "Couldn't confirm that. Try again.";
  }
  return "Couldn't confirm that. Try again.";
}

interface SectionProps {
  record: FoodRecord;
  /** Called with the refreshed record so the detail view re-renders in place. */
  onUpdated: (record: FoodRecord) => void;
}

/**
 * Correct the carb range. Closed, it is a single "Correct carbs" button; open,
 * it is a low/high editor seeded from the current range. States plainly that the
 * correction never feeds dosing math and carries the server never-dose qualifier.
 */
export function MealCorrectionSection({ record, onUpdated }: SectionProps) {
  const range = effectiveCarbRange(record);
  const [editing, setEditing] = useState(false);
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();

  const open = useCallback(() => {
    // Seed from the currently-displayed range so a small fix is a couple of taps.
    setLow(String(Math.round(range.low)));
    setHigh(String(Math.round(range.high)));
    setError(null);
    setEditing(true);
  }, [range.low, range.high]);

  const cancel = useCallback(() => {
    setEditing(false);
    setError(null);
  }, []);

  const submit = useCallback(async () => {
    const parsed = parseCarbInputs(low, high);
    if (!parsed.ok) {
      setError(parsed.reason);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await correctFoodRecord(record.id, {
        corrected_carbs_low: parsed.low,
        corrected_carbs_high: parsed.high,
      });
      onUpdated(updated);
      setEditing(false);
    } catch (err) {
      setError(describeCorrectionError(err));
    } finally {
      setSaving(false);
    }
  }, [low, high, record.id, onUpdated]);

  if (!editing) {
    return (
      <button
        type="button"
        onClick={open}
        data-testid="meal-correct-button"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        <Pencil className="h-4 w-4" />
        Correct carbs
      </button>
    );
  }

  return (
    <div
      data-testid="meal-correction-editor"
      className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-5 space-y-4"
    >
      <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
        Correct the carb estimate (grams)
      </h2>
      <div className="flex gap-3">
        <label className="flex-1 text-xs text-slate-500 dark:text-slate-400">
          Low (g)
          <input
            type="number"
            inputMode="numeric"
            min={CARB_GRAMS_MIN}
            max={CARB_GRAMS_MAX}
            value={low}
            onChange={(e) => setLow(e.target.value)}
            data-testid="meal-correct-low"
            aria-invalid={!!error}
            aria-describedby={error ? errorId : undefined}
            className="mt-1 w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-white focus:border-blue-400 focus:outline-none"
          />
        </label>
        <label className="flex-1 text-xs text-slate-500 dark:text-slate-400">
          High (g)
          <input
            type="number"
            inputMode="numeric"
            min={CARB_GRAMS_MIN}
            max={CARB_GRAMS_MAX}
            value={high}
            onChange={(e) => setHigh(e.target.value)}
            data-testid="meal-correct-high"
            aria-invalid={!!error}
            aria-describedby={error ? errorId : undefined}
            className="mt-1 w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-white focus:border-blue-400 focus:outline-none"
          />
        </label>
      </div>

      {/* AC2: corrected values fix the record only -- they are decoupled from all
          dosing math, and the never-dose framing is the server-cleared qualifier. */}
      <p
        data-testid="meal-correct-decoupling"
        className="text-xs text-slate-500 dark:text-slate-400"
      >
        Correcting only updates this record — corrected values are never fed to
        IoB, treatment safety, or carb-ratio math.
      </p>
      <MealSafetyQualifier qualifier={record.safety_qualifier} />

      {error && (
        <p
          role="alert"
          id={errorId}
          data-testid="meal-correct-error"
          className="text-xs text-red-600 dark:text-red-400"
        >
          {error}
        </p>
      )}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={cancel}
          disabled={saving}
          data-testid="meal-correct-cancel"
          className="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={saving}
          data-testid="meal-correct-save"
          className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 transition-colors"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}

/**
 * Confirm or correct what the food is. Distinct from carb correction: this is
 * what opens external authoritative grounding (USDA / Open Food Facts /
 * restaurant facts) server-side, so a confident misidentification is never
 * certified with a citation. An own-history suggestion (when present) pre-fills
 * a one-click confirm.
 */
export function MealIdentitySection({ record, onUpdated }: SectionProps) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();

  const candidate = prefillIdentity(record);

  const openEditor = useCallback(() => {
    setName(candidate);
    setError(null);
    setEditing(true);
  }, [candidate]);

  const cancelEditor = useCallback(() => {
    setEditing(false);
    setError(null);
  }, []);

  const submit = useCallback(
    async (value: string) => {
      const trimmed = value.trim();
      if (!trimmed) {
        setError("Tell us what this food is.");
        return;
      }
      setSaving(true);
      setError(null);
      try {
        const updated = await confirmFoodIdentity(record.id, trimmed);
        onUpdated(updated);
        setEditing(false);
      } catch (err) {
        setError(describeIdentityError(err));
      } finally {
        setSaving(false);
      }
    },
    [record.id, onUpdated]
  );

  // Editing the free-text name (used for both "Correct" and "Change what this is").
  if (editing) {
    return (
      <div
        data-testid="meal-identity-editor"
        className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-5 space-y-4"
      >
        <label className="block text-xs text-slate-500 dark:text-slate-400">
          Food name
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="meal-identity-input"
            aria-invalid={!!error}
            aria-describedby={error ? errorId : undefined}
            className="mt-1 w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-white focus:border-blue-400 focus:outline-none"
          />
        </label>
        <IdentityGroundingExplainer />
        {error && (
          <p
            role="alert"
            id={errorId}
            data-testid="meal-identity-error"
            className="text-xs text-red-600 dark:text-red-400"
          >
            {error}
          </p>
        )}
        <div className="flex gap-3">
          <button
            type="button"
            onClick={cancelEditor}
            disabled={saving}
            data-testid="meal-identity-cancel"
            className="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => submit(name)}
            disabled={saving || !name.trim()}
            data-testid="meal-identity-save"
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 transition-colors"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {saving ? "Confirming…" : "Confirm"}
          </button>
        </div>
      </div>
    );
  }

  // Already confirmed: let the user change what it is (which re-opens grounding).
  if (record.identity_confirmed) {
    return (
      <div className="space-y-2">
        <p
          data-testid="meal-identity-confirmed-note"
          className="text-sm text-slate-600 dark:text-slate-300"
        >
          <Check className="inline h-4 w-4 text-emerald-600 dark:text-emerald-400" />{" "}
          You confirmed this food.
        </p>
        <button
          type="button"
          onClick={openEditor}
          data-testid="meal-identity-change"
          className="inline-flex items-center gap-1.5 text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          <Pencil className="h-4 w-4" />
          Change what this is
        </button>
      </div>
    );
  }

  // Not yet confirmed: prompt to confirm (opens grounding) or correct the name.
  return (
    <div
      data-testid="meal-identity-prompt"
      className="rounded-xl border border-blue-500/30 bg-blue-500/5 dark:bg-blue-500/10 p-5 space-y-3"
    >
      <p className="text-sm text-slate-900 dark:text-white">
        {record.suggested_identity ? (
          <>
            Looks like your saved “{record.suggested_identity}” — confirm?
          </>
        ) : (
          <>Confirm what this food is so we can ground it against real nutrition data.</>
        )}
      </p>
      <IdentityGroundingExplainer />
      {error && (
        <p
          role="alert"
          id={errorId}
          data-testid="meal-identity-error"
          className="text-xs text-red-600 dark:text-red-400"
        >
          {error}
        </p>
      )}
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => submit(candidate)}
          disabled={saving || !candidate}
          data-testid="meal-identity-confirm"
          className="inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 transition-colors"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {saving ? "Confirming…" : "Confirm"}
        </button>
        <button
          type="button"
          onClick={openEditor}
          disabled={saving}
          data-testid="meal-identity-correct"
          className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
        >
          <X className="h-4 w-4" />
          That’s not it
        </button>
      </div>
    </div>
  );
}
