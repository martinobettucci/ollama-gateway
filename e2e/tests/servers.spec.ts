import { test, expect } from '@playwright/test';
import fs from 'fs';

const PROXY = 'http://127.0.0.1:8791';
const OUT = 'output';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

async function login(page) {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await expect(page.locator('h1')).toContainText('Tableau de bord');
}

test('serveurs: page, test du serveur par défaut (en ligne + modèles), ajout d\'un serveur', async ({ page }) => {
  await login(page);
  await page.getByRole('link', { name: 'Serveurs' }).click();
  await expect(page.locator('h1')).toContainText("Serveurs d'exécution");

  // Le serveur local par défaut existe, marqué « par défaut » et « non testé » au départ.
  const local = page.locator('.card', { hasText: 'Ollama local' });
  await expect(local.locator('.badge', { hasText: 'par défaut' })).toBeVisible();

  // Test de disponibilité → en ligne + modèles détectés (faux Ollama : demo:latest + autre:latest).
  await local.getByRole('button', { name: 'Tester' }).click();
  const localAfter = page.locator('.card', { hasText: 'Ollama local' });
  await expect(localAfter.locator('.badge', { hasText: 'en ligne' })).toBeVisible();
  await expect(localAfter).toContainText('demo:latest');
  await expect(localAfter).toContainText('autre:latest');
  await page.screenshot({ path: `${OUT}/06-servers.jpg`, type: 'jpeg', fullPage: true });

  // Ajout d'un serveur distant (avec jeton d'auth).
  await page.fill('#new-name', 'Ollama atelier');
  await page.fill('#new-url', 'http://127.0.0.1:11533');
  await page.fill('#new-tok', 'jeton-distant');
  await page.locator('[data-testid=server-create-form] button[type=submit]').click();
  const added = page.locator('.card', { hasText: 'Ollama atelier' });
  await expect(added).toBeVisible();
  await expect(added.locator('.badge', { hasText: 'auth' })).toBeVisible();  // jeton chiffré présent
});

test('restriction de modèle: clé limitée → proxy 403 hors allowlist + listings filtrés + cases sur le détail', async ({ page, request }) => {
  await login(page);

  // S'assurer que le serveur par défaut a été sondé (peuple les cases à cocher).
  await page.getByRole('link', { name: 'Serveurs' }).click();
  await page.locator('.card', { hasText: 'Ollama local' }).getByRole('button', { name: 'Tester' }).click();

  // Créer une clé restreinte à demo:latest sur le serveur par défaut.
  await page.getByRole('link', { name: 'Tableau de bord' }).click();
  await page.fill('#label', 'client-restreint');
  await page.fill('#models', 'demo:latest');
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  const secret = (await page.locator('[data-testid=created-secret]').innerText()).trim();
  expect(secret).toContain('sk-ollama-');

  // Le proxy honore la restriction, quelle que soit l'API.
  const okOllama = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${secret}` }, data: { model: 'demo:latest' },
  });
  expect(okOllama.status()).toBe(200);
  const blockedOllama = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${secret}` }, data: { model: 'autre:latest' },
  });
  expect(blockedOllama.status()).toBe(403);
  const blockedOpenAI = await request.post(`${PROXY}/v1/chat/completions`, {
    headers: { Authorization: `Bearer ${secret}` }, data: { model: 'autre:latest', messages: [] },
  });
  expect(blockedOpenAI.status()).toBe(403);

  // Les listings sont filtrés à l'allowlist.
  const tags = await request.get(`${PROXY}/api/tags`, {
    headers: { Authorization: `Bearer ${secret}` },
  });
  const names = (await tags.json()).models.map((m: any) => m.name);
  expect(names).toEqual(['demo:latest']);

  // Sur le détail de la clé : serveur rattaché sélectionné + case demo:latest cochée.
  await page.getByRole('link', { name: 'client-restreint' }).click();
  await expect(page.locator('[data-testid=server-select]')).toBeVisible();
  const demoCheck = page.locator('[data-testid=model-checks] input[value="demo:latest"]');
  await expect(demoCheck).toBeChecked();
  await page.screenshot({ path: `${OUT}/07-key-restricted.jpg`, type: 'jpeg', fullPage: true });
});
