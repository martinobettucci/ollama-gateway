import { test, expect } from '@playwright/test';
import fs from 'fs';

const OUT = 'output';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

test('admin: login, création de clé (secret unique), détail + édition', async ({ page }) => {
  // Accès protégé → redirigé vers le login.
  await page.goto('/admin');
  await expect(page).toHaveURL(/\/admin\/login/);
  // Pied de page d'attribution P2Enjoy (lien vers le site) visible dès le login.
  const footerLink = page.locator('[data-testid="app-footer"] a[href="https://p2enjoy.studio"]');
  await expect(footerLink).toBeVisible();
  await expect(page.locator('[data-testid="app-footer"]')).toContainText('Made proudly with AI by');
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

  // La modale de configuration client s'ouvre automatiquement ; on la ferme ici
  // (elle a son test dédié plus bas).
  await expect(page.locator('[data-testid=env-dialog]')).toBeVisible();
  await page.locator('#env-done').click();

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

test('modale de configuration client : variables d\'env selon les API cochées + copie', async ({ page }) => {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');

  await page.fill('#label', 'cli-env');
  await page.locator('[data-testid=create-form] button[type=submit]').click();

  // La modale s'ouvre seule à la création ; par défaut, l'API Ollama est cochée.
  const dlg = page.locator('[data-testid=env-dialog]');
  await expect(dlg).toBeVisible();
  const out = dlg.locator('[data-testid=env-output]');
  await expect(out).toContainText('OLLAMA_HOST=http://127.0.0.1:8791');
  await expect(out).toContainText('OLLAMA_API_KEY=sk-ollama-');
  await expect(out).not.toContainText('OPENAI_BASE_URL');

  // Cocher OpenAI + Anthropic → les variables correspondantes apparaissent.
  await dlg.locator('#env-api-openai').check();
  await dlg.locator('#env-api-anthropic').check();
  await expect(out).toContainText('OPENAI_BASE_URL=http://127.0.0.1:8791/v1');
  await expect(out).toContainText('OPENAI_API_KEY=sk-ollama-');
  await expect(out).toContainText('ANTHROPIC_BASE_URL=http://127.0.0.1:8791');
  await expect(out).toContainText('ANTHROPIC_API_KEY=sk-ollama-');
  await page.screenshot({ path: `${OUT}/09-env-modal.jpg`, type: 'jpeg' });

  // Copie en un clic (repli execCommand en http) : retour visuel « Copié ! ».
  await dlg.locator('[data-testid=env-copy]').click();
  await expect(dlg.locator('#env-copy-label')).toHaveText('Copié !');

  await page.locator('#env-done').click();
  await expect(dlg).toBeHidden();
});

test('essayer maintenant : chat de test d\'une clé → réponse réelle du serveur', async ({ page }) => {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');

  // Ouvre le détail de la clé de démo puis la modale « Essayer maintenant ».
  await page.getByRole('link', { name: 'demo (dev)' }).click();
  await page.locator('[data-testid=try-open]').click();
  const dlg = page.locator('[data-testid=try-dialog]');
  await expect(dlg).toBeVisible();

  // Sélection d'un modèle (sondé sur le serveur) et de l'API OpenAI Chat Completions.
  await expect(page.locator('[data-testid=try-model] option')).toHaveCount(2);  // demo + autre
  await page.locator('[data-testid=try-model]').selectOption('demo:latest');
  await page.locator('[data-testid=try-api]').selectOption('openai-chat');

  // Envoie un message : le relais interroge le serveur rattaché (faux Ollama) et affiche la réponse.
  await page.locator('[data-testid=try-msg]').fill('Dis bonjour');
  await page.locator('[data-testid=try-send]').click();
  const log = page.locator('[data-testid=try-log]');
  await expect(log.locator('.chat-msg.user')).toContainText('Dis bonjour');
  await expect(log.locator('.chat-msg.bot')).toContainText('faux modèle');
  await expect(log.locator('.chat-msg.bot .chat-model')).toContainText('demo:latest');
  await expect(log.locator('.chat-msg.bot .chat-model')).toContainText('OpenAI Chat Completions');
  await page.screenshot({ path: `${OUT}/10-try-chat.jpg`, type: 'jpeg' });

  // La modale doit RÉELLEMENT se fermer (bouton Fermer + touche Échap) — régression corrigée.
  await page.locator('#try-close').click();
  await expect(dlg).toBeHidden();
  await page.locator('[data-testid=try-open]').click();
  await expect(dlg).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dlg).toBeHidden();
});

test('console de logs : journal + bannir une origine bloque le proxy (403 avant auth)', async ({ page, request }) => {
  const PROXY = 'http://127.0.0.1:8791';
  const DEMO = 'sk-ollama-devdemokey000000000000000000000000000000000000000000000000';
  // X-Forwarded-For de confiance (le pair 127.0.0.1 est un proxy de confiance en E2E) : le log
  // porte cette IP synthétique, dont le bannissement n'affecte PAS les requêtes du runner (127.0.0.1).
  const XFF = { 'X-Forwarded-For': '198.51.100.77' };

  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');

  // Génère une requête journalisée (200) depuis l'origine synthétique.
  const ok = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}`, ...XFF }, data: { model: 'demo:latest' },
  });
  expect(ok.status()).toBe(200);

  // Console de logs : la requête apparaît avec son origine.
  await page.getByRole('link', { name: 'Logs' }).click();
  await expect(page.locator('h1')).toContainText('Journal');
  const row = page.locator('[data-testid=log-row]', { hasText: '198.51.100.77' }).first();
  await expect(row).toBeVisible();
  await page.screenshot({ path: `${OUT}/11-logs.jpg`, type: 'jpeg', fullPage: true });

  // Bannir l'origine directement depuis la ligne → apparaît dans « Origines bannies ».
  await row.locator('[data-testid=log-ban]').click();
  await expect(page.locator('[data-testid=bans-table]')).toContainText('198.51.100.77');

  // Le proxy refuse désormais cette origine (403), AVANT l'auth de clé.
  const blocked = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}`, ...XFF }, data: { model: 'demo:latest' },
  });
  expect(blocked.status()).toBe(403);
  // Les autres origines (le runner, 127.0.0.1) restent servies.
  const still = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}` }, data: { model: 'demo:latest' },
  });
  expect(still.status()).toBe(200);

  // Débannir depuis la console (hygiène) → l'origine synthétique est réacceptée.
  await page.locator('[data-testid=bans-table] form[action^="/admin/bans/"] button').first().click();
  await expect(page.locator('[data-testid=bans-table]')).toHaveCount(0);
});

test('origines vues : liste + recherche + WHOIS (modale)', async ({ page, request }) => {
  const PROXY = 'http://127.0.0.1:8791';
  const DEMO = 'sk-ollama-devdemokey000000000000000000000000000000000000000000000000';
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');

  // Génère une requête pour peupler les origines de la clé de démo (depuis 127.0.0.1).
  const ok = await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}` }, data: { model: 'demo:latest' },
  });
  expect(ok.status()).toBe(200);

  await page.getByRole('link', { name: 'demo (dev)' }).click();
  const table = page.locator('[data-testid=origins-table]');
  await expect(table).toContainText('127.0.0.1');

  // Recherche : un terme qui ne correspond pas masque toutes les lignes.
  await page.locator('[data-testid=origin-search]').fill('203.0.199');
  await expect(page.locator('.origin-row:visible')).toHaveCount(0);
  await expect(page.locator('#origin-empty')).toBeVisible();
  await page.locator('[data-testid=origin-search]').fill('127');
  await expect(page.locator('.origin-row:visible').first()).toContainText('127.0.0.1');

  // WHOIS d'une origine loopback → modale, résumé « local » (aucun appel réseau).
  await page.locator('.origin-row', { hasText: '127.0.0.1' }).first()
    .locator('[data-testid=origin-whois]').click();
  const dlg = page.locator('[data-testid=whois-dialog]');
  await expect(dlg).toBeVisible();
  await expect(page.locator('[data-testid=whois-summary]')).toContainText('loopback');
  await page.screenshot({ path: `${OUT}/12-origins-whois.jpg`, type: 'jpeg' });
  await page.locator('#whois-close').click();
  await expect(dlg).toBeHidden();
});

test('contenu des requêtes : visionneuse ouvre le fichier + grep filtre', async ({ page, request }) => {
  const PROXY = 'http://127.0.0.1:8791';
  const DEMO = 'sk-ollama-devdemokey000000000000000000000000000000000000000000000000';
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');

  // Génère un contenu identifiable pour la clé de démo (écrit dans les fichiers reqlog).
  await request.post(`${PROXY}/api/chat`, {
    headers: { Authorization: `Bearer ${DEMO}` },
    data: { model: 'demo:latest', prompt: 'grep-me-please-xyz' },
  });
  await page.waitForTimeout(400);  // laisse la tâche de fond écrire le fichier

  // Console de logs → lien « Contenu des requêtes ».
  await page.goto('/admin/logs');
  await page.locator('[data-testid=content-link]').click();
  await expect(page.locator('h1')).toContainText('Contenu');

  // Sélection explicite de la clé de démo (dossier), puis lecture de son contenu.
  const demoVal = await page.locator('[data-testid=content-key] option', { hasText: 'demo (dev)' })
    .first().getAttribute('value');
  await page.goto('/admin/logs/content?key=' + demoVal);
  const results = page.locator('[data-testid=content-results]');
  await expect(results).toContainText('/api/chat');
  await expect(results).toContainText('grep-me-please-xyz');
  await expect(results).toContainText('«masqué»');       // secret masqué, jamais la clé
  await page.screenshot({ path: `${OUT}/25-logs-content.jpg`, type: 'jpeg', fullPage: true });

  // grep : terme présent → au moins une ligne ; terme absent → aucune.
  await page.locator('[data-testid=content-grep]').fill('grep-me-please-xyz');
  await page.locator('[data-testid=content-filter]').click();
  await expect(page.locator('[data-testid=content-line]').first()).toBeVisible();
  await page.locator('[data-testid=content-grep]').fill('zzz-absent-term');
  await page.locator('[data-testid=content-filter]').click();
  await expect(page.locator('[data-testid=content-line]')).toHaveCount(0);
});

test('plein viewport : le layout occupe toute la largeur, pas de colonne centrée', async ({ page }) => {
  // Règle dure : l'app remplit 100 % du viewport (largeur ET hauteur), login compris.
  await page.goto('/admin/login');
  const login = await page.evaluate(() => ({
    mainW: document.querySelector('main')!.getBoundingClientRect().width,
    clientW: document.documentElement.clientWidth,
    bodyH: document.body.getBoundingClientRect().height,
    clientH: document.documentElement.clientHeight,
  }));
  expect(login.mainW).toBe(login.clientW);
  expect(login.bodyH).toBeGreaterThanOrEqual(login.clientH);

  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await expect(page.locator('h1')).toContainText('Tableau de bord');
  const dash = await page.evaluate(() => ({
    mainW: document.querySelector('main')!.getBoundingClientRect().width,
    clientW: document.documentElement.clientWidth,
  }));
  expect(dash.mainW).toBe(dash.clientW);
});
