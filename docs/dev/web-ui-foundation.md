---
title: Web UI Foundation
description: Developer reference for GlycemicGPT web themes, semantic tokens, typography, icons, and UI primitives.
---

# Web UI Foundation

This page documents the shared frontend foundation for `apps/web`. It is meant for contributors and maintainers who need to build UI that survives theme changes without rewriting component internals.

This is not a full product design system. It is the current foundation: semantic colors, class driven themes, font roles, sprite icons, base primitives, product components, and the checks that keep those pieces reliable.

## Ownership Map

| Area | Canonical file |
| --- | --- |
| Raw shared color values | `apps/web/src/styles/config/colors.css` |
| Semantic theme variables and mode mappings | `apps/web/src/styles/config/theme.css` |
| Legacy compatibility variables | `apps/web/src/styles/config/legacy-theme.css` |
| Class driven variants | `apps/web/src/styles/config/custom-variants.css` |
| Font families and role utilities | `apps/web/src/styles/config/fonts.css` |
| Shared radius tokens | `apps/web/src/styles/config/radius.css` |
| Shared animations | `apps/web/src/styles/config/animations.css` |
| Global element defaults | `apps/web/src/styles/base.css` |
| Base primitives | `apps/web/src/base` |
| Product components | `apps/web/src/components` |
| Icon sprite | `apps/web/public/static_assets/iconSprite.svg` |
| Icon names, titles, and sizes | `apps/web/src/base/Icon/iconConfig.ts` |
| Class composition | `apps/web/src/lib/ui/twMerge.ts` |
| Runtime theme choices | `apps/web/src/providers/theme-config.ts` |

Global styling enters through `apps/web/src/app/globals.css`. Keep the import order stable:

1. Tailwind CSS theme, preflight, and utilities.
2. Raw color tokens from `colors.css`.
3. Class driven variants from `custom-variants.css`.
4. Font utilities from `fonts.css`.
5. Shared radius tokens from `radius.css`.
6. Shared animations from `animations.css`.
7. Legacy compatibility variables from `legacy-theme.css`.
8. Semantic theme variables from `theme.css`.
9. Global base rules from `base.css`.

## Theme Model

Raw colors and semantic theme variables are separate on purpose.

A semantic token is a named design role. It says what a color is for, not what color it is. For example, `--color-accent` means "the current action color". It does not mean blue, yellow, green, or any other fixed hue.

That indirection lets components stay stable while themes change underneath them. A button can keep using `bg-accent text-accent-foreground`, and each theme decides which raw colors those roles map to.

Example flow:

```css
/* colors.css */
:root {
  --color-base-accent-blue: #5eb1ff;
  --color-base-ink: #191919;
  --color-base-cool-silver: #f7f9fb;
}

/* theme.css */
:root {
  --color-accent: var(--color-base-accent-blue);
  --color-accent-foreground: var(--color-base-ink);
}

.theme-dark {
  --color-accent: var(--color-base-accent-blue);
  --color-accent-foreground: var(--color-base-ink);
}

.theme-seasonal {
  --color-accent: var(--color-base-cool-silver);
  --color-accent-foreground: var(--color-base-ink);
}
```

```tsx
<button className="bg-accent text-accent-foreground">
  Save changes
</button>
```

The component only knows that it needs the accent background and the approved foreground for text placed on that background. It does not know or care which palette value the current theme uses.

1. Add raw palette values as `--color-base-*` tokens in `colors.css`.
2. Map raw tokens to semantic variables in `theme.css`.
3. Reassign the same semantic variables inside theme classes such as `.theme-dark`.
4. Use Tailwind utilities that reference semantic variables inside components.

Components should describe intent, not raw color. Use classes such as `bg-surface-page`, `bg-surface-primary`, `text-foreground-primary`, `text-foreground-secondary`, `bg-accent`, `text-accent-foreground`, `border-border-default`, `text-signal-error-text`, and `bg-signal-check-fill`.

Do not use raw palette classes such as `text-slate-500`, `bg-blue-600`, or `hover:bg-red-700` in new shared UI.

Light and dark mode are class driven. New semantic theme mode is enabled by adding a `theme-*` class to a wrapper. During the migration, the app root also keeps legacy `light` and `dark` classes so existing `dark:*` utilities continue to work. Do not use `prefers-color-scheme` in CSS for theme decisions.

## Semantic Color Families

Semantic variables describe usage, not literal hue.

| Family | Purpose | Example utilities |
| --- | --- | --- |
| `surface-*` | Page backgrounds, panels, raised areas, inverse regions | `bg-surface-page`, `bg-surface-primary`, `bg-surface-secondary` |
| `foreground-*` | Text and icons placed on approved surfaces | `text-foreground-primary`, `text-foreground-secondary`, `text-foreground-muted` |
| `accent-*` | Primary action color and text placed on accent backgrounds | `bg-accent`, `hover:bg-accent-hover`, `text-accent-foreground` |
| `border-*` | Outlines, dividers, hover borders, focus borders | `border-border-default`, `ring-border-active` |
| `signal-*-fill` | Status fills, indicators, charts, diagrams, and badges | `bg-signal-check-fill`, `bg-signal-warning-fill` |
| `signal-*-text` | Signal colored text and icons on neutral surfaces | `text-signal-error-text`, `text-signal-info-text` |
| `overlay-*` | Scrims above app surfaces | `bg-overlay-primary` |

Avoid vague names such as `ui-primary`, `ui-secondary`, and `ui-background`. If a new shared meaning is needed, add one semantic token and give it matching assignments for every supported theme.

## Color Accessibility

Color pairings must follow the [Color Accessibility Guide](./color-accessibility.md). The current guide defines approved combinations for light, dark, and seasonal theme modes.

Normal text needs AA contrast, non text UI needs enough contrast to identify controls and state, and color must not be the only way to communicate medical or product status.

Useful WCAG references:

1. [WCAG 2.2 Conformance](https://www.w3.org/WAI/WCAG22/Understanding/conformance)
2. [WCAG 1.4.3 Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
3. [WCAG 1.4.11 Non Text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)
4. [WCAG 1.4.1 Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)
5. [WCAG 2.4.7 Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html)
6. [WCAG 2.4.13 Focus Appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html)

Baseline rules:

1. Normal text needs at least `4.5:1` contrast.
2. Large text needs at least `3:1` contrast.
3. Important icons, borders, selected states, focus indicators, and controls need at least `3:1` contrast against adjacent colors.
4. High contrast mode is an enhancement. It is not permission to ship failures in the default theme.
5. Do not rely on color alone for state, status, or medical meaning.
6. If a pairing is not documented, calculate contrast before using it.

Accent rules:

1. Use `bg-accent text-accent-foreground` for selected tabs, filled primary controls, checked controls, and highlight surfaces with text inside.
2. Do not put white text on `bg-accent`.
3. Use `text-foreground-secondary` for secondary paragraphs and labels on `bg-surface-page` or `bg-surface-primary`.
4. Use `text-accent` only for short emphasis on approved neutral surfaces.

## Typography

Typography utilities live in `apps/web/src/styles/config/fonts.css`.

Use complete role utilities instead of repeated font family, size, weight, line height, and spacing stacks:

1. `font_header_1`
2. `font_header_2`
3. `font_header_3`
4. `font_header_4`
5. `font_body_1`
6. `font_body_2`
7. `font_body_3`
8. `font_body_4`
9. `font_metric_label`
10. `font_metric_caption`

Font families:

| Role | Family | Utility |
| --- | --- | --- |
| Primary UI text | Poppins | `font_poppins` |
| Labels and compact metric text | JetBrains Mono | `font_jetbrains_mono` |

Font delivery rules:

1. Register app fonts with `next/font/local`, not `next/font/google`.
2. Keep font files in `apps/web/src/app/fonts` so builds do not depend on Google Fonts or CDN reachability.
3. Keep Inter as the app default through `--font-inter` and `--font-sans` unless the product intentionally changes the global app font.
4. Scope Poppins and JetBrains Mono through CSS variables and role utilities until the broader app is intentionally migrated.
5. Register variable fonts with an explicit weight range so Next.js generates real variable font CSS instead of synthetic weights.
6. Keep the matching SIL OFL 1.1 license files beside the redistributed font files.

Role utilities should define font family, size, weight, line height, and letter spacing. Do not usually combine role utilities with `font_regular`, `font_bold`, `font_normal`, or `font_medium`. If a repeated visual style needs that, add or adjust a role utility instead.

Font utilities should use `rem` units so text follows browser text size settings.

Useful typography accessibility references:

1. [WCAG 1.4.4 Resize Text](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html)
2. [WCAG 1.4.12 Text Spacing](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html)
3. [WCAG 1.4.10 Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)

## Radius

Shared radius tokens live in `apps/web/src/styles/config/radius.css`.

Use radius tokens as opt in utilities in components, such as `rounded-button`. Do not apply radius tokens globally to raw elements. A token should make a radius reusable, not silently restyle every matching element in the app.

## Class Composition

Use `twMerge` from `apps/web/src/lib/ui/twMerge.ts` for dynamic class composition.

Do not call `clsx`, `classnames`, or `tailwind-merge` directly inside components. The local wrapper understands project font classes, so it can normalize conflicts such as `font_header_1` followed by `font_body_1`.

When adding a local utility class group that can conflict with itself, update `twMerge.ts` and add focused tests.

## Components

Base primitives live in `apps/web/src/base`. They provide accessible structure, stable typing, and default behavior. They may own minimal structural styling when it supports the primitive contract, such as layout reset classes, intrinsic sizing, hidden input mechanics, or sprite rendering defaults. They may also accept `className` props so composed components can apply semantic classes.

Base primitives should not own product appearance. Keep semantic colors, rich visual states, typography roles, branded treatments, and heavy layout styling in `apps/web/src/components`.

Current primitives:

1. `Button` owns the accessible button shell and default `type="button"` behavior.
2. `Input` owns the shared input shell.
3. `Icon` owns sprite based icon rendering.

Product components live in `apps/web/src/components` and compose base primitives with semantic classes. Current examples include `PrimaryButton`, `SecondaryButton`, `HighlightButton`, `TextInput`, and `Checkbox`.

Reusable component folders should follow the colocated pattern:

1. `Component.tsx` owns rendering.
2. `Component.types.ts` or `component.types.ts` owns props and exported types.
3. `Component.test.tsx` or `Component.spec.tsx` owns tests.
4. `index.ts` owns public exports.
5. Component CSS stays beside the component only when the component owns local theme variables.

Keep base components thin and visually neutral. Minimal structural classes are acceptable in `apps/web/src/base`. Semantic color classes, product level visual states, branded styling, and product behavior belong in `apps/web/src/components`.

## Component Accessibility

Components must support keyboard use, visible focus, correct names, roles, values, and labels.

Rules:

1. Icon only controls need an accessible name through visible text, `aria-label`, or `aria-labelledby`.
2. Interactive controls need visible focus through semantic border or ring tokens.
3. Disabled states must remain identifiable without relying only on color.
4. Form inputs need clear labels and useful error text.
5. Status and medical meaning must use text, icon shape, or labels in addition to color.

Useful component accessibility references:

1. [WCAG 2.1.1 Keyboard](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html)
2. [WCAG 2.4.7 Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html)
3. [WCAG 4.1.2 Name, Role, Value](https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html)
4. [WCAG 3.3.2 Labels or Instructions](https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html)

## Icons

Shared icons use the SVG sprite at `apps/web/public/static_assets/iconSprite.svg`.

Use `Icon` from `apps/web/src/base/Icon` when a symbol exists in the sprite. Register every symbol in `apps/web/src/base/Icon/iconConfig.ts` with a default title and size. `IconName` is derived from that config.

Icon rules:

1. Add only icons required by current work.
2. Keep sprite symbols minimal and reusable.
3. Use `currentColor` in sprite paths so icons follow text color utilities.
4. Let the configured `title` and `size` be the default for shared icons.
5. Use the `title` prop only when visible context needs a more specific accessible name.
6. Use `decorative` when an icon is purely visual and should be hidden from assistive technology.
7. Do not duplicate inline SVG markup in components when a shared sprite symbol exists.

Current icon sources:

1. [Octicons, GitHub icon set](https://www.figma.com/community/file/809920999413919915)

Useful icon accessibility references:

1. [WCAG 1.1.1 Non Text Content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html)
2. [WCAG 4.1.2 Name, Role, Value](https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html)
3. [WCAG 1.4.11 Non Text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

## Adding A Theme

Follow this path for a new semantic theme:

1. Add raw palette values to `colors.css`.
2. Reassign existing semantic tokens in a new `.theme-*` block in `theme.css`.
3. Add the selectable theme to `theme-config.ts`.
4. Set `semanticClass` to the new class without the dot.
5. Set `legacyClass` to only `light` or `dark`.
6. Update color accessibility documentation with approved pairings.
7. Run `npm run validate:theme-colors` from `apps/web`.
8. Run focused provider tests, `npm run typecheck`, and the checks for the changed surface.

Do not create legacy classes for new semantic themes. Do not create per component color variable families such as `--background-color-primary-button` or `--color-primary-button`.

## Tests

Every base component added to `apps/web/src/base` needs colocated unit tests.

Test for:

1. Meaningful rendering contracts.
2. Accessible attributes and labels.
3. State behavior.
4. Emitted events.
5. Class composition behavior when it matters.

Avoid low value snapshot tests. Prefer direct assertions for roles, attributes, callbacks, and sprite references.

Before considering UI foundation work done, run these commands from `apps/web`:

```bash
npm test
npm run typecheck
npm run build
```
