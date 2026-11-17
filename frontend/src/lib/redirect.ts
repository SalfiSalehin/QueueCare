/** Only allow same-site relative paths as a post-login destination (blocks open redirects like //evil.com). */
export function safeNext(value: string | null | undefined, fallback = "/app"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return fallback;
  return value;
}
