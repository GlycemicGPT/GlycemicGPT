import type { ButtonProps } from "@/base/Button";

export type PrimaryButtonSize = "sm" | "md" | "icon";

export type PrimaryButtonProps = ButtonProps & {
  size?: PrimaryButtonSize;
};
