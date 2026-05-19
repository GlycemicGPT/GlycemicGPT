import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { ThemeProvider } from "@/providers";

// Inter Variable, served from a self-hosted file. Using next/font/local
// (not next/font/google) eliminates the build-time HTTP call to Google
// Fonts that previously made every Docker build a hostage to Google's
// CDN reachability -- a single timeout there killed the v0.8.0 web
// release image. See apps/web/src/app/fonts/LICENSE.txt for the SIL
// OFL 1.1 license under which Inter is redistributed (Inter project:
// https://github.com/rsms/inter).
//
// `weight: "100 900"` is required for Next.js to recognise this as a
// variable font and generate CSS that unlocks the full weight range
// (otherwise font-semibold / font-bold fall back to fake-bold). The
// `fallback` chain matches Tailwind's default sans stack so first-paint
// before the local font loads uses a metric-similar system font.
const inter = localFont({
  src: "./fonts/InterVariable.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
  variable: "--font-inter",
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
    <html lang="en" className="" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("glycemicgpt-theme");if(t==="light"){document.documentElement.className="light"}else if(t==="dark"){document.documentElement.className="dark"}else{document.documentElement.className=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}}catch(e){document.documentElement.className=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}})()`,
          }}
        />
      </head>
      <body className={inter.className}>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
