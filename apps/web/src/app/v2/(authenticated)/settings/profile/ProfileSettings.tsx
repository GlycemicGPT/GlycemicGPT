"use client";

import { useState, useEffect, useCallback } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  getCurrentUser,
  updateProfile,
  updateGlucoseUnit,
  updateMealIntelligence,
  getSessionTimeout,
  updateSessionTimeout,
  changePassword,
  type CurrentUserResponse,
  type SessionTimeoutResponse,
} from "@/lib/api";
import { sessionTimeoutOptions, formatSessionTimeout } from "@/lib/session-timeout";
import { unitLabel, type GlucoseUnit } from "@/lib/glucose-units";
import { useUserContext } from "@/providers/user-provider";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { LoadingState } from "@/components/LoadingState";
import { SaveButton, type SaveButtonState } from "@/components/SaveButton";
import { SelectField } from "@/components/SelectField";
import { StatusBadge } from "@/components/StatusBadge";
import { Switch } from "@/components/Switch";
import { TextInput } from "@/components/TextInput";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { PageHeader } from "@/components/PageHeader";
import { SettingsReadOnlyValue } from "@/components/settings/SettingsReadOnlyValue";
import { SettingsRow } from "@/components/settings/SettingsRow";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { settingsPageIcons } from "@/components/settings/settings-navigation";
import { useNotifications } from "@/compositions/NotificationsProvider";

import {
  displayNameSchema,
  getDisplayNameValidationErrors,
} from "./displayNameSchema";
import {
  getPasswordValidationErrors,
  passwordSchema,
  type PasswordField,
  type PasswordFormValues,
  type PasswordValidationErrors,
} from "./passwordSchema";

const GLUCOSE_UNIT_OPTIONS: {
  value: GlucoseUnit;
  label: string;
  hint: string;
}[] = [
  { value: "mgdl", label: "mg/dL", hint: "US standard" },
  { value: "mmol", label: "mmol/L", hint: "International (UK, EU, AU)" },
];

const ROLE_LABELS: Record<string, string> = {
  diabetic: "Diabetic",
  caregiver: "Caregiver",
  admin: "Administrator",
};

export type ProfileSettingsSection = "account" | "glucose" | "meal";

export interface ProfilePageProps {
  embedded?: boolean;
  preferenceLabelAs?: "h2" | "p";
  sections?: readonly ProfileSettingsSection[];
  spaciousSections?: boolean;
}

const DEFAULT_SECTIONS: readonly ProfileSettingsSection[] = ["account"];

const EMPTY_PASSWORD_ERRORS: PasswordValidationErrors = {
  confirmPassword: [],
  currentPassword: [],
  newPassword: [],
};

function isCurrentPasswordError(message: string): boolean {
  return /current password/i.test(message);
}

export function ProfileSettings({
  embedded = false,
  preferenceLabelAs = "p",
  sections = DEFAULT_SECTIONS,
  spaciousSections = false,
}: ProfilePageProps = {}) {
  const pathname = usePathname();
  const router = useRouter();
  const [profile, setProfile] = useState<CurrentUserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isOffline, setIsOffline] = useState(false);

  // Display name form
  const [displayName, setDisplayName] = useState("");
  const [displayNameErrors, setDisplayNameErrors] = useState<string[]>([]);
  const [hasAttemptedDisplayNameSave, setHasAttemptedDisplayNameSave] =
    useState(false);
  const [displayNameSaveState, setDisplayNameSaveState] =
    useState<SaveButtonState>("idle");

  // Glucose display unit. Persists via the dedicated glucose-unit
  // endpoint and refreshes the shared user context so the dashboard re-renders.
  const { refreshUser } = useUserContext();
  const { notifySuccess } = useNotifications();
  const [isSavingUnit, setIsSavingUnit] = useState(false);

  // Meal-intelligence feature toggle. Persists via the dedicated endpoint and
  // refreshes the user context so the "Meals" nav appears/disappears.
  const [isSavingMeal, setIsSavingMeal] = useState(false);

  // Web-session length. Absolute lifetime (minutes) fetched from its dedicated
  // endpoint; a change applies at the user's next sign-in, so no context
  // refresh is needed. `null` until loaded (only fetched for the account view).
  const [sessionTimeout, setSessionTimeout] =
    useState<SessionTimeoutResponse | null>(null);
  const sessionMinutes = sessionTimeout?.minutes ?? null;
  const sessionLengthOptions = sessionTimeoutOptions(sessionTimeout);
  const [isSavingSession, setIsSavingSession] = useState(false);

  // Password form
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordErrors, setPasswordErrors] =
    useState<PasswordValidationErrors>(EMPTY_PASSWORD_ERRORS);
  const [currentPasswordServerError, setCurrentPasswordServerError] = useState<
    string | null
  >(null);
  const [passwordSaveState, setPasswordSaveState] =
    useState<SaveButtonState>("idle");
  const isSavingPassword = passwordSaveState === "saving";

  // Auto-clear success message after 5 seconds
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const fetchProfile = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await getCurrentUser();
      setProfile(data);
      setDisplayName(data.display_name || "");
      setDisplayNameErrors([]);
      setHasAttemptedDisplayNameSave(false);
      setDisplayNameSaveState("idle");
      setIsOffline(false);
    } catch (err) {
      if (err instanceof Error && err.message.includes("401")) {
        router.replace(
          `/login?expired=true&redirect=${encodeURIComponent(pathname)}`,
        );
        return;
      }
      setIsOffline(true);
    } finally {
      setIsLoading(false);
    }
  }, [pathname, router]);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  // Session length only renders in the account view; fetch it there so other
  // embeds (glucose/meal) don't make a needless request. Best-effort: a failure
  // just leaves the control unrendered rather than blocking the page.
  const showsSessionLength = sections.includes("account");
  useEffect(() => {
    if (!showsSessionLength) return;
    let cancelled = false;
    getSessionTimeout()
      .then((data) => {
        if (!cancelled) setSessionTimeout(data);
      })
      .catch(() => {
        // Non-fatal — the control simply doesn't appear.
      });
    return () => {
      cancelled = true;
    };
  }, [showsSessionLength]);

  // The Session section renders only once its preference has loaded; while it is
  // absent (still loading, or a failed best-effort fetch) the Password section
  // is the last one on the account page and must keep the bottom scroll-spacer
  // itself, so it is never obscured at the bottom of the viewport.
  const sessionSectionVisible =
    showsSessionLength &&
    !isLoading &&
    profile !== null &&
    sessionMinutes !== null;

  const handleUpdateName = async (e: React.FormEvent) => {
    e.preventDefault();
    setHasAttemptedDisplayNameSave(true);
    setError(null);
    setSuccess(null);

    const validationResult = displayNameSchema.safeParse(displayName);
    if (!validationResult.success) {
      setDisplayNameSaveState("idle");
      setDisplayNameErrors(getDisplayNameValidationErrors(displayName));
      return;
    }

    setDisplayNameSaveState("saving");
    setDisplayNameErrors([]);

    try {
      const updated = await updateProfile({
        display_name: validationResult.data || null,
      });
      setProfile(updated);
      setDisplayName(updated.display_name || "");
      setHasAttemptedDisplayNameSave(false);
      setDisplayNameSaveState("saved");
      try {
        await refreshUser();
      } catch {
        // Non-fatal: the display name is persisted and applies on the next load.
      }
    } catch (err) {
      setDisplayNameSaveState("idle");
      setDisplayNameErrors([
        err instanceof Error ? err.message : "Failed to update display name",
      ]);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    const validationResult = passwordSchema.safeParse({
      confirmPassword,
      currentPassword,
      newPassword,
    });

    if (!validationResult.success) {
      setPasswordErrors(
        getPasswordValidationErrors({
          confirmPassword,
          currentPassword,
          newPassword,
        }),
      );
      return;
    }

    setPasswordSaveState("saving");
    setPasswordErrors(EMPTY_PASSWORD_ERRORS);
    setCurrentPasswordServerError(null);
    setError(null);
    setSuccess(null);

    try {
      await changePassword({
        current_password: validationResult.data.currentPassword,
        new_password: validationResult.data.newPassword,
      });
      setPasswordSaveState("saved");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordErrors(EMPTY_PASSWORD_ERRORS);
      setCurrentPasswordServerError(null);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to change password";

      setPasswordSaveState("idle");
      if (isCurrentPasswordError(message)) {
        setCurrentPasswordServerError(message);
      } else {
        setError(message);
      }
    }
  };

  const handlePasswordFieldChange = (field: PasswordField, value: string) => {
    const nextValues: PasswordFormValues = {
      confirmPassword: field === "confirmPassword" ? value : confirmPassword,
      currentPassword: field === "currentPassword" ? value : currentPassword,
      newPassword: field === "newPassword" ? value : newPassword,
    };
    const currentValidationErrors = getPasswordValidationErrors(nextValues);

    setPasswordSaveState("idle");
    if (field === "confirmPassword") {
      setConfirmPassword(value);
    } else if (field === "currentPassword") {
      setCurrentPassword(value);
      setCurrentPasswordServerError(null);
    } else {
      setNewPassword(value);
    }

    setPasswordErrors((visibleErrors) => ({
      confirmPassword: visibleErrors.confirmPassword.filter((error) =>
        currentValidationErrors.confirmPassword.includes(error),
      ),
      currentPassword: visibleErrors.currentPassword.filter((error) =>
        currentValidationErrors.currentPassword.includes(error),
      ),
      newPassword: visibleErrors.newPassword.filter((error) =>
        currentValidationErrors.newPassword.includes(error),
      ),
    }));
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
        err instanceof Error ? err.message : "Failed to update glucose unit",
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
      // Persisted. Update local state + notify success BEFORE the best-effort
      // context refresh so a refresh failure never reads as a save failure.
      setProfile((prev) =>
        prev ? { ...prev, meal_intelligence_enabled: enabled } : prev,
      );
      notifySuccess(
        enabled ? "Meal Intelligence enabled" : "Meal Intelligence disabled",
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
          : "Failed to update meal intelligence",
      );
    } finally {
      setIsSavingMeal(false);
    }
  };

  const handleSelectSessionLength = async (minutes: number) => {
    if (sessionMinutes === null || sessionMinutes === minutes || isSavingSession)
      return;
    setIsSavingSession(true);
    setError(null);
    setSuccess(null);
    try {
      const updated = await updateSessionTimeout(minutes);
      // Persisted. It applies at the next sign-in, so there's no context to
      // refresh -- just reflect the saved value and confirm.
      setSessionTimeout(updated);
      const label = formatSessionTimeout(updated.minutes);
      notifySuccess(`Session length set to ${label}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update session length",
      );
    } finally {
      setIsSavingSession(false);
    }
  };

  const nameHasChanges =
    profile !== null &&
    (displayName.trim() || null) !== (profile.display_name || null);

  const showsAccount = sections.includes("account");
  const showsGlucose = sections.includes("glucose");
  const showsMeal = sections.includes("meal");

  const preferenceRows =
    !isLoading && profile ? (
      <div className="space-y-8">
        {showsGlucose ? (
          <SettingsRow
            control={
              <SelectField
                disabled={isSavingUnit || isOffline}
                helperText={
                  isSavingUnit
                    ? "Saving..."
                    : "Glucose data remains stored in mg/dL."
                }
                id="glucose-display-unit"
                label="Glucose display unit"
                onChange={(event) =>
                  void handleSelectUnit(event.target.value as GlucoseUnit)
                }
                options={GLUCOSE_UNIT_OPTIONS.map((option) => ({
                  label: `${option.label}, ${option.hint}`,
                  value: option.value,
                }))}
                title={
                  isOffline
                    ? "Cannot change unit while disconnected"
                    : undefined
                }
                value={profile.glucose_unit ?? "mgdl"}
                visuallyHideLabel
              />
            }
            description="Choose how glucose values are shown across your dashboard."
            label="Glucose display unit"
            labelAs={preferenceLabelAs}
          />
        ) : null}

        {showsMeal ? (
          <SettingsRow
            control={
              <div className="space-y-2 md:flex md:justify-end">
                <Switch
                  checked={profile.meal_intelligence_enabled ?? true}
                  disabled={isSavingMeal || isOffline}
                  id="meal-intelligence-toggle"
                  label="Enable Meal Intelligence"
                  onCheckedChange={handleToggleMealIntelligence}
                  title={
                    isOffline
                      ? "Cannot change this while disconnected"
                      : undefined
                  }
                  visuallyHideLabel
                />
                {isSavingMeal ? (
                  <p
                    aria-live="polite"
                    className="font_body_3 text-foreground-secondary md:ml-3"
                  >
                    Saving...
                  </p>
                ) : null}
              </div>
            }
            description="Estimate carbs from meal photos and log meals. A vision capable AI provider is required for carb estimates."
            label="Meal Intelligence"
            labelAs={preferenceLabelAs}
          />
        ) : null}
      </div>
    ) : null;

  const content = (
    <>
      {isOffline && (
        <FeedbackMessage
          actionDisabled={isLoading}
          actionLabel={isLoading ? "Retrying..." : "Retry connection"}
          message="Unable to connect to server. Profile management is unavailable."
          onAction={fetchProfile}
          title="Offline"
          variant="offline"
        />
      )}

      {error && (
        <FeedbackMessage
          message={error}
          title="Could not save"
          variant="error"
        />
      )}

      {success && (
        <FeedbackMessage message={success} title="Saved" variant="success" />
      )}

      {isLoading && <LoadingState label="Loading profile..." />}

      {showsAccount && !isLoading && profile && (
        <div className="rounded-panel bg-surface-elevated p-6">
          <dl className="grid gap-6 sm:grid-cols-2">
            <SettingsReadOnlyValue
              label="Email"
              labelClassName="text-foreground-primary"
              value={profile.email}
            />
            <SettingsReadOnlyValue
              label="Role"
              labelClassName="text-foreground-primary"
              value={ROLE_LABELS[profile.role] || profile.role}
            />
            <SettingsReadOnlyValue
              label="Account created"
              labelClassName="text-foreground-primary"
              value={new Date(profile.created_at).toLocaleDateString(
                undefined,
                {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                },
              )}
            />
            <SettingsReadOnlyValue
              label="Account status"
              labelClassName="text-foreground-primary"
              value={
                <StatusBadge variant={profile.is_active ? "success" : "error"}>
                  {profile.is_active ? "Active" : "Inactive"}
                </StatusBadge>
              }
            />
          </dl>
        </div>
      )}

      {showsAccount && !isLoading && profile && (
        <SettingsSection
          className={spaciousSections ? "before:-top-16" : undefined}
          separated
          title="Personal Information"
        >
          <form className="max-w-md space-y-4" onSubmit={handleUpdateName}>
            <TextInput
              disabled={displayNameSaveState === "saving"}
              errorMessages={displayNameErrors}
              id="display-name"
              label="Display Name"
              onChange={(event) => {
                const nextDisplayName = event.target.value;
                setDisplayName(nextDisplayName);
                if (hasAttemptedDisplayNameSave) {
                  const currentValidationErrors =
                    getDisplayNameValidationErrors(nextDisplayName);
                  const remainingVisibleErrors = displayNameErrors.filter(
                    (visibleError) =>
                      currentValidationErrors.includes(visibleError),
                  );
                  setDisplayNameErrors(remainingVisibleErrors);
                  if (remainingVisibleErrors.length === 0) {
                    setHasAttemptedDisplayNameSave(false);
                  }
                } else {
                  setDisplayNameErrors([]);
                }
                setDisplayNameSaveState("idle");
              }}
              optionalText="Optional"
              placeholder="Enter your display name"
              value={displayName}
            />
            <SaveButton
              disabled={!nameHasChanges || isOffline}
              state={displayNameSaveState}
              title={isOffline ? "Cannot save while disconnected" : undefined}
            />
          </form>
        </SettingsSection>
      )}

      {(showsGlucose || showsMeal) &&
        preferenceRows &&
        (embedded ? (
          preferenceRows
        ) : (
          <SettingsSection separated title="Preferences">
            {preferenceRows}
          </SettingsSection>
        ))}

      {showsAccount && !isLoading && profile && (
        <SettingsSection
          // Owns the bottom scroll-spacer only when Session (which follows it)
          // isn't rendered — otherwise Password would be the last section with
          // no breathing room below it.
          className={
            sessionSectionVisible
              ? spaciousSections
                ? "before:-top-16"
                : undefined
              : spaciousSections
                ? "pb-[40vh] before:-top-16"
                : "pb-[40vh]"
          }
          description="Use a strong password that you do not reuse elsewhere."
          separated
          title="Password"
        >
          <form className="max-w-md space-y-4" onSubmit={handleChangePassword}>
            <TextInput
              autoComplete="current-password"
              disabled={isSavingPassword || isOffline}
              errorMessages={[
                ...passwordErrors.currentPassword,
                ...(currentPasswordServerError
                  ? [currentPasswordServerError]
                  : []),
              ]}
              id="current-password"
              label="Current Password"
              onChange={(event) =>
                handlePasswordFieldChange("currentPassword", event.target.value)
              }
              type="password"
              value={currentPassword}
            />
            <TextInput
              autoComplete="new-password"
              disabled={isSavingPassword || isOffline}
              errorMessages={passwordErrors.newPassword}
              id="new-password"
              label="New Password"
              onChange={(event) =>
                handlePasswordFieldChange("newPassword", event.target.value)
              }
              type="password"
              value={newPassword}
            />
            <TextInput
              autoComplete="new-password"
              disabled={isSavingPassword || isOffline}
              errorMessages={passwordErrors.confirmPassword}
              id="confirm-password"
              label="Confirm New Password"
              onChange={(event) =>
                handlePasswordFieldChange("confirmPassword", event.target.value)
              }
              type="password"
              value={confirmPassword}
            />

            <SaveButton
              disabled={
                isSavingPassword ||
                !currentPassword ||
                !newPassword ||
                !confirmPassword ||
                isOffline
              }
              title={
                isOffline
                  ? "Cannot change password while disconnected"
                  : undefined
              }
              label="Change Password"
              savedLabel="Password Changed"
              savingLabel="Changing..."
              state={passwordSaveState}
            />
          </form>
        </SettingsSection>
      )}

      {sessionSectionVisible && (
        <SettingsSection
          // Last section on the account page when it renders: carries the bottom
          // scroll-spacer so the page has breathing room below it. When it is
          // absent, the Password section above takes the spacer instead.
          className={
            spaciousSections ? "pb-[40vh] before:-top-16" : "pb-[40vh]"
          }
          separated
          title="Session"
        >
          <SettingsRow
            control={
              <SelectField
                disabled={isSavingSession || isOffline}
                helperText={
                  isSavingSession
                    ? "Saving..."
                    : "Applies the next time you sign in."
                }
                id="session-length"
                label="Session length"
                onChange={(event) =>
                  void handleSelectSessionLength(Number(event.target.value))
                }
                options={sessionLengthOptions.map((option) => ({
                  label: option.label,
                  value: String(option.value),
                }))}
                title={
                  isOffline
                    ? "Cannot change session length while disconnected"
                    : undefined
                }
                value={String(sessionMinutes)}
                visuallyHideLabel
              />
            }
            description="How long you stay signed in on this device before you have to sign in again."
            label="Session length"
            labelAs={preferenceLabelAs}
          />
        </SettingsSection>
      )}
    </>
  );

  if (embedded) {
    return <div className="space-y-6">{content}</div>;
  }

  return (
    <SettingsPage>
      <PageHeader
        description="Manage your account information and security."
        icon={settingsPageIcons.account}
        title="Account"
      />
      {spaciousSections ? <div className="space-y-32">{content}</div> : content}
    </SettingsPage>
  );
}

export default function ProfilePage() {
  return <ProfileSettings />;
}
