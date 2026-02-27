import type { NextConfig } from "next";

// Allow API origin in CSP connect-src when NEXT_PUBLIC_API_URL is set
// (local dev uses http://localhost:8000; Docker uses same-origin proxy)
const apiOrigin = process.env.NEXT_PUBLIC_API_URL || "";
const connectSrc = apiOrigin
  ? `'self' ${apiOrigin}`
  : "'self'";

const securityHeaders = [
  {
    key: "X-Frame-Options",
    value: "DENY",
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      `connect-src ${connectSrc}`,
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
];

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },

  /**
   * Proxy all /api/* requests to the backend API server.
   *
   * The browser only talks to the Next.js origin (port 3000). Next.js
   * forwards API calls server-to-server, eliminating CORS and making
   * the architecture reverse-proxy-agnostic. Works identically whether
   * accessed via localhost, LAN IP, or a Cloudflare tunnel.
   *
   * Note: In standalone mode, rewrites are evaluated at build time and
   * baked into routes-manifest.json. To change the API destination,
   * rebuild the image with API_URL set. The default (http://api:8000)
   * works for Docker Compose and Kubernetes where the API service is
   * named "api".
   */
  async rewrites() {
    const apiUrl = process.env.API_URL || "http://api:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
