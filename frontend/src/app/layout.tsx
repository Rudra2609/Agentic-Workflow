import type { Metadata, Viewport } from "next";
import { Archivo, JetBrains_Mono } from "next/font/google";
import type { ReactNode } from "react";

import { ToastProvider } from "@/components/Toast";
import { PREFERENCES_INIT_SCRIPT, PreferencesProvider } from "@/lib/preferences";

import "./globals.css";

// Archivo (variable width + weight): headings use its expanded width, body its normal width — one family, two voices.
// JetBrains Mono: real ids only (developer mode).
const archivo = Archivo({ subsets: ["latin"], axes: ["wdth"], variable: "--font-body", display: "swap" });
const code = JetBrains_Mono({ subsets: ["latin"], variable: "--font-code", display: "swap" });

export const metadata: Metadata = {
  title: { default: "HMAP", template: "%s · HMAP" },
  description: "Describe a goal, review the plan, and let your AI team do the work.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#9cc492" },
    { media: "(prefers-color-scheme: dark)", color: "#140c0b" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${archivo.variable} ${code.variable}`}>
      <head>
        {/* theme + mode before first paint: no flash of the wrong theme */}
        <script dangerouslySetInnerHTML={{ __html: PREFERENCES_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen font-sans text-sm">
        <PreferencesProvider>
          <ToastProvider>{children}</ToastProvider>
        </PreferencesProvider>
      </body>
    </html>
  );
}
