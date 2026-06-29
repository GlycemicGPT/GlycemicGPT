import { forwardRef, type Ref } from "react";
import { Button } from "@/base/Button";
import { twMerge } from "@/lib/ui/twMerge";
import type { SecondaryButtonProps, SecondaryButtonSize } from "./secondaryButton.types";

const SIZE_CLASS: Record<SecondaryButtonSize, string> = {
  sm: "h-7 gap-1.5 px-2 font_metric_caption",
  md: "h-8 gap-1.5 px-3 font_metric_caption",
  icon: "h-8 w-8 p-0 [&>svg]:h-4 [&>svg]:w-4",
};

export const SecondaryButton = forwardRef<HTMLButtonElement, SecondaryButtonProps>(
  (
    {
      children,
      className,
      size = "md",
      ...props
    }: SecondaryButtonProps,
    ref: Ref<HTMLButtonElement>,
  ) => (
    <Button
      {...props}
      className={twMerge(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-button border transition-colors cursor-pointer",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "border-border-default bg-surface-primary text-foreground-primary shadow-sm",
        "hover:border-border-hover hover:bg-surface-secondary",
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

SecondaryButton.displayName = "SecondaryButton";
