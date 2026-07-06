import { test, expect } from '@playwright/test';
import fs from 'fs';

const PROXY = 'http://127.0.0.1:8791';
const DEMO = 'sk-ollama-devdemokey000000000000000000000000000000000000000000000000';
const OUT = 'output';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

test('proxy: clé valide → 200 streamé, clé bidon/absente → 401', async ({ request }) => {
  const ok = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}` },
    data: { model: 'demo:latest', stream: true },
  });
  expect(ok.status()).toBe(200);
  const body = await ok.text();
  expect(body).toContain('Bonjour');
  expect(body).toContain('"eval_count"');   // chunk final traversé (streaming complet)

  const bad = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: 'Bearer sk-ollama-nope' }, data: {},
  });
  expect(bad.status()).toBe(401);

  const none = await request.post(`${PROXY}/api/chat`, { data: {} });
  expect(none.status()).toBe(401);
});

test('proxy: désactivation via l\'UI → 401, réactivation, usage visible', async ({ page, request }) => {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await expect(page.locator('h1')).toContainText('Tableau de bord');

  const row = page.locator('[data-testid=key-row]', { hasText: 'demo (dev)' });
  await row.getByRole('button', { name: 'désactiver' }).click();
  await expect(row.locator('.pill.off')).toBeVisible();

  // Clé désactivée → le proxy refuse.
  const disabled = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}` }, data: { model: 'demo:latest' },
  });
  expect(disabled.status()).toBe(401);

  // Réactivation.
  await row.getByRole('button', { name: 'activer' }).click();
  await expect(row.locator('.pill.on')).toBeVisible();

  // L'usage a été journalisé (compteur global > 0).
  await page.reload();
  const reqs = await page.locator('[data-testid=stat-reqs]').innerText();
  expect(parseInt(reqs, 10)).toBeGreaterThan(0);
  await page.screenshot({ path: `${OUT}/04-usage.jpg`, type: 'jpeg', fullPage: true });
});
