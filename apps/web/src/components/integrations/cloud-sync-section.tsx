"use client";

import { RefreshCw } from "lucide-react";
import clsx from "clsx";
import type { IntegrationResponse } from "@/lib/api";
import { CollapsibleSection } from "@/components/ui/collapsible-section";
import { TANDEM_COUNTRY_GROUPS } from "@/lib/tandem-countries";
import { IntegrationCard, PasswordInput, StatusBadge } from "./integration-card";
import { TandemSyncCard } from "./tandem-sync-card";
import { MedtronicImportCard } from "./medtronic-import-card";
import { MedtronicConnectCard } from "./medtronic-connect-card";

interface CloudSyncSectionProps {
  tandem: IntegrationResponse | null;
  tandemEmail: string;
  tandemPassword: string;
  tandemCountry: string;
  isTandemConnecting: boolean;
  isOffline: boolean;
  onTandemEmailChange: (value: string) => void;
  onTandemPasswordChange: (value: string) => void;
  onTandemCountryChange: (value: string) => void;
  onConnectTandem: () => Promise<void>;
  onDisconnectTandem: () => Promise<void>;
}

/**
 * Cloud Sync: pull pump data from a vendor's cloud (no Bluetooth pairing
 * required). One subsection per vendor -- Tandem t:connect today; Medtronic
 * CareLink / Insulet Omnipod planned. Each subsection owns the full cloud
 * integration for that vendor: connecting the account AND the sync controls.
 */
export function CloudSyncSection({
  tandem,
  tandemEmail,
  tandemPassword,
  tandemCountry,
  isTandemConnecting,
  isOffline,
  onTandemEmailChange,
  onTandemPasswordChange,
  onTandemCountryChange,
  onConnectTandem,
  onDisconnectTandem,
}: CloudSyncSectionProps) {
  return (
    <CollapsibleSection title="Cloud Sync" icon={RefreshCw}>
      <div className="space-y-4">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Pull pump history from your vendor&apos;s cloud on a schedule or on
          demand — no Bluetooth pairing required. More vendors coming.
        </p>
        <CollapsibleSection
          title="Tandem"
          variant="subsection"
          badge={<StatusBadge status={tandem?.status ?? null} />}
        >
          <div className="space-y-4">
            <IntegrationCard
              title="Tandem t:connect"
              description="Connect your Tandem t:connect account to sync pump and Control-IQ data"
              status={tandem?.status ?? null}
              lastSyncAt={tandem?.last_sync_at ?? null}
              lastError={tandem?.last_error ?? null}
              onConnect={onConnectTandem}
              onDisconnect={onDisconnectTandem}
              isConnecting={isTandemConnecting}
              isOffline={isOffline}
              fields={
                <div className="space-y-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label
                        htmlFor="tandem-email"
                        className="block text-sm font-medium text-slate-300 mb-1"
                      >
                        Tandem t:connect Email
                      </label>
                      <input
                        id="tandem-email"
                        type="email"
                        value={tandemEmail}
                        onChange={(e) => onTandemEmailChange(e.target.value)}
                        disabled={isTandemConnecting}
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
                      id="tandem-password"
                      value={tandemPassword}
                      onChange={onTandemPasswordChange}
                      disabled={isTandemConnecting}
                      label="Tandem t:connect Password"
                    />
                  </div>
                  <div className="max-w-sm">
                    <label
                      htmlFor="tandem-country"
                      className="block text-sm font-medium text-slate-300 mb-1"
                    >
                      Country
                    </label>
                    <select
                      id="tandem-country"
                      value={tandemCountry}
                      onChange={(e) => onTandemCountryChange(e.target.value)}
                      disabled={isTandemConnecting}
                      className={clsx(
                        "w-full rounded-lg border px-3 py-2 text-sm",
                        "bg-slate-800 border-slate-700 text-slate-200",
                        "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                        "disabled:opacity-50 disabled:cursor-not-allowed"
                      )}
                    >
                      {TANDEM_COUNTRY_GROUPS.map((group) => (
                        <optgroup key={group.label} label={group.label}>
                          {group.options.map((opt) => (
                            <option key={opt.code} value={opt.code}>
                              {opt.label}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                    <p className="text-xs text-slate-500 mt-1">
                      Tandem routes data through one of two cloud backends. Pick
                      the country your t:connect account is registered in — the
                      wrong cluster will fail to sync.
                    </p>
                  </div>
                </div>
              }
            />

            {tandem?.status === "connected" && (
              <TandemSyncCard isOffline={isOffline} />
            )}
          </div>
        </CollapsibleSection>

        <CollapsibleSection title="Medtronic CareLink" variant="subsection">
          <div className="space-y-4">
            {/* Automatic sync (CarePartner/Connect) -- ongoing recent data. */}
            <MedtronicConnectCard isOffline={isOffline} />
            {/* Manual historical import -- deep backfill from the CareLink site. */}
            <MedtronicImportCard isOffline={isOffline} />
          </div>
        </CollapsibleSection>
      </div>
    </CollapsibleSection>
  );
}
