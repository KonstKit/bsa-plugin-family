import { defineConfig } from '@playwright/test';

const SUPPORTED_BROWSER_NAMES = new Set(['chromium', 'firefox', 'webkit']);

function resolveProjectNames() {
  const rawValue = process.env.PREVIEW_PLAYWRIGHT_PROJECTS;
  if (!rawValue) {
    return ['chromium'];
  }
  const names = rawValue
    .split(/[,\s]+/)
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);

  if (names.length == 0) {
    throw new Error('PREVIEW_PLAYWRIGHT_PROJECTS is set but empty.');
  }

  const invalidNames = names.filter((name) => !SUPPORTED_BROWSER_NAMES.has(name));
  if (invalidNames.length > 0) {
    throw new Error(
      `Unsupported PREVIEW_PLAYWRIGHT_PROJECTS values: ${invalidNames.join(', ')}. Supported values: chromium, firefox, webkit.`
    );
  }
  return names;
}

const projectNames = resolveProjectNames();

export default defineConfig({
  testDir: __dirname,
  testMatch: ['playwright_smoke.spec.ts'],
  timeout: 30_000,
  projects: projectNames.map((name) => ({
    name,
    use: {
      browserName: name,
      headless: true
    }
  }))
});
