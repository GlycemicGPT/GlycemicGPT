/**
 * AI Provider Configuration Page
 *
 * Story 14.3: Expanded AI Provider Page
 *
 * Allows users to configure their AI provider from 5 options across 3 categories:
 * - Subscription Plans: Claude Subscription, ChatGPT Subscription
 * - Pay-Per-Token APIs: Claude API, OpenAI API
 * - Self-Hosted: Custom OpenAI-Compatible
 */

"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Brain,
  CheckCircle2,
  Eye,
  EyeOff,
  Globe,
  Key,
  Loader2,
  Server,
  Trash2,
  Wifi,
  WifiOff,
  Zap,
} from "lucide-react";
import {
  getAIProvider,
  configureAIProvider,
  configureSubscriptionProvider,
  testAIProvider,
  deleteAIProvider,
  startSubscriptionAuth,
  submitSubscriptionToken,
  getSubscriptionAuthStatus,
  revokeSubscriptionAuth,
  getSidecarHealth,
  type AIProviderConfigResponse,
  type AIProviderType,
  type AIProviderStatus,
  type SidecarProviderName,
  type SubscriptionAuthStatusResponse,
  type SidecarHealthResponse,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

// Provider definitions grouped by category
interface ProviderOption {
  value: AIProviderType;
  label: string;
  description: string;
  requiresBaseUrl: boolean;
  requiresApiKey: boolean;
  requiresModelName: boolean;
  apiKeyPlaceholder: string;
  apiKeyHint: string;
  baseUrlPlaceholder?: string;
  modelPlaceholder?: string;
  pricingHint: string;
}

// Mapping from frontend provider type to sidecar provider name
const SUBSCRIPTION_SIDECAR_MAP: Record<string, SidecarProviderName> = {
  claude_subscription: "claude",
  chatgpt_subscription: "codex",
};

const SUBSCRIPTION_PROVIDERS: ProviderOption[] = [
  {
    value: "claude_subscription",
    label: "Claude Subscription",
    description: "Use your Claude Max/Pro subscription via the built-in AI sidecar.",
    requiresBaseUrl: false,
    requiresApiKey: false,
    requiresModelName: false,
    apiKeyPlaceholder: "not-needed",
    apiKeyHint: "",
    modelPlaceholder: "claude-sonnet-4-5-20250929",
    pricingHint: "Unlimited usage with your subscription",
  },
  {
    value: "chatgpt_subscription",
    label: "ChatGPT Subscription",
    description: "Use your ChatGPT Plus/Team subscription via the built-in AI sidecar.",
    requiresBaseUrl: false,
    requiresApiKey: false,
    requiresModelName: false,
    apiKeyPlaceholder: "not-needed",
    apiKeyHint: "",
    modelPlaceholder: "gpt-4o",
    pricingHint: "Unlimited usage with your subscription",
  },
];

const API_PROVIDERS: ProviderOption[] = [
  {
    value: "claude_api",
    label: "Claude API (Anthropic)",
    description: "Direct Anthropic API. Supports Claude Sonnet, Opus, and Haiku models.",
    requiresBaseUrl: false,
    requiresApiKey: true,
    requiresModelName: false,
    apiKeyPlaceholder: "sk-ant-...",
    apiKeyHint: "Get your API key from console.anthropic.com",
    modelPlaceholder: "claude-sonnet-4-5-20250929",
    pricingHint: "Pay-per-token",
  },
  {
    value: "openai_api",
    label: "OpenAI API",
    description: "Direct OpenAI API. Supports GPT-4o and other OpenAI models.",
    requiresBaseUrl: false,
    requiresApiKey: true,
    requiresModelName: false,
    apiKeyPlaceholder: "sk-...",
    apiKeyHint: "Get your API key from platform.openai.com",
    modelPlaceholder: "gpt-4o",
    pricingHint: "Pay-per-token",
  },
];

const SELF_HOSTED_PROVIDERS: ProviderOption[] = [
  {
    value: "openai_compatible",
    label: "Custom OpenAI-Compatible",
    description: "Any OpenAI-compatible endpoint: LiteLLM, Ollama, vLLM, or other self-hosted models.",
    requiresBaseUrl: true,
    requiresApiKey: false,
    requiresModelName: true,
    apiKeyPlaceholder: "optional-key",
    apiKeyHint: "Only required if your endpoint needs authentication.",
    baseUrlPlaceholder: "http://localhost:11434/v1",
    modelPlaceholder: "llama3.1:70b",
    pricingHint: "Free (self-hosted)",
  },
];

const ALL_PROVIDERS = [...SUBSCRIPTION_PROVIDERS, ...API_PROVIDERS, ...SELF_HOSTED_PROVIDERS];

const PROVIDER_LABELS: Record<AIProviderType, string> = {
  claude_subscription: "Claude Subscription",
  chatgpt_subscription: "ChatGPT Subscription",
  claude_api: "Claude API (Anthropic)",
  openai_api: "OpenAI API",
  openai_compatible: "Custom OpenAI-Compatible",
  claude: "Claude (Legacy)",
  openai: "OpenAI (Legacy)",
};

const STATUS_CONFIG: Record<AIProviderStatus, { label: string; color: string; bg: string }> = {
  connected: { label: "Connected", color: "text-green-400", bg: "bg-green-500/10" },
  error: { label: "Error", color: "text-red-400", bg: "bg-red-500/10" },
  pending: { label: "Pending", color: "text-amber-400", bg: "bg-amber-500/10" },
};

export default function AIProviderPage() {
  const [isLoading, setIsLoading] = useState(true);
  const [config, setConfig] = useState<AIProviderConfigResponse | null>(null);
  const [isOffline, setIsOffline] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Form state
  const [providerType, setProviderType] = useState<AIProviderType>("claude_api");
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [modelName, setModelName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  // Action state
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Subscription auth state (Story 15.2 / 15.5)
  const [subscriptionToken, setSubscriptionToken] = useState("");
  const [isSubmittingToken, setIsSubmittingToken] = useState(false);
  const [sidecarHealth, setSidecarHealth] = useState<SidecarHealthResponse | null>(null);
  const [subscriptionAuth, setSubscriptionAuth] = useState<SubscriptionAuthStatusResponse | null>(null);
  const [authInstructions, setAuthInstructions] = useState<string | null>(null);
  const [isRevokingAuth, setIsRevokingAuth] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [isConfiguringSubscription, setIsConfiguringSubscription] = useState(false);
  const [isStartingAuth, setIsStartingAuth] = useState(false);

  const selectedProvider =
    ALL_PROVIDERS.find((p) => p.value === providerType) || API_PROVIDERS[0];

  const isSubscription = providerType in SUBSCRIPTION_SIDECAR_MAP;
  const sidecarProvider = SUBSCRIPTION_SIDECAR_MAP[providerType] || null;

  const handleProviderSwitch = (newType: AIProviderType) => {
    setProviderType(newType);
    // Clear form fields to prevent stale data from hidden fields being sent
    setApiKey("");
    setBaseUrl("");
    setModelName("");
    setSubscriptionToken("");
    setAuthInstructions(null);
    // Clear stale messages from previous provider context
    setError(null);
    setSuccess(null);
    setConfirmRevoke(false);
  };

  // Auto-clear success message
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(null), 5000);
    return () => clearTimeout(timer);
  }, [success]);

  const fetchConfig = useCallback(async () => {
    try {
      const data = await getAIProvider();
      setConfig(data);
      // Map legacy provider types to their modern equivalents
      const knownType = ALL_PROVIDERS.some((p) => p.value === data.provider_type)
        ? data.provider_type
        : "claude_api";
      setProviderType(knownType);
      setModelName(data.model_name || "");
      setBaseUrl(data.base_url || "");
      setIsOffline(false);
    } catch (err) {
      const is401 = err instanceof Error && err.message.includes("401");
      const is404 = err instanceof Error && err.message.includes("404");
      if (is404) {
        setConfig(null);
        setIsOffline(false);
      } else if (!is401) {
        setIsOffline(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  // Fetch subscription auth state when subscription provider is selected
  const fetchSubscriptionStatus = useCallback(async () => {
    const [health, auth] = await Promise.all([
      getSidecarHealth().catch(() => null),
      getSubscriptionAuthStatus().catch(() => null),
    ]);
    setSidecarHealth(health);
    setSubscriptionAuth(auth);
  }, []);

  useEffect(() => {
    if (isSubscription) {
      fetchSubscriptionStatus();
    }
  }, [isSubscription, fetchSubscriptionStatus]);

  const handleStartAuth = async () => {
    if (!sidecarProvider) return;
    setIsStartingAuth(true);
    setError(null);
    try {
      const result = await startSubscriptionAuth(sidecarProvider);
      setAuthInstructions(result.instructions);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start auth flow"
      );
    } finally {
      setIsStartingAuth(false);
    }
  };

  const handleSubmitToken = async () => {
    if (!sidecarProvider || !subscriptionToken.trim()) return;
    setIsSubmittingToken(true);
    setError(null);
    setSuccess(null);
    try {
      await submitSubscriptionToken(sidecarProvider, subscriptionToken.trim());
      setSubscriptionToken("");
      setAuthInstructions(null);
      await fetchSubscriptionStatus();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to submit token"
      );
      setIsSubmittingToken(false);
      return;
    }

    // Auto-configure the provider in the DB via the sidecar endpoint
    try {
      const result = await configureSubscriptionProvider({
        sidecar_provider: sidecarProvider,
        model_name: modelName.trim() || null,
      });
      setConfig(result);
      setSuccess("Token accepted and provider configured via sidecar.");
    } catch (err) {
      // Token was accepted but DB configuration failed
      setSuccess("Token accepted.");
      setError(
        err instanceof Error
          ? `Provider configuration failed: ${err.message}`
          : "Token accepted, but failed to save provider configuration. Click 'Save Configuration' to retry."
      );
    } finally {
      setIsSubmittingToken(false);
    }
  };

  const handleConfigureSubscription = async () => {
    if (!sidecarProvider) return;
    setIsConfiguringSubscription(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await configureSubscriptionProvider({
        sidecar_provider: sidecarProvider,
        model_name: modelName.trim() || null,
      });
      setConfig(result);
      setSuccess("Subscription provider configured successfully.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to configure subscription provider"
      );
    } finally {
      setIsConfiguringSubscription(false);
    }
  };

  const handleRevokeAuth = async () => {
    if (!sidecarProvider) return;
    setIsRevokingAuth(true);
    setError(null);
    setSuccess(null);
    let configRemovalFailed = false;
    try {
      await revokeSubscriptionAuth(sidecarProvider);
      // Also remove the DB config since the sidecar auth is gone
      if (config?.sidecar_provider === sidecarProvider) {
        try {
          await deleteAIProvider();
        } catch {
          configRemovalFailed = true;
        }
        setConfig(null);
      }
      if (configRemovalFailed) {
        setSuccess("Sidecar auth revoked.");
        setError("Failed to remove provider configuration. Use 'Remove AI Provider' to clean up.");
      } else {
        setSuccess("Subscription auth revoked and provider removed.");
      }
      // Clear form state
      setModelName("");
      setSubscriptionToken("");
      setAuthInstructions(null);
      setConfirmRevoke(false);
      await fetchSubscriptionStatus();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to revoke auth"
      );
      setConfirmRevoke(false);
    } finally {
      setIsRevokingAuth(false);
    }
  };

  const handleSave = async () => {
    // Validate required fields based on provider
    if (selectedProvider.requiresApiKey && !apiKey.trim()) {
      setError("Please enter an API key");
      return;
    }
    if (selectedProvider.requiresBaseUrl && !baseUrl.trim()) {
      setError("Please enter a base URL for this provider type");
      return;
    }
    if (selectedProvider.requiresModelName && !modelName.trim()) {
      setError("Please enter a model name for this provider type");
      return;
    }

    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await configureAIProvider({
        provider_type: providerType,
        api_key: apiKey.trim() || "not-needed",
        model_name: modelName.trim() || null,
        base_url: baseUrl.trim() || null,
      });
      setConfig(result);
      setApiKey("");
      setSuccess("AI provider configured successfully");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to configure AI provider"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    setIsTesting(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await testAIProvider();
      if (result.success) {
        setSuccess(result.message);
        await fetchConfig();
      } else {
        setError(result.message);
        await fetchConfig();
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to test AI provider"
      );
    } finally {
      setIsTesting(false);
    }
  };

  const handleDelete = async () => {
    setIsDeleting(true);
    setError(null);
    setSuccess(null);

    try {
      await deleteAIProvider();
      setConfig(null);
      setConfirmDelete(false);
      setApiKey("");
      setModelName("");
      setBaseUrl("");
      setSubscriptionToken("");
      setAuthInstructions(null);
      setProviderType("claude_api");
      setSuccess("AI provider configuration removed");
      // Refresh sidecar auth state (backend revokes sidecar auth on delete)
      await fetchSubscriptionStatus().catch(() => {});
    } catch (err) {
      setConfirmDelete(false);
      setError(
        err instanceof Error ? err.message : "Failed to remove AI provider"
      );
    } finally {
      setIsDeleting(false);
    }
  };

  const isConfigured = config !== null;
  const statusInfo = config ? STATUS_CONFIG[config.status] : null;

  // Determine if save button should be enabled
  const canSave = (() => {
    if (isOffline || isSaving) return false;
    if (selectedProvider.requiresApiKey && !apiKey.trim()) return false;
    if (selectedProvider.requiresBaseUrl && !baseUrl.trim()) return false;
    if (selectedProvider.requiresModelName && !modelName.trim()) return false;
    return true;
  })();

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Back link */}
      <Link
        href="/dashboard/settings"
        className="inline-flex items-center gap-2 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors text-sm"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Settings
      </Link>

      {/* Page header */}
      <div className="flex items-center gap-3">
        <div className="p-3 bg-slate-100 dark:bg-slate-800 rounded-lg">
          <Brain className="h-6 w-6 text-purple-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">AI Provider</h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm">
            Configure your AI provider for glucose analysis and insights
          </p>
        </div>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner
          onRetry={async () => {
            setIsRetrying(true);
            await fetchConfig();
            setIsRetrying(false);
          }}
          isRetrying={isRetrying}
          message="Unable to connect to server. AI provider settings are unavailable."
        />
      )}

      {/* Error banner */}
      {error && (
        <div
          role="alert"
          className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 text-sm"
        >
          {error}
        </div>
      )}

      {/* Success banner */}
      {success && (
        <div
          role="status"
          className="bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg px-4 py-3 text-sm"
        >
          {success}
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading AI provider configuration"
        >
          <Loader2 className="h-8 w-8 text-purple-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading AI configuration...</p>
        </div>
      )}

      {/* Current configuration status */}
      {!isLoading && isConfigured && (
        <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {config.status === "connected" ? (
                <Wifi className="h-5 w-5 text-green-400" />
              ) : (
                <WifiOff className="h-5 w-5 text-red-400" />
              )}
              <h2 className="text-lg font-semibold">Current Configuration</h2>
            </div>
            {statusInfo && (
              <span
                className={`inline-flex items-center gap-1.5 ${statusInfo.bg} ${statusInfo.color} text-xs font-medium px-2.5 py-1 rounded-full`}
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                {statusInfo.label}
              </span>
            )}
          </div>

          <div className="bg-slate-100 dark:bg-slate-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500 dark:text-slate-400">Provider</span>
              <span className="text-slate-900 dark:text-white font-medium">
                {PROVIDER_LABELS[config.provider_type] || config.provider_type}
              </span>
            </div>
            {config.sidecar_provider ? (
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">Authentication</span>
                <span className="text-green-400 text-xs flex items-center gap-1">
                  <Wifi className="h-3 w-3" />
                  Managed by sidecar
                </span>
              </div>
            ) : (
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">API Key</span>
                <span className="text-slate-900 dark:text-white font-mono text-xs">
                  {config.masked_api_key}
                </span>
              </div>
            )}
            {config.base_url && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">Base URL</span>
                <span className="text-slate-900 dark:text-white font-mono text-xs truncate max-w-[200px]">
                  {config.base_url}
                </span>
              </div>
            )}
            {config.model_name && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">Model</span>
                <span className="text-slate-900 dark:text-white font-mono text-xs">
                  {config.model_name}
                </span>
              </div>
            )}
            {config.last_validated_at && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">Last Validated</span>
                <span className="text-slate-900 dark:text-white text-xs">
                  {new Date(config.last_validated_at).toLocaleString()}
                </span>
              </div>
            )}
            {config.last_error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mt-2">
                <p className="text-xs text-red-400">{config.last_error}</p>
              </div>
            )}
          </div>

          {/* Action buttons for configured state */}
          <div className="flex flex-col gap-2">
            <button
              onClick={handleTest}
              disabled={isTesting || isDeleting || isOffline}
              title={isOffline ? "Cannot test while disconnected" : undefined}
              className="w-full bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed text-slate-900 dark:text-white font-medium rounded-lg px-4 py-3 transition-colors flex items-center justify-center gap-2"
              aria-label="Test connection"
            >
              {isTesting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Zap className="h-4 w-4" />
              )}
              Test Connection
            </button>

            {!confirmDelete ? (
              <button
                onClick={() => setConfirmDelete(true)}
                disabled={isTesting || isDeleting || isOffline}
                title={isOffline ? "Cannot remove while disconnected" : undefined}
                className="w-full text-red-400 hover:text-red-300 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-colors flex items-center justify-center gap-2 py-2"
                aria-label="Remove AI provider"
              >
                <Trash2 className="h-4 w-4" />
                Remove AI Provider
              </button>
            ) : (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 space-y-3">
                <p className="text-red-400 text-sm">
                  Are you sure? Removing the AI provider will disable all AI
                  features including daily briefs, insights, and chat.
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={handleDelete}
                    disabled={isDeleting}
                    className="flex-1 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-3 py-2 transition-colors"
                  >
                    {isDeleting ? (
                      <Loader2 className="h-4 w-4 animate-spin mx-auto" />
                    ) : (
                      "Yes, Remove"
                    )}
                  </button>
                  <button
                    onClick={() => setConfirmDelete(false)}
                    className="flex-1 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-900 dark:text-white text-sm font-medium rounded-lg px-3 py-2 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Configuration form */}
      {!isLoading && (
        <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 space-y-5">
          <div className="flex items-center gap-2">
            <Key className="h-5 w-5 text-purple-400" />
            <h2 className="text-lg font-semibold">
              {isConfigured ? "Update Configuration" : "Set Up AI Provider"}
            </h2>
          </div>

          {!isConfigured && (
            <p className="text-slate-500 dark:text-slate-400 text-sm">
              GlycemicGPT uses your own AI (BYOAI) to analyze glucose data and
              generate insights. Choose from subscription plans, direct API keys,
              or self-hosted models below. Your credentials are encrypted before
              storage and never shared.
            </p>
          )}

          {/* Provider selection by category */}
          <div className="space-y-4">
            {/* Subscription Plans */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Globe className="h-4 w-4 text-blue-400" />
                <label className="text-sm font-medium text-slate-600 dark:text-slate-300">
                  Subscription Plans
                </label>
                <span className="text-xs text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded-full">
                  Unlimited usage
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {SUBSCRIPTION_PROVIDERS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleProviderSwitch(option.value)}
                    disabled={isOffline}
                    className={`text-left p-3 rounded-lg border transition-colors ${
                      providerType === option.value
                        ? "border-purple-500 bg-purple-500/10"
                        : "border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 hover:border-slate-400 dark:hover:border-slate-600"
                    } disabled:opacity-50 disabled:cursor-not-allowed`}
                    aria-pressed={providerType === option.value}
                    aria-label={`Select ${option.label}`}
                  >
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{option.label}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{option.description}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Pay-Per-Token APIs */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Key className="h-4 w-4 text-amber-400" />
                <label className="text-sm font-medium text-slate-600 dark:text-slate-300">
                  Pay-Per-Token APIs
                </label>
                <span className="text-xs text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full">
                  Usage-based pricing
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {API_PROVIDERS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleProviderSwitch(option.value)}
                    disabled={isOffline}
                    className={`text-left p-3 rounded-lg border transition-colors ${
                      providerType === option.value
                        ? "border-purple-500 bg-purple-500/10"
                        : "border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 hover:border-slate-400 dark:hover:border-slate-600"
                    } disabled:opacity-50 disabled:cursor-not-allowed`}
                    aria-pressed={providerType === option.value}
                    aria-label={`Select ${option.label}`}
                  >
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{option.label}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{option.description}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Self-Hosted */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Server className="h-4 w-4 text-green-400" />
                <label className="text-sm font-medium text-slate-600 dark:text-slate-300">
                  Self-Hosted
                </label>
                <span className="text-xs text-green-400 bg-green-500/10 px-2 py-0.5 rounded-full">
                  Free (self-hosted)
                </span>
              </div>
              <div className="grid grid-cols-1 gap-2">
                {SELF_HOSTED_PROVIDERS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleProviderSwitch(option.value)}
                    disabled={isOffline}
                    className={`text-left p-3 rounded-lg border transition-colors ${
                      providerType === option.value
                        ? "border-purple-500 bg-purple-500/10"
                        : "border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 hover:border-slate-400 dark:hover:border-slate-600"
                    } disabled:opacity-50 disabled:cursor-not-allowed`}
                    aria-pressed={providerType === option.value}
                    aria-label={`Select ${option.label}`}
                  >
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{option.label}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{option.description}</p>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Dynamic form fields based on selected provider */}
          <div className="space-y-4 border-t border-slate-200 dark:border-slate-800 pt-4">
            <p className="text-xs text-slate-500">
              {selectedProvider.pricingHint}
            </p>

            {/* Subscription provider: token paste flow */}
            {isSubscription && (
              <div className="space-y-4">
                {/* Sidecar status */}
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-slate-500 dark:text-slate-400">AI Sidecar:</span>
                  {sidecarHealth === null ? (
                    <span className="text-slate-500">Checking...</span>
                  ) : sidecarHealth.available ? (
                    <span className="text-green-400 flex items-center gap-1">
                      <Wifi className="h-3.5 w-3.5" />
                      Ready
                    </span>
                  ) : (
                    <span className="text-red-400 flex items-center gap-1">
                      <WifiOff className="h-3.5 w-3.5" />
                      Unavailable
                    </span>
                  )}
                </div>

                {/* Optional model name for subscription providers (always visible) */}
                <div className="space-y-2">
                  <label
                    htmlFor="sub-model-name"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300"
                  >
                    Model Name{" "}
                    <span className="text-slate-500 font-normal">(optional)</span>
                  </label>
                  <input
                    id="sub-model-name"
                    type="text"
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                    placeholder={selectedProvider.modelPlaceholder}
                    disabled={isOffline || isConfiguringSubscription || isSubmittingToken}
                    className="w-full bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-4 py-3 text-slate-900 dark:text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent disabled:opacity-50 text-sm"
                  />
                  <p className="text-xs text-slate-500">
                    Leave blank to use the default model.
                  </p>
                </div>

                {/* Current auth status for this provider */}
                {subscriptionAuth?.sidecar_available && sidecarProvider && (() => {
                  const providerAuth = sidecarProvider === "claude"
                    ? subscriptionAuth.claude
                    : subscriptionAuth.codex;
                  const isAuthed = providerAuth?.authenticated === true;
                  // Check if DB config already matches this sidecar provider
                  const isAlreadyConfigured = config?.sidecar_provider === sidecarProvider;

                  if (isAuthed) {
                    return (
                      <div className="space-y-4">
                        <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4 space-y-3">
                          <div className="flex items-center gap-2">
                            <CheckCircle2 className="h-5 w-5 text-green-400" />
                            <span className="text-green-400 font-medium text-sm">
                              {sidecarProvider === "claude" ? "Claude" : "ChatGPT"} subscription connected via sidecar
                            </span>
                          </div>
                          {!confirmRevoke ? (
                            <button
                              onClick={() => setConfirmRevoke(true)}
                              disabled={isRevokingAuth || isOffline}
                              className="text-red-400 hover:text-red-300 disabled:opacity-50 text-sm transition-colors flex items-center gap-1"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              Sign out
                            </button>
                          ) : (
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-red-400">This will remove your auth token and provider config.</span>
                              <button
                                onClick={handleRevokeAuth}
                                disabled={isRevokingAuth || isOffline}
                                className="text-red-400 hover:text-red-300 disabled:opacity-50 text-xs font-medium transition-colors flex items-center gap-1"
                              >
                                {isRevokingAuth ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  "Confirm"
                                )}
                              </button>
                              <button
                                onClick={() => setConfirmRevoke(false)}
                                className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white text-xs transition-colors"
                              >
                                Cancel
                              </button>
                            </div>
                          )}
                        </div>

                        {/* Save/Update configuration button */}
                        <button
                          onClick={handleConfigureSubscription}
                          disabled={isOffline || isConfiguringSubscription}
                          className="w-full bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-3 transition-colors flex items-center justify-center gap-2"
                        >
                          {isConfiguringSubscription ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <CheckCircle2 className="h-4 w-4" />
                          )}
                          {isAlreadyConfigured ? "Update Configuration" : "Save Configuration"}
                        </button>
                      </div>
                    );
                  }

                  return null;
                })()}

                {/* Token paste form (shown when not authenticated) */}
                {(!subscriptionAuth?.sidecar_available ||
                  !(sidecarProvider === "claude"
                    ? subscriptionAuth?.claude?.authenticated
                    : subscriptionAuth?.codex?.authenticated)) && (
                  <div className="space-y-3">
                    {!authInstructions ? (
                      <button
                        onClick={handleStartAuth}
                        disabled={isOffline || isStartingAuth || !sidecarHealth?.available}
                        className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-3 transition-colors flex items-center justify-center gap-2"
                      >
                        {isStartingAuth ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Key className="h-4 w-4" />
                        )}
                        Sign in with {sidecarProvider === "claude" ? "Claude" : "ChatGPT"}
                      </button>
                    ) : (
                      <>
                        <div className="bg-slate-100 dark:bg-slate-800 rounded-lg p-4 space-y-2">
                          <p className="text-sm text-slate-600 dark:text-slate-300 font-medium">How to get your token:</p>
                          <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                            {authInstructions}
                          </p>
                        </div>
                        <div className="space-y-2">
                          <label
                            htmlFor="subscription-token"
                            className="block text-sm font-medium text-slate-600 dark:text-slate-300"
                          >
                            Paste your token
                          </label>
                          <textarea
                            id="subscription-token"
                            value={subscriptionToken}
                            onChange={(e) => setSubscriptionToken(e.target.value)}
                            placeholder="Paste the token from the CLI command..."
                            disabled={isOffline || isSubmittingToken}
                            autoComplete="off"
                            spellCheck={false}
                            maxLength={5000}
                            rows={3}
                            className="w-full bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-4 py-3 text-slate-900 dark:text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent disabled:opacity-50 font-mono text-xs resize-vertical"
                          />
                        </div>
                        <button
                          onClick={handleSubmitToken}
                          disabled={isOffline || isSubmittingToken || !subscriptionToken.trim()}
                          className="w-full bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-3 transition-colors flex items-center justify-center gap-2"
                        >
                          {isSubmittingToken ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <CheckCircle2 className="h-4 w-4" />
                          )}
                          Connect
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Non-subscription providers: standard form fields */}
            {!isSubscription && (
              <>
                {/* Base URL input (shown for self-hosted) */}
                {selectedProvider.requiresBaseUrl && (
                  <div className="space-y-2">
                    <label
                      htmlFor="base-url"
                      className="block text-sm font-medium text-slate-600 dark:text-slate-300"
                    >
                      Base URL <span className="text-red-400">*</span>
                    </label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Globe className="h-4 w-4 text-slate-500" />
                      </div>
                      <input
                        id="base-url"
                        type="url"
                        value={baseUrl}
                        onChange={(e) => setBaseUrl(e.target.value)}
                        placeholder={selectedProvider.baseUrlPlaceholder}
                        disabled={isOffline || isSaving}
                        className="w-full bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg pl-10 pr-4 py-3 text-slate-900 dark:text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent disabled:opacity-50 font-mono text-sm"
                      />
                    </div>
                    <p className="text-xs text-slate-500">
                      The URL of your self-hosted endpoint (e.g., http://your-server:11434/v1)
                    </p>
                  </div>
                )}

                {/* API Key input */}
                <div className="space-y-2">
                  <label
                    htmlFor="api-key"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300"
                  >
                    API Key{" "}
                    {selectedProvider.requiresApiKey ? (
                      <span className="text-red-400">*</span>
                    ) : (
                      <span className="text-slate-500 font-normal">(optional)</span>
                    )}
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <Key className="h-4 w-4 text-slate-500" />
                    </div>
                    <input
                      id="api-key"
                      type={showApiKey ? "text" : "password"}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={selectedProvider.apiKeyPlaceholder}
                      disabled={isOffline || isSaving}
                      autoComplete="off"
                      className="w-full bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg pl-10 pr-12 py-3 text-slate-900 dark:text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent disabled:opacity-50 font-mono text-sm"
                    />
                    <button
                      type="button"
                      onClick={() => setShowApiKey(!showApiKey)}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
                      aria-label={showApiKey ? "Hide API key" : "Show API key"}
                    >
                      {showApiKey ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                  <p className="text-xs text-slate-500">
                    {selectedProvider.apiKeyHint}
                  </p>
                </div>

                {/* Model Name input */}
                <div className="space-y-2">
                  <label
                    htmlFor="model-name"
                    className="block text-sm font-medium text-slate-600 dark:text-slate-300"
                  >
                    Model Name{" "}
                    {selectedProvider.requiresModelName ? (
                      <span className="text-red-400">*</span>
                    ) : (
                      <span className="text-slate-500 font-normal">(optional)</span>
                    )}
                  </label>
                  <input
                    id="model-name"
                    type="text"
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                    placeholder={selectedProvider.modelPlaceholder}
                    disabled={isOffline || isSaving}
                    className="w-full bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg px-4 py-3 text-slate-900 dark:text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent disabled:opacity-50 text-sm"
                  />
                  <p className="text-xs text-slate-500">
                    {selectedProvider.requiresModelName
                      ? "Required: specify which model to use on your endpoint."
                      : "Leave blank to use the default model."}
                  </p>
                </div>
              </>
            )}
          </div>

          {/* Save button (only for non-subscription providers) */}
          {!isSubscription && (
            <button
              onClick={handleSave}
              disabled={!canSave}
              title={
                isOffline
                  ? "Cannot save while disconnected"
                  : !canSave
                    ? "Fill in required fields first"
                    : undefined
              }
              className="w-full bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-3 transition-colors flex items-center justify-center gap-2"
              aria-label={isConfigured ? "Update AI provider" : "Save and validate"}
            >
              {isSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              {isConfigured ? "Update Configuration" : "Save & Validate"}
            </button>
          )}
        </div>
      )}

      {/* Info card */}
      <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
        <div className="flex items-start gap-2">
          <Brain className="h-4 w-4 text-slate-500 mt-0.5 shrink-0" />
          <p className="text-xs text-slate-500">
            Your credentials are encrypted before storage and only used to
            communicate with your chosen AI provider. We never share your
            credentials with third parties. The connection is validated before
            saving -- invalid configurations will not be stored.
          </p>
        </div>
      </div>
    </div>
  );
}
