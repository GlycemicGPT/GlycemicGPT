import { type ReactElement } from "react";
import { twMerge } from "@/lib/ui/twMerge";
import type { IconProps } from "./Icon.types";
import { icons } from "./iconConfig";

/**
 * Icon optimization using SVG sprites, read more here:
 * https://benadam.me/thoughts/react-svg-sprites/
 *
 * Icons used in this project are sourced from the following library:
 * Octicons - GitHub's icon set - https://www.figma.com/community/file/809920999413919915
 * Plump Line Free - Streamline Icons - https://www.streamlinehq.com/icons/plump-line-free?icon=ico_8ZIh7saR93KkCbDz
 *
 */

const SPRITE_PATH = "/static_assets/iconSprite.svg";

export function Icon({
  className,
  decorative = false,
  icon,
  title,
  ...props
}: IconProps): ReactElement {
  const iconConfig = icons[icon];
  const accessibleTitle = decorative ? undefined : title ?? iconConfig.title;

  return (
    <svg
      {...props}
      aria-hidden={accessibleTitle ? undefined : true}
      aria-label={accessibleTitle}
      className={twMerge(
        "inline flex-none fill-current",
        iconConfig.size,
        className,
      )}
      focusable="false"
      role={accessibleTitle ? "img" : undefined}
    >
      <use href={`${SPRITE_PATH}#${icon}`} />
    </svg>
  );
}
