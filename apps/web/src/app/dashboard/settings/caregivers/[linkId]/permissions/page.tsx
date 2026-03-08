"use client";

/**
 * Story 8.2: Caregiver Permission Management
 *
 * Allows diabetic users to configure per-caregiver data access permissions.
 * Toggle switches control what data each caregiver can see.
 */

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  Shield,
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  Activity,
  BarChart3,
  Syringe,
  Brain,
  Bell,
} from "lucide-react";
import clsx from "clsx";
import {
  getCaregiverPermissions,
  updateCaregiverPermissions,
  listLinkedCaregivers,
  type CaregiverPermissions,
} from "@/lib/api";

interface PermissionToggle {
  key: keyof CaregiverPermissions;
  label: string;
  description: string;
  icon: typeof Activity;
  defaultValue: boolean;
}

const PERMISSION_TOGGLES: PermissionToggle[] = [
  {
    key: "can_view_glucose",
    label: "View current glucose",
    description: "See real-time glucose readings and trend",
    icon: Activity,
    defaultValue: true,
  },
  {
    key: "can_view_history",
    label: "View glucose history",
    description: "See historical glucose charts and data",
    icon: BarChart3,
    defaultValue: true,
  },
  {
    key: "can_view_iob",
    label: "View IoB/CoB data",
    description: "See insulin on board and carb data",
    icon: Syringe,
    defaultValue: true,
  },
  {
    key: "can_view_ai_suggestions",
    label: "View AI suggestions",
    description: "See AI-generated analysis and recommendations",
    icon: Brain,
    defaultValue: false,
  },
  {
    key: "can_receive_alerts",
    label: "Receive emergency alerts",
    description: "Get notified during glucose emergencies",
    icon: Bell,
    defaultValue: true,
  },
];

export default function CaregiverPermissionsPage() {
  const params = useParams();
  const linkId = params.linkId as string;

  const [permissions, setPermissions] = useState<CaregiverPermissions | null>(
    null
  );
  const [caregiverEmail, setCaregiverEmail] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);
  const [originalPermissions, setOriginalPermissions] =
    useState<CaregiverPermissions | null>(null);

  const fetchPermissions = useCallback(async () => {
    try {
      setError(null);
      const [permData, caregiversData] = await Promise.all([
        getCaregiverPermissions(linkId),
        listLinkedCaregivers(),
      ]);
      setPermissions(permData.permissions);
      setOriginalPermissions(permData.permissions);

      // Find the caregiver email from the linked caregivers list
      const caregiver = caregiversData.caregivers.find(
        (cg) => cg.link_id === linkId
      );
      if (caregiver) {
        setCaregiverEmail(caregiver.caregiver_email);
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to load permissions"
      );
    } finally {
      setIsLoading(false);
    }
  }, [linkId]);

  useEffect(() => {
    fetchPermissions();
  }, [fetchPermissions]);

  const handleToggle = (key: keyof CaregiverPermissions) => {
    if (!permissions || isSaving) return;

    const updated = { ...permissions, [key]: !permissions[key] };
    setPermissions(updated);
    setSuccess(null);

    // Check if there are unsaved changes
    if (originalPermissions) {
      const changed = Object.keys(updated).some(
        (k) =>
          updated[k as keyof CaregiverPermissions] !==
          originalPermissions[k as keyof CaregiverPermissions]
      );
      setHasChanges(changed);
    }
  };

  const handleSave = async () => {
    if (!permissions || !originalPermissions) return;

    setIsSaving(true);
    setError(null);
    setSuccess(null);

    // Only send changed fields
    const changes: Partial<CaregiverPermissions> = {};
    for (const key of Object.keys(permissions) as (keyof CaregiverPermissions)[]) {
      if (permissions[key] !== originalPermissions[key]) {
        changes[key] = permissions[key];
      }
    }

    try {
      const result = await updateCaregiverPermissions(linkId, changes);
      setPermissions(result.permissions);
      setOriginalPermissions(result.permissions);
      setHasChanges(false);
      setSuccess("Permissions updated successfully");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to update permissions"
      );
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <Link
            href="/dashboard/settings/caregivers"
            className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mb-2"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Caregivers
          </Link>
          <h1 className="text-2xl font-bold">Caregiver Permissions</h1>
        </div>
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading permissions"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading permissions...</p>
        </div>
      </div>
    );
  }

  if (error && !permissions) {
    return (
      <div className="space-y-6">
        <div>
          <Link
            href="/dashboard/settings/caregivers"
            className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mb-2"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Caregivers
          </Link>
          <h1 className="text-2xl font-bold">Caregiver Permissions</h1>
        </div>
        <div
          className="bg-red-500/10 rounded-xl p-6 border border-red-500/20 text-center"
          role="alert"
        >
          <AlertTriangle className="h-8 w-8 text-red-400 mx-auto mb-3" />
          <p className="text-red-400">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <Link
          href="/dashboard/settings/caregivers"
          className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mb-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Caregivers
        </Link>
        <h1 className="text-2xl font-bold">Caregiver Permissions</h1>
        {caregiverEmail && (
          <p className="text-slate-500 dark:text-slate-400">
            Configure data access for{" "}
            <span className="text-blue-400">{caregiverEmail}</span>
          </p>
        )}
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

      {/* Permission toggles */}
      {permissions && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <Shield className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Data Access</h2>
              <p className="text-xs text-slate-500">
                Control what this caregiver can see and receive
              </p>
            </div>
          </div>

          <div className="space-y-1">
            {PERMISSION_TOGGLES.map((toggle) => {
              const Icon = toggle.icon;
              const isEnabled = permissions[toggle.key];

              return (
                <div
                  key={toggle.key}
                  className={clsx(
                    "flex items-center justify-between py-3 px-2 rounded-lg hover:bg-slate-100/50 dark:hover:bg-slate-800/50 transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900",
                    isSaving
                      ? "opacity-50 cursor-not-allowed"
                      : "cursor-pointer"
                  )}
                  onClick={() => handleToggle(toggle.key)}
                  role="switch"
                  aria-checked={isEnabled}
                  aria-label={toggle.label}
                  aria-disabled={isSaving}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      handleToggle(toggle.key);
                    }
                  }}
                >
                  <div className="flex items-center gap-3">
                    <Icon
                      className={clsx(
                        "h-4 w-4 shrink-0",
                        isEnabled ? "text-blue-400" : "text-slate-600"
                      )}
                    />
                    <div>
                      <p className="text-sm font-medium text-slate-200">
                        {toggle.label}
                      </p>
                      <p className="text-xs text-slate-500">
                        {toggle.description}
                      </p>
                    </div>
                  </div>
                  <div
                    className={clsx(
                      "relative w-10 h-5 rounded-full transition-colors shrink-0 ml-4",
                      isEnabled ? "bg-blue-600" : "bg-slate-300 dark:bg-slate-700"
                    )}
                  >
                    <div
                      className={clsx(
                        "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform",
                        isEnabled ? "translate-x-5" : "translate-x-0.5"
                      )}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Save button */}
          <div className="mt-6 flex items-center gap-3">
            <button
              type="button"
              onClick={handleSave}
              disabled={!hasChanges || isSaving}
              className={clsx(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-blue-600 text-white hover:bg-blue-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              {isSaving ? "Saving..." : "Save Changes"}
            </button>
            {hasChanges && (
              <p className="text-xs text-slate-500">You have unsaved changes</p>
            )}
          </div>
        </div>
      )}

      {/* Info card */}
      <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
        <p className="text-xs text-slate-500">
          Changes take effect immediately after saving. Caregivers will only
          see data that you have enabled. Emergency alert permissions control
          whether this caregiver receives escalation notifications.
        </p>
      </div>
    </div>
  );
}
