import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

// Contrôle de la CIBLE (« passerelle ») rattachée à une clé : une clé émise pour une passerelle
// ne doit servir QUE par cette passerelle. Le proxy compare l'hôte réellement emprunté à l'URL de
// la cible rattachée et refuse 403 sinon.
//
// Forme de production reproduite : en prod, Caddy (pair de confiance) transmet l'hôte demandé par
// le client via `X-Forwarded-Host`. Ici Playwright appelle le proxy depuis 127.0.0.1, qui est un
// pair de confiance (TRUSTED_PROXY_IPS) — l'en-tête est donc honoré exactement comme derrière
// l'edge. (`Host` lui-même n'est pas modifiable depuis le client HTTP de Playwright.)

const ROOT = path.resolve(__dirname, '..', '..');
const PY = path.join(ROOT, '.venv', 'bin', 'python');
const DB = path.join(__dirname, '..', 'e2e-data', 'gateway.db');
const OUT = 'output';
const PROXY = 'http://127.0.0.1:8791';

const GW_HOST = 'passerelle-e2e.example:9443';
const GW_URL = `https://${GW_HOST}`;

test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));
test.afterAll(() => {
  // Clé ET cible jetables : on ne pollue pas les captures ni les specs suivantes.
  execSync(
    `${PY} -c "import os,sqlite3;c=sqlite3.connect(os.environ['GATEWAY_DB_PATH']);` +
    `c.execute(\\"DELETE FROM api_keys WHERE label='tgt-e2e'\\");` +
    `c.execute(\\"DELETE FROM targets WHERE name='passerelle-e2e'\\");c.commit()"`,
    { cwd: ROOT, env: { ...process.env, GATEWAY_DB_PATH: DB } });
});

test('cible contraignante : servie par sa passerelle, refusée par une autre', async ({ page, request }) => {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');

  // 1. Créer la passerelle (cible publique).
  await page.goto('/admin/targets');
  await page.fill('#new-tname', 'passerelle-e2e');
  await page.fill('#new-turl', GW_URL);
  await page.locator('[data-testid=target-create-form] button[type=submit]').click();
  await expect(page.locator('body')).toContainText('passerelle-e2e');
  await page.screenshot({ path: `${OUT}/38-target-created.jpg`, type: 'jpeg', fullPage: true });

  // 2. Créer une clé RATTACHÉE à cette passerelle.
  await page.goto('/admin');
  await page.fill('#label', 'tgt-e2e');
  // Le libellé de l'option est « nom — url » (avec les espaces du gabarit) : on résout la valeur
  // depuis l'option portant le nom, plutôt que de dépendre d'un libellé exact fragile.
  const targetValue = await page
    .locator('[data-testid=target-select] option', { hasText: 'passerelle-e2e' })
    .first().getAttribute('value');
  expect(targetValue).toBeTruthy();
  await page.selectOption('[data-testid=target-select]', targetValue!);
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  const out = await page.locator('[data-testid=env-output]').textContent();
  const secret = (out!.match(/OLLAMA_API_KEY=(\S+)/) || [])[1];
  expect(secret).toBeTruthy();
  await page.locator('#env-done').click();

  const body = { model: 'demo:latest', messages: [{ role: 'user', content: 'bonjour' }] };

  // 3. Arrivée PAR la passerelle rattachée → servie.
  const ok = await request.post(`${PROXY}/api/chat`, {
    headers: {
      Authorization: `Bearer ${secret}`,
      'X-Forwarded-Host': GW_HOST,
      'X-Forwarded-Proto': 'https',
    },
    data: body,
  });
  expect(ok.status()).toBe(200);

  // 4. Arrivée par une AUTRE passerelle (même amont) → refusée.
  const other = await request.post(`${PROXY}/api/chat`, {
    headers: {
      Authorization: `Bearer ${secret}`,
      'X-Forwarded-Host': 'autre-passerelle.example:9443',
      'X-Forwarded-Proto': 'https',
    },
    data: body,
  });
  expect(other.status()).toBe(403);
  expect(await other.text()).toContain('passerelle');

  // 5. Même hôte mais AUTRE PORT = autre passerelle (cas edge LAN vs URL publique) → refusée.
  const wrongPort = await request.post(`${PROXY}/api/chat`, {
    headers: {
      Authorization: `Bearer ${secret}`,
      'X-Forwarded-Host': 'passerelle-e2e.example:11435',
      'X-Forwarded-Proto': 'https',
    },
    data: body,
  });
  expect(wrongPort.status()).toBe(403);

  // 6. Le refus est journalisé (403 visible dans la console de logs).
  await page.goto('/admin/logs');
  await expect(page.locator('body')).toContainText('403');
  await page.screenshot({ path: `${OUT}/39-target-binding-refused.jpg`, type: 'jpeg', fullPage: true });
});
