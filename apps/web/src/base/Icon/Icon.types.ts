import type { SVGAttributes } from "react";
import type { Stylable } from "../types";
import type { IconName } from "./iconConfig";

export type { IconName };

export type IconProps = Stylable &
  Omit<SVGAttributes<SVGSVGElement>, "children" | "aria-hidden"> & {
    icon: IconName;
    /**
     * Set to `true` when the icon is purely visual and its meaning is already
     * conveyed by nearby text (e.g. an icon next to a "Delete" label). This
     * hides it from screen readers to avoid duplicate announcements.
     *
     * Leave as `false` (default) when the icon is the only thing conveying
     * meaning (e.g. an icon-only button), so it stays labelled and announced.
     */
    decorative?: boolean;
    /**
     * Overrides the default accessible label from the icon config. Ignored when
     * `decorative` is `true`.
     */
    title?: string;
  };
