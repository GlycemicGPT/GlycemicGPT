"use client";

import { Radio } from "lucide-react";
import clsx from "clsx";
import type { IntegrationResponse } from "@/lib/api";
import { CollapsibleSection } from "@/components/ui/collapsible-section";
import {
  IntegrationCard,
  PasswordInput,
  StatusBadge,
} from "./integration-card";

interface CGMIntegrationsSectionProps {
  dexcom: IntegrationResponse | null;
  dexcomEmail: string;
  dexcomPassword: string;
  isDexcomConnecting: boolean;
  isOffline: boolean;
  onDexcomEmailChange: (value: string) => void;
  onDexcomPasswordChange: (value: string) => void;
  onConnectDexcom: () => Promise<void>;
  onDisconnectDexcom: () => Promise<void>;
}

export function CGMIntegrationsSection({
  dexcom,
  dexcomEmail,
  dexcomPassword,
  isDexcomConnecting,
  isOffline,
  onDexcomEmailChange,
  onDexcomPasswordChange,
  onConnectDexcom,
  onDisconnectDexcom,
}: CGMIntegrationsSectionProps) {
  return (
    <CollapsibleSection title="CGM Integrations" icon={Radio}>
      <div className="space-y-4">
        <CollapsibleSection
          title="Dexcom"
          variant="subsection"
          badge={<StatusBadge status={dexcom?.status ?? null} />}
        >
          <IntegrationCard
            title="Dexcom G7"
            description="Connect your Dexcom account to sync continuous glucose monitor data"
            status={dexcom?.status ?? null}
            lastSyncAt={dexcom?.last_sync_at ?? null}
            lastError={dexcom?.last_error ?? null}
            onConnect={onConnectDexcom}
            onDisconnect={onDisconnectDexcom}
            isConnecting={isDexcomConnecting}
            isOffline={isOffline}
            fields={
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="dexcom-email"
                    className="block text-sm font-medium text-slate-300 mb-1"
                  >
                    Dexcom Email
                  </label>
                  <input
                    id="dexcom-email"
                    type="email"
                    value={dexcomEmail}
                    onChange={(e) => onDexcomEmailChange(e.target.value)}
                    disabled={isDexcomConnecting}
                    placeholder="you@example.com"
                    autoComplete="email"
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-800 border-slate-700 text-slate-200",
                      "placeholder:text-slate-500",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                  />
                </div>
                <PasswordInput
                  id="dexcom-password"
                  value={dexcomPassword}
                  onChange={onDexcomPasswordChange}
                  disabled={isDexcomConnecting}
                  label="Dexcom Password"
                />
              </div>
            }
          />
        </CollapsibleSection>
      </div>
    </CollapsibleSection>
  );
}
