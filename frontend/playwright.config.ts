import { defineConfig, devices } from "@playwright/test";

// End-to-end: the real Next.js build against the real backend (tests/e2e_server.py), external APIs faked.
// The frontend must be built with NEXT_PUBLIC_API_URL=http://localhost:8010 (see `npm run e2e:build`).
const DATA = process.env.E2E_DATA || "/tmp/reel-checker-e2e";
const PYTHON = process.env.E2E_PYTHON || "python";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: "http://localhost:3010", ...devices["Pixel 7"], trace: "retain-on-failure" },
  webServer: [
    {
      command: `${PYTHON} -m tests.e2e_server --port 8010 --data ${DATA} --frontend http://localhost:3010`,
      cwd: "../backend",
      url: "http://localhost:8010/api/health",
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "node .next/standalone/server.js", // the same server the Docker image runs
      url: "http://localhost:3010",
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      env: { PORT: "3010", HOSTNAME: "localhost" },
    },
  ],
});
