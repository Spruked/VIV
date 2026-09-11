import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.CALI_CRM_FRONTEND_URL || 'http://127.0.0.1:21001',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'npm run dev:local',
    url: 'http://127.0.0.1:21001',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
