import type { NextConfig } from "next";

// The backend has no published port. The browser talks only to the frontend,
// which proxies /api/* to the backend over the internal Docker network.
// BACKEND_URL is read at build time (see the Dockerfile build arg).
const backendUrl = process.env.BACKEND_URL ?? "http://backend:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
