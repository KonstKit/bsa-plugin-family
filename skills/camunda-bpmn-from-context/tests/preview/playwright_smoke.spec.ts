import { expect, test } from '@playwright/test';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const previewDir = process.env.PREVIEW_DIR;
const previewHtml = previewDir ? path.join(previewDir, 'index.html') : '';

test('offline preview imports, fits, exposes controls, and stays offline', async ({ page }) => {
  expect(previewDir, 'Set PREVIEW_DIR to a built preview package before running smoke').toBeTruthy();
  const requests: string[] = [];
  page.on('request', (request) => {
    requests.push(request.url());
  });

  await page.goto(pathToFileURL(previewHtml).toString());

  await expect(page.getByTestId('version-stamp')).toContainText('preview_schema_version');
  await expect(page.getByTestId('viewer-mode')).toHaveText('Viewer Only');
  await expect(page.getByTestId('preview-error')).toBeHidden();

  await page.waitForFunction(() => Boolean((window as any).__previewRuntime?.imported));
  await expect(page.getByTestId('zoom-indicator')).not.toHaveText('100%');

  await page.getByTestId('zoom-in').click();
  await page.getByTestId('zoom-out').click();
  await page.getByTestId('zoom-reset').click();
  await page.getByTestId('pan-right').click();

  await page.waitForFunction(() => Boolean((window as any).__previewRuntime?.versionStamp));
  const runtime = await page.evaluate(() => (window as any).__previewRuntime);
  expect(runtime.imported).toBe(true);
  expect(runtime.networkRequired).toBe(false);
  expect(runtime.errors).toEqual([]);
  expect(runtime.sequenceFlowCount).toBeGreaterThan(0);
  expect(runtime.renderedConnectionCount).toBeGreaterThan(0);
  expect(runtime.shapeCount).toBeGreaterThan(runtime.renderedConnectionCount);
  expect(runtime.connectionLayerConsistent).toBe(true);
  expect(runtime.expectedConnectionCount).toBe(runtime.renderedConnectionCount);
  expect(runtime.expectedSequenceFlowCount).toBe(runtime.sequenceFlowCount);

  const externalRequests = requests.filter((url) => !url.startsWith('file://') && !url.startsWith('data:'));
  expect(externalRequests).toEqual([]);
});
