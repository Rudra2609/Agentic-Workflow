# Routes (Next.js App Router, file-based)

Route groups: `(app)` = signed-in shell layout, `(auth)` = sign-in layout. Redirects in next.config.ts: /projects->/, /agents->/team, /events->/activity, /dead-letters->/issues. `/api/*` proxied to FastAPI.

| Path | File | Layout | Renders |
|---|---|---|---|
| `/` | `frontend/src/app/(app)/page.tsx` | (app) | Workspace: greeting, stub notice, goal composer, project list |
| `/projects/[id]` | `frontend/src/app/(app)/projects/[id]/page.tsx` | (app) | Project workspace: stage rail, plan review, requirements, plan DAG, inspector, results, activity |
| `/team` | `frontend/src/app/(app)/team/page.tsx` | (app) | AI team roles + developer registry |
| `/activity` | `frontend/src/app/(app)/activity/page.tsx` | (app) | Activity timeline / dev event stream |
| `/issues` | `frontend/src/app/(app)/issues/page.tsx` | (app) | Failed projects and dead letters |
| `/settings` | `frontend/src/app/(app)/settings/page.tsx` | (app) | Profile, appearance, password, sessions |
| `/features/[route]` | `frontend/src/app/(app)/features/[route]/page.tsx` | (app) | Plug-in feature pages (Echo) |
| `/login` | `frontend/src/app/(auth)/login/page.tsx` | (auth) | Sign in |
| `/register` | `frontend/src/app/(auth)/register/page.tsx` | (auth) | Create account |
| `/forgot-password` | `frontend/src/app/(auth)/forgot-password/page.tsx` | (auth) | Request reset |
| `/reset-password` | `frontend/src/app/(auth)/reset-password/page.tsx` | (auth) | Choose new password |

### `frontend/next.config.ts`

```ts
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

```
