import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-xl text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-teal-700 px-4 py-2.5 text-white shadow-xs hover:bg-teal-800",
        secondary: "border border-slate-300 bg-white px-4 py-2.5 text-slate-800 hover:bg-slate-100",
        ghost: "px-3 py-2 text-slate-700 hover:bg-slate-100",
        danger: "border border-red-300 bg-white px-4 py-2 text-red-700 hover:bg-red-50",
      },
      size: { md: "", sm: "!px-3 !py-1.5 text-xs" },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  loading?: boolean;
}

export function Button({ className, variant, size, loading, disabled, children, type = "button", ...props }: ButtonProps) {
  return (
    <button type={type} className={cn(button({ variant, size }), className)} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
      {loading && <span aria-hidden className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}
