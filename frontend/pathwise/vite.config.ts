import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the FastAPI backend. The target follows the backend
// port: run.command exports PATHWISE_BACKEND_URL so the two never drift.
const backend = process.env.PATHWISE_BACKEND_URL ?? "http://127.0.0.1:8077";

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.PORT ?? 5173),
    proxy: {
      "/api": backend,
    },
  },
});
