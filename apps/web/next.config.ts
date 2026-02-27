import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,

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
