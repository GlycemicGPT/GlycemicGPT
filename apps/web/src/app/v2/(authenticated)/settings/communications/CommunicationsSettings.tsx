"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Icon } from "@/base";

import {
  ApiError,
  getTelegramStatus,
  type TelegramStatusResponse,
} from "@/lib/api";
import { SettingsOfflineNotice } from "@/components/settings/SettingsOfflineNotice";
import { LoadingState } from "@/components/LoadingState";
import { TelegramLogo } from "@/components/TelegramLogo";

export interface CommunicationsPageProps {
  telegramHref?: string;
  telegramStatusRefreshKey?: number;
}

type TelegramChannelState = "ready" | "not_configured" | "unavailable";

export function CommunicationsSettings({
  telegramHref = "/settings/alarms-notification#telegram",
  telegramStatusRefreshKey = 0,
}: CommunicationsPageProps = {}) {
  const pathname = usePathname();
  const router = useRouter();
  const [telegramStatus, setTelegramStatus] =
    useState<TelegramStatusResponse | null>(null);
  const [telegramChannelState, setTelegramChannelState] =
    useState<TelegramChannelState>("unavailable");
  const [isLoading, setIsLoading] = useState(true);
  const [isOffline, setIsOffline] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await getTelegramStatus();
      setTelegramStatus(data);
      setTelegramChannelState("ready");
      setIsOffline(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(
          `/login?expired=true&redirect=${encodeURIComponent(pathname)}`,
        );
        return;
      }

      const expectedUnavailableStatus =
        err instanceof ApiError && err.status === 503;

      setTelegramStatus(null);
      setTelegramChannelState(
        err instanceof Error &&
          err.message.includes("Telegram bot is not configured")
          ? "not_configured"
          : "unavailable",
      );

      if (!expectedUnavailableStatus) {
        setIsOffline(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, [pathname, router]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus, telegramStatusRefreshKey]);

  const telegramLinked = telegramStatus?.linked === true;
  const telegramBotAvailable =
    telegramChannelState === "ready" &&
    Boolean(telegramStatus?.bot_username?.trim());

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div data-settings-page-header>
        <h1 className="font_poppins font_header_2">Communications</h1>
        <p className="text-foreground-secondary">
          Configure notification channels for alerts and daily briefs
        </p>
      </div>

      {/* Offline banner */}
      {isOffline && (
        <SettingsOfflineNotice
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
        <LoadingState
          className="min-h-0 rounded-panel border border-border-default bg-surface-primary p-12"
          label="Loading channels..."
        />
      )}

      {/* Channel cards */}
      {!isLoading && (
        <div className="space-y-4">
          {/* Telegram channel */}
          <Link
            href={telegramHref}
            className="block bg-surface-primary rounded-panel border border-border-default p-6 hover:border-border-hover transition-colors group"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-accent/10 rounded-panel group-hover:bg-accent/20 transition-colors">
                  <TelegramLogo decorative className="h-6 w-6" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font_poppins font_header_4 group-hover:text-foreground-primary transition-colors">
                      Telegram
                    </h2>
                    {telegramLinked ? (
                      <span className="inline-flex items-center gap-1 bg-signal-check-fill/10 text-signal-check-text font_ui_caption px-2 py-0.5 rounded-pill">
                        <Icon decorative icon="check" className="h-3 w-3" />
                        Connected
                      </span>
                    ) : telegramBotAvailable ? (
                      <span className="inline-flex items-center gap-1 bg-signal-check-fill/10 text-signal-check-text font_ui_caption px-2 py-0.5 rounded-pill">
                        <Icon decorative icon="check" className="h-3 w-3" />
                        Bot Available
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 bg-surface-secondary text-foreground-primary font_ui_caption px-2 py-0.5 rounded-pill">
                        <Icon
                          decorative
                          icon="circle-slash"
                          className="h-3 w-3"
                        />
                        {telegramChannelState === "not_configured"
                          ? "Not Configured"
                          : "Status Unavailable"}
                      </span>
                    )}
                  </div>
                  <p className="font_body_2 text-foreground-secondary mt-1">
                    {telegramLinked && telegramStatus?.link?.username
                      ? `Linked as @${telegramStatus.link.username}`
                      : telegramBotAvailable && telegramStatus?.bot_username
                        ? `@${telegramStatus.bot_username} is ready. Link your Telegram account to receive notifications.`
                        : "Receive alerts and daily briefs via Telegram bot"}
                  </p>
                </div>
              </div>
              <Icon
                decorative
                icon="chevron"
                className="h-5 w-5 text-foreground-secondary text-foreground-secondary group-hover:text-foreground-secondary group-hover:text-foreground-secondary transition-colors"
              />
            </div>
          </Link>

          {/* Future channels - coming soon */}
          <div className="bg-surface-elevated rounded-panel border border-border-default p-6 opacity-60">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-surface-secondary rounded-panel">
                  <Icon
                    decorative
                    icon="gear"
                    className="h-6 w-6 text-foreground-primary"
                  />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font_poppins font_header_4 text-foreground-primary">
                      Discord
                    </h2>
                    <span className="font_ui_caption px-2 py-0.5 rounded-pill bg-surface-secondary text-foreground-primary">
                      Coming Soon
                    </span>
                  </div>
                  <p className="font_body_2 text-foreground-primary mt-1">
                    Receive notifications via Discord webhook
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-surface-elevated rounded-panel border border-border-default p-6 opacity-60">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-surface-secondary rounded-panel">
                  <Icon
                    decorative
                    icon="mail"
                    className="h-6 w-6 text-foreground-primary"
                  />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font_poppins font_header_4 text-foreground-primary">
                      Email
                    </h2>
                    <span className="font_ui_caption px-2 py-0.5 rounded-pill bg-surface-secondary text-foreground-primary">
                      Coming Soon
                    </span>
                  </div>
                  <p className="font_body_2 text-foreground-primary mt-1">
                    Receive daily brief summaries via email
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Info card */}
      <div className="bg-surface-elevated rounded-panel p-4 border border-border-default">
        <div className="flex items-start gap-2">
          <Icon
            decorative
            icon="bell"
            className="h-4 w-4 text-foreground-primary mt-0.5 shrink-0"
          />
          <p className="font_body_3 text-foreground-primary">
            Communication channels determine how you receive glucose alerts,
            daily brief summaries, and caregiver notifications. Configure at
            least one channel to stay informed about your glucose trends.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function CommunicationsPage() {
  return <CommunicationsSettings />;
}
