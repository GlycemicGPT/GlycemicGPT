import { forwardRef, useId, type Ref } from "react";
import { Input } from "@/base/Input";
import { twMerge } from "@/lib/ui/twMerge";
import type { TextInputProps } from "./textInput.types";

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(
  (
    {
      className,
      containerClassName,
      errorMessage,
      id,
      inputClassName,
      label,
      labelClassName,
      "aria-describedby": ariaDescribedBy,
      "aria-invalid": ariaInvalid,
      ...props
    }: TextInputProps,
    ref: Ref<HTMLInputElement>,
  ) => {
    const generatedId = useId();
    const inputId = id ?? generatedId;
    const errorId = `${inputId}-error`;
    const describedBy = [ariaDescribedBy, errorMessage ? errorId : undefined]
      .filter(Boolean)
      .join(" ");

    return (
      <div className={twMerge("grid w-full gap-1.5", containerClassName)}>
        <label
          className={twMerge("font_metric_label text-foreground-primary", labelClassName)}
          htmlFor={inputId}
        >
          {label}
        </label>
        <Input
          {...props}
          aria-describedby={describedBy || undefined}
          aria-invalid={ariaInvalid ?? Boolean(errorMessage)}
          className={twMerge(
            "font_ui_input h-10 w-full rounded-md border border-border-default bg-surface-primary px-3 text-foreground-primary shadow-sm transition-colors",
            "placeholder:text-foreground-secondary",
            "hover:border-border-hover",
            "disabled:cursor-not-allowed disabled:border-border-disabled disabled:opacity-50",
            "focus-visible:border-border-active focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-active",
            errorMessage && "border-signal-error-text focus-visible:border-signal-error-text focus-visible:ring-signal-error-text",
            inputClassName,
            className,
          )}
          id={inputId}
          ref={ref}
        />
        {errorMessage ? (
          <p className="font_body_3 text-signal-error-text" id={errorId}>
            {errorMessage}
          </p>
        ) : null}
      </div>
    );
  },
);

TextInput.displayName = "TextInput";
