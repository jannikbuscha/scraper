// Playwright E2E suite (docs/UI.md §7, §8.9). Each webServer runs
// e2e/start-server.mjs: a fresh temporary database (mdt db upgrade + mdt seed),
// served together with the built frontend (frontend/dist) by `mdt serve` on a
// free port. Two projects, two servers: `chromium` runs the Phase 1 scenarios
// in parallel; `collectors` runs the Phase 2 scenarios (e2e/collectors.spec.ts)
// serially against a server of its own whose collectors answer from the
// stored fixtures (replay). Build the frontend first (`make e2e` does both;
// `npm run e2e` only runs the suite).
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';

import { defineConfig, devices } from '@playwright/test';

/** A free TCP port on 127.0.0.1, asked from the operating system. */
function freePort(): string {
  const script = `
    const server = require('node:net').createServer();
    server.listen(0, '127.0.0.1', () => {
      process.stdout.write(String(server.address().port));
      server.close();
    });`;
  return execFileSync(process.execPath, ['-e', script], { encoding: 'utf8' }).trim();
}

// The config is loaded by the runner and again by every worker: the ports are
// chosen once and handed on through the environment, which workers inherit.
const port = (process.env.MDT_E2E_PORT ??= freePort());
const baseURL = `http://127.0.0.1:${port}`;
const collectorsPort = (process.env.MDT_E2E_COLLECTORS_PORT ??= freePort());
const collectorsURL = `http://127.0.0.1:${collectorsPort}`;

/** The Phase 2 scenarios: collector runs touch many records, so they get their own server. */
const COLLECTOR_SPECS = /collectors\.spec\.ts$/;

/** Shared settings of both servers. */
const serverOptions = {
  reuseExistingServer: false,
  timeout: 120_000,
  // SIGTERM lets the script stop the server and remove its temporary database.
  gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
  stdout: 'ignore',
  stderr: 'pipe',
} as const;

// Preinstalled browsers of the cloud development environment, as the Makefile
// sets them; workers inherit the variable. Playwright then runs the Chromium
// build of its own version from there (headless: its headless shell);
// elsewhere its default location (`npx playwright install chromium`).
const PREINSTALLED_BROWSERS = '/opt/pw-browsers';
if (process.env.PLAYWRIGHT_BROWSERS_PATH === undefined && existsSync(PREINSTALLED_BROWSERS)) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = PREINSTALLED_BROWSERS;
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // No retries: a flaky scenario must fail visibly and be fixed.
  retries: 0,
  // The scenarios use distinct records, so they run in parallel on one database
  // (locally: Playwright's default, half the CPU cores).
  workers: process.env.CI ? 2 : undefined,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL,
    locale: 'en-US',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: COLLECTOR_SPECS,
      // A wide viewport: the table and the comments panel fit side by side.
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } },
    },
    {
      name: 'collectors',
      testMatch: COLLECTOR_SPECS,
      // One file, run in order (test.describe.configure({ mode: 'serial' })).
      fullyParallel: false,
      // Runs poll until they finish; replayed runs take seconds, not minutes.
      timeout: 180_000,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 }, baseURL: collectorsURL },
    },
  ],
  webServer: [
    { ...serverOptions, command: `node e2e/start-server.mjs ${port}`, url: `${baseURL}/api/health` },
    {
      ...serverOptions,
      command: `node e2e/start-server.mjs ${collectorsPort} collectors`,
      url: `${collectorsURL}/api/health`,
    },
  ],
});
