import { test, expect } from '@playwright/test';
import fs from 'fs';

// Navigation mobile : sous le point de rupture (900 px), les 7 entrées ne tiennent pas sur une
// ligne — la barre se replie derrière un bouton et devient une pile verticale. Régression visée :
// avant, la nav mesurait 852 px, forçait le document à 875 px et rendait 4 entrées INATTEIGNABLES.

const OUT = 'output';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

async function login(page) {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
}

test('mobile : aucun débordement horizontal et toutes les entrées atteignables', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);

  // 1) Le document ne déborde JAMAIS de la largeur du viewport (règle dure plein viewport).
  const doc = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(doc.scroll).toBeLessThanOrEqual(doc.client);

  // 2) Repliée par défaut : bouton visible, pile masquée.
  const toggle = page.locator('[data-testid=nav-toggle]');
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('.pills')).toBeHidden();
  await page.screenshot({ path: `${OUT}/36-nav-mobile-closed.jpg`, type: 'jpeg' });

  // 3) Ouverte : les 7 entrées sont visibles ET entièrement dans le viewport.
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  const items = page.locator('.pills .pill-link');
  await expect(items).toHaveCount(7);
  for (let i = 0; i < 7; i++) {
    const box = await items.nth(i).boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390 + 1);
    expect(box!.height).toBeGreaterThanOrEqual(44);   // cible tactile ≥ 44 px
  }
  // Toujours aucun débordement une fois dépliée.
  const after = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(after).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `${OUT}/37-nav-mobile-open.jpg`, type: 'jpeg' });

  // 4) L'entrée courante reste signalée, et la déconnexion est bien présente.
  await expect(page.locator('.pills .pill-link.active')).toHaveCount(1);
  await expect(page.locator('.pills .pill-exit')).toBeVisible();

  // 5) Échap referme (voie d'échappement) et rend le focus au bouton.
  await page.keyboard.press('Escape');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toBeFocused();

  // 6) Une entrée réellement navigable depuis le menu mobile (preuve d'accessibilité réelle).
  await toggle.click();
  await page.locator('.pills a', { hasText: 'Logs' }).click();
  await page.waitForURL('**/admin/logs');
});

test('desktop : la rangée de pilules est conservée, sans bouton de repli', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await login(page);
  await expect(page.locator('[data-testid=nav-toggle]')).toBeHidden();
  await expect(page.locator('.pills')).toBeVisible();
  await expect(page.locator('.pills .pill-link')).toHaveCount(7);
  const doc = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(doc.scroll).toBeLessThanOrEqual(doc.client);
});
