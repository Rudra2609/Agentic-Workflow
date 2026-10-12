import type { Metadata } from "next";
import { Suspense } from "react";

import { ResetPasswordView } from "@/views/AuthViews";

export const metadata: Metadata = { title: "Choose a new password" };

export default function Page() {
  return (
    <Suspense>
      <ResetPasswordView />
    </Suspense>
  );
}
