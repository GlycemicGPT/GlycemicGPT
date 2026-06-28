import type { ButtonHTMLAttributes } from "react";
import type { Stylable } from "../types";

export type ButtonProps = Stylable &
  ButtonHTMLAttributes<HTMLButtonElement> & {
    ariaLabel?: string;
  };
