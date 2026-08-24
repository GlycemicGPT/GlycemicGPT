"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/base";
import { DestructiveButton } from "@/components/DestructiveButton";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { HighlightButton } from "@/components/HighlightButton";
import { SecondaryButton } from "@/components/SecondaryButton";
import { formatUpdatedAgo } from "@/lib/format-updated-ago";
import { twMerge } from "@/lib/ui/twMerge";
import { ConnectionCollapsibleSection } from "./ConnectionCollapsibleSection";
import type {
  ConnectionInfoCalloutProps,
  ConnectionSettingsAccordionProps,
  ConnectionSettingsFormProps,
  ConnectionSettingsListProps,
  ConnectionSettingsStatus,
} from "./ConnectionSettings.types";

const CONNECTION_HEADER_GRID_CLASS_NAME =
  "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 sm:grid-cols-[minmax(13rem,1fr)_10rem_10rem] sm:gap-x-4";

const STATUS_LABEL: Record<ConnectionSettingsStatus, string> = {
  connected: "Connected",
  disconnected: "Not Connected",
  error: "Error",
  pending: "Pending",
};

const STATUS_CLASS: Record<ConnectionSettingsStatus, string> = {
  connected:
    "rounded-pill bg-signal-check-fill/20 px-2 py-0.5 text-signal-check-text",
  disconnected:
    "rounded-none bg-transparent px-0 py-0 text-foreground-secondary",
  error:
    "rounded-pill bg-signal-error-fill/20 px-2 py-0.5 text-signal-error-text",
  pending:
    "rounded-pill bg-signal-warning-fill/20 px-2 py-0.5 text-signal-warning-text",
};

function ConnectionStatusValue({
  status,
  statusLabel,
}: {
  status?: ConnectionSettingsStatus | null;
  statusLabel?: string;
}) {
  const effectiveStatus = status ?? "disconnected";

  return (
    <span
      className={twMerge(
        "font_metric_caption inline-flex justify-self-start",
        STATUS_CLASS[effectiveStatus],
      )}
    >
      {statusLabel ?? STATUS_LABEL[effectiveStatus]}
    </span>
  );
}

function ConnectionUpdatedAt({ timestamp }: { timestamp?: string | null }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!timestamp) return;

    setNow(Date.now());
    const interval = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(interval);
  }, [timestamp]);

  const label = formatUpdatedAgo(timestamp ?? null, now);
  const value = label ? label.replace(/^Updated /, "") : "-";

  return (
    <time
      className="font_metric_caption col-span-2 text-foreground-primary sm:col-span-1"
      dateTime={timestamp ?? undefined}
    >
      {value}
    </time>
  );
}

export function ConnectionSettingsList({
  children,
  className,
  ...props
}: ConnectionSettingsListProps) {
  return (
    <div {...props} className={twMerge("space-y-4", className)}>
      <div
        aria-hidden="true"
        className={twMerge(
          CONNECTION_HEADER_GRID_CLASS_NAME,
          "rounded-panel bg-surface-elevated px-4 py-2 pr-12 font_metric_caption uppercase text-foreground-primary",
        )}
      >
        <span className="pl-8">Source</span>
        <span>Status</span>
        <span className="col-span-2 sm:col-span-1">Updated</span>
      </div>
      {children}
    </div>
  );
}

export function ConnectionSettingsAccordion({
  children,
  defaultOpen = false,
  icon,
  name,
  status,
  statusLabel,
  updatedAt,
}: ConnectionSettingsAccordionProps) {
  return (
    <ConnectionCollapsibleSection
      defaultOpen={defaultOpen}
      headerContent={
        <div className={CONNECTION_HEADER_GRID_CLASS_NAME}>
          <span className="flex min-w-0 items-center gap-3">
            <Icon
              className="h-5 w-5 text-foreground-primary"
              decorative
              icon={icon}
            />
            <span className="truncate font_body_2 text-foreground-primary">
              {name}
            </span>
          </span>
          <ConnectionStatusValue status={status} statusLabel={statusLabel} />
          <ConnectionUpdatedAt timestamp={updatedAt} />
        </div>
      }
      title={name}
      variant="subsection"
    >
      {children}
    </ConnectionCollapsibleSection>
  );
}

export function ConnectionInfoCallout({
  children,
  className,
  icon = "lightbulb",
  iconSlot,
  title,
  ...props
}: ConnectionInfoCalloutProps) {
  return (
    <div
      {...props}
      className={twMerge(
        "rounded-panel border border-signal-info-fill bg-signal-info-fill/20 p-4",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {iconSlot ?? (
          <Icon
            className="h-5 w-5 shrink-0 text-signal-info-text"
            decorative
            icon={icon}
          />
        )}
        <p className="font_body_2 text-foreground-primary">{title}</p>
      </div>
      <div className="font_body_3 mt-2 text-foreground-primary">{children}</div>
    </div>
  );
}

export function ConnectionSettingsForm({
  actionsClassName,
  children,
  isOffline = false,
  isSubmitting,
  lastError,
  onDisconnect,
  onSubmit,
  status,
}: ConnectionSettingsFormProps) {
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isConfirmingDisconnect, setIsConfirmingDisconnect] = useState(false);
  const hasConnection = status != null && status !== "disconnected";
  const showSubmit = status !== "connected";
  const actionsDisabled = isSubmitting || isDisconnecting || isOffline;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await onSubmit();
    } catch {
      // Connection failures are surfaced through the integration response.
    }
  };

  const handleDisconnect = async () => {
    setIsDisconnecting(true);
    try {
      await onDisconnect();
    } finally {
      setIsDisconnecting(false);
      setIsConfirmingDisconnect(false);
    }
  };

  return (
    <div className="space-y-4">
      {lastError && status === "error" ? (
        <FeedbackMessage
          message={lastError}
          title="Connection error"
          variant="error"
        />
      ) : null}
      <form noValidate onSubmit={handleSubmit}>
        {children}
        <div
          className={twMerge(
            "mt-4 flex flex-wrap items-center gap-3",
            actionsClassName,
          )}
        >
          {showSubmit ? (
            <HighlightButton
              disabled={actionsDisabled}
              title={
                isOffline ? "Cannot connect while disconnected" : undefined
              }
              type="submit"
            >
              <Icon className="h-4 w-4" decorative icon="link" />
              {isSubmitting
                ? "Testing..."
                : hasConnection
                  ? "Update Credentials"
                  : "Test Connection"}
            </HighlightButton>
          ) : null}

          {hasConnection && !isConfirmingDisconnect ? (
            <DestructiveButton
              className="cursor-pointer"
              disabled={actionsDisabled}
              onClick={() => setIsConfirmingDisconnect(true)}
            >
              <Icon className="h-4 w-4" decorative icon="circle-slash" />
              Disconnect
            </DestructiveButton>
          ) : null}

          {hasConnection && isConfirmingDisconnect ? (
            <div className="flex flex-wrap items-center gap-2">
              <DestructiveButton
                className="cursor-pointer"
                disabled={actionsDisabled}
                onClick={handleDisconnect}
              >
                <Icon className="h-4 w-4" decorative icon="circle-slash" />
                {isDisconnecting ? "Disconnecting..." : "Yes, Disconnect"}
              </DestructiveButton>
              <SecondaryButton
                disabled={actionsDisabled}
                onClick={() => setIsConfirmingDisconnect(false)}
              >
                Cancel
              </SecondaryButton>
            </div>
          ) : null}
        </div>
      </form>
    </div>
  );
}
