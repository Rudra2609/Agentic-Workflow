import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginView } from "@/views/AuthViews";

export const metadata: Metadata = { title: "Sign in" };

export default function Page() {
  return (
    <Suspense>
      <LoginView />
    </Suspense>
  );
}
