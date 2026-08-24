import { useId, type ReactElement } from "react";

import { twMerge } from "@/lib/ui/twMerge";

import type { TelegramLogoProps } from "./TelegramLogo.types";

const telegramPlanePath =
  "M22.987 10.209c.124-.806-.642-1.441-1.358-1.127L7.365 15.345c-.514.225-.476 1.003.056 1.173l2.942.937c.562.179 1.17.086 1.66-.253l6.632-4.582c.2-.138.418.147.247.323l-4.774 4.922c-.463.477-.371 1.286.186 1.636l5.345 3.351c.6.376 1.37-.001 1.483-.726z";

export function TelegramLogo({
  className,
  decorative = false,
  title = "Telegram",
  ...props
}: TelegramLogoProps): ReactElement {
  const gradientId = `telegram-logo-gradient-${useId().replaceAll(
    /[^a-zA-Z0-9]/g,
    "",
  )}`;
  const accessibleTitle = decorative ? undefined : title;

  return (
    <svg
      {...props}
      aria-hidden={accessibleTitle ? undefined : true}
      aria-label={accessibleTitle}
      className={twMerge("inline h-6 w-6 flex-none", className)}
      focusable="false"
      role={accessibleTitle ? "img" : undefined}
      viewBox="0 0 32 32"
    >
      <defs>
        <linearGradient
          gradientUnits="userSpaceOnUse"
          id={gradientId}
          x1="16"
          x2="16"
          y1="2"
          y2="30"
        >
          <stop stopColor="var(--color-brand-telegram-gradient-start)" />
          <stop
            offset="1"
            stopColor="var(--color-brand-telegram-gradient-end)"
          />
        </linearGradient>
      </defs>
      <circle cx="16" cy="16" fill={`url(#${gradientId})`} r="14" />
      <path
        d={telegramPlanePath}
        fill="var(--color-brand-telegram-foreground)"
      />
    </svg>
  );
}
