import type { NextConfig } from "next";

// The platform never phones home (doc 02 §3: laptop-only, no deployment). This runs before Next.js creates its
// telemetry client, so `next build` / `next start` / `next dev` send nothing.
process.env.NEXT_TELEMETRY_DISABLED ??= "1";

/** The FastAPI backend, reached by this server (not the browser). Server-side only: never NEXT_PUBLIC_. */
const API_ORIGIN = (process.env.HMAP_API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Browser -> this server -> API: session cookies stay first-party and no CORS is needed.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
  // Old page addresses keep working.
  async redirects() {
    return [
      { source: "/projects", destination: "/", permanent: false },
      { source: "/agents", destination: "/team", permanent: false },
      { source: "/events", destination: "/activity", permanent: false },
      { source: "/dead-letters", destination: "/issues", permanent: false },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
