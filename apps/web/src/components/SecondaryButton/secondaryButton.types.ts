import type { ButtonProps } from "@/base/Button";

export type SecondaryButtonSize = "sm" | "md" | "icon";

export type SecondaryButtonProps = ButtonProps & {
  size?: SecondaryButtonSize;
};
