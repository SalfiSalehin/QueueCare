import type { Metadata } from "next";
import { Bricolage_Grotesque, Figtree } from "next/font/google";
import type { ReactNode } from "react";
import "@/styles/globals.css";
import { Providers } from "./providers";

const display = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-display", display: "swap" });
const body = Figtree({ subsets: ["latin"], variable: "--font-body", display: "swap" });

export const metadata: Metadata = {
  title: { default: "QueueCare", template: "%s · QueueCare" },
  description: "Clinic appointments and live queue. Demonstration system with synthetic data only.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body>
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
