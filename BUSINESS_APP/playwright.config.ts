import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  outputDir:"../test-results/business",
  workers: 1,
  fullyParallel: false,
  timeout: 45000,
  use: {
    launchOptions: {
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
    },
    baseURL: "http://127.0.0.1:5174/business/",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node scripts/python.mjs -m scripts.business_test_server",
      url: "http://127.0.0.1:8876/api/health",
      cwd: "..",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev --workspace BUSINESS_APP -- --mode test",
      url: "http://127.0.0.1:5174/business/",
      cwd: "..",
      reuseExistingServer: false,
    },
  ],
});
