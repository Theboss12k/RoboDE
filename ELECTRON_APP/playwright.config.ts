import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', outputDir: '../test-results/electron', workers: 1, timeout: 45000,
  webServer: { command: 'node scripts/python.mjs -m scripts.hosted_test_server', cwd: '..',
    url: 'http://127.0.0.1:8082/login', reuseExistingServer: false, timeout: 30000 },
});
