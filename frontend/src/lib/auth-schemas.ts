import { z } from "zod";

/**
 * Validation for the sign-in and sign-up forms. These only improve the form's feedback: the backend validates again
 * and is the authority (it rejects short passwords and bad emails itself). Kept here, not inside the pages, so the
 * rules are unit tested and survive library upgrades (Zod 3 to 4 changed several details).
 */
export const loginSchema = z.object({
  email: z.string().min(1, "Enter your email").email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
export type LoginValues = z.infer<typeof loginSchema>;

export const registerSchema = z.object({
  full_name: z.string().trim().min(1, "Enter your name").max(200),
  email: z.string().min(1, "Enter your email").email("Enter a valid email address"),
  password: z.string().min(12, "Use at least 12 characters"),
});
export type RegisterValues = z.infer<typeof registerSchema>;
