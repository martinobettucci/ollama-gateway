import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

// Gabarit VS Code (« point de terminaison personnalisé ») proposé à la création d'une clé :
// bloc SÉPARÉ (zone copiable + bouton propres, les variables d'environnement restent visibles),
// portant le SECRET RÉEL (plus de placeholder `${input:…}`) et des capacités LUES sur le serveur
// d'exécution (`POST /api/show`) — appel d'outils, vision, fenêtres d'entrée/sortie — et non des
// constantes devinées. Clés jetables, nettoyées après, pour ne pas polluer les captures du
// manuel produites par les autres specs.

const ROOT = path.resolve(__dirname, '..', '..');
const PY = path.join(ROOT, '.venv', 'bin', 'python');
const DB = path.join(__dirname, '..', 'e2e-data', 'gateway.db');
const OUT = 'output';

test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

test.afterAll(() => {
  execSync(
    `${PY} -c "import os,sqlite3;c=sqlite3.connect(os.environ['GATEWAY_DB_PATH']);` +
    `c.execute(\\"DELETE FROM api_keys WHERE label LIKE 'vscode-e2e%'\\");c.commit()"`,
    { cwd: ROOT, env: { ...process.env, GATEWAY_DB_PATH: DB } });
});

async function login(page) {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
}

/** Crée une clé et renvoie [secret, modale ouverte]. `models` = libellés à cocher (vide = tous). */
async function createKey(page, label: string, models: string[]) {
  await page.fill('#label', label);
  for (const m of models) {
    await page.locator(`[data-testid=model-checks] input[value="${m}"]`).check();
  }
  await page.locator('[data-testid=create-form] button[type=submit]').click();
  const out = await page.locator('[data-testid=env-output]').textContent();
  return (out.match(/OLLAMA_API_KEY=(\S+)/) || [])[1];
}

test('gabarit VS Code : secret réel et capacités lues sur le serveur d\'exécution', async ({ page }) => {
  await login(page);
  const secret = await createKey(page, 'vscode-e2e', ['demo:latest', 'autre:latest']);
  expect(secret).toMatch(/^sk-ollama-/);

  // Le bloc VS Code est masqué tant qu'on ne le demande pas ; le cocher déclenche la sonde.
  await expect(page.locator('[data-testid=env-vscode-block]')).toBeHidden();
  await page.locator('#env-vscode').check();
  const hint = page.locator('[data-testid=env-vscode-hint]');
  await expect(hint).toBeVisible();
  await expect(hint).toHaveText(/Capacités lues sur le serveur d'exécution/);

  // Bloc SÉPARÉ : les variables d'environnement restent affichées à côté, intactes.
  await expect(page.locator('[data-testid=env-output]')).toContainText(`OLLAMA_API_KEY=${secret}`);

  const raw = await page.locator('[data-testid=env-vscode-output]').textContent();
  const conf = JSON.parse(raw);

  // 1. Le SECRET réel remplace le placeholder d'entrée VS Code.
  expect(raw).not.toContain('${input:');
  expect(conf[0].apiKey).toBe(secret);
  expect(conf[0].vendor).toBe('customendpoint');
  expect(conf[0].apiType).toBe('chat-completions');

  // 2. Les capacités viennent du serveur, modèle par modèle (elles DIFFÈRENT entre modèles).
  const byId = Object.fromEntries(conf[0].models.map((m) => [m.id, m]));
  expect(Object.keys(byId).sort()).toEqual(['autre:latest', 'demo:latest']);

  // demo:latest publie `capabilities: [tools, vision]`, fenêtre 8k → 6144 / 2048.
  expect(byId['demo:latest'].toolCalling).toBe(true);
  expect(byId['demo:latest'].vision).toBe(true);
  expect(byId['demo:latest'].maxInputTokens).toBe(6144);
  expect(byId['demo:latest'].maxOutputTokens).toBe(2048);

  // autre:latest ne publie pas `capabilities` : outils déduits du gabarit `.Tools`, pas de vision.
  // Sa fenêtre (256k) dépasse le plafond de contexte de la clé → c'est le plafond qui borne.
  expect(byId['autre:latest'].toolCalling).toBe(true);
  expect(byId['autre:latest'].vision).toBe(false);
  const total = byId['autre:latest'].maxInputTokens + byId['autre:latest'].maxOutputTokens;
  expect(total).toBeLessThan(262144);
  expect(total % 1024).toBe(0);

  // Captures du MANUEL, toutes deux en viewport (une capture d'ÉLÉMENT déborderait de la modale
  // et laisserait apparaître la page du dessous). (1) Haut de la modale : les deux zones copiables
  // qui coexistent. (2) Bas du bloc VS Code : capacités par modèle, message d'état, bouton propre.
  await page.screenshot({ path: `${OUT}/41-vscode-blocks.jpg`, type: 'jpeg' });
  await page.locator('[data-testid=env-vscode-copy]').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${OUT}/40-vscode-template.jpg`, type: 'jpeg' });

  // Bouton de copie PROPRE au bloc VS Code (repli execCommand : admin LAN servi en http).
  await page.locator('[data-testid=env-vscode-copy]').click();
  await expect(page.locator('#env-vscode-copy-label')).toHaveText('Copié !');
  // Celui des variables d'environnement est indépendant et reste sur son libellé initial.
  await expect(page.locator('#env-copy-label')).toHaveText('Copier les variables');

  await page.locator('#env-done').click();
});

test('gabarit VS Code : sans allowlist, tout le catalogue du serveur est décrit', async ({ page }) => {
  await login(page);
  await createKey(page, 'vscode-e2e-all', []);
  await page.locator('#env-vscode').check();
  // La sonde est asynchrone : la sortie reste vide tant que l'amont n'a pas répondu.
  const vsOut = page.locator('[data-testid=env-vscode-output]');
  await expect(vsOut).toContainText('customendpoint');

  const conf = JSON.parse(await vsOut.textContent());
  const ids = conf[0].models.map((m) => m.id).sort();
  expect(ids).toContain('demo:latest');
  expect(ids).toContain('autre:latest');
  // Chaque entrée porte les 4 champs réclamés : outils, vision, entrée max, sortie max.
  for (const m of conf[0].models) {
    expect(typeof m.toolCalling).toBe('boolean');
    expect(typeof m.vision).toBe('boolean');
    expect(m.maxInputTokens).toBeGreaterThan(0);
    expect(m.maxOutputTokens).toBeGreaterThan(0);
    expect(m.url).toMatch(/\/v1$/);
  }

  // Bornes DÉCLARÉES par l'amont (Modelfile `num_ctx 2048` / `num_predict 512`) : elles priment
  // sur le calcul de repli, qui aurait donné 1024/1024 (plancher de sortie).
  const declared = conf[0].models.find((m) => m.id === 'x/fakeflux:1b');
  expect(declared.maxOutputTokens).toBe(512);
  expect(declared.maxInputTokens).toBe(1536);
  await page.locator('#env-done').click();
});

test('gabarit VS Code : les deux blocs sont indépendants', async ({ page }) => {
  await login(page);
  const secret = await createKey(page, 'vscode-e2e-toggle', ['demo:latest']);
  const env = page.locator('[data-testid=env-output]');
  const block = page.locator('[data-testid=env-vscode-block]');

  await page.locator('#env-vscode').check();
  await expect(page.locator('[data-testid=env-vscode-output]')).toContainText('customendpoint');

  // Changer les API cochées ne touche PAS le gabarit VS Code…
  await page.locator('#env-api-openai').check();
  await expect(env).toContainText('OPENAI_BASE_URL=');
  await expect(page.locator('[data-testid=env-vscode-output]')).toContainText('customendpoint');

  // …et masquer le gabarit ne touche pas les variables d'environnement.
  await page.locator('#env-vscode').uncheck();
  await expect(block).toBeHidden();
  await expect(env).toContainText(`OLLAMA_API_KEY=${secret}`);
  await page.locator('#env-done').click();
});
