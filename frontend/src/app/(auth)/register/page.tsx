import type { Metadata } from "next";
import { Suspense } from "react";

import { RegisterView } from "@/views/AuthViews";

export const metadata: Metadata = { title: "Create account" };

export default function Page() {
  return (
    <Suspense>
      <RegisterView />
    </Suspense>
  );
}
