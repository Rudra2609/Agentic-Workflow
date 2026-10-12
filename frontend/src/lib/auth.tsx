"use client";

/**
 * Who is signed in. The API is the security boundary (every route checks the session cookie); this provider only
 * decides what to render: the app for a signed-in user, otherwise a redirect to /login?next=<where they were>.
 * Any 401 from the API (expired or revoked session) triggers the same redirect.
 */
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ErrorState } from "@/components/ui";

import { api, isApiError, UNAUTHORIZED_EVENT } from "./api";
import type { User } from "./types";

interface Auth {
  user: User;
  setUser: (u: User) => void;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

/** Only allow same-site relative paths as post-login targets (no open redirects). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  if (next.startsWith("/login") || next.startsWith("/register")) return "/";
  return next;
}

export function AuthProvider({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<unknown>(null);

  const toLogin = useCallback(() => {
    const here = typeof window === "undefined" ? pathname : window.location.pathname + window.location.search;
    router.replace(`/login?next=${encodeURIComponent(safeNext(here))}`);
  }, [router, pathname]);

  useEffect(() => {
    const controller = new AbortController();
    api
      .me(controller.signal)
      .then((me) => setUser(me.user))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (isApiError(err) && err.status === 401) toLogin();
        else setError(err);
      });
    return () => controller.abort();
    // only on mount: later expiry is reported through UNAUTHORIZED_EVENT
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      toLogin();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [toLogin]);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      router.replace("/login");
    }
  }, [router]);

  const value = useMemo(() => (user ? { user, setUser, signOut } : null), [user, signOut]);
  if (error) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <ErrorState error={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }
  if (!value) return <>{fallback}</>;
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
