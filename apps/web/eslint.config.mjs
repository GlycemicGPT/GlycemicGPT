import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // Allow unused variables prefixed with underscore
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Block next/font/google -- it makes a build-time HTTP request to
      // fonts.googleapis.com on every `npm run build`, and a single
      // timeout there killed the v0.8.0 web container release. Use
      // next/font/local with a self-hosted font instead. See
      // apps/web/src/app/layout.tsx for the canonical pattern.
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "next/font/google",
              message:
                "Do not use next/font/google -- it makes a build-time HTTP call to fonts.googleapis.com that can break releases. Use next/font/local with a self-hosted woff2 instead. See apps/web/src/app/layout.tsx.",
            },
          ],
          // Also block any deeper paths under next/font/google (e.g.
          // `next/font/google/something`) so the rule can't be trivially
          // sidestepped by importing from a sub-module.
          patterns: [
            {
              group: ["next/font/google/**"],
              message:
                "Do not import from any next/font/google sub-path -- same Google Fonts build-time HTTP dependency. Use next/font/local instead.",
            },
          ],
        },
      ],
    },
  },
];

export default eslintConfig;
