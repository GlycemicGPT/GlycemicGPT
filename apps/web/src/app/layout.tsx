import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { ThemeProvider } from "@/providers";
import { getThemeInitScript } from "@/providers/theme-config";

// Keep app fonts registered through next/font/local. Local files avoid build
// time HTTP calls to Google Fonts. A single CDN timeout previously broke the
// v0.8.0 web release image, so this is a release reliability requirement.
//
// Inter remains the app default. See apps/web/src/app/fonts/LICENSE.txt for
// the SIL OFL 1.1 license from the Inter project at https://github.com/rsms/inter.
// The weight range tells Next.js this is a variable font and unlocks the full
// weight range instead of relying on fake bold. The fallback chain matches
// Tailwind's default sans stack for metric similar first paint.
const inter = localFont({
  src: "./fonts/InterVariable.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
  variable: "--font-inter",
});

// Poppins is loaded from local SIL OFL 1.1 files for the new design system
// role utilities. It is scoped by CSS variables today, so the existing app
// keeps Inter as the default font outside surfaces that opt into Poppins.
const poppins = localFont({
  src: [
    {
      path: "./fonts/Poppins-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "./fonts/Poppins-Bold.ttf",
      weight: "700",
      style: "normal",
    },
  ],
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
  variable: "--font-poppins",
});

// JetBrains Mono is loaded from local SIL OFL 1.1 variable font files for
// metric labels and compact values. The explicit weight range lets Next.js
// generate real variable font CSS for all supported mono weights.
const labelFont = localFont({
  src: [
    {
      path: "./fonts/JetBrainsMono-VariableFont_wght.ttf",
      weight: "100 800",
      style: "normal",
    },
    {
      path: "./fonts/JetBrainsMono-Italic-VariableFont_wght.ttf",
      weight: "100 800",
      style: "italic",
    },
  ],
  display: "swap",
  fallback: ["ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: "GlycemicGPT",
  description: "AI-powered diabetes management - your on-call endo at home",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
  manifest: "/manifest.json",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${poppins.variable} ${labelFont.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: getThemeInitScript(),
          }}
        />
      </head>
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
