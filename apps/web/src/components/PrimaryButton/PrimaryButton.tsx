import { forwardRef, type Ref } from "react";
import { Button } from "@/base/Button";
import { twMerge } from "@/lib/ui/twMerge";
import type { PrimaryButtonProps, PrimaryButtonSize } from "./primaryButton.types";

const SIZE_CLASS: Record<PrimaryButtonSize, string> = {
  sm: "h-8 gap-1.5 px-3 font_body_3",
  md: "h-10 gap-2 px-4 font_body_2",
  icon: "h-9 w-9 p-0",
};

export const PrimaryButton = forwardRef<HTMLButtonElement, PrimaryButtonProps>(
  (
    {
      children,
      className,
      size = "md",
      ...props
    }: PrimaryButtonProps,
    ref: Ref<HTMLButtonElement>,
  ) => (
    <Button
      {...props}
      className={twMerge(
        "inline-flex shrink-0 items-center justify-center rounded-button transition-colors cursor-pointer",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "border border-surface-inverse bg-surface-inverse text-foreground-inverse shadow-sm",
        "hover:border-border-hover",
        "focus-visible:ring-2 focus-visible:ring-border-active",
        SIZE_CLASS[size],
        className,
      )}
      ref={ref}
    >
      {children}
    </Button>
  ),
);

PrimaryButton.displayName = "PrimaryButton";
