import { forwardRef, type Ref } from "react";
import { Button } from "@/base/Button";
import { twMerge } from "@/lib/ui/twMerge";
import type { HighlightButtonProps, HighlightButtonSize } from "./highlightButton.types";

const SIZE_CLASS: Record<HighlightButtonSize, string> = {
  sm: "h-8 gap-1.5 px-3 font_body_3",
  md: "h-10 gap-2 px-4 font_body_2",
  icon: "h-9 w-9 p-0",
};

export const HighlightButton = forwardRef<HTMLButtonElement, HighlightButtonProps>(
  (
    {
      children,
      className,
      size = "md",
      ...props
    }: HighlightButtonProps,
    ref: Ref<HTMLButtonElement>,
  ) => (
    <Button
      {...props}
      className={twMerge(
        "inline-flex shrink-0 items-center justify-center rounded-button transition-colors cursor-pointer",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "bg-accent text-accent-foreground shadow-sm",
        "hover:bg-accent-hover",
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

HighlightButton.displayName = "HighlightButton";
