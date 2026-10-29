import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { proxy: { "/api": process.env.ROBOT_IDE_TEST_UPSTREAM || "http://127.0.0.1:8765" } },
  build: { chunkSizeWarningLimit: 1800 },
});
