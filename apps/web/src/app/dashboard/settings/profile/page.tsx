"use client";

/**
 * Story 10.2: Profile Settings Page
 *
 * Allows users to view their account info, update display name,
 * and change their password.
 */

import { useState, useEffect, useCallback } from "react";
import {
  User,
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  Key,
  Shield,
  Droplet,
  UtensilsCrossed,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";
import {
  getCurrentUser,
  updateProfile,
  updateGlucoseUnit,
  updateMealIntelligence,
  changePassword,
  type CurrentUserResponse,
} from "@/lib/api";
import { unitLabel, type GlucoseUnit } from "@/lib/glucose-units";
import { useUserContext } from "@/providers";
import { OfflineBanner } from "@/components/ui/offline-banner";

const GLUCOSE_UNIT_OPTIONS: { value: GlucoseUnit; label: string; hint: string }[] =
  [
    { value: "mgdl", label: "mg/dL", hint: "US standard" },
    { value: "mmol", label: "mmol/L", hint: "International (UK, EU, AU)" },
  ];

const ROLE_LABELS: Record<string, string> = {
  diabetic: "Diabetic",
  caregiver: "Caregiver",
  admin: "Administrator",
};

export default function ProfilePage() {
  const [profile, setProfile] = useState<CurrentUserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isOffline, setIsOffline] = useState(false);

  // Display name form
  const [displayName, setDisplayName] = useState("");
  const [isSavingName, setIsSavingName] = useState(false);

  // Glucose display unit. Persists via the dedicated glucose-unit
  // endpoint and refreshes the shared user context so the dashboard re-renders.
  const { refreshUser } = useUserContext();
  const [isSavingUnit, setIsSavingUnit] = useState(false);

  // Meal-intelligence feature toggle. Persists via the dedicated endpoint and
  // refreshes the user context so the "Meals" nav appears/disappears.
  const [isSavingMeal, setIsSavingMeal] = useState(false);

  // Password form
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSavingPassword, setIsSavingPassword] = useState(false);

  // Auto-clear success message after 5 seconds
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const fetchProfile = useCallback(async () => {
    try {
      setError(null);
      const data = await getCurrentUser();
      setProfile(data);
      setDisplayName(data.display_name || "");
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  const handleUpdateName = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingName(true);
    setError(null);
    setSuccess(null);

    try {
      const updated = await updateProfile({
        display_name: displayName.trim() || null,
      });
      setProfile(updated);
      setDisplayName(updated.display_name || "");
      setSuccess("Display name updated successfully");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update display name"
      );
    } finally {
      setIsSavingName(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match");
      return;
    }

    setIsSavingPassword(true);
    setError(null);
    setSuccess(null);

    try {
      await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setSuccess("Password changed successfully");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setShowPasswordForm(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to change password"
      );
    } finally {
      setIsSavingPassword(false);
    }
  };

  const handleSelectUnit = async (unit: GlucoseUnit) => {
    if (!profile || (profile.glucose_unit ?? "mgdl") === unit || isSavingUnit)
      return;
    setIsSavingUnit(true);
    setError(null);
    setSuccess(null);
    try {
      await updateGlucoseUnit(unit);
      // Persisted. Update local state + report success BEFORE the best-effort
      // context refresh so a refresh failure never reads as a save failure.
      // Functional update so a concurrent profile change isn't clobbered.
      setProfile((prev) => (prev ? { ...prev, glucose_unit: unit } : prev));
      setSuccess(`Glucose unit set to ${unitLabel(unit)}`);
      // Propagate to the shared user context so display sites across the
      // dashboard switch units immediately. Best-effort: the unit is
      // already saved and will apply on the next load if this refresh fails.
      try {
        await refreshUser();
      } catch {
        // Non-fatal — the preference is persisted.
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update glucose unit"
      );
    } finally {
      setIsSavingUnit(false);
    }
  };

  const handleToggleMealIntelligence = async (enabled: boolean) => {
    if (
      !profile ||
      (profile.meal_intelligence_enabled ?? true) === enabled ||
      isSavingMeal
    )
      return;
    setIsSavingMeal(true);
    setError(null);
    setSuccess(null);
    try {
      await updateMealIntelligence(enabled);
      // Persisted. Update local state + report success BEFORE the best-effort
      // context refresh so a refresh failure never reads as a save failure.
      setProfile((prev) =>
        prev ? { ...prev, meal_intelligence_enabled: enabled } : prev
      );
      setSuccess(
        enabled ? "Meal Intelligence enabled" : "Meal Intelligence disabled"
      );
      // Propagate to the shared user context so the Meals nav (and meal
      // surfaces) appear/disappear immediately. Best-effort: already saved.
      try {
        await refreshUser();
      } catch {
        // Non-fatal — the preference is persisted.
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to update meal intelligence"
      );
    } finally {
      setIsSavingMeal(false);
    }
  };

  const nameHasChanges =
    profile !== null &&
    (displayName.trim() || null) !== (profile.display_name || null);

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
        <h1 className="text-2xl font-bold">Profile</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Manage your account and personal information
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner
          onRetry={fetchProfile}
          isRetrying={isLoading}
          message="Unable to connect to server. Profile management is unavailable."
        />
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
          aria-label="Loading profile"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading profile...</p>
        </div>
      )}

      {/* Account Information (read-only) */}
      {!isLoading && profile && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <Shield className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Account Information</h2>
              <p className="text-xs text-slate-500">
                Read-only account details
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-xs text-slate-500 mb-1">Email</p>
              <p className="text-sm text-slate-700 dark:text-slate-200 font-medium">
                {profile.email}
              </p>
            </div>
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-xs text-slate-500 mb-1">Role</p>
              <p className="text-sm text-slate-700 dark:text-slate-200 font-medium">
                {ROLE_LABELS[profile.role] || profile.role}
              </p>
            </div>
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-xs text-slate-500 mb-1">Account Created</p>
              <p className="text-sm text-slate-700 dark:text-slate-200 font-medium">
                {new Date(profile.created_at).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </p>
            </div>
            <div className="bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50">
              <p className="text-xs text-slate-500 mb-1">Account Status</p>
              <p className="text-sm font-medium">
                <span
                  className={
                    profile.is_active
                      ? "text-green-700 dark:text-green-400"
                      : "text-red-700 dark:text-red-400"
                  }
                >
                  {profile.is_active ? "Active" : "Inactive"}
                </span>
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Display Name (editable) */}
      {!isLoading && profile && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-green-500/10 rounded-lg">
              <User className="h-5 w-5 text-green-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Display Name</h2>
              <p className="text-xs text-slate-500">
                Set a name to personalize your experience
              </p>
            </div>
          </div>

          <form onSubmit={handleUpdateName} className="space-y-4">
            <div>
              <label
                htmlFor="display-name"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
              >
                Display Name
              </label>
              <input
                id="display-name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                disabled={isSavingName}
                maxLength={100}
                placeholder="Enter your display name"
                className={clsx(
                  "w-full rounded-lg border px-3 py-2 text-sm",
                  "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                  "placeholder:text-slate-500",
                  "focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
                aria-describedby="display-name-hint"
              />
              <p
                id="display-name-hint"
                className="text-xs text-slate-500 mt-1"
              >
                Optional. Max 100 characters.
              </p>
            </div>

            <button
              type="submit"
              disabled={isSavingName || !nameHasChanges || isOffline}
              title={isOffline ? "Cannot save while disconnected" : undefined}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-blue-600 text-white hover:bg-blue-500",
                "transition-colors",
                "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-blue-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isSavingName ? (
                <Loader2
                  className="h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Check className="h-4 w-4" aria-hidden="true" />
              )}
              {isSavingName ? "Saving..." : "Save Changes"}
            </button>
          </form>
        </div>
      )}

      {/* Glucose Display Unit */}
      {!isLoading && profile && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-sky-500/10 rounded-lg">
              <Droplet className="h-5 w-5 text-sky-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Glucose Display Unit</h2>
              <p className="text-xs text-slate-500">
                Choose how glucose values are shown across your dashboard
              </p>
            </div>
          </div>

          <div
            role="radiogroup"
            aria-label="Glucose display unit"
            className="grid grid-cols-2 gap-3 max-w-md"
          >
            {GLUCOSE_UNIT_OPTIONS.map((option) => {
              const isActive = (profile.glucose_unit ?? "mgdl") === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={isActive}
                  onClick={() => handleSelectUnit(option.value)}
                  disabled={isSavingUnit || isOffline}
                  title={
                    isOffline ? "Cannot change unit while disconnected" : undefined
                  }
                  className={clsx(
                    "flex flex-col items-start gap-0.5 rounded-lg border px-4 py-3 text-left",
                    "transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-sky-500",
                    "disabled:cursor-not-allowed disabled:opacity-60",
                    isActive
                      ? "border-sky-500 bg-sky-500/10"
                      : "border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700"
                  )}
                >
                  <span className="flex items-center gap-1.5 text-sm font-medium text-slate-800 dark:text-slate-100">
                    {isActive && (
                      <Check className="h-4 w-4 text-sky-500" aria-hidden="true" />
                    )}
                    {option.label}
                  </span>
                  <span className="text-xs text-slate-500">{option.hint}</span>
                </button>
              );
            })}
          </div>

          <p className="text-xs text-slate-500 mt-3 flex items-center gap-1.5">
            {isSavingUnit && (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            )}
            {isSavingUnit
              ? "Saving..."
              : "Your glucose data is always stored in mg/dL; this only changes how it is displayed."}
          </p>
        </div>
      )}

      {/* Meal Intelligence */}
      {!isLoading && profile && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-emerald-500/10 rounded-lg">
              <UtensilsCrossed className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Meal Intelligence</h2>
              <p className="text-xs text-slate-500">
                Estimate carbs from a meal photo and log meals
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between gap-4 max-w-md">
            <div>
              <label
                htmlFor="meal-intelligence-toggle"
                className="text-sm font-medium text-slate-600 dark:text-slate-300"
              >
                Enable Meal Intelligence
              </label>
              <p className="text-xs text-slate-500">
                Requires a vision-capable AI provider. Turning it on without one
                shows the feature, but carb estimates will be unavailable.
              </p>
            </div>
            <button
              id="meal-intelligence-toggle"
              type="button"
              role="switch"
              aria-checked={profile.meal_intelligence_enabled ?? true}
              onClick={() =>
                handleToggleMealIntelligence(
                  !(profile.meal_intelligence_enabled ?? true)
                )
              }
              disabled={isSavingMeal || isOffline}
              title={
                isOffline
                  ? "Cannot change this while disconnected"
                  : undefined
              }
              className={clsx(
                "relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent",
                "transition-colors duration-200 ease-in-out",
                "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-emerald-500",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                (profile.meal_intelligence_enabled ?? true)
                  ? "bg-emerald-600"
                  : "bg-slate-300 dark:bg-slate-700"
              )}
            >
              <span
                className={clsx(
                  "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-xs",
                  "transform transition duration-200 ease-in-out",
                  (profile.meal_intelligence_enabled ?? true)
                    ? "translate-x-5"
                    : "translate-x-0"
                )}
              />
            </button>
          </div>

          {isSavingMeal && (
            <p className="text-xs text-slate-500 mt-3 flex items-center gap-1.5">
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              Saving...
            </p>
          )}
        </div>
      )}

      {/* Password Change */}
      {!isLoading && profile && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-amber-500/10 rounded-lg">
              <Key className="h-5 w-5 text-amber-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Password</h2>
              <p className="text-xs text-slate-500">
                Change your account password
              </p>
            </div>
          </div>

          {!showPasswordForm ? (
            <button
              type="button"
              onClick={() => setShowPasswordForm(true)}
              disabled={isOffline}
              title={isOffline ? "Cannot change password while disconnected" : undefined}
              className={clsx(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                "transition-colors",
                "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-slate-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              <Key className="h-4 w-4" aria-hidden="true" />
              Change Password
            </button>
          ) : (
            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label
                  htmlFor="current-password"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Current Password
                </label>
                <input
                  id="current-password"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  disabled={isSavingPassword}
                  autoComplete="current-password"
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                />
              </div>

              <div>
                <label
                  htmlFor="new-password"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  New Password
                </label>
                <input
                  id="new-password"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={isSavingPassword}
                  autoComplete="new-password"
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  aria-describedby="password-hint"
                />
                <p id="password-hint" className="text-xs text-slate-500 mt-1">
                  Min 8 characters, must include uppercase, lowercase, and
                  number
                </p>
              </div>

              <div>
                <label
                  htmlFor="confirm-password"
                  className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                >
                  Confirm New Password
                </label>
                <input
                  id="confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={isSavingPassword}
                  autoComplete="new-password"
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 text-sm",
                    "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                />
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="submit"
                  disabled={
                    isSavingPassword ||
                    !currentPassword ||
                    !newPassword ||
                    !confirmPassword ||
                    isOffline
                  }
                  title={isOffline ? "Cannot change password while disconnected" : undefined}
                  className={clsx(
                    "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                    "bg-blue-600 text-white hover:bg-blue-500",
                    "transition-colors",
                    "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-blue-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  {isSavingPassword ? (
                    <Loader2
                      className="h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <Check className="h-4 w-4" aria-hidden="true" />
                  )}
                  {isSavingPassword ? "Changing..." : "Change Password"}
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setShowPasswordForm(false);
                    setCurrentPassword("");
                    setNewPassword("");
                    setConfirmPassword("");
                  }}
                  disabled={isSavingPassword}
                  className={clsx(
                    "px-4 py-2 rounded-lg text-sm font-medium",
                    "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700",
                    "transition-colors",
                    "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-slate-500",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
