import type { Metadata } from "next";
import { Suspense } from "react";

import { ForgotPasswordView } from "@/views/AuthViews";

export const metadata: Metadata = { title: "Reset password" };

export default function Page() {
  return (
    <Suspense>
      <ForgotPasswordView />
    </Suspense>
  );
}
