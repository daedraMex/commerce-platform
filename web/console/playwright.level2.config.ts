import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL;

if (!baseURL) {
  throw new Error("E2E_BASE_URL is required for the level-2 end-to-end tests.");
}

export default defineConfig({
  testDir: "./e2e-level2",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 1,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never" }]]
    : [["list"]],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "phone",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
