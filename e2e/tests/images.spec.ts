import { test, expect } from '@playwright/test';
import fs from 'fs';

const OUT = 'output';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

async function login(page) {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await expect(page.locator('h1')).toContainText('Tableau de bord');
}

test('image: création clé avec capacité image + modèle x/, génération dans l\'onglet Image', async ({ page }) => {
  await login(page);

  // Clé avec capacité « Image via Ollama » + modèle d'image x/fakeflux:1b (saisie libre robuste).
  await page.fill('#label', 'img-key');
  await page.locator('[data-testid=api-image-checks] input[value=ollama-image]').check();
  await page.fill('#image_models', 'x/fakeflux:1b');
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  await expect(page.locator('[data-testid=env-dialog]')).toBeVisible();
  await page.locator('#env-done').click();

  // Détail de la clé → « Essayer maintenant » → onglets Texte/Image visibles.
  await page.getByRole('link', { name: 'img-key' }).click();
  await page.locator('[data-testid=try-open]').click();
  await expect(page.locator('[data-testid=try-dialog]')).toBeVisible();
  await expect(page.locator('[data-testid=try-tabs]')).toBeVisible();

  // Onglet Image : le panneau Texte se masque, le panneau Image s'affiche (pas de superposition).
  await page.locator('[data-testid=tab-image]').click();
  await expect(page.locator('.try-panel[data-panel=text]')).toBeHidden();
  await expect(page.locator('.try-panel[data-panel=image]')).toBeVisible();
  await expect(page.locator('[data-testid=img-model]')).toHaveValue('x/fakeflux:1b');
  await page.fill('[data-testid=img-prompt]', 'a small red circle');
  await page.locator('[data-testid=img-send]').click();

  const img = page.locator('[data-testid=img-result]');
  await expect(img).toBeVisible({ timeout: 15000 });
  // L'image affichée est bien une data URL PNG non vide.
  expect(await img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
  await page.screenshot({ path: `${OUT}/18-image-trynow.jpg`, type: 'jpeg', fullPage: true });
});

test('image: joindre une image d\'entrée (image-to-image) est accepté', async ({ page }) => {
  await login(page);
  await page.fill('#label', 'img2img');
  await page.locator('[data-testid=api-image-checks] input[value=ollama-image]').check();
  await page.fill('#image_models', 'x/fakeflux:1b');
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  await page.locator('#env-done').click();

  await page.getByRole('link', { name: 'img2img' }).click();
  await page.locator('[data-testid=try-open]').click();
  await page.locator('[data-testid=tab-image]').click();

  // Joint un PNG 1×1 comme image d'entrée.
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64');
  await page.locator('[data-testid=img-attach]').setInputFiles({
    name: 'in.png', mimeType: 'image/png', buffer: png });
  await page.fill('[data-testid=img-prompt]', 'make it blue');
  await page.locator('[data-testid=img-send]').click();
  await expect(page.locator('[data-testid=img-result]')).toBeVisible({ timeout: 15000 });
});
