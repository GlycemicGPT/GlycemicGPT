import { forwardRef, type Ref } from "react";
import { twMerge } from "@/lib/ui/twMerge";
import type { InputProps } from "./Input.types";

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }: InputProps, ref: Ref<HTMLInputElement>) => (
    <input
      {...props}
      className={twMerge(className)}
      ref={ref}
      type={type}
    />
  ),
);

Input.displayName = "Input";
