import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    // Tests must not depend on the developer's .env: pin the value the code is written against.
    env: { NEXT_PUBLIC_API_BASE_URL: "/api/v1" },
  },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
});
