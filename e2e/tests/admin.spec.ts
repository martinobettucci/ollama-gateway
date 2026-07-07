import { test, expect } from '@playwright/test';
import fs from 'fs';

const OUT = 'output';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

test('admin: login, création de clé (secret unique), détail + édition', async ({ page }) => {
  // Accès protégé → redirigé vers le login.
  await page.goto('/admin');
  await expect(page).toHaveURL(/\/admin\/login/);
  await page.screenshot({ path: `${OUT}/00-login.jpg`, type: 'jpeg', fullPage: true });
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await expect(page.locator('h1')).toContainText('Tableau de bord');
  await page.screenshot({ path: `${OUT}/01-dashboard.jpg`, type: 'jpeg', fullPage: true });

  // Création d'une clé avec origine + quota.
  await page.fill('#label', 'e2e-client');
  await page.fill('#monthly_token_cap', '100000');
  await page.fill('#origins', '203.0.113.0/24');
  await page.locator('[data-testid=create-form] button[type=submit]').click();

  // Le secret n'est montré qu'une fois.
  const secret = await page.locator('[data-testid=created-secret]').innerText();
  expect(secret).toContain('sk-ollama-');
  await page.screenshot({ path: `${OUT}/02-key-created.jpg`, type: 'jpeg', fullPage: true });
  await expect(page.locator('[data-testid=keys-table]')).toContainText('e2e-client');

  // Détail + édition du rate-limit.
  await page.getByRole('link', { name: 'e2e-client' }).click();
  await expect(page.locator('h1')).toContainText('e2e-client');
  await page.fill('#rpm_limit', '30');
  await page.locator('[data-testid=edit-form] button[type=submit]').click();
  await expect(page.locator('[data-testid=edit-form] #rpm_limit')).toHaveValue('30');
  await page.screenshot({ path: `${OUT}/03-key-detail.jpg`, type: 'jpeg', fullPage: true });
});

test('admin: manuel utilisateur affiché en modale (markdown + captures)', async ({ page }) => {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');

  await page.locator('[data-testid=manual-open]').click();
  const dialog = page.locator('#manual-dialog');
  await expect(dialog).toBeVisible();
  // Contenu markdown rendu (titre + capture d'écran servie par /static/manual/).
  await expect(dialog.locator('h1').first()).toContainText('Manuel');
  const img = dialog.locator('img[src="/static/manual/01-dashboard.jpg"]');
  await expect(img).toBeVisible();
  expect(await img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
  await page.screenshot({ path: `${OUT}/05-manual.jpg`, type: 'jpeg' });

  // Fermeture par la croix.
  await page.locator('#manual-close').click();
  await expect(dialog).toBeHidden();
});
