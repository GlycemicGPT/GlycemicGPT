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
  dexcomRegion: string;
  isDexcomConnecting: boolean;
  isOffline: boolean;
  onDexcomEmailChange: (value: string) => void;
  onDexcomPasswordChange: (value: string) => void;
  onDexcomRegionChange: (value: string) => void;
  onConnectDexcom: () => Promise<void>;
  onDisconnectDexcom: () => Promise<void>;
}

export function CGMIntegrationsSection({
  dexcom,
  dexcomEmail,
  dexcomPassword,
  dexcomRegion,
  isDexcomConnecting,
  isOffline,
  onDexcomEmailChange,
  onDexcomPasswordChange,
  onDexcomRegionChange,
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
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label
                      htmlFor="dexcom-email"
                      className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
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
                        "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                        "placeholder:text-slate-500 dark:placeholder:text-slate-500",
                        "focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-transparent",
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
                <div className="max-w-xs">
                  <label
                    htmlFor="dexcom-region"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
                  >
                    Region
                  </label>
                  <select
                    id="dexcom-region"
                    value={dexcomRegion}
                    onChange={(e) => onDexcomRegionChange(e.target.value)}
                    disabled={isDexcomConnecting}
                    className={clsx(
                      "w-full rounded-lg border px-3 py-2 text-sm",
                      "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                      "focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                  >
                    <option value="US">United States</option>
                    <option value="OUS">
                      Outside US (EU, UK, Canada, Australia, etc.)
                    </option>
                    <option value="JP">Japan & Asia-Pacific</option>
                  </select>
                  <p className="text-xs text-slate-500 mt-1">
                    Dexcom Share is regional. Pick the region that matches
                    your account; a mismatch will look identical to a wrong
                    password.
                  </p>
                </div>
                <div className="rounded-lg bg-slate-100/50 dark:bg-slate-800/40 border border-slate-300/50 dark:border-slate-700/50 p-3 text-xs text-slate-500 dark:text-slate-400">
                  <p className="font-medium text-slate-600 dark:text-slate-300 mb-1">
                    Before connecting
                  </p>
                  <p>
                    Open your Dexcom G6/G7 app and make sure Share is enabled
                    <span className="font-medium text-slate-600 dark:text-slate-300">
                      {" "}
                      and at least one follower has been invited
                    </span>
                    — Dexcom only activates the Share API after the first
                    follower invite exists.
                  </p>
                </div>
              </div>
            }
          />
        </CollapsibleSection>
      </div>
    </CollapsibleSection>
  );
}
