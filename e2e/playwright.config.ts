import { defineConfig, devices } from '@playwright/test';

// The deployed web application under test (no trailing slash needed).
export const BASE_URL = (process.env.STAGING_WEB_URL || 'https://staging.eduralms.com').replace(/\/+$/, '');

export default defineConfig({
  testDir: './tests',
  // The three flows share one gateway rate limit (100 requests/minute per IP), so run them one at a time.
  workers: 1,
  fullyParallel: false,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  // A 429 from the shared gateway limit is transient, so a failed test is tried again after a pause.
  retries: 2,
  reporter: [['list'], ['html', { open: 'never' }], ['junit', { outputFile: 'results/junit.xml' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
