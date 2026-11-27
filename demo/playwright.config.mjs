import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 8961);

export default defineConfig({
  testDir: 'tests',
  globalSetup: './tests/global-setup.mjs',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}/jibu/`,
    trace: 'retain-on-failure',
    serviceWorkers: 'allow',
    launchOptions: process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `node build.mjs && node serve.mjs`,
    env: { PORT: String(PORT) },
    url: `http://localhost:${PORT}/jibu/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
