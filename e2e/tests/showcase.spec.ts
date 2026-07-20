import { test } from '@playwright/test';

// Tour guidé de l'application, ENREGISTRÉ EN VIDÉO (Playwright `video: 'on'`) pour le README.
// S'appuie sur le seed rétro-daté (global-setup) : les graphes montrent de vraies courbes.
// Les pauses rendent la vidéo regardable. La vidéo est récupérée depuis output/results/ après coup.
test('showcase: tour guidé de la passerelle', async ({ page }) => {
  const pause = (ms = 1200) => page.waitForTimeout(ms);

  // Connexion
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await pause(600);
  await page.click('button[type=submit]');
  await page.waitForURL('**/admin');
  await pause(1600);

  // Détail d'une clé : graphes (horizons, valeurs), usage par modèle
  await page.goto('/admin/keys/1');
  await page.getByTestId('key-permodel').waitFor();
  await page.getByTestId('key-reqs-chart').scrollIntoViewIfNeeded();
  await pause(1600);
  await page.getByTestId('horizon-2w').click();     // recadre l'horizon
  await pause(1300);
  await page.getByTestId('values-toggle').check();  // affiche les valeurs sur les points
  await pause(1600);

  // Serveurs d'exécution
  await page.getByRole('link', { name: 'Serveurs' }).click();
  await page.waitForURL('**/admin/servers');
  await pause(1400);

  // Monitoring d'un serveur
  await page.locator('[data-testid^=monitor-link-]').first().click();
  await page.waitForURL('**/monitor');
  await page.getByTestId('status-donut').scrollIntoViewIfNeeded();
  await pause(1800);

  // Console de logs
  await page.getByRole('link', { name: 'Logs' }).click();
  await page.waitForURL('**/admin/logs');
  await pause(1500);

  // Manuel en ligne intégré
  await page.getByTestId('manual-open').click();
  await page.getByTestId('manual-content').waitFor();
  await pause(2000);
});
