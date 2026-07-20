import { test, expect } from '@playwright/test';

const OUT = 'output';
const PROXY = 'http://127.0.0.1:8791';
const DEMO = 'sk-ollama-devdemokey000000000000000000000000000000000000000000000000';

// Feature « graphes clé » : sélecteur d'horizon, case « afficher les valeurs » (UI, non persistée)
// et table d'usage PAR MODÈLE sur la page de la clé.
test('clé : horizons + case valeurs + usage par modèle', async ({ page, request }) => {
  // Générer de l'usage pour la clé démo sur 2 modèles (alimente la table par modèle).
  for (const model of ['demo:latest', 'autre:latest']) {
    await request.post(`${PROXY}/api/chat`, {
      headers: { Authorization: `Bearer ${DEMO}` },
      data: { model, stream: true },
    });
  }
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await page.goto('/admin/keys/1');   // clé démo (seedée en premier)

  // Sélecteur d'horizon : les 5 pilules.
  for (const h of ['24h', '1w', '2w', '1m', '3m']) {
    await expect(page.getByTestId(`horizon-${h}`)).toBeVisible();
  }
  // Graphes en courbe (SVG) présents (requêtes + tokens).
  await expect(page.getByTestId('key-reqs-chart').locator('svg')).toBeVisible();
  await expect(page.getByTestId('key-tokens-chart').locator('svg')).toBeVisible();
  // Table « usage par modèle » avec les 2 modèles.
  const perModel = page.getByTestId('key-permodel');
  await expect(perModel).toBeVisible();
  await expect(perModel).toContainText('demo:latest');
  await expect(perModel).toContainText('autre:latest');

  // Capture (manuel + vision) : état par défaut — valeurs masquées, horizon 1 mois, vraies courbes
  // (grâce au seed rétro-daté) + table par modèle.
  await page.screenshot({ path: `${OUT}/27-key-charts.jpg`, type: 'jpeg', fullPage: true });

  // Case « afficher les valeurs » : décochée par défaut → coche révèle .show-values (non persistée).
  const cb = page.getByTestId('values-toggle');
  await expect(cb).not.toBeChecked();
  await cb.check();
  await expect(page.locator('body')).toHaveClass(/show-values/);

  // Changer d'horizon recharge la page avec ?horizon=.
  await page.getByTestId('horizon-24h').click();
  await expect(page).toHaveURL(/horizon=24h/);
});
