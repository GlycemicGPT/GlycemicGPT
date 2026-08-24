import { useId, type ReactElement } from "react";

import { lumoseLogoPaths } from "@/components/LumoseLogoIcon/LumoseLogoIcon";
import { twMerge } from "@/lib/ui/twMerge";

import type { LumoseLogoTextIconProps } from "./LumoseLogoTextIcon.types";

const wordmarkPaths = [
  "M57.06,51.33a8.55,8.55,0,0,1-8.59-8.59V10.82h6.05V42.74a2.45,2.45,0,0,0,2.54,2.53h24a2.44,2.44,0,0,0,2.53-2.53V10.82h6.06V42.74a8.62,8.62,0,0,1-8.59,8.59Z",
  "M164.74,51.33V19.41a2.49,2.49,0,0,0-2.61-2.54H145.4a2.42,2.42,0,0,0-2.46,2.54V51.33h-6.13V19.41a2.42,2.42,0,0,0-2.46-2.54h-16.8A2.46,2.46,0,0,0,115,19.41V51.33H109V10.82h53.17a8.25,8.25,0,0,1,6.07,2.52,8.23,8.23,0,0,1,2.52,6.07V51.33Z",
  "M255.62,50.33A8.6,8.6,0,0,1,247,41.82h6.06a2.44,2.44,0,0,0,2.53,2.45h24a2.45,2.45,0,0,0,2.54-2.53V35.6a2.42,2.42,0,0,0-2.54-2.46h-24A8.6,8.6,0,0,1,247,24.55V18.41a8.23,8.23,0,0,1,2.52-6.07,8.25,8.25,0,0,1,6.07-2.52h24a8.18,8.18,0,0,1,6.1,2.51,8.3,8.3,0,0,1,2.49,6h-6.05a2.46,2.46,0,0,0-2.54-2.46h-24a2.46,2.46,0,0,0-2.54,2.54v6.14A2.42,2.42,0,0,0,255.62,27h24a8.18,8.18,0,0,1,6.1,2.51,8.3,8.3,0,0,1,2.49,6.08v6.14a8.55,8.55,0,0,1-8.59,8.59Z",
  "M336,26.72V18.13a2.45,2.45,0,0,0-2.53-2.54h-24a2.43,2.43,0,0,0-2.52,2.54V41.45A2.43,2.43,0,0,0,309.45,44h32.61v6.06H309.45a8.6,8.6,0,0,1-8.59-8.6V18.13a8.19,8.19,0,0,1,2.52-6.06,8.17,8.17,0,0,1,6.07-2.54h24a8.15,8.15,0,0,1,6.06,2.54,8.16,8.16,0,0,1,2.53,6.06V32.86H309.93V26.68Z",
] as const;

export function LumoseLogoTextIcon({
  className,
  decorative = false,
  title = "Lumose",
  ...props
}: LumoseLogoTextIconProps): ReactElement {
  const gradientId = `lumose-logo-text-icon-gradient-${useId().replaceAll(
    /[^a-zA-Z0-9]/g,
    "",
  )}`;
  const accessibleTitle = decorative ? undefined : title;

  return (
    <svg
      {...props}
      aria-hidden={accessibleTitle ? undefined : true}
      aria-label={accessibleTitle}
      className={twMerge("inline h-auto w-52 flex-none", className)}
      focusable="false"
      role={accessibleTitle ? "img" : undefined}
      viewBox="0 0 342.06 54.91"
    >
      <defs>
        <linearGradient
          gradientUnits="userSpaceOnUse"
          id={gradientId}
          x1="0"
          x2="268.88"
          y1="0"
          y2="243.31"
        >
          <stop offset="0" stopColor="var(--color-brand-gradient-start)" />
          <stop offset="0.48" stopColor="var(--color-brand-gradient-middle)" />
          <stop offset="1" stopColor="var(--color-brand-gradient-end)" />
        </linearGradient>
      </defs>
      <polygon
        fill="currentColor"
        points="34.78 45.2 34.78 51.33 0 51.33 0 0 6.13 0 6.13 45.2 34.78 45.2"
      />
      {wordmarkPaths.map((path) => (
        <path d={path} fill="currentColor" key={path} />
      ))}
      <g transform="translate(183.98 7.42) scale(0.1952)">
        {lumoseLogoPaths.map((path) => (
          <path d={path} fill={`url(#${gradientId})`} key={path} />
        ))}
      </g>
    </svg>
  );
}
