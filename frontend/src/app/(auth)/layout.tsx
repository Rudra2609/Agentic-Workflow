import type { ReactNode } from "react";

import { HmapMark } from "@/components/AppShell";
import { AuthBackdrop, HierarchyStack } from "@/components/AuthBackdrop";

/**
 * Sign-in pages. Desktop: the hierarchy stack (the one bold element) with a plain, specific headline; the form on a
 * lifted card. Mobile: the mark and the form only.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative isolate min-h-screen overflow-hidden">
      <AuthBackdrop />
      <div className="mx-auto grid min-h-screen max-w-7xl lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <aside className="hidden flex-col px-12 py-10 lg:flex">
          <div className="flex items-center gap-2">
            <HmapMark className="size-8" />
            <span className="font-display text-xl font-semibold tracking-tight">hmap</span>
          </div>
          <div className="my-auto">
            <h1 className="max-w-[15ch] text-[3.25rem] leading-[1.02] font-bold tracking-[-0.03em] text-balance text-fg">
              Your goal goes in at the top.
            </h1>
            <p className="mt-5 max-w-[46ch] text-[1.0625rem] leading-relaxed text-fg-2">
              A manager agent turns it into a plan you can check, then hands each step down to a specialist —
              researcher, developer, tester, writer, reviewer. Follow every step as it happens, and stop it whenever
              you want.
            </p>
            <HierarchyStack />
          </div>
          <p className="text-xs text-muted">IT-314 Group 23. Runs on this computer.</p>
        </aside>

        <main id="main" className="flex flex-col items-center justify-center px-4 py-10 sm:px-8">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <HmapMark className="size-8" />
            <span className="font-display text-xl font-semibold tracking-tight">hmap</span>
          </div>
          <div className="hm-clipped w-full max-w-[25rem] rounded-[3px] p-7 sm:p-9">
            <span aria-hidden="true" className="hm-clip" />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
