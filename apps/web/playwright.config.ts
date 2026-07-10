import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // Every spec here shares one live API server backed by one throwaway
  // SQLite file (see docs/DEVELOPMENT.md) - there's no per-test DB reset or
  // isolation. import-flow.spec.ts in particular assumes it starts against
  // an empty database. That only holds if spec files run one at a time, not
  // in Playwright's default parallel workers, which would let two specs
  // that each import a pipeline race each other against the same DB.
  workers: 1,
  webServer: {
    command: "pnpm dev",
    port: 5173,
    reuseExistingServer: true,
  },
});
