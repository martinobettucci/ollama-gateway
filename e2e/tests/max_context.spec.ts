import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

// Limite de CONTEXTE par clé : le proxy compte les tokens (tiktoken + marge 15 %) et refuse (413)
// AVANT l'amont, puis injecte `options.num_ctx` pour contraindre le serveur d'exécution.
// Clé jetable, nettoyée après, pour ne pas polluer les captures des specs suivantes.

const ROOT = path.resolve(__dirname, '..', '..');
const PY = path.join(ROOT, '.venv', 'bin', 'python');
const DB = path.join(__dirname, '..', 'e2e-data', 'gateway.db');
const OUT = 'output';
const PROXY = 'http://127.0.0.1:8791';

test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));
test.afterAll(() => {
  execSync(
    `${PY} -c "import os,sqlite3;c=sqlite3.connect(os.environ['GATEWAY_DB_PATH']);` +
    `c.execute(\\"DELETE FROM api_keys WHERE label='ctx-e2e'\\");c.commit()"`,
    { cwd: ROOT, env: { ...process.env, GATEWAY_DB_PATH: DB } });
});

test('contexte max : sélection à la création, refus 413 au-delà, requête normale OK', async ({ page, request }) => {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');

  // Créer une clé avec un plafond de contexte volontairement petit (4k).
  await page.fill('#label', 'ctx-e2e');
  await page.selectOption('[data-testid=max-ctx]', '4096');
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  const out = await page.locator('[data-testid=env-output]').textContent();
  const secret = (out.match(/OLLAMA_API_KEY=(\S+)/) || [])[1];
  await page.locator('#env-done').click();

  // Le plafond est affiché sur la ligne de la clé (badge).
  const row = page.locator('[data-testid=key-row]', { hasText: 'ctx-e2e' });
  await expect(row.locator('[data-testid=ctx-badge]')).toHaveText('4k');
  await page.screenshot({ path: `${OUT}/33-max-context.jpg`, type: 'jpeg', fullPage: true });

  // Requête normale (petit prompt) → acceptée.
  const ok = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${secret}` },
    data: { model: 'demo:latest', messages: [{ role: 'user', content: 'bonjour' }] },
  });
  expect(ok.status()).toBe(200);

  // Requête au contexte démesuré → refusée 413 AVANT l'amont, avec le détail du comptage.
  const big = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${secret}` },
    data: { model: 'demo:latest', messages: [{ role: 'user', content: 'mot '.repeat(5000) }] },
  });
  expect(big.status()).toBe(413);
  const body = await big.json();
  expect(body.max_context_tokens).toBe(4096);
  expect(body.tokens_with_margin).toBeGreaterThan(4096);
  // La marge de 15 % est bien appliquée sur l'estimation.
  expect(body.tokens_with_margin).toBe(Math.ceil(body.tokens_estimated * 1.15));

  // Le refus est journalisé (visible dans la console de logs).
  await page.goto('/admin/logs');
  await expect(page.locator('table', { hasText: '413' }).first()).toBeVisible();
});

test('contexte max : le proxy impose num_ctx à l\'amont (Ollama natif)', async ({ request }) => {
  // La clé démo (plafond par défaut 112k) : l'amont doit recevoir options.num_ctx = 114688.
  const DEMO = 'sk-ollama-devdemokey000000000000000000000000000000000000000000000000';
  const r = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}` },
    data: { model: 'demo:latest', messages: [{ role: 'user', content: 'bonjour' }] },
  });
  expect(r.status()).toBe(200);
  const seen = await (await request.get('http://127.0.0.1:11533/last-body')).json();
  expect(seen.options.num_ctx).toBe(114688);
});

test('stats : paliers de contexte réellement utilisés (camembert + tableau), clé et serveur',
  async ({ page, request }) => {
    const DEMO = 'sk-ollama-devdemokey000000000000000000000000000000000000000000000000';
    // Deux requêtes pour alimenter la statistique.
    for (const content of ['bonjour', 'mot '.repeat(200)]) {
      const r = await request.post(`${PROXY}/api/chat`, {
        headers: { Authorization: `Bearer ${DEMO}` },
        data: { model: 'demo:latest', messages: [{ role: 'user', content }] },
      });
      expect(r.status()).toBe(200);
    }

    await page.goto('/admin/login');
    await page.fill('#password', 'adminpass');
    await page.click('button[type=submit]');

    // --- Page de la CLÉ : camembert + tableau des paliers ---
    await page.locator('[data-testid=key-row]', { hasText: 'demo (dev)' })
      .getByRole('link').first().click();
    await expect(page.locator('[data-testid=ctx-donut] svg')).toBeVisible();
    const rows = page.locator('[data-testid=ctx-buckets] tbody tr');
    await expect(rows.first()).toBeVisible();
    // Chaque ligne : un palier de l'échelle, un compte, un dernier usage non vide.
    const firstSize = await rows.first().locator('td').first().innerText();
    expect(firstSize.trim()).toMatch(/^\d+k$/);
    const lastUsed = await rows.first().locator('td').nth(3).innerText();
    expect(lastUsed.trim().length).toBeGreaterThan(0);
    await page.screenshot({ path: `${OUT}/34-ctx-stats-key.jpg`, type: 'jpeg', fullPage: true });

    // --- Monitoring du SERVEUR : même statistique ---
    await page.goto('/admin/servers');
    await page.locator('[data-testid^=monitor-link-]').first().click();
    await page.waitForURL('**/monitor');
    await expect(page.locator('[data-testid=ctx-donut] svg')).toBeVisible();
    await expect(page.locator('[data-testid=ctx-buckets] tbody tr').first()).toBeVisible();
    await page.screenshot({ path: `${OUT}/35-ctx-stats-server.jpg`, type: 'jpeg', fullPage: true });
  });
