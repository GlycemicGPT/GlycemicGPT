import type { InputHTMLAttributes, ReactNode } from "react";
import type { Stylable } from "@/base/types";

export type CheckboxProps = Stylable<"input" | "label"> &
  Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "type"> & {
    label: ReactNode;
    onCheckedChange?: (checked: boolean) => void;
  };
