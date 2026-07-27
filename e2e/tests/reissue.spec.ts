import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

// Réémission d'une clé (rotation du secret, même compte) + repli du bouton « Copier » en contexte
// NON sécurisé (admin LAN servi en http → navigator.clipboard absent). On utilise des clés jetables
// (jamais la clé démo) et on nettoie après, pour ne pas polluer les captures des specs suivantes.

const ROOT = path.resolve(__dirname, '..', '..');
const PY = path.join(ROOT, '.venv', 'bin', 'python');
const DB = path.join(__dirname, '..', 'e2e-data', 'gateway.db');
const OUT = 'output';
const PROXY = 'http://127.0.0.1:8791';

test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

test.afterAll(() => {
  execSync(
    `${PY} -c "import os,sqlite3;c=sqlite3.connect(os.environ['GATEWAY_DB_PATH']);` +
    `c.execute(\\"DELETE FROM api_keys WHERE label IN ('reissue-e2e','copy-e2e')\\");c.commit()"`,
    { cwd: ROOT, env: { ...process.env, GATEWAY_DB_PATH: DB } });
});

async function login(page) {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
}

async function createKey(page, label: string) {
  await page.fill('#label', label);
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  const out = await page.locator('[data-testid=env-output]').textContent();
  return (out.match(/OLLAMA_API_KEY=(\S+)/) || [])[1];
}

test('réémission : ancien secret invalidé, nouveau opérationnel, compte conservé', async ({ page, request }) => {
  await login(page);
  const secret1 = await createKey(page, 'reissue-e2e');
  expect(secret1).toMatch(/^sk-ollama-/);
  await page.locator('#env-done').click();

  // L'ancien secret fonctionne.
  let r = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${secret1}` }, data: { model: 'demo:latest' } });
  expect(r.status()).toBe(200);

  // Réémettre (confirmation acceptée).
  page.on('dialog', (d) => d.accept());
  const row = page.locator('[data-testid=key-row]', { hasText: 'reissue-e2e' });
  await row.locator('[data-testid=reissue-btn]').click();

  // Nouvelle modale, nouveau secret.
  await expect(page.locator('[data-testid=env-dialog]')).toBeVisible();
  const out2 = await page.locator('[data-testid=env-output]').textContent();
  const secret2 = (out2.match(/OLLAMA_API_KEY=(\S+)/) || [])[1];
  expect(secret2).toMatch(/^sk-ollama-/);
  expect(secret2).not.toBe(secret1);
  await page.screenshot({ path: `${OUT}/32-reissue.jpg`, type: 'jpeg', fullPage: true });
  await page.locator('#env-done').click();

  // Ancien secret => 401, nouveau => 200 ; la clé (même compte) est toujours active.
  r = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${secret1}` }, data: { model: 'demo:latest' } });
  expect(r.status()).toBe(401);
  r = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${secret2}` }, data: { model: 'demo:latest' } });
  expect(r.status()).toBe(200);
  await expect(row.locator('.badge.on')).toBeVisible();
});

test('copie : repli execCommand en contexte non sécurisé (navigator.clipboard absent)', async ({ page }) => {
  // Simule l'admin servi en http sur le LAN : pas de contexte sécurisé → clipboard API indisponible.
  await page.addInitScript(() => {
    try { Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true }); }
    catch (e) { /* certains navigateurs interdisent la redéfinition — le test reste valide */ }
  });
  await login(page);
  await createKey(page, 'copy-e2e');

  const copyBtn = page.locator('[data-testid=env-copy]');
  const copiedText = await copyBtn.getAttribute('data-copied');
  await copyBtn.click();
  // Le repli (textarea DANS le <dialog> + execCommand) doit réussir → libellé « Copié ».
  await expect(page.locator('#env-copy-label')).toHaveText(copiedText);
});
