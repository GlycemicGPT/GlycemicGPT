"use client";

/**
 * Story 12.2: Communications Settings Hub
 *
 * Unified hub for configuring notification channels: Telegram, and future
 * channels (Discord, Email, etc.). Shows connection status for each channel
 * and links to detailed configuration pages.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  MessageCircle,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronRight,
  Radio,
  Mail,
  Hash,
} from "lucide-react";
import {
  getTelegramStatus,
  type TelegramStatusResponse,
} from "@/lib/api";
import { OfflineBanner } from "@/components/ui/offline-banner";

export default function CommunicationsPage() {
  const [telegramStatus, setTelegramStatus] =
    useState<TelegramStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isOffline, setIsOffline] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await getTelegramStatus();
      setTelegramStatus(data);
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
    fetchStatus();
  }, [fetchStatus]);

  const telegramLinked = telegramStatus?.linked === true;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <Link
          href="/dashboard/settings"
          className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mb-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Settings
        </Link>
        <h1 className="text-2xl font-bold">Communications</h1>
        <p className="text-slate-500 dark:text-slate-400">
          Configure notification channels for alerts and daily briefs
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <OfflineBanner
          onRetry={async () => {
            setIsRetrying(true);
            await fetchStatus();
            setIsRetrying(false);
          }}
          isRetrying={isRetrying}
          message="Unable to connect to server. Channel status may be outdated."
        />
      )}

      {/* Loading state */}
      {isLoading && (
        <div
          className="bg-white dark:bg-slate-900 rounded-xl p-12 border border-slate-200 dark:border-slate-800 text-center"
          role="status"
          aria-label="Loading communication channels"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading channels...</p>
        </div>
      )}

      {/* Channel cards */}
      {!isLoading && (
        <div className="space-y-4">
          {/* Telegram channel */}
          <Link
            href="/dashboard/settings/telegram"
            className="block bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 hover:border-slate-300 dark:hover:border-slate-700 transition-colors group"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-blue-500/10 rounded-lg group-hover:bg-blue-500/20 transition-colors">
                  <MessageCircle className="h-6 w-6 text-blue-400" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold group-hover:text-slate-900 dark:group-hover:text-white transition-colors">
                      Telegram
                    </h2>
                    {telegramLinked ? (
                      <span className="inline-flex items-center gap-1 bg-green-500/10 text-green-400 text-xs font-medium px-2 py-0.5 rounded-full">
                        <CheckCircle2 className="h-3 w-3" />
                        Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400 text-xs font-medium px-2 py-0.5 rounded-full">
                        <XCircle className="h-3 w-3" />
                        Not Connected
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                    {telegramLinked && telegramStatus?.link?.username
                      ? `Linked as @${telegramStatus.link.username}`
                      : "Receive alerts and daily briefs via Telegram bot"}
                  </p>
                </div>
              </div>
              <ChevronRight className="h-5 w-5 text-slate-400 dark:text-slate-600 group-hover:text-slate-500 dark:group-hover:text-slate-400 transition-colors" />
            </div>
          </Link>

          {/* Future channels - coming soon */}
          <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl border border-slate-200/50 dark:border-slate-800/50 p-6 opacity-60">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-slate-100 dark:bg-slate-800 rounded-lg">
                  <Hash className="h-6 w-6 text-slate-500" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold text-slate-500">
                      Discord
                    </h2>
                    <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500">
                      Coming Soon
                    </span>
                  </div>
                  <p className="text-sm text-slate-600 mt-1">
                    Receive notifications via Discord webhook
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl border border-slate-200/50 dark:border-slate-800/50 p-6 opacity-60">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-slate-100 dark:bg-slate-800 rounded-lg">
                  <Mail className="h-6 w-6 text-slate-500" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold text-slate-500">
                      Email
                    </h2>
                    <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500">
                      Coming Soon
                    </span>
                  </div>
                  <p className="text-sm text-slate-600 mt-1">
                    Receive daily brief summaries via email
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Info card */}
      <div className="bg-slate-50/50 dark:bg-slate-900/50 rounded-xl p-4 border border-slate-200 dark:border-slate-800">
        <div className="flex items-start gap-2">
          <Radio className="h-4 w-4 text-slate-500 mt-0.5 shrink-0" />
          <p className="text-xs text-slate-500">
            Communication channels determine how you receive glucose alerts,
            daily brief summaries, and caregiver notifications. Configure at
            least one channel to stay informed about your glucose trends.
          </p>
        </div>
      </div>
    </div>
  );
}
