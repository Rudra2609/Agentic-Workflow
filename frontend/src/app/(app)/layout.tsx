import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { EventStreamProvider } from "@/components/EventStreamProvider";
import { LoadingState } from "@/components/ui";
import { AuthProvider } from "@/lib/auth";

/** Every page in this group needs a signed-in user (the API enforces it; this decides what to render). */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider fallback={<LoadingState label="Opening your workspace…" />}>
      <EventStreamProvider>
        <AppShell>{children}</AppShell>
      </EventStreamProvider>
    </AuthProvider>
  );
}
