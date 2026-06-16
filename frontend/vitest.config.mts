import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const root = dirname(fileURLToPath(import.meta.url));

// Frontend unit/component tests. `@/...` mirrors the tsconfig path alias (@/* -> ./*). esbuild's
// automatic JSX runtime handles .tsx (no @vitejs/plugin-react needed — there's no Fast Refresh in tests).
export default defineConfig({
  resolve: { alias: { "@": root } },
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["app/**/*.{test,spec}.{ts,tsx}"],
    css: false,
  },
});
