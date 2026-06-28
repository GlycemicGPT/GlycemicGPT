import type { ButtonProps } from "@/base/Button";

export type HighlightButtonSize = "sm" | "md" | "icon";

export type HighlightButtonProps = ButtonProps & {
  size?: HighlightButtonSize;
};
