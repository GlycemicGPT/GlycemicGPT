import { useId } from "react";
import { lumoseLogoPaths } from "@/components/LumoseLogoIcon/LumoseLogoIcon";
import { twMerge } from "@/lib/ui/twMerge";
import type { LumoseLoadingLogoProps } from "./LumoseLoadingLogo.types";

export function LumoseLoadingLogo({
  className,
  decorative = false,
  label = "Loading",
  ...props
}: LumoseLoadingLogoProps) {
  const id = `lumose-loading-logo-${useId().replaceAll(":", "")}`;
  const flowGradientId = `${id}-flow`;
  const contrastFilterId = `${id}-contrast`;

  return (
    <span
      {...props}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label}
      aria-live={decorative ? undefined : "polite"}
      className={twMerge(
        "inline-flex h-12 w-12 flex-none text-brand-gradient-middle",
        className,
      )}
      role={decorative ? undefined : "status"}
    >
      <svg
        aria-hidden="true"
        className="lumose-loading-logo-pulse h-full w-full overflow-visible"
        focusable="false"
        viewBox="0 0 268.88 243.31"
      >
        <defs>
          <linearGradient
            className="lumose-loading-logo-flow"
            gradientUnits="userSpaceOnUse"
            id={flowGradientId}
            x1="-125"
            x2="25"
            y1="0"
            y2="0"
          >
            <stop
              offset="0"
              stopColor="var(--color-brand-highlight)"
              stopOpacity="0"
            />
            <stop
              offset="0.36"
              stopColor="var(--color-brand-highlight)"
              stopOpacity="0.16"
            />
            <stop offset="0.5" stopColor="var(--color-brand-highlight)" />
            <stop
              offset="0.64"
              stopColor="var(--color-brand-highlight)"
              stopOpacity="0.16"
            />
            <stop
              offset="1"
              stopColor="var(--color-brand-highlight)"
              stopOpacity="0"
            />
          </linearGradient>
          <filter
            colorInterpolationFilters="sRGB"
            height="210%"
            id={contrastFilterId}
            width="200%"
            x="-50%"
            y="-50%"
          >
            <feGaussianBlur
              in="SourceAlpha"
              result="shadow-blur"
              stdDeviation="6"
            />
            <feOffset dy="5" in="shadow-blur" result="shadow-offset" />
            <feFlood
              floodColor="var(--color-surface-fixed-dark)"
              floodOpacity="0.52"
              result="shadow-color"
            />
            <feComposite
              in="shadow-color"
              in2="shadow-offset"
              operator="in"
              result="shadow"
            />
            <feGaussianBlur
              in="SourceGraphic"
              result="accent-glow"
              stdDeviation="4"
            />
            <feComponentTransfer in="SourceGraphic" result="brightened-logo">
              <feFuncR intercept="0.04" slope="1.24" type="linear" />
              <feFuncG intercept="0.04" slope="1.24" type="linear" />
              <feFuncB intercept="0.04" slope="1.24" type="linear" />
            </feComponentTransfer>
            <feMerge>
              <feMergeNode in="shadow" />
              <feMergeNode in="accent-glow" />
              <feMergeNode in="brightened-logo" />
            </feMerge>
          </filter>
        </defs>

        <g filter={`url(#${contrastFilterId})`}>
          <g fill="currentColor" fillOpacity="0.42">
            {lumoseLogoPaths.map((path) => (
              <path d={path} key={path} />
            ))}
          </g>
          <g fill={`url(#${flowGradientId})`}>
            {lumoseLogoPaths.map((path) => (
              <path d={path} key={path} />
            ))}
          </g>
        </g>
      </svg>
    </span>
  );
}
