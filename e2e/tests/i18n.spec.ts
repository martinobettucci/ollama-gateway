import { test, expect } from '@playwright/test';
import fs from 'fs';

const OUT = 'output';
test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

// Le navigateur est en fr-FR (locale globale de la config) : la négociation Accept-Language
// rend le panel en français par défaut, puis on teste l'override par le sélecteur de langue.

async function login(page) {
  await page.goto('/admin/login');
  await page.fill('#password', 'adminpass');
  await page.click('button[type=submit]');
  await expect(page.locator('h1')).toContainText('Tableau de bord');
}

// Bascule de langue via le sélecteur du pied de page : ouvrir le disclosure (drapeau) puis
// cliquer l'option (drapeau + nom natif) → POST /admin/lang.
async function switchTo(page, code: string) {
  const dd = page.locator('[data-testid=lang-form]');               // le <details>
  if (!(await dd.evaluate((el: HTMLDetailsElement) => el.open))) {
    await page.locator('[data-testid=lang-select]').click();        // ouvre si replié
  }
  await page.locator(`.langsel-opt[data-lang="${code}"]`).click();  // soumet lang=code
  await expect(page.locator('html')).toHaveAttribute('lang', code);
}

test('i18n : le sélecteur bascule le panel dans la langue choisie et la mémorise', async ({ page }) => {
  await login(page);

  // Le sélecteur de langue vit dans le pied de page (bas à droite), replié sur le seul drapeau.
  const sel = page.locator('[data-testid=lang-select]');
  await expect(sel).toBeVisible();
  await expect(page.locator('[data-testid=app-footer] .langsel')).toBeVisible();
  // Ouvrir la liste : 24 langues (drapeau + nom natif), FR marquée comme courante par défaut.
  await sel.click();
  await expect(page.locator('.langsel-opt')).toHaveCount(24);
  await expect(page.locator('.langsel-opt[data-lang="fr"]')).toHaveClass(/current/);
  await page.screenshot({ path: `${OUT}/24-lang-menu.jpg`, type: 'jpeg', fullPage: true });

  // → Anglais : le tableau de bord et la navigation passent en anglais.
  await switchTo(page, 'en');
  await expect(page.locator('h1')).toContainText('Dashboard');
  await expect(page.locator('nav')).toContainText('Servers');
  await expect(page.locator('h1')).not.toContainText('Tableau de bord');
  await page.screenshot({ path: `${OUT}/19-lang-en.jpg`, type: 'jpeg', fullPage: true });

  // → Allemand.
  await switchTo(page, 'de');
  await expect(page.locator('h1')).toContainText('Dashboard');
  await expect(page.locator('nav')).toContainText('Server');
  await page.screenshot({ path: `${OUT}/20-lang-de.jpg`, type: 'jpeg', fullPage: true });

  // → Espagnol.
  await switchTo(page, 'es');
  await expect(page.locator('h1')).toContainText('Panel');
  await expect(page.locator('nav')).toContainText('Servidores');
  await page.screenshot({ path: `${OUT}/21-lang-es.jpg`, type: 'jpeg', fullPage: true });

  // La langue persiste (session) : une nouvelle navigation reste en espagnol.
  await page.goto('/admin/servers');
  await expect(page.locator('html')).toHaveAttribute('lang', 'es');
  await expect(page.locator('h1')).toContainText('Servidores de ejecución');

  // Retour au français : la charte reste identique, seul le texte change.
  await switchTo(page, 'fr');
  await expect(page.locator('h1')).toContainText("Serveurs d'exécution");
});

test('i18n : le détail de clé et la modale « Essayer » sont traduits', async ({ page }) => {
  await login(page);
  await switchTo(page, 'en');

  // Ouvre la clé de démo seedée (« demo (dev) »).
  await page.getByRole('link', { name: 'demo (dev)' }).first().click();
  await expect(page.getByRole('button', { name: 'Try now' })).toBeVisible();
  // Libellés de formulaire d'édition traduits.
  await expect(page.locator('[data-testid=edit-form]')).toContainText('Allowed models');
  await expect(page.locator('[data-testid=edit-form]')).toContainText('Log retention (days)');
  await page.screenshot({ path: `${OUT}/22-lang-key-detail-en.jpg`, type: 'jpeg', fullPage: true });

  // La modale « Essayer » ouvre et affiche ses libellés anglais + le hint JS ne fuit pas.
  await page.locator('[data-testid=try-open]').click();
  await expect(page.locator('[data-testid=try-dialog]')).toBeVisible();
  await expect(page.locator('#try-hint')).toContainText('Send a message');
  await page.screenshot({ path: `${OUT}/23-lang-try-en.jpg`, type: 'jpeg' });
});
