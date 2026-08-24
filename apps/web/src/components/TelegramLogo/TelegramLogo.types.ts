import type { SVGProps } from "react";

export type TelegramLogoProps = Omit<SVGProps<SVGSVGElement>, "children"> & {
  decorative?: boolean;
  title?: string;
};
