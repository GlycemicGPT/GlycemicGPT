import { forwardRef, type Ref } from "react";
import { twMerge } from "@/lib/ui/twMerge";
import type { ButtonProps } from "./Button.types";

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      ariaLabel,
      children,
      className,
      disabled,
      type = "button",
      ...props
    }: ButtonProps,
    ref: Ref<HTMLButtonElement>,
  ) => (
    <button
      {...props}
      aria-label={ariaLabel}
      className={twMerge(className)}
      disabled={disabled}
      ref={ref}
      type={type}
    >
      {children}
    </button>
  ),
);

Button.displayName = "Button";
