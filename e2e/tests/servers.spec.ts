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

test('restriction de modèle: cases sondées au rattachement → 403 hors allowlist + listings filtrés', async ({ page, request }) => {
  await login(page);

  // SPEC « rattachement » : le formulaire de création sonde le serveur choisi et affiche les
  // modèles réellement disponibles en cases à cocher — on coche demo:latest (pas de saisie libre).
  await page.fill('#label', 'client-restreint');
  const createChecks = page.locator('[data-testid=create-form] [data-testid=model-checks]');
  await createChecks.locator('input[value="demo:latest"]').check();
  await expect(createChecks.locator('input[value="autre:latest"]')).not.toBeChecked();
  await page.screenshot({ path: `${OUT}/08-create-model-checks.jpg`, type: 'jpeg', fullPage: true });
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  await expect(page.locator('[data-testid=env-dialog]')).toBeVisible();
  await page.locator('#env-done').click();
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

  // Sur le détail de la clé : le serveur rattaché est re-sondé, la case demo:latest est cochée
  // et autre:latest (disponible mais non autorisé) est décochée.
  await page.getByRole('link', { name: 'client-restreint' }).click();
  await expect(page.locator('[data-testid=server-select]')).toBeVisible();
  const detailChecks = page.locator('[data-testid=model-checks]');
  await expect(detailChecks.locator('input[value="demo:latest"]')).toBeChecked();
  await expect(detailChecks.locator('input[value="autre:latest"]')).not.toBeChecked();
  await page.screenshot({ path: `${OUT}/07-key-restricted.jpg`, type: 'jpeg', fullPage: true });
});

const DEMO = 'sk-ollama-devdemokey000000000000000000000000000000000000000000000000';

test('gestion des modèles: pull → visible → delete ; le proxy refuse /api/pull au client', async ({ page, request }) => {
  await login(page);
  await page.getByRole('link', { name: 'Serveurs' }).click();

  const local = page.locator('.card', { hasText: 'Ollama local' });
  // Ouvre le bloc « Modèles du serveur » et télécharge un modèle (commande d'admin LAN-only).
  await local.getByText('Modèles du serveur').click();
  const pullForm = local.locator('[data-testid^=pull-form-]');
  await pullForm.locator('input[name=model]').fill('llama3:8b');
  // Capture manuel : bloc « Modèles du serveur » déplié (pull + suppression par modèle).
  await page.screenshot({ path: `${OUT}/26-model-manage.jpg`, type: 'jpeg', fullPage: true });
  await pullForm.locator('button[type=submit]').click();

  // Flash de succès + le modèle apparaît (sonde rejouée → last_models rafraîchi).
  const localAfter = page.locator('.card', { hasText: 'Ollama local' });
  await expect(page.locator('.flash')).toContainText('téléchargé');
  await expect(localAfter).toContainText('llama3:8b');
  await page.screenshot({ path: `${OUT}/09-model-pull.jpg`, type: 'jpeg', fullPage: true });

  // Suppression : accepte la confirmation, le modèle disparaît de la liste.
  await localAfter.getByText('Modèles du serveur').click();
  page.on('dialog', d => d.accept());
  await localAfter.locator('[data-testid^=models-del-] button', { hasText: 'llama3:8b' }).click();
  const localFinal = page.locator('.card', { hasText: 'Ollama local' });
  await expect(page.locator('.flash')).toContainText('supprimé');
  await expect(localFinal.locator('[data-testid^=models-del-]')).not.toContainText('llama3:8b');
  await page.screenshot({ path: `${OUT}/10-model-delete.jpg`, type: 'jpeg', fullPage: true });

  // GARDE DE SÉCURITÉ : le proxy public refuse toute commande de gestion, clé valide comprise.
  const pull = await request.post(`${PROXY}/api/pull`, {
    headers: { Authorization: `Bearer ${DEMO}` }, data: { model: 'demo:latest' },
  });
  expect(pull.status()).toBe(403);
  expect(await pull.text()).toContain('gestion');
  const del = await request.delete(`${PROXY}/api/delete`, {
    headers: { Authorization: `Bearer ${DEMO}` }, data: { model: 'demo:latest' },
  });
  expect(del.status()).toBe(403);
});

test('monitoring: traçage du dernier usage par modèle sur le serveur', async ({ page, request }) => {
  await login(page);
  // Génère de l'usage attribué au serveur par défaut via le proxy (modèle demo:latest).
  await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}` }, data: { model: 'demo:latest', stream: false },
  });
  await page.getByRole('link', { name: 'Serveurs' }).click();
  const local = page.locator('.card', { hasText: 'Ollama local' });
  await local.getByRole('link', { name: 'Monitor' }).click();
  await expect(page.locator('h1')).toContainText('Monitor');
  // La table « Usage par modèle » trace demo:latest avec son dernier usage.
  const perModel = page.locator('[data-testid=monitor-permodel]');
  await expect(perModel).toBeVisible();
  await expect(perModel).toContainText('demo:latest');
  await page.screenshot({ path: `${OUT}/11-per-model.jpg`, type: 'jpeg', fullPage: true });
});

test('picker de modèles: serveur hors ligne → repli en saisie libre', async ({ page }) => {
  await login(page);

  // Ajouter un serveur injoignable (port fermé), puis créer une clé dessus.
  await page.getByRole('link', { name: 'Serveurs' }).click();
  await page.fill('#new-name', 'Injoignable');
  await page.fill('#new-url', 'http://127.0.0.1:59999');
  await page.locator('[data-testid=server-create-form] button[type=submit]').click();
  await expect(page.locator('.card', { hasText: 'Injoignable' })).toBeVisible();

  await page.getByRole('link', { name: 'Tableau de bord' }).click();
  await page.locator('#server_id').selectOption({ label: 'Injoignable' });
  // Repli spec : pas de cases, message + saisie libre utilisable.
  await expect(page.locator('#model-status')).toContainText('injoignable');
  await expect(page.locator('[data-testid=create-form] [data-testid=model-checks] input')).toHaveCount(0);
  await page.fill('#models', 'llama3:latest');
  await page.fill('#label', 'cle-offline');
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  await expect(page.locator('[data-testid=env-dialog]')).toBeVisible();
  await page.locator('#env-done').click();
  await expect(page.locator('[data-testid=created-secret]')).toBeVisible();
  // L'allowlist saisie librement est bien enregistrée.
  await page.getByRole('link', { name: 'cle-offline' }).click();
  await expect(page.locator('#models')).toHaveValue('llama3:latest');
});
