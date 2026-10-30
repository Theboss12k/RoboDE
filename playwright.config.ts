import { fileURLToPath } from 'node:url';
import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  outputDir:"./test-results/ide",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    storageState: fileURLToPath(new URL("./tests/expert-mode.json", import.meta.url)),
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1512, height: 982 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {command: "node scripts/python.mjs -m scripts.ide_test_server", url: "http://127.0.0.1:8877/api/health", reuseExistingServer:false},
    {command: "npm run dev --workspace SERVER_CLIENT/client", url: "http://127.0.0.1:5173", env:{ROBOT_IDE_TEST_UPSTREAM:"http://127.0.0.1:8877"}, reuseExistingServer:false, timeout:40000},
  ],
});
