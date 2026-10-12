import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "FDH_");
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": {
          target: env.FDH_DEV_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/tests/setup.ts"],
      restoreMocks: true,
      clearMocks: true,
    },
  };
});
