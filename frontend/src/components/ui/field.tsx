import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { forwardRef, useId } from "react";
import { cn } from "@/lib/cn";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: ReactNode;
}

export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field({ label, error, hint, className, id, ...props }, ref) {
  const auto = useId();
  const inputId = id ?? auto;
  const describedBy = [error ? `${inputId}-error` : null, hint ? `${inputId}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="space-y-1">
      <label htmlFor={inputId} className="block text-sm font-medium text-slate-800">{label}</label>
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(
          "block w-full rounded-xl border bg-white px-3.5 py-2.5 text-sm text-slate-900 placeholder:text-slate-400",
          error ? "border-red-500" : "border-slate-300",
          className,
        )}
        {...props}
      />
      {hint && <p id={`${inputId}-hint`} className="text-xs text-slate-600">{hint}</p>}
      {error && <p id={`${inputId}-error`} role="alert" className="text-xs text-red-700">{error}</p>}
    </div>
  );
});

interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  hint?: ReactNode;
}

/** A labelled native select (native keeps it accessible and works well on phones). */
export function SelectField({ label, hint, className, id, children, ...props }: SelectFieldProps) {
  const auto = useId();
  const selectId = id ?? auto;
  return (
    <div className="space-y-1">
      <label htmlFor={selectId} className="block text-sm font-medium text-slate-800">{label}</label>
      <select
        id={selectId}
        aria-describedby={hint ? `${selectId}-hint` : undefined}
        className={cn("block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900", className)}
        {...props}
      >
        {children}
      </select>
      {hint && <p id={`${selectId}-hint`} className="text-xs text-slate-600">{hint}</p>}
    </div>
  );
}
