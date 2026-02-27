"use client";

/**
 * Story 12.1: Integrations Settings Page
 *
 * Allows users to configure Dexcom and Tandem integration credentials,
 * test connections, and view connection status. Organized into expandable
 * category sections (Pump, CGM) for scalability.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Loader2,
  AlertTriangle,
  Check,
  ArrowLeft,
  Link2,
} from "lucide-react";
import Link from "next/link";
import {
  listIntegrations,
  connectDexcom,
  disconnectDexcom,
  connectTandem,
  disconnectTandem,
  type IntegrationResponse,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";
import { PumpIntegrationsSection } from "@/components/integrations/pump-integrations-section";
import { CGMIntegrationsSection } from "@/components/integrations/cgm-integrations-section";

export default function IntegrationsPage() {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isOffline, setIsOffline] = useState(false);

  // Integration state
  const [dexcom, setDexcom] = useState<IntegrationResponse | null>(null);
  const [tandem, setTandem] = useState<IntegrationResponse | null>(null);

  // Dexcom form
  const [dexcomEmail, setDexcomEmail] = useState("");
  const [dexcomPassword, setDexcomPassword] = useState("");
  const [isDexcomConnecting, setIsDexcomConnecting] = useState(false);

  // Tandem form
  const [tandemEmail, setTandemEmail] = useState("");
  const [tandemPassword, setTandemPassword] = useState("");
  const [tandemRegion, setTandemRegion] = useState("US");
  const [isTandemConnecting, setIsTandemConnecting] = useState(false);

  // Auto-clear success message
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const fetchIntegrations = useCallback(async () => {
    try {
      setError(null);
      const data = await listIntegrations();

      const dexcomInt = data.integrations.find(
        (i) => i.integration_type === "dexcom"
      );
      const tandemInt = data.integrations.find(
        (i) => i.integration_type === "tandem"
      );

      setDexcom(dexcomInt || null);
      setTandem(tandemInt || null);
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
    fetchIntegrations();
  }, [fetchIntegrations]);

  const handleConnectDexcom = async () => {
    if (!dexcomEmail || !dexcomPassword) {
      setError("Please enter your Dexcom email and password");
      return;
    }

    setIsDexcomConnecting(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await connectDexcom({
        username: dexcomEmail,
        password: dexcomPassword,
      });
      setDexcom(result.integration);
      setDexcomPassword("");
      setSuccess("Dexcom connected successfully");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to connect Dexcom"
      );
    } finally {
      setIsDexcomConnecting(false);
    }
  };

  const handleDisconnectDexcom = async () => {
    setError(null);
    setSuccess(null);

    try {
      await disconnectDexcom();
      setDexcom(null);
      setDexcomEmail("");
      setDexcomPassword("");
      setSuccess("Dexcom disconnected");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to disconnect Dexcom"
      );
    }
  };

  const handleConnectTandem = async () => {
    if (!tandemEmail || !tandemPassword) {
      setError("Please enter your Tandem email and password");
      return;
    }

    setIsTandemConnecting(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await connectTandem({
        username: tandemEmail,
        password: tandemPassword,
        region: tandemRegion,
      });
      setTandem(result.integration);
      setTandemPassword("");
      setSuccess("Tandem connected successfully");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to connect Tandem"
      );
    } finally {
      setIsTandemConnecting(false);
    }
  };

  const handleDisconnectTandem = async () => {
    setError(null);
    setSuccess(null);

    try {
      await disconnectTandem();
      setTandem(null);
      setTandemEmail("");
      setTandemPassword("");
      setSuccess("Tandem disconnected");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to disconnect Tandem"
      );
    }
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <Link
          href="/dashboard/settings"
          className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-300 mb-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </Link>
        <h1 className="text-2xl font-bold">Integrations</h1>
        <p className="text-slate-400">
          Connect your Dexcom and Tandem accounts to sync glucose and pump data
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner
          onRetry={fetchIntegrations}
          isRetrying={isLoading}
          message="Unable to connect to server. Integration management is unavailable."
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
          className="bg-slate-900 rounded-xl p-12 border border-slate-800 text-center"
          role="status"
          aria-label="Loading integrations"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-400">Loading integrations...</p>
        </div>
      )}

      {/* Pump Integrations (Tandem) */}
      {!isLoading && (
        <PumpIntegrationsSection
          tandem={tandem}
          tandemEmail={tandemEmail}
          tandemPassword={tandemPassword}
          tandemRegion={tandemRegion}
          isTandemConnecting={isTandemConnecting}
          isOffline={isOffline}
          onTandemEmailChange={setTandemEmail}
          onTandemPasswordChange={setTandemPassword}
          onTandemRegionChange={setTandemRegion}
          onConnectTandem={handleConnectTandem}
          onDisconnectTandem={handleDisconnectTandem}
        />
      )}

      {/* CGM Integrations (Dexcom) */}
      {!isLoading && (
        <CGMIntegrationsSection
          dexcom={dexcom}
          dexcomEmail={dexcomEmail}
          dexcomPassword={dexcomPassword}
          isDexcomConnecting={isDexcomConnecting}
          isOffline={isOffline}
          onDexcomEmailChange={setDexcomEmail}
          onDexcomPasswordChange={setDexcomPassword}
          onConnectDexcom={handleConnectDexcom}
          onDisconnectDexcom={handleDisconnectDexcom}
        />
      )}

      {/* Info card */}
      <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-800">
        <div className="flex items-start gap-2">
          <Link2 className="h-4 w-4 text-slate-500 mt-0.5 shrink-0" />
          <p className="text-xs text-slate-500">
            Your credentials are encrypted before storage and are only used to
            fetch your glucose and pump data. We never share your credentials
            with third parties. Connection is validated before credentials are
            saved — invalid credentials will not be stored.
          </p>
        </div>
      </div>
    </div>
  );
}
