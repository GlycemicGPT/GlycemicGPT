"use client";

/**
 * Stories 8.1 & 8.2: Caregiver Invitation Management & Permissions
 *
 * Allows diabetic users to create, view, and revoke caregiver invitations.
 * Also shows linked caregivers with a link to manage their data permissions.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  UserPlus,
  Plus,
  Loader2,
  AlertTriangle,
  Check,
  Copy,
  X,
  ArrowLeft,
  Clock,
  CheckCircle,
  XCircle,
  Shield,
  Settings2,
} from "lucide-react";
import clsx from "clsx";
import {
  listCaregiverInvitations,
  createCaregiverInvitation,
  revokeCaregiverInvitation,
  listLinkedCaregivers,
  type CaregiverInvitationListItem,
  type LinkedCaregiverItem,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

const STATUS_CONFIG: Record<
  string,
  { label: string; className: string; icon: typeof Clock }
> = {
  pending: {
    label: "Pending",
    className: "bg-yellow-500/20 text-yellow-400",
    icon: Clock,
  },
  accepted: {
    label: "Accepted",
    className: "bg-green-500/20 text-green-400",
    icon: CheckCircle,
  },
  expired: {
    label: "Expired",
    className: "bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400",
    icon: XCircle,
  },
  revoked: {
    label: "Revoked",
    className: "bg-red-500/20 text-red-400",
    icon: X,
  },
};

export default function CaregiversPage() {
  const [invitations, setInvitations] = useState<
    CaregiverInvitationListItem[]
  >([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null);
  const [newInviteUrl, setNewInviteUrl] = useState<string | null>(null);
  const [linkedCaregivers, setLinkedCaregivers] = useState<LinkedCaregiverItem[]>([]);

  const fetchInvitations = useCallback(async () => {
    try {
      setError(null);
      const data = await listCaregiverInvitations();
      setInvitations(data.invitations);
      setIsOffline(false);
    } catch (err) {
      if (!(err instanceof Error && err.message.includes("401"))) {
        setIsOffline(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchLinkedCaregivers = useCallback(async () => {
    try {
      const data = await listLinkedCaregivers();
      setLinkedCaregivers(data.caregivers);
    } catch {
      // Non-critical: linked caregivers section is supplementary.
      // 401/fetch failures are expected when API is down.
    }
  }, []);

  useEffect(() => {
    fetchInvitations();
    fetchLinkedCaregivers();
  }, [fetchInvitations, fetchLinkedCaregivers]);

  const handleCreate = async () => {
    setIsCreating(true);
    setError(null);
    setSuccess(null);
    setNewInviteUrl(null);

    try {
      const invitation = await createCaregiverInvitation();
      setNewInviteUrl(invitation.invite_url);
      setSuccess("Invitation created! Share the link below with your caregiver.");
      await fetchInvitations();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create invitation"
      );
    } finally {
      setIsCreating(false);
    }
  };

  const handleRevoke = async (id: string) => {
    if (
      !window.confirm(
        "Revoke this invitation? The caregiver will no longer be able to use this link."
      )
    ) {
      return;
    }

    setRevokingId(id);
    setError(null);
    setSuccess(null);

    try {
      await revokeCaregiverInvitation(id);
      setSuccess("Invitation revoked");
      await fetchInvitations();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to revoke invitation"
      );
    } finally {
      setRevokingId(null);
    }
  };

  const handleCopy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedUrl(url);
      setTimeout(() => setCopiedUrl(null), 2000);
    } catch {
      setError("Failed to copy to clipboard");
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  const pendingCount = invitations.filter((i) => i.status === "pending").length;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <a
          href="/dashboard/settings"
          className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mb-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </a>
        <h1 className="text-2xl font-bold">Caregiver Access</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Invite caregivers to monitor your glucose data via Telegram
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner
          onRetry={fetchInvitations}
          isRetrying={isLoading}
          message="Unable to connect to server. Caregiver management is unavailable."
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

      {/* New invite URL */}
      {newInviteUrl && (
        <div className="bg-blue-500/10 rounded-xl p-4 border border-blue-500/20">
          <p className="text-sm text-blue-400 mb-2">
            Share this link with your caregiver:
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-slate-100 dark:bg-slate-800 rounded px-3 py-2 text-sm text-slate-900 dark:text-slate-200 overflow-x-auto">
              {newInviteUrl}
            </code>
            <button
              type="button"
              onClick={() => handleCopy(newInviteUrl)}
              className="shrink-0 p-2 rounded-lg bg-blue-600 text-white hover:bg-blue-500 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              aria-label="Copy invite link"
            >
              {copiedUrl === newInviteUrl ? (
                <Check className="h-4 w-4" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </button>
          </div>
          <p className="text-xs text-slate-500 mt-2">
            This link expires in 7 days. The caregiver will create an account
            using this link.
          </p>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading invitations"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading invitations...</p>
        </div>
      )}

      {/* Invitations list */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <UserPlus className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Invitations</h2>
              <p className="text-xs text-slate-500">
                {pendingCount} pending,{" "}
                {invitations.filter((i) => i.status === "accepted").length}{" "}
                accepted
              </p>
            </div>
          </div>

          {invitations.length === 0 && (
            <div className="text-center py-8">
              <UserPlus className="h-10 w-10 text-slate-600 mx-auto mb-3" />
              <p className="text-slate-500 dark:text-slate-400 mb-1">No invitations yet</p>
              <p className="text-xs text-slate-500">
                Create an invitation to give a caregiver access to your
                glucose data
              </p>
            </div>
          )}

          {invitations.length > 0 && (
            <div className="space-y-3 mb-4">
              {invitations.map((inv) => {
                const config = STATUS_CONFIG[inv.status] || STATUS_CONFIG.pending;
                const StatusIcon = config.icon;
                return (
                  <div
                    key={inv.id}
                    className="flex items-center justify-between bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <StatusIcon className="h-4 w-4 shrink-0" />
                        <span
                          className={clsx(
                            "text-xs px-2 py-0.5 rounded-full",
                            config.className
                          )}
                        >
                          {config.label}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                        Created {formatDate(inv.created_at)} &middot; Expires{" "}
                        {formatDate(inv.expires_at)}
                      </div>
                      {inv.accepted_by_email && (
                        <div className="text-xs text-green-400 mt-1">
                          Accepted by {inv.accepted_by_email}
                        </div>
                      )}
                    </div>
                    {inv.status === "pending" && (
                      <button
                        type="button"
                        onClick={() => handleRevoke(inv.id)}
                        disabled={revokingId === inv.id || isOffline}
                        className="shrink-0 ml-3 p-2 rounded-lg text-slate-500 dark:text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50 disabled:cursor-not-allowed"
                        aria-label="Revoke invitation"
                      >
                        {revokingId === inv.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <X className="h-4 w-4" />
                        )}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Create button */}
          {pendingCount < 10 && (
            <button
              type="button"
              onClick={handleCreate}
              disabled={isCreating || isOffline}
              title={isOffline ? "Cannot create invitations while disconnected" : undefined}
              className={clsx(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium",
                "bg-blue-600 text-white hover:bg-blue-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isCreating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              {isCreating ? "Creating..." : "Create Invitation"}
            </button>
          )}

          {pendingCount >= 10 && (
            <p className="text-xs text-slate-500">
              Maximum of 10 pending invitations reached
            </p>
          )}
        </div>
      )}

      {/* Linked Caregivers section (Story 8.2) */}
      {linkedCaregivers.length > 0 && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-green-500/10 rounded-lg">
              <Shield className="h-5 w-5 text-green-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Linked Caregivers</h2>
              <p className="text-xs text-slate-500">
                {linkedCaregivers.length} caregiver{linkedCaregivers.length !== 1 ? "s" : ""} linked
              </p>
            </div>
          </div>

          <div className="space-y-3">
            {linkedCaregivers.map((cg) => {
              const permCount = [
                cg.permissions.can_view_glucose,
                cg.permissions.can_view_history,
                cg.permissions.can_view_iob,
                cg.permissions.can_view_ai_suggestions,
                cg.permissions.can_receive_alerts,
              ].filter(Boolean).length;

              return (
                <div
                  key={cg.link_id}
                  className="flex items-center justify-between bg-slate-100/50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-300/50 dark:border-slate-700/50"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-900 dark:text-slate-200 truncate">
                      {cg.caregiver_email}
                    </p>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Linked {new Date(cg.linked_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                      {" "}&middot;{" "}
                      {permCount}/5 permissions enabled
                    </p>
                  </div>
                  <Link
                    href={`/dashboard/settings/caregivers/${cg.link_id}/permissions`}
                    className="shrink-0 ml-3 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-300 bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  >
                    <Settings2 className="h-3.5 w-3.5" />
                    Permissions
                  </Link>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Info card */}
      <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
        <h3 className="text-sm font-medium text-slate-600 dark:text-slate-300 mb-2">
          How it works
        </h3>
        <ol className="text-xs text-slate-500 space-y-1 list-decimal list-inside">
          <li>Create an invitation to generate a unique link</li>
          <li>Share the link with your caregiver</li>
          <li>They create an account using the link</li>
          <li>
            Once linked, they can check your glucose via Telegram bot
          </li>
        </ol>
      </div>
    </div>
  );
}
