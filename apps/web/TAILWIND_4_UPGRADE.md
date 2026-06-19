# Tailwind CSS 4 Upgrade

This app now uses the Tailwind CSS 4 PostCSS package and CSS first configuration.

1. Tailwind is imported from `src/app/globals.css` with `@import "tailwindcss";`.
2. The previous custom Tailwind theme values now live in the `@theme` block in `src/app/globals.css`.
3. The `glucose` and `alert` color namespaces are preserved as Tailwind 4 theme variables.
4. The `animate-pulse-slow` and `animate-pulse-fast` utilities are preserved as Tailwind 4 animation variables.
5. Dark mode is still class based through the app theme provider. The provider continues to apply `html.light` and `html.dark`.
6. PostCSS now uses `@tailwindcss/postcss`. `autoprefixer` was removed because Tailwind CSS 4 handles prefixing through its compiler.
7. Compatibility class rewrites preserve Tailwind CSS 3 visual behavior, including `shadow-xs`, `rounded-sm`, `outline-hidden`, and `shrink-*` where needed.
8. This upgrade intentionally does not add the future UI foundation, new base components, icon infrastructure, or new product design tokens.
