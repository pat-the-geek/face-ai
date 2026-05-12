/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En dev (Docker), `api` est le hostname du service compose.
// Le frontend s'adresse à /api/* et /static/*, et Vite proxy vers le backend.
const API_TARGET = process.env.VITE_API_TARGET || "http://api:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/static": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
    watch: {
      usePolling: true, // requis pour HMR sous bind-mount macOS vers Linux
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{js,jsx}"],
      exclude: [
        "src/**/*.test.{js,jsx}",
        "src/test/**",
        "src/main.jsx",
      ],
    },
  },
});
