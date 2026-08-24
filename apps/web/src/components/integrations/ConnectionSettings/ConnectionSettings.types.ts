import type { HTMLAttributes, ReactNode } from "react";
import type { IconName } from "@/base/Icon";

export type ConnectionSettingsStatus =
  "connected" | "disconnected" | "error" | "pending";

export type ConnectionSettingsListProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export type ConnectionSettingsAccordionProps = {
  children: ReactNode;
  defaultOpen?: boolean;
  icon: IconName;
  name: string;
  status?: ConnectionSettingsStatus | null;
  statusLabel?: string;
  updatedAt?: string | null;
};

export type ConnectionInfoCalloutProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  icon?: IconName;
  iconSlot?: ReactNode;
  title: ReactNode;
};

export type ConnectionSettingsFormProps = {
  actionsClassName?: string;
  children: ReactNode;
  isOffline?: boolean;
  isSubmitting: boolean;
  lastError?: string | null;
  onDisconnect: () => Promise<void>;
  onSubmit: () => Promise<void>;
  status?: ConnectionSettingsStatus | null;
};
