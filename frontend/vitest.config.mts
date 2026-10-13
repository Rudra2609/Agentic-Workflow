import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    // Pure-logic tests run in Node; component/hook tests opt in with `// @vitest-environment happy-dom`.
    environment: "node",
    // members keep their panel tests next to the panel (src/features/<plugin>/*.test.ts)
    include: ["tests/**/*.test.{ts,tsx}", "src/features/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
