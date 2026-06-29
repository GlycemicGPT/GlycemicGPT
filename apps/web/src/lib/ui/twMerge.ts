import type { ClassNameValue } from "tailwind-merge";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * Local font utility classes defined as `@utility` roles in
 * src/styles/config/fonts.css. Grouping them here lets tailwind-merge resolve
 * conflicts between classes that target the same concern. Keep these in sync
 * with the `@utility` definitions in fonts.css.
 *
 * Complete typographic roles live in their own group so only one wins, while
 * the weight and tracking modifiers stay separate so they can combine with a
 * role.
 */
const fontClassGroups = {
  fontFace: ["font_poppins", "font_jetbrains_mono"],
  fontTypography: [
    "font_header_1",
    "font_header_2",
    "font_header_3",
    "font_header_4",
    "font_body_1",
    "font_body_2",
    "font_body_3",
    "font_body_4",
    "font_metric_label",
    "font_metric_caption",
    "font_page_title",
    "font_section_title",
    "font_body_text",
    "font_body_text_strong",
    "font_ui_label",
    "font_ui_caption",
    "font_ui_input",
    "font_ui_mono_value",
  ],
  fontWeight: ["font_regular", "font_bold"],
  fontTracking: ["font_normal", "font_medium"],
};

/**
 * A custom `tw-merge` that understands the project's local font utility classes
 * in addition to the default Tailwind ones, so conflicting font roles resolve
 * to a single winning class.
 */
const customTwMerge = extendTailwindMerge<string, string>({
  extend: {
    classGroups: fontClassGroups,
  },
});

/**
 * Utility function that merges Tailwind class values with support for
 * composition and the project's local font utility classes.
 */
export const twMerge = (...classes: ClassNameValue[]) => customTwMerge(...classes);
