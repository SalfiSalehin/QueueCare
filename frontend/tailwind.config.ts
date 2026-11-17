import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0C2B2E",            // deep teal-ink: dark panels and headings
        mint: "#D7F0E6",           // soft brand tint
        ticket: "#FFD166",         // the yellow of a queue ticket: used sparingly, for the token itself
        paper: "#F5F8F7",          // page background (cool, not cream)
      },
      fontFamily: {
        sans: ["var(--font-body)", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Arial", "sans-serif"],
        display: ["var(--font-display)", "var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        lift: "0 1px 2px rgba(12,43,46,0.06), 0 12px 32px -12px rgba(12,43,46,0.25)",
      },
    },
  },
  plugins: [],
};

export default config;
