import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests", testMatch: "*.spec.ts", timeout: 30000,
  use: { baseURL: "http://127.0.0.1:4175", channel: "chrome", headless: true, screenshot: "only-on-failure", viewport: { width: 1000, height: 1000 } },
  webServer: { command: "node tests/host.mjs", url: "http://127.0.0.1:4175", reuseExistingServer: false },
});
