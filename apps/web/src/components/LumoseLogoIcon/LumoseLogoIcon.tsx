import { useId, type ReactElement } from "react";
import { twMerge } from "@/lib/ui/twMerge";
import type { LumoseLogoIconProps } from "./LumoseLogoIcon.types";

export const lumoseLogoPaths = [
  "m126.17 18.52-16.84 17.89A51.79 51.79 0 0 0 38 111.15l-9.07 9.64h-1.38a37.2 37.2 0 0 0-11.86 1.92A76.33 76.33 0 0 1 126.17 18.52",
  "M194.26 0h-1.71a76.08 76.08 0 0 0-52.66 21.08c-.25.24-.5.48-.74.73l-4.31 4.57-.39.42-17 18-5 5.33-65 69.11-4.53 4.76-7.78 8.27-.09.09a27 27 0 0 0-7.51-1.06 25.5 25.5 0 0 0-3.84.28 27 27 0 1 0 29 36.45 26 26 0 0 0 1.56-6 27.2 27.2 0 0 0-.26-9.33 24 24 0 0 0-.7-2.63l.7-.74 7.26-7.72s12.6-13.53 12.54-13.54l42.74-45.4 11.33-12 20-21.22 1.64-1.75 11.8-12.7a51.8 51.8 0 0 1 73 71.95 50 50 0 0 1-3.92 4.71h29.82A76 76 0 0 0 268.86 78v-1.68A76.33 76.33 0 0 0 194.26 0M27.54 169.23a10.89 10.89 0 1 1 10.89-10.89 10.89 10.89 0 0 1-10.89 10.89",
  "m254.13 122.69-.95 1-23 24.54-77 82.3-6.39 6.82-3.9 4.17a15.48 15.48 0 0 1-14.73-.17l-3.16-3.07-7.11-6.9-57.11-55.48a37.3 37.3 0 0 0 4.35-17.56c0-1.1 0-2.19-.14-3.26l2.73-2.9 2.3-2.44 2.98 2.84 54.33 52.79 3.26 3.16a10.8 10.8 0 0 0 4.14.78 10.4 10.4 0 0 0 5-1.17l2.36-2.51 49.56-53 3.66-3.91-25.72.38-11.65.16A23.75 23.75 0 0 1 115.2 142a23.5 23.5 0 0 1-.79-6.08 23.75 23.75 0 0 1 23.75-23.75 23.3 23.3 0 0 1 5.25.59 23.67 23.67 0 0 1 15.31 11.29l13.27-.2 42.45-.61 4.48-.07h.14l34-.5Z",
] as const;

export function LumoseLogoIcon({
  className,
  decorative = false,
  title = "Lumose logo",
  ...props
}: LumoseLogoIconProps): ReactElement {
  const gradientId = `lumose-logo-gradient-${useId().replaceAll(":", "")}`;
  const accessibleTitle = decorative ? undefined : title;

  return (
    <svg
      {...props}
      aria-hidden={accessibleTitle ? undefined : true}
      aria-label={accessibleTitle}
      className={twMerge("inline h-10 w-10 flex-none", className)}
      focusable="false"
      role={accessibleTitle ? "img" : undefined}
      viewBox="0 0 268.88 243.31"
    >
      <defs>
        <linearGradient
          id={gradientId}
          x1="268.88"
          x2="0"
          y1="0"
          y2="243.31"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="var(--color-brand-gradient-start)" />
          <stop offset="0.48" stopColor="var(--color-brand-gradient-middle)" />
          <stop offset="1" stopColor="var(--color-brand-gradient-end)" />
        </linearGradient>
      </defs>
      {lumoseLogoPaths.map((path) => (
        <path d={path} fill={`url(#${gradientId})`} key={path} />
      ))}
    </svg>
  );
}
