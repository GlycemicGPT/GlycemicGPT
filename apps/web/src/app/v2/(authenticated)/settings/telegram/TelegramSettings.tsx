"use client";

import { Button, Icon } from "@/base";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import {
  ApiError,
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
import { SettingsOfflineNotice } from "@/components/settings/SettingsOfflineNotice";
import { SettingsReadOnlyValue } from "@/components/settings/SettingsReadOnlyValue";
import { TextInput } from "@/components/TextInput";
import { LoadingState } from "@/components/LoadingState";
import { DestructiveButton } from "@/components/DestructiveButton";
import { ConnectionInfoCallout } from "@/components/integrations/ConnectionSettings";
import { TelegramLogo } from "@/components/TelegramLogo";
import { useConfirmation } from "@/compositions/ConfirmationProvider";
import { twMerge } from "@/lib/ui/twMerge";

type PageState = "loading" | "not_linked" | "code_generated" | "linked";

interface TelegramSettingsProps {
  onLinkStatusChange?: () => void;
}

export function TelegramSettings({
  onLinkStatusChange,
}: TelegramSettingsProps = {}) {
  const pathname = usePathname();
  const router = useRouter();
  const { confirm } = useConfirmation();
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

  // Bot configuration state.
  const [botConfig, setBotConfig] = useState<TelegramBotConfigResponse | null>(
    null,
  );
  const [botToken, setBotToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [botActionLoading, setBotActionLoading] = useState(false);
  const [botConfigError, setBotConfigError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const botConfigured = botConfig?.configured === true;
  const canManageBot = botConfig?.can_manage === true;

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

  const redirectIfUnauthorized = useCallback(
    (err: unknown) => {
      if (!(err instanceof ApiError) || err.status !== 401) {
        return false;
      }

      router.replace(
        `/login?expired=true&redirect=${encodeURIComponent(pathname)}`,
      );
      return true;
    },
    [pathname, router],
  );

  const fetchBotConfig = useCallback(async () => {
    setBotConfigError(null);
    try {
      const data = await getTelegramBotConfig();
      setBotConfig(data);
      return data;
    } catch (err) {
      if (redirectIfUnauthorized(err)) {
        return null;
      }
      setBotConfigError("Unable to load Telegram bot configuration.");
      return null;
    }
  }, [redirectIfUnauthorized]);

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
      if (redirectIfUnauthorized(err)) {
        return;
      }

      const isBotUnavailable = err instanceof ApiError && err.status === 503;
      if (!isBotUnavailable) {
        setIsOffline(true);
      }
      if (isBotUnavailable) {
        setIsOffline(false);
      }
      if (pageState === "loading") {
        setPageState("not_linked");
      }
    }
  }, [clearTimers, pageState, redirectIfUnauthorized]);

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
        setBotConfigError(null);
        setBotConfig({
          configured: true,
          can_manage: true,
          bot_username: result.bot_username,
          configured_at: new Date().toISOString(),
        });
        setBotToken("");
        setSuccess(`Bot token validated! Connected as @${result.bot_username}`);
        // Re-fetch status now that bot is configured
        await fetchStatus();
        onLinkStatusChange?.();
      } else {
        setError(
          "Token validation failed. Please check the token and try again.",
        );
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to validate bot token",
      );
    } finally {
      setBotActionLoading(false);
    }
  };

  const handleRemoveBotToken = async () => {
    const confirmed = await confirm({
      title: "Remove existing bot?",
      description: (
        <>
          Removing <strong>@{botConfig?.bot_username}</strong> will disconnect
          every linked Telegram account and delete pending verification codes.
          Telegram notifications will stop until a new bot is added.
        </>
      ),
      confirmLabel: "Remove bot for everyone",
      tone: "destructive",
    });
    if (!confirmed) return;

    setError(null);
    setSuccess(null);
    setBotActionLoading(true);

    try {
      await removeTelegramBotToken();
      onLinkStatusChange?.();
      const refreshedConfig = await fetchBotConfig();
      clearTimers();
      setStatus(null);
      setCodeData(null);
      setPageState("not_linked");
      if (refreshedConfig?.configured) {
        await fetchStatus();
        setSuccess(
          `Database bot removed. @${refreshedConfig.bot_username} remains configured through the server environment.`,
        );
      } else if (refreshedConfig) {
        setSuccess("Existing Telegram bot removed. You can now add a new bot.");
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to remove bot token",
      );
    } finally {
      setBotActionLoading(false);
    }
  };

  const handleGenerateCode = async () => {
    clearTimers();
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
          Math.floor((expiresAt - Date.now()) / 1000),
        );
        setTimeLeft(remaining);
        if (remaining <= 0) {
          clearTimers();
          setPageState("not_linked");
          setCodeData(null);
          setError("Verification code expired. Please generate a new one.");
          return false;
        }
        return true;
      };
      if (!updateCountdown()) return;
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
            onLinkStatusChange?.();
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
    const confirmed = await confirm({
      title: "Disconnect Telegram?",
      description:
        "You will stop receiving Telegram notifications until you connect your account again.",
      confirmLabel: "Yes, disconnect",
      tone: "destructive",
    });
    if (!confirmed) return;

    setError(null);
    setSuccess(null);
    setActionLoading(true);

    try {
      await unlinkTelegram();
      setStatus(null);
      setPageState("not_linked");
      setSuccess("Telegram account disconnected.");
      onLinkStatusChange?.();
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
        err instanceof Error ? err.message : "Failed to send test message",
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
        data-settings-back-link
        href="/settings/alarms-notification#delivery-channels"
        className="inline-flex items-center gap-2 text-foreground-secondary hover:text-foreground-primary transition-colors font_body_2"
      >
        <Icon decorative icon="chevron" className="h-4 w-4 rotate-180" />
        Back to Communications
      </Link>

      {/* Page header */}
      <div className="flex items-center gap-3" data-settings-page-header>
        <div className="p-3 bg-surface-secondary rounded-panel">
          <TelegramLogo decorative className="h-6 w-6" />
        </div>
        <div>
          <h1 className="font_poppins font_header_2">Telegram</h1>
          <p className="text-foreground-secondary font_body_2">
            Configure bot setup and link your Telegram account
          </p>
        </div>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <SettingsOfflineNotice
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
          className="bg-signal-error-fill/10 border border-signal-error-text text-signal-error-text rounded-panel px-4 py-3 font_body_2"
        >
          {error}
        </div>
      )}

      {/* Success banner */}
      {success && (
        <div
          role="status"
          className="bg-signal-check-fill/10 border border-signal-check-text text-signal-check-text rounded-panel px-4 py-3 font_body_2"
        >
          {success}
        </div>
      )}

      {/* ================================================================ */}
      {/* Step 1: Bot setup for administrators */}
      {/* ================================================================ */}
      {botConfigError && (
        <div
          role="alert"
          className="flex items-center justify-between gap-4 rounded-panel border border-signal-error-text bg-signal-error-fill/10 px-4 py-3 font_body_2 text-signal-error-text"
        >
          <p>{botConfigError}</p>
          <Button
            type="button"
            onClick={() => void fetchBotConfig()}
            className="font_ui_label underline"
          >
            Retry
          </Button>
        </div>
      )}

      {botConfigured && botConfig && (
        <ConnectionInfoCallout
          iconSlot={<TelegramLogo decorative className="h-5 w-5 shrink-0" />}
          title="Existing Telegram bot available"
        >
          <p>
            Lumose already has <strong>@{botConfig.bot_username}</strong>{" "}
            configured. Connect your Telegram account below to use this bot.
          </p>
          {!canManageBot && (
            <p className="mt-2">
              Caregiver accounts cannot remove or replace the shared bot.
            </p>
          )}
        </ConnectionInfoCallout>
      )}

      {canManageBot && botConfigured && botConfig && (
        <section
          aria-labelledby="existing-bot-heading"
          className="space-y-5 rounded-panel border border-border-default bg-surface-primary p-6"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2
              className="font_poppins font_header_4"
              id="existing-bot-heading"
            >
              Existing bot
            </h2>
            <span className="inline-flex items-center gap-1.5 rounded-pill bg-signal-check-fill/10 px-2.5 py-1 font_ui_caption text-signal-check-text">
              <Icon decorative icon="check" className="h-3.5 w-3.5" />
              Active
            </span>
          </div>

          <dl className="grid gap-4 rounded-panel bg-surface-secondary p-4 sm:grid-cols-2">
            <SettingsReadOnlyValue
              label="Bot username"
              value={`@${botConfig.bot_username}`}
            />
            <SettingsReadOnlyValue
              label="Configured"
              value={
                botConfig.configured_at
                  ? new Date(botConfig.configured_at).toLocaleDateString()
                  : "Server environment"
              }
            />
          </dl>

          {botConfig.configured_at ? (
            <div className="space-y-3 border-t border-border-default pt-5">
              <div className="space-y-1">
                <h3 className="font_ui_label text-foreground-primary">
                  Replace this bot
                </h3>
                <p className="font_body_3 text-foreground-secondary">
                  Remove the existing bot first. This disconnects every linked
                  Telegram account, then exposes the fresh bot setup form.
                </p>
              </div>
              <DestructiveButton
                aria-label="Remove existing bot"
                disabled={isOffline || botActionLoading}
                onClick={() => void handleRemoveBotToken()}
              >
                <Icon decorative icon="trash" className="h-4 w-4" />
                {botActionLoading ? "Removing..." : "Remove existing bot"}
              </DestructiveButton>
            </div>
          ) : (
            <ConnectionInfoCallout title="Managed outside Lumose">
              This bot is configured through the server environment. Remove the
              environment setting before adding a different bot here.
            </ConnectionInfoCallout>
          )}
        </section>
      )}

      {canManageBot && botConfig !== null && !botConfigured && (
        <section
          aria-labelledby="new-bot-heading"
          className="space-y-5 rounded-panel border border-border-default bg-surface-primary p-6"
        >
          <div className="space-y-2">
            <h2 className="font_poppins font_header_4" id="new-bot-heading">
              Add a new Telegram bot
            </h2>
            <p className="font_body_2 text-foreground-secondary">
              Create a completely new bot with @BotFather, then validate its
              token before Lumose stores it securely.
            </p>
          </div>

          <div className="space-y-3">
            <h3 className="font_ui_label text-foreground-secondary">
              Create the bot:
            </h3>
            <ol className="list-decimal list-inside space-y-2 font_body_2 text-foreground-secondary">
              <li>
                Open Telegram and search for{" "}
                <span className="text-foreground-primary font_poppins">
                  @BotFather
                </span>
              </li>
              <li>
                Send{" "}
                <span className="font_poppins text-foreground-primary">
                  /newbot
                </span>{" "}
                and follow the prompts
              </li>
              <li>Copy the new bot token provided by BotFather</li>
              <li>Paste it below and add the bot</li>
            </ol>
          </div>

          <TextInput
            disabled={isOffline}
            id="bot-token"
            label="New bot token"
            leadingAdornment={
              <Icon
                decorative
                icon="key"
                className="h-4 w-4 text-foreground-secondary"
              />
            }
            onChange={(e) => setBotToken(e.target.value)}
            placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyz"
            trailingAdornment={
              <Button
                type="button"
                onClick={() => setShowToken(!showToken)}
                className="flex items-center text-foreground-secondary transition-colors hover:text-foreground-primary"
                aria-label={showToken ? "Hide token" : "Show token"}
              >
                <Icon
                  decorative
                  icon={showToken ? "eye-slash" : "eye"}
                  className="h-4 w-4"
                />
              </Button>
            }
            type={showToken ? "text" : "password"}
            value={botToken}
          />

          <Button
            onClick={handleValidateToken}
            disabled={!botToken.trim() || botActionLoading || isOffline}
            title={
              isOffline
                ? "Cannot add a bot while disconnected"
                : !botToken.trim()
                  ? "Enter a bot token first"
                  : undefined
            }
            className="w-full bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed text-accent-foreground font_ui_label rounded-panel px-4 py-3 transition-colors flex items-center justify-center gap-2"
            aria-label="Validate and add bot"
          >
            {botActionLoading ? (
              <Icon decorative icon="clock" className="h-4 w-4 animate-spin" />
            ) : (
              <Icon decorative icon="check" className="h-4 w-4" />
            )}
            Add bot
          </Button>
        </section>
      )}

      {/* ================================================================ */}
      {/* Step 2: Account Linking (User) */}
      {/* ================================================================ */}

      {/* Loading state */}
      {pageState === "loading" && (
        <LoadingState
          className="min-h-0 rounded-panel border border-border-default bg-surface-primary p-8"
          label="Loading Telegram settings..."
        />
      )}

      {/* Bot not configured warning */}
      {botConfig !== null &&
        !botConfigured &&
        !canManageBot &&
        pageState !== "loading" && (
          <div className="bg-signal-warning-fill/10 border border-signal-warning-text rounded-panel px-4 py-3 font_body_2 text-signal-warning-text">
            Telegram bot not configured. An administrator must set up the bot
            token first before accounts can be linked.
          </div>
        )}

      {/* Not linked state */}
      {pageState === "not_linked" && botConfigured && (
        <div className="bg-surface-primary rounded-panel p-6 border border-border-default space-y-6">
          <div className="space-y-4">
            <h2 className="font_poppins font_header_4">
              Connect with the existing bot
            </h2>
            <p className="text-foreground-secondary font_body_2">
              Link your Telegram account to receive glucose alerts and
              notifications directly in Telegram.
            </p>
          </div>

          <div className="space-y-3">
            <h3 className="font_ui_label text-foreground-secondary">
              How it works:
            </h3>
            <ol className="list-decimal list-inside space-y-2 font_body_2 text-foreground-secondary">
              <li>
                Click &quot;Generate Code&quot; below to get a verification code
              </li>
              <li>
                Open Telegram and search for{" "}
                {status?.bot_username || botConfig?.bot_username ? (
                  <span className="text-foreground-primary font_poppins">
                    @{status?.bot_username || botConfig?.bot_username}
                  </span>
                ) : (
                  "the Lumose bot"
                )}
              </li>
              <li>
                Send the command{" "}
                <span className="font_poppins text-foreground-primary">
                  /start YOUR_CODE
                </span>{" "}
                to the bot
              </li>
            </ol>
          </div>

          <Button
            onClick={handleGenerateCode}
            disabled={actionLoading || isOffline}
            title={
              isOffline ? "Cannot generate code while disconnected" : undefined
            }
            className="w-full bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed text-accent-foreground font_ui_label rounded-panel px-4 py-3 transition-colors flex items-center justify-center gap-2"
          >
            {actionLoading ? (
              <Icon decorative icon="clock" className="h-4 w-4 animate-spin" />
            ) : (
              <TelegramLogo decorative className="h-4 w-4" />
            )}
            Generate Code
          </Button>
        </div>
      )}

      {/* Code generated state */}
      {pageState === "code_generated" && codeData && (
        <div className="bg-surface-primary rounded-panel p-6 border border-border-default space-y-6">
          <div className="space-y-2">
            <h2 className="font_poppins font_header_4">Verification Code</h2>
            <p className="text-foreground-secondary font_body_2">
              Send this command to{" "}
              <span className="text-foreground-primary font_poppins">
                @{codeData.bot_username}
              </span>{" "}
              on Telegram:
            </p>
          </div>

          {/* Code display */}
          <div className="bg-surface-secondary rounded-panel p-4 flex items-center justify-between gap-3">
            <code className="font_header_2 font_poppins text-foreground-primary select-all">
              /start {codeData.code}
            </code>
            <Button
              onClick={handleCopyCode}
              className="p-2 hover:bg-surface-secondary rounded-panel transition-colors text-foreground-primary hover:text-foreground-primary shrink-0"
              aria-label="Copy command to clipboard"
            >
              {copied ? (
                <Icon
                  decorative
                  icon="check"
                  className="h-5 w-5 text-signal-check-text"
                />
              ) : (
                <Icon decorative icon="copy" className="h-5 w-5" />
              )}
            </Button>
          </div>

          {/* Countdown */}
          <div className="flex items-center justify-between font_body_2">
            <span className="text-foreground-secondary">
              Code expires in{" "}
              <span
                className={twMerge(
                  "font_poppins",
                  timeLeft <= 60
                    ? "text-signal-error-text"
                    : "text-foreground-primary",
                )}
              >
                {formatTimeLeft(timeLeft)}
              </span>
            </span>
            <span className="text-foreground-secondary flex items-center gap-1">
              <Icon decorative icon="clock" className="h-3 w-3" />
              Waiting for verification...
            </span>
          </div>
          <span
            aria-atomic="true"
            aria-live="polite"
            className="sr-only"
            role="status"
          >
            Code expires in{" "}
            {timeLeft <= 60
              ? "less than one minute"
              : `${Math.ceil(timeLeft / 60)} minutes`}
            . Waiting for verification.
          </span>

          {/* Cancel */}
          <Button
            onClick={() => {
              clearTimers();
              setPageState("not_linked");
              setCodeData(null);
            }}
            className="w-full text-foreground-secondary hover:text-foreground-primary font_body_2 transition-colors"
          >
            Cancel
          </Button>
        </div>
      )}

      {/* Linked state */}
      {pageState === "linked" && status?.link && (
        <div className="space-y-4">
          {/* Connection status card */}
          <div className="bg-surface-primary rounded-panel p-6 border border-border-default space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font_poppins font_header_4">Connection Status</h2>
              <span className="inline-flex items-center gap-1.5 bg-signal-check-fill/10 text-signal-check-text font_ui_caption px-2.5 py-1 rounded-pill">
                <Icon decorative icon="check" className="h-3.5 w-3.5" />
                Connected
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 font_body_2">
              {status.link.username && (
                <div>
                  <span className="text-foreground-secondary">Username</span>
                  <p className="text-foreground-primary font_poppins mt-0.5">
                    @{status.link.username}
                  </p>
                </div>
              )}
              <div>
                <span className="text-foreground-secondary">Linked</span>
                <p className="text-foreground-primary mt-0.5">
                  {new Date(status.link.linked_at).toLocaleDateString()}
                </p>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="bg-surface-primary rounded-panel p-6 border border-border-default space-y-3">
            <h2 className="font_poppins font_header_4">Actions</h2>

            <Button
              onClick={handleTestMessage}
              disabled={actionLoading || isOffline}
              title={
                isOffline
                  ? "Cannot send test message while disconnected"
                  : undefined
              }
              className="w-full bg-surface-secondary hover:bg-surface-secondary disabled:opacity-50 disabled:cursor-not-allowed text-foreground-primary font_ui_label rounded-panel px-4 py-3 transition-colors flex items-center justify-center gap-2"
              aria-label="Send test message"
            >
              {actionLoading ? (
                <Icon
                  decorative
                  icon="clock"
                  className="h-4 w-4 animate-spin"
                />
              ) : (
                <Icon decorative icon="share" className="h-4 w-4" />
              )}
              Send Test Message
            </Button>

            <Button
              onClick={() => void handleUnlink()}
              disabled={isOffline || actionLoading}
              title={
                isOffline
                  ? "Cannot disconnect while disconnected from server"
                  : undefined
              }
              className="w-full text-signal-error-text hover:text-signal-error-text disabled:opacity-50 disabled:cursor-not-allowed font_body_2 transition-colors flex items-center justify-center gap-2 py-2"
            >
              <Icon decorative icon="circle-slash" className="h-4 w-4" />
              Disconnect Telegram
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
