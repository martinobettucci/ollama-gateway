import { test, expect } from '@playwright/test';
import fs from 'fs';

// Export de la configuration (phase 3) : depuis le panel, un bouton télécharge l'état courant
// (serveurs/cibles/clés) au format YAML déclaratif — l'inverse du mode headless — SANS aucun secret.

const OUT = 'output';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

test('export: le bouton du panel télécharge un gateway.yaml sans secret', async ({ page }) => {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await expect(page.locator('h1')).toContainText('Tableau de bord');

  const exportBtn = page.locator('[data-testid=nav-export]');
  await expect(exportBtn).toBeVisible();

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    exportBtn.click(),
  ]);
  expect(download.suggestedFilename()).toBe('gateway.yaml');
  const text = fs.readFileSync(await download.path(), 'utf-8');

  // Structure déclarative présente…
  expect(text).toContain('servers:');
  expect(text).toContain('keys:');
  expect(text).toContain('demo (dev)');           // la clé seedée figure (par label)
  // …et AUCUN secret : ni la clé démo en clair, ni de champ `value`.
  expect(text).not.toContain('sk-ollama-devdemokey');
  expect(text).not.toContain('value:');

  // Vision : le tableau de bord avec la pilule « Exporter » dans la navigation.
  await page.screenshot({ path: `${OUT}/30-export.jpg`, type: 'jpeg', fullPage: true });

  // Le YAML téléchargé, rendu pour observation.
  await page.setContent(`<html><body style="font-family:system-ui;background:#f7f8fa;padding:24px">
    <h1 style="color:#23468C">gateway.yaml exporté (sans secret)</h1>
    <pre style="background:#fff;border-radius:12px;padding:16px;border-top:4px solid #238C33;
      font-size:13px;white-space:pre-wrap">${text.replace(/</g, '&lt;')}</pre></body></html>`);
  await page.screenshot({ path: `${OUT}/31-export-yaml.jpg`, type: 'jpeg', fullPage: true });
});
