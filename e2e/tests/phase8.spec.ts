import { test, expect } from '@playwright/test';
import fs from 'fs';

const OUT = 'output';
const PROXY = 'http://127.0.0.1:8791';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

async function login(page) {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await expect(page.locator('h1')).toContainText('Tableau de bord');
}

test('phase8: compatibilité d\'API — test + matrice sur la page Serveurs', async ({ page }) => {
  await login(page);
  await page.goto('/admin/servers');
  // Lance le test de compatibilité sur le serveur par défaut (sonde d'accessibilité des chemins).
  await page.locator('[data-testid^=compat-test-]').first().click();
  await expect(page.locator('.flash')).toContainText('Compatibilité testée');
  // La matrice stockée s'affiche (au moins un endpoint servi par le faux Ollama).
  const matrix = page.locator('[data-testid^=compat-]').first();
  await matrix.locator('summary').click();
  await expect(matrix).toContainText('/api/chat');
  await page.screenshot({ path: `${OUT}/13-compat.jpg`, type: 'jpeg', fullPage: true });
});

test('phase8: cibles publiques — création + rattachement', async ({ page }) => {
  await login(page);
  await page.goto('/admin/targets');
  await expect(page.locator('h1')).toContainText('Cibles publiques');
  await page.fill('#new-tname', 'prod-eu');
  await page.fill('#new-turl', 'https://llm.example:21434');
  await page.locator('[data-testid=target-create-form] button[type=submit]').click();
  await expect(page.locator('[data-testid=target-card]').filter({ hasText: 'prod-eu' }))
    .toBeVisible();
  await page.screenshot({ path: `${OUT}/14-targets.jpg`, type: 'jpeg', fullPage: true });
});

test('phase8: clé avancée — API, cible, repli, expiration/plafonds de vie', async ({ page }) => {
  await login(page);
  // Création avec API cochées + cible + plafonds de vie.
  await page.fill('#label', 'trial-key');
  await page.locator('[data-testid=api-checks] input[value=ollama]').check();
  await page.locator('[data-testid=api-checks] input[value=openai]').check();
  await page.fill('#total_token_cap', '50000');
  await page.fill('#total_request_cap', '200');
  await page.fill('#idle_expiry_days', '14');
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  const secret = await page.locator('[data-testid=created-secret]').innerText();
  expect(secret).toContain('sk-ollama-');
  await page.locator('#env-done').click();

  // Génère de l'usage réel via le proxy (attribué au serveur par défaut) pour peupler le monitor.
  for (let i = 0; i < 3; i++) {
    const r = await page.request.post(`${PROXY}/api/chat`, {
      headers: { authorization: `Bearer ${secret}` },
      data: { model: 'demo:latest', stream: false, messages: [{ role: 'user', content: 'hi' }] },
    });
    expect(r.status()).toBe(200);
  }

  // Détail de la clé : champs avancés visibles (repli + expiration).
  await page.getByRole('link', { name: 'trial-key' }).click();
  await expect(page.locator('[data-testid=fallback-select]')).toBeVisible();
  await expect(page.locator('[data-testid=expiry-fields]')).toBeVisible();
  await expect(page.locator('#total_token_cap')).toHaveValue('50000');
  await page.screenshot({ path: `${OUT}/15-key-advanced.jpg`, type: 'jpeg', fullPage: true });
});

test('phase8: recherche/filtres des clés (tableau de bord)', async ({ page }) => {
  await login(page);
  await expect(page.locator('[data-testid=key-filters]')).toBeVisible();
  await page.fill('[data-testid=key-search]', 'zzz-inexistant');
  await expect(page.locator('[data-testid=key-empty]')).toBeVisible();
  await page.fill('[data-testid=key-search]', '');
  await page.screenshot({ path: `${OUT}/16-key-filters.jpg`, type: 'jpeg', fullPage: true });
});

test('phase8: monitoring d\'un serveur — conso par clé + graphiques', async ({ page }) => {
  await login(page);
  await page.goto('/admin/servers');
  await page.locator('[data-testid^=monitor-link-]').first().click();
  await expect(page.locator('h1')).toContainText('Monitor');
  await expect(page.locator('[data-testid=status-donut] svg')).toBeVisible();
  await expect(page.locator('[data-testid=monitor-perkey]')).toBeVisible();
  await page.screenshot({ path: `${OUT}/17-monitor.jpg`, type: 'jpeg', fullPage: true });
});
