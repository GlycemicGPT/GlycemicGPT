---
title: Color Accessibility Guide
description: Approved semantic color pairings and contrast rules for GlycemicGPT web UI.
---

# Color Accessibility Guide

This guide defines approved color pairings for the current web UI foundation.

## Baseline Rules

1. The default light and dark themes should pass WCAG AA. See [WCAG 2.2 conformance](https://www.w3.org/WAI/WCAG22/Understanding/conformance).
2. Normal text needs at least `4.5:1` contrast. See [WCAG 1.4.3 Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
3. Large text needs at least `3:1` contrast. See [WCAG 1.4.3 Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
4. Important icons, borders, selected states, and controls need at least `3:1` contrast against adjacent colors. See [WCAG 1.4.11 Non Text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html).
5. Focus indicators must be visible and should keep at least `3:1` contrast against adjacent colors. See [WCAG 2.4.7 Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html) and [WCAG 2.4.13 Focus Appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html).
6. High contrast mode is an enhancement. It is not a reason to ship known contrast failures in the default theme. See [WCAG conforming alternate versions](https://www.w3.org/WAI/WCAG22/Understanding/conformance#conforming-alt-versions).
7. Do not rely on color alone for state, status, or medical meaning. See [WCAG 1.4.1 Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html).
8. Use semantic utilities first. Do not use raw Tailwind palette classes for shared UI.
9. If a pairing is not listed here, calculate contrast before using it.

## Current Tokens

```text
Light surfaces:
--color-surface-page: #ffffff
--color-surface-primary: #ffffff
--color-surface-secondary: #e6e8e6
--color-surface-tertiary: #ced0ce

Dark surfaces:
--color-surface-page: #3a414b
--color-surface-primary: #3a414b
--color-surface-secondary: #5f6266
--color-surface-tertiary: #949ea8

Foreground:
--color-foreground-primary: #191919 in light, #ffffff in dark
--color-foreground-secondary: #767676 in light, #a7b0ba in dark
--color-foreground-muted: #ced0ce in light, #5f6266 in dark

Accent:
--color-accent: #5eb1ff
--color-accent-hover: #4da8ff in light, #70bdff in dark
--color-accent-foreground: #191919

Signal:
--color-signal-partial-fill: #6f53ca in light, #bbaee6 in dark
--color-signal-partial-text: #6f53ca in light, #e5e0ff in dark
--color-signal-info-fill: #2b7272 in light, #65c5c5 in dark
--color-signal-info-text: #2b7272 in light, #a5f3f3 in dark
--color-signal-check-fill: #2a7643 in light, #67c987 in dark
--color-signal-check-text: #2a7643 in light, #a7f3c0 in dark
--color-signal-warning-fill: #f8c129 in light, #f6a61d in dark
--color-signal-warning-text: #b24600 in light, #ffe08a in dark
--color-signal-error-fill: #cd1d0c in light, #e94b3a in dark
--color-signal-error-text: #cd1d0c in light, #ffd9d5 in dark
```

## Light Theme Pairings

Approved for normal text:

1. `bg-surface-page` or `bg-surface-primary` with `text-foreground-primary`: `17.58:1`.
2. `bg-surface-page` or `bg-surface-primary` with `text-foreground-secondary`: `4.54:1`.
3. `bg-surface-secondary` with `text-foreground-primary`: `14.27:1`.
4. `bg-surface-tertiary` with `text-foreground-primary`: `11.33:1`.
5. `bg-accent` with `text-accent-foreground`: `7.71:1`.
6. `bg-accent-hover` with `text-accent-foreground`: `7.00:1`.

Allowed only for large text or non text UI:

1. `bg-surface-secondary` with `text-foreground-secondary`: `3.69:1`.

Not approved for readable text:

1. `bg-surface-page` or `bg-surface-primary` with `text-foreground-muted`: `1.55:1`.
2. `bg-accent` with white text: `2.28:1`.

## Dark Theme Pairings

Approved for normal text:

1. `bg-surface-page` or `bg-surface-primary` with `text-foreground-primary`: `10.31:1`.
2. `bg-surface-page` or `bg-surface-primary` with `text-foreground-secondary`: `4.69:1`.
3. `bg-surface-page` or `bg-surface-primary` with `text-accent`: `4.52:1`.
4. `bg-surface-secondary` with `text-foreground-primary`: `6.13:1`.
5. `bg-accent` with `text-accent-foreground`: `7.71:1`.
6. `bg-accent-hover` with `text-accent-foreground`: `8.72:1`.

Allowed only for large text or non text UI:

1. `bg-surface-tertiary` with `text-foreground-inverse`: `3.79:1`.

Not approved for readable text:

1. `bg-surface-page` or `bg-surface-primary` with `text-foreground-muted`: `1.68:1`.
2. `bg-surface-secondary` with `text-foreground-secondary`: `2.79:1`.
3. `bg-accent` with white text: `2.28:1`.

## Accent Rules

1. Use `bg-accent text-accent-foreground` for selected tabs, primary filled controls, checked controls, and highlight surfaces with text inside.
2. Do not put white text on `bg-accent`.
3. Use white text on dark surfaces for primary copy.
4. Use `text-foreground-secondary` for secondary paragraphs and labels on `bg-surface-page` or `bg-surface-primary`.
5. Do not use `text-accent` for paragraph copy. Use it for short emphasis only when the background is `bg-surface-page` or `bg-surface-primary`.

## Surface Rules

1. `bg-surface-page` and `bg-surface-primary` can host normal text with primary and secondary foreground colors in both themes.
2. `bg-surface-secondary` can host normal text only with `text-foreground-primary` in both themes.
3. `bg-surface-tertiary` should not host normal body text in dark mode with the current semantic foreground tokens.
4. `text-foreground-muted` is for disabled, decorative, or non essential text only. Do not use it for labels, paragraphs, form hints, or critical metadata.

## Signal Color Rules

1. Use `*-fill` signal tokens for backgrounds, badges, indicators, chart areas, and alert surfaces.
2. Use `*-text` signal tokens for signal-colored text and icons on neutral surfaces.
3. Use only the documented foreground color for text and icons placed directly on matching signal fill backgrounds.
4. Do not use a fill token as body text unless its exact background pairing has been checked.
5. Light theme signal text tokens pass normal text contrast on page, primary, and secondary surfaces. They pass non text contrast on tertiary.
6. Dark theme signal text tokens pass normal text contrast on page, primary, and secondary surfaces. They are not approved on tertiary.
7. Do not rely on color alone for medical or safety critical meaning. Pair signal color with text, icon shape, or label. See [WCAG 1.4.1 Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html).

## Signal Contrast Reference

Light theme signal text on neutral surfaces:

1. `signal-partial-text`: `5.58:1` on page or primary, `4.53:1` on secondary, `3.59:1` on tertiary.
2. `signal-info-text`: `5.60:1` on page or primary, `4.54:1` on secondary, `3.61:1` on tertiary.
3. `signal-check-text`: `5.57:1` on page or primary, `4.52:1` on secondary, `3.59:1` on tertiary.
4. `signal-warning-text`: `5.57:1` on page or primary, `4.52:1` on secondary, `3.59:1` on tertiary.
5. `signal-error-text`: `5.56:1` on page or primary, `4.51:1` on secondary, `3.58:1` on tertiary.

Light theme signal fills with documented foreground:

1. `signal-partial-fill` with white text: `5.58:1`.
2. `signal-info-fill` with white text: `5.60:1`.
3. `signal-check-fill` with white text: `5.57:1`.
4. `signal-warning-fill` with ink text: `10.59:1`.
5. `signal-error-fill` with white text: `5.56:1`.

Dark theme signal text on neutral surfaces:

1. `signal-partial-text`: `8.07:1` on page or primary, `4.80:1` on secondary, `2.13:1` on tertiary.
2. `signal-info-text`: `8.20:1` on page or primary, `4.88:1` on secondary, `2.17:1` on tertiary.
3. `signal-check-text`: `7.96:1` on page or primary, `4.74:1` on secondary, `2.10:1` on tertiary.
4. `signal-warning-text`: `7.99:1` on page or primary, `4.75:1` on secondary, `2.11:1` on tertiary.
5. `signal-error-text`: `7.92:1` on page or primary, `4.71:1` on secondary, `2.09:1` on tertiary.

Dark theme signal fills with documented foreground:

1. `signal-partial-fill` with ink text: `8.63:1`.
2. `signal-info-fill` with ink text: `8.66:1`.
3. `signal-check-fill` with ink text: `8.61:1`.
4. `signal-warning-fill` with ink text: `8.70:1`.
5. `signal-error-fill` with ink text: `4.63:1`.

## Agent Workflow

1. Start with the semantic pairing listed above.
2. If the pair is not listed, calculate the contrast ratio before coding.
3. If the pair fails, change the semantic mapping or add a narrowly justified semantic token.
4. Do not solve a shared UI contrast problem with a local raw color class.
5. Update this guide when shared token values or approved pairings change.

## WCAG References

1. [WCAG 2.2 Conformance](https://www.w3.org/WAI/WCAG22/Understanding/conformance)
2. [WCAG 1.4.1 Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)
3. [WCAG 1.4.3 Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
4. [WCAG 1.4.11 Non Text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)
5. [WCAG 2.4.7 Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html)
6. [WCAG 2.4.13 Focus Appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html)
