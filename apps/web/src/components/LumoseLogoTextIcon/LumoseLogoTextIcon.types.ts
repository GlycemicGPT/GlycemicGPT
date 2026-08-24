import type { SVGProps } from "react";

export type LumoseLogoTextIconProps = Omit<
  SVGProps<SVGSVGElement>,
  "children"
> & {
  decorative?: boolean;
  title?: string;
};
