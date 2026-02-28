// @ts-check
const { defineConfig } = require('@playwright/test');

const baseURL = process.env.MOCK_UI_BASE_URL || 'http://127.0.0.1:9082';

module.exports = defineConfig({
  testDir: './tests',
  fullyParallel: false,
  retries: 0,
  timeout: 30000,
  use: {
    baseURL,
    trace: 'retain-on-failure'
  }
});
