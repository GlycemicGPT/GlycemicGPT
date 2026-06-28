import type { ReactElement } from "react";
import { Icon, Input } from "@/base";
import { twMerge } from "@/lib/ui/twMerge";
import type { CheckboxProps } from "./Checkbox.types";

export function Checkbox({
  checked,
  className,
  disabled,
  inputClassName,
  label,
  labelClassName,
  onCheckedChange,
  ...props
}: CheckboxProps): ReactElement {
  return (
    <label
      className={twMerge(
        "font_body_2 group inline-flex cursor-pointer items-start gap-3 text-foreground-secondary",
        disabled && "cursor-not-allowed opacity-60",
        labelClassName,
      )}
    >
      <Input
        {...props}
        checked={checked}
        className={twMerge("peer sr-only", inputClassName)}
        disabled={disabled}
        onChange={(event) => onCheckedChange?.(event.target.checked)}
        type="checkbox"
      />
      <span
        aria-hidden="true"
        className={twMerge(
          "mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded border border-border-default bg-surface-primary text-transparent transition-colors",
          !disabled && "group-hover:border-border-hover group-hover:bg-surface-secondary",
          "peer-focus-visible:ring-2 peer-focus-visible:ring-border-active",
          checked && "border-accent bg-accent text-accent-foreground",
          checked && !disabled && "group-hover:border-accent-hover group-hover:bg-accent-hover",
          disabled && "border-border-disabled",
          className,
        )}
      >
        <Icon decorative icon="check" />
      </span>
      <span>{label}</span>
    </label>
  );
}
