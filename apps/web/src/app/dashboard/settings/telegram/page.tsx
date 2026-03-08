/**
 * Telegram Settings Page
 *
 * Story 7.1: Telegram Bot Setup & Configuration
 * Story 12.3: Add Telegram Bot Token Configuration
 *
 * Two-step flow:
 * 1. Bot Setup (Admin): Configure bot token via @BotFather
 * 2. Account Linking (User): Link personal Telegram account
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  Copy,
  Eye,
  EyeOff,
  Key,
  Loader2,
  MessageCircle,
  Send,
  Trash2,
  Unlink,
} from "lucide-react";
import {
  generateTelegramCode,
  getTelegramBotConfig,
  getTelegramStatus,
  saveTelegramBotToken,
  removeTelegramBotToken,
  sendTelegramTestMessage,
  TelegramBotConfigResponse,
  TelegramStatusResponse,
  TelegramVerificationCodeResponse,
  unlinkTelegram,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

type PageState = "loading" | "not_linked" | "code_generated" | "linked";

export default function TelegramSettingsPage() {
  const [pageState, setPageState] = useState<PageState>("loading");
  const [status, setStatus] = useState<TelegramStatusResponse | null>(null);
  const [codeData, setCodeData] =
    useState<TelegramVerificationCodeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [timeLeft, setTimeLeft] = useState<number>(0);
  const [copied, setCopied] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  // Bot config state (Story 12.3)
  const [botConfig, setBotConfig] = useState<TelegramBotConfigResponse | null>(
    null
  );
  const [botToken, setBotToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [botActionLoading, setBotActionLoading] = useState(false);
  const [confirmRemoveBot, setConfirmRemoveBot] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const botConfigured = botConfig?.configured === true;

  const clearTimers = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
      countdownRef.current = null;
    }
  }, []);

  const fetchBotConfig = useCallback(async () => {
    try {
      const data = await getTelegramBotConfig();
      setBotConfig(data);
      return data;
    } catch {
      // If bot-config endpoint fails, treat as not configured
      setBotConfig({ configured: false, bot_username: null, configured_at: null });
      return null;
    }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await getTelegramStatus();
      setStatus(data);
      setIsOffline(false);
      if (data.linked) {
        setPageState("linked");
        clearTimers();
      } else if (pageState !== "code_generated") {
        setPageState("not_linked");
      }
    } catch (err) {
      const is401 = err instanceof Error && err.message.includes("401");
      const is503 = err instanceof Error && err.message.includes("503");
      if (!is401 && !is503) {
        setIsOffline(true);
      }
      // 503 means bot not configured - not an offline state
      if (is503) {
        setIsOffline(false);
      }
      if (pageState === "loading") {
        setPageState("not_linked");
      }
    }
  }, [clearTimers, pageState]);

  // Initial load
  useEffect(() => {
    const init = async () => {
      await fetchBotConfig();
      await fetchStatus();
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => clearTimers();
  }, [clearTimers]);

  const handleValidateToken = async () => {
    if (!botToken.trim()) return;
    setError(null);
    setSuccess(null);
    setBotActionLoading(true);

    try {
      const result = await saveTelegramBotToken(botToken.trim());
      if (result.valid) {
        setBotConfig({
          configured: true,
          bot_username: result.bot_username,
          configured_at: new Date().toISOString(),
        });
        setBotToken("");
        setSuccess(
          `Bot token validated! Connected as @${result.bot_username}`
        );
        // Re-fetch status now that bot is configured
        await fetchStatus();
      } else {
        setError("Token validation failed. Please check the token and try again.");
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to validate bot token"
      );
    } finally {
      setBotActionLoading(false);
    }
  };

  const handleRemoveBotToken = async () => {
    setError(null);
    setSuccess(null);
    setBotActionLoading(true);

    try {
      await removeTelegramBotToken();
      setBotConfig({
        configured: false,
        bot_username: null,
        configured_at: null,
      });
      setConfirmRemoveBot(false);
      setSuccess("Bot token removed.");
    } catch (err) {
      setConfirmRemoveBot(false);
      setError(
        err instanceof Error ? err.message : "Failed to remove bot token"
      );
    } finally {
      setBotActionLoading(false);
    }
  };

  const handleGenerateCode = async () => {
    setError(null);
    setSuccess(null);
    setActionLoading(true);

    try {
      const data = await generateTelegramCode();
      setCodeData(data);
      setPageState("code_generated");

      // Start countdown timer
      const expiresAt = new Date(data.expires_at).getTime();
      const updateCountdown = () => {
        const remaining = Math.max(
          0,
          Math.floor((expiresAt - Date.now()) / 1000)
        );
        setTimeLeft(remaining);
        if (remaining <= 0) {
          clearTimers();
          setPageState("not_linked");
          setCodeData(null);
          setError("Verification code expired. Please generate a new one.");
        }
      };
      updateCountdown();
      countdownRef.current = setInterval(updateCountdown, 1000);

      // Start polling for verification
      pollRef.current = setInterval(async () => {
        try {
          const statusData = await getTelegramStatus();
          if (statusData.linked) {
            setStatus(statusData);
            setPageState("linked");
            setSuccess("Telegram account linked successfully!");
            setCodeData(null);
            clearTimers();
          }
        } catch {
          // Silently ignore poll errors
        }
      }, 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate code");
    } finally {
      setActionLoading(false);
    }
  };

  const handleUnlink = async () => {
    setError(null);
    setSuccess(null);
    setActionLoading(true);

    try {
      await unlinkTelegram();
      setStatus(null);
      setPageState("not_linked");
      setSuccess("Telegram account disconnected.");
      setConfirmDisconnect(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to unlink");
    } finally {
      setActionLoading(false);
    }
  };

  const handleTestMessage = async () => {
    setError(null);
    setSuccess(null);
    setActionLoading(true);

    try {
      await sendTelegramTestMessage();
      setSuccess("Test message sent! Check your Telegram.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to send test message"
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleCopyCode = async () => {
    if (!codeData) return;
    try {
      await navigator.clipboard.writeText(`/start ${codeData.code}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setSuccess("Select and copy the command manually.");
    }
  };

  const formatTimeLeft = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Back link */}
      <Link
        href="/dashboard/settings/communications"
        className="inline-flex items-center gap-2 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors text-sm"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Communications
      </Link>

      {/* Page header */}
      <div className="flex items-center gap-3">
        <div className="p-3 bg-slate-100 dark:bg-slate-800 rounded-lg">
          <MessageCircle className="h-6 w-6 text-blue-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Telegram</h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm">
            Configure bot setup and link your Telegram account
          </p>
        </div>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner
          onRetry={async () => {
            setIsRetrying(true);
            await fetchBotConfig();
            await fetchStatus();
            setIsRetrying(false);
          }}
          isRetrying={isRetrying}
          message="Unable to connect to server. Telegram settings are unavailable."
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

      {/* ================================================================ */}
      {/* Step 1: Bot Setup (Admin) - Story 12.3 */}
      {/* ================================================================ */}
      <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-blue-400" />
            <h2 className="text-lg font-semibold">Bot Setup</h2>
          </div>
          {botConfigured && (
            <span className="inline-flex items-center gap-1.5 bg-green-500/10 text-green-400 text-xs font-medium px-2.5 py-1 rounded-full">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Configured
            </span>
          )}
        </div>

        {botConfigured ? (
          /* Bot is configured - show status */
          <div className="space-y-4">
            <div className="bg-slate-100 dark:bg-slate-800 rounded-lg p-4 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">Bot Username</span>
                <span className="text-slate-900 dark:text-white font-mono">
                  @{botConfig.bot_username}
                </span>
              </div>
              {botConfig.configured_at && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">Configured On</span>
                  <span className="text-slate-900 dark:text-white">
                    {new Date(botConfig.configured_at).toLocaleDateString()}
                  </span>
                </div>
              )}
            </div>

            {/* Remove bot token */}
            {!confirmRemoveBot ? (
              <button
                onClick={() => setConfirmRemoveBot(true)}
                disabled={isOffline || botActionLoading}
                title={
                  isOffline
                    ? "Cannot remove token while disconnected"
                    : undefined
                }
                className="w-full text-red-400 hover:text-red-300 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-colors flex items-center justify-center gap-2 py-2"
                aria-label="Remove bot token"
              >
                <Trash2 className="h-4 w-4" />
                Remove Bot Token
              </button>
            ) : (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 space-y-3">
                <p className="text-red-400 text-sm">
                  Are you sure? Removing the bot token will disable all Telegram
                  notifications.
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={handleRemoveBotToken}
                    disabled={botActionLoading}
                    className="flex-1 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-3 py-2 transition-colors"
                  >
                    {botActionLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin mx-auto" />
                    ) : (
                      "Yes, Remove"
                    )}
                  </button>
                  <button
                    onClick={() => setConfirmRemoveBot(false)}
                    className="flex-1 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-900 dark:text-white text-sm font-medium rounded-lg px-3 py-2 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Bot is NOT configured - show setup form */
          <div className="space-y-4">
            <p className="text-slate-500 dark:text-slate-400 text-sm">
              A Telegram bot token is required before users can link their
              accounts. Create a bot via{" "}
              <span className="text-slate-900 dark:text-white font-mono">@BotFather</span> on
              Telegram to get a token.
            </p>

            <div className="space-y-3">
              <h3 className="text-sm font-medium text-slate-600 dark:text-slate-300">
                How to get a bot token:
              </h3>
              <ol className="list-decimal list-inside space-y-2 text-sm text-slate-500 dark:text-slate-400">
                <li>
                  Open Telegram and search for{" "}
                  <span className="text-slate-900 dark:text-white font-mono">@BotFather</span>
                </li>
                <li>
                  Send <span className="font-mono text-slate-900 dark:text-white">/newbot</span> and
                  follow the prompts
                </li>
                <li>Copy the bot token provided by BotFather</li>
                <li>Paste it below and click &quot;Validate Token&quot;</li>
              </ol>
            </div>

            {/* Token input */}
            <div className="space-y-2">
              <label
                htmlFor="bot-token"
                className="block text-sm font-medium text-slate-600 dark:text-slate-300"
              >
                Bot Token
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Key className="h-4 w-4 text-slate-500" />
                </div>
                <input
                  id="bot-token"
                  type={showToken ? "text" : "password"}
                  value={botToken}
                  onChange={(e) => setBotToken(e.target.value)}
                  placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyz"
                  disabled={isOffline}
                  className="w-full bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg pl-10 pr-12 py-3 text-slate-900 dark:text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 font-mono text-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowToken(!showToken)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
                  aria-label={showToken ? "Hide token" : "Show token"}
                >
                  {showToken ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            {/* Validate button */}
            <button
              onClick={handleValidateToken}
              disabled={
                !botToken.trim() || botActionLoading || isOffline
              }
              title={
                isOffline
                  ? "Cannot validate token while disconnected"
                  : !botToken.trim()
                    ? "Enter a bot token first"
                    : undefined
              }
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-3 transition-colors flex items-center justify-center gap-2"
              aria-label="Validate bot token"
            >
              {botActionLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              Validate Token
            </button>
          </div>
        )}
      </div>

      {/* ================================================================ */}
      {/* Step 2: Account Linking (User) */}
      {/* ================================================================ */}

      {/* Loading state */}
      {pageState === "loading" && (
        <div className="bg-white dark:bg-slate-900 rounded-xl p-8 border border-slate-200 dark:border-slate-800 flex items-center justify-center">
          <Loader2 className="h-6 w-6 text-slate-400 animate-spin" />
        </div>
      )}

      {/* Bot not configured warning */}
      {!botConfigured && pageState !== "loading" && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg px-4 py-3 text-sm text-amber-400">
          Telegram bot not configured. An administrator must set up the bot
          token first before accounts can be linked.
        </div>
      )}

      {/* Not linked state */}
      {pageState === "not_linked" && (
        <div
          className={`bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 space-y-6 ${!botConfigured ? "opacity-60 pointer-events-none" : ""}`}
          aria-disabled={!botConfigured}
        >
          <div className="space-y-4">
            <h2 className="text-lg font-semibold">
              Connect Your Telegram Account
            </h2>
            <p className="text-slate-500 dark:text-slate-400 text-sm">
              Link your Telegram account to receive glucose alerts and
              notifications directly in Telegram.
            </p>
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-medium text-slate-600 dark:text-slate-300">
              How it works:
            </h3>
            <ol className="list-decimal list-inside space-y-2 text-sm text-slate-500 dark:text-slate-400">
              <li>
                Click &quot;Generate Code&quot; below to get a verification code
              </li>
              <li>
                Open Telegram and search for{" "}
                {status?.bot_username || botConfig?.bot_username ? (
                  <span className="text-slate-900 dark:text-white font-mono">
                    @{status?.bot_username || botConfig?.bot_username}
                  </span>
                ) : (
                  "the GlycemicGPT bot"
                )}
              </li>
              <li>
                Send the command{" "}
                <span className="font-mono text-slate-900 dark:text-white">/start YOUR_CODE</span>{" "}
                to the bot
              </li>
            </ol>
          </div>

          <button
            onClick={handleGenerateCode}
            disabled={actionLoading || isOffline || !botConfigured}
            title={
              isOffline
                ? "Cannot generate code while disconnected"
                : !botConfigured
                  ? "Bot must be configured first"
                  : undefined
            }
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-3 transition-colors flex items-center justify-center gap-2"
            aria-label="Generate verification code"
          >
            {actionLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <MessageCircle className="h-4 w-4" />
            )}
            Generate Code
          </button>
        </div>
      )}

      {/* Code generated state */}
      {pageState === "code_generated" && codeData && (
        <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 space-y-6">
          <div className="space-y-2">
            <h2 className="text-lg font-semibold">Verification Code</h2>
            <p className="text-slate-500 dark:text-slate-400 text-sm">
              Send this command to{" "}
              <span className="text-slate-900 dark:text-white font-mono">
                @{codeData.bot_username}
              </span>{" "}
              on Telegram:
            </p>
          </div>

          {/* Code display */}
          <div className="bg-slate-100 dark:bg-slate-800 rounded-lg p-4 flex items-center justify-between gap-3">
            <code className="text-2xl font-mono tracking-widest text-slate-900 dark:text-white select-all">
              /start {codeData.code}
            </code>
            <button
              onClick={handleCopyCode}
              className="p-2 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white shrink-0"
              aria-label="Copy command to clipboard"
            >
              {copied ? (
                <CheckCircle2 className="h-5 w-5 text-green-400" />
              ) : (
                <Copy className="h-5 w-5" />
              )}
            </button>
          </div>

          {/* Countdown */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-500 dark:text-slate-400">
              Code expires in{" "}
              <span
                className={`font-mono ${timeLeft <= 60 ? "text-red-400" : "text-slate-900 dark:text-white"}`}
              >
                {formatTimeLeft(timeLeft)}
              </span>
            </span>
            <span className="text-slate-500 flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              Waiting for verification...
            </span>
          </div>

          {/* Cancel */}
          <button
            onClick={() => {
              clearTimers();
              setPageState("not_linked");
              setCodeData(null);
            }}
            className="w-full text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white text-sm transition-colors"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Linked state */}
      {pageState === "linked" && status?.link && (
        <div className="space-y-4">
          {/* Connection status card */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Connection Status</h2>
              <span className="inline-flex items-center gap-1.5 bg-green-500/10 text-green-400 text-xs font-medium px-2.5 py-1 rounded-full">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Connected
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm">
              {status.link.username && (
                <div>
                  <span className="text-slate-500">Username</span>
                  <p className="text-slate-900 dark:text-white font-mono mt-0.5">
                    @{status.link.username}
                  </p>
                </div>
              )}
              <div>
                <span className="text-slate-500">Linked</span>
                <p className="text-slate-900 dark:text-white mt-0.5">
                  {new Date(status.link.linked_at).toLocaleDateString()}
                </p>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 border border-slate-200 dark:border-slate-800 space-y-3">
            <h2 className="text-lg font-semibold">Actions</h2>

            <button
              onClick={handleTestMessage}
              disabled={actionLoading || isOffline}
              title={
                isOffline
                  ? "Cannot send test message while disconnected"
                  : undefined
              }
              className="w-full bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed text-slate-900 dark:text-white font-medium rounded-lg px-4 py-3 transition-colors flex items-center justify-center gap-2"
              aria-label="Send test message"
            >
              {actionLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Send Test Message
            </button>

            {!confirmDisconnect ? (
              <button
                onClick={() => setConfirmDisconnect(true)}
                disabled={isOffline}
                title={
                  isOffline
                    ? "Cannot disconnect while disconnected from server"
                    : undefined
                }
                className="w-full text-red-400 hover:text-red-300 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-colors flex items-center justify-center gap-2 py-2"
                aria-label="Disconnect Telegram"
              >
                <Unlink className="h-4 w-4" />
                Disconnect Telegram
              </button>
            ) : (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 space-y-3">
                <p className="text-red-400 text-sm">
                  Are you sure? You will stop receiving Telegram notifications.
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={handleUnlink}
                    disabled={actionLoading}
                    className="flex-1 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-3 py-2 transition-colors"
                  >
                    Yes, Disconnect
                  </button>
                  <button
                    onClick={() => setConfirmDisconnect(false)}
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
    </div>
  );
}
