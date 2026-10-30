import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "./",
  // Discover the lazy editor's imports at startup so opening it cannot trigger
  // dependency optimization and a page reload that discards the selected tab.
  optimizeDeps: {
    include: [
      "@monaco-editor/react",
      "monaco-editor/editor/contrib/codelens/browser/codeLensCache.js",
      "monaco-editor/editor/contrib/inlayHints/browser/inlayHintsController.js",
      "monaco-editor/editor/common/services/treeViewsDndService.js",
      "monaco-editor/editor/contrib/suggest/browser/suggestMemory.js",
      "monaco-editor/platform/actionWidget/browser/actionWidget.js",
      "monaco-editor/editor/editor.api.js",
      "monaco-editor/languages/definitions/python/register.js",
      "monaco-editor/languages/features/json/register.js",
    ],
  },
  server: { proxy: { "/api": process.env.ROBOT_IDE_TEST_UPSTREAM || "http://127.0.0.1:8765" } },
  build: { chunkSizeWarningLimit: 1800 },
});
