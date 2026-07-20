import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

// Réconciliation déclarative (mode headless) : app/reconcile.py. On exerce deux plans :
//  1) CLI sur une base NEUVE et ISOLÉE → couverture complète (serveurs/cibles/clés, prune) sans
//     polluer la base E2E partagée (les captures du manuel s'en trouveraient faussées).
//  2) Base E2E partagée → preuve de bout en bout : une clé importée est acceptée par le proxy et
//     visible au dashboard (vision), puis désactivée quand on la retire du YAML. Nettoyée après.

const ROOT = path.resolve(__dirname, '..', '..');
const PY = path.join(ROOT, '.venv', 'bin', 'python');
const DATA = path.join(__dirname, '..', 'e2e-data');
const DB = path.join(DATA, 'gateway.db');
const OUT = 'output';
const PROXY = 'http://127.0.0.1:8791';
const IMPORTED = 'sk-ollama-recoimportedkey0000000000000000000000000000000000000000';

test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

function runPy(args: string, env: Record<string, string>) {
  execSync(`${PY} ${args}`, {
    cwd: ROOT, stdio: 'inherit',
    env: { ...process.env, P2E_MASTER_KEY: 'e2e-master', ...env },
  });
}

function writeYaml(name: string, text: string): string {
  const p = path.join(DATA, name);
  fs.writeFileSync(p, text);
  return p;
}

test('reconcile CLI: serveurs/cibles/clés créés dans une base neuve + idempotence + prune', () => {
  const TDB = path.join(DATA, 'reco-fresh.db');
  for (const f of [TDB, `${TDB}-wal`, `${TDB}-shm`]) fs.rmSync(f, { force: true });
  const yaml = `
servers:
  - name: reco-local
    base_url: http://127.0.0.1:11533
    default: true
    models: [demo:latest, autre:latest]
targets:
  - name: reco-public
    base_url: https://passerelle.exemple:8443
    default: true
keys:
  - name: reco-import
    value: \${RECO_KEY}
    label: Import déclaratif
    server: reco-local
    target: reco-public
    rpm_limit: 33
  - name: reco-jetable
    server: reco-local
`;
  const ypath = writeYaml('reco-fresh.yaml', yaml);
  // GATEWAY_CONFIG posé → mode déclaratif : bootstrap init n'auto-crée aucun serveur « Ollama local ».
  const env = { GATEWAY_DB_PATH: TDB, GATEWAY_CONFIG: ypath, APP_ENV: 'dev', RECO_KEY: IMPORTED };
  runPy('-m app.bootstrap init', env);
  runPy(`-m app.reconcile apply ${ypath}`, env);

  const snapshot = () => JSON.parse(execSync(
    `${PY} -c "import os,sqlite3,json;c=sqlite3.connect(os.environ['GATEWAY_DB_PATH']);` +
    `c.row_factory=sqlite3.Row;` +
    `print(json.dumps({` +
    `'servers':[r['name'] for r in c.execute('select name from servers order by name')],` +
    `'default_server':[r['name'] for r in c.execute('select name from servers where is_default=1')],` +
    `'targets':[r['name'] for r in c.execute('select name from targets order by name')],` +
    `'keys':{r['external_ref']:r['enabled'] for r in c.execute('select external_ref,enabled from api_keys')}` +
    `}))"`,
    { cwd: ROOT, env: { ...process.env, GATEWAY_DB_PATH: TDB } }).toString());

  let st = snapshot();
  expect(st.servers).toEqual(['reco-local']);          // aucun « Ollama local » parasite (déclaratif)
  expect(st.default_server).toEqual(['reco-local']);
  expect(st.targets).toEqual(['reco-public']);
  expect(st.keys).toEqual({ 'reco-import': 1, 'reco-jetable': 1 });

  // Idempotence : 2e passage à l'identique → aucun doublon.
  runPy(`-m app.reconcile apply ${ypath}`, env);
  st = snapshot();
  expect(st.servers).toEqual(['reco-local']);
  expect(Object.keys(st.keys).sort()).toEqual(['reco-import', 'reco-jetable']);

  // Retrait de reco-jetable SANS prune → clé désactivée (toujours en base).
  const y2 = writeYaml('reco-fresh-2.yaml', yaml.replace(/\n  - name: reco-jetable\n    server: reco-local\n/, '\n'));
  runPy(`-m app.reconcile apply ${y2}`, { ...env, GATEWAY_CONFIG: y2 });
  st = snapshot();
  expect(st.keys['reco-jetable']).toBe(0);             // désactivée, pas supprimée

  // prune: true → suppression définitive.
  const y3 = writeYaml('reco-fresh-3.yaml', 'prune: true\n' + yaml.replace(/\n  - name: reco-jetable\n    server: reco-local\n/, '\n'));
  runPy(`-m app.reconcile apply ${y3}`, { ...env, GATEWAY_CONFIG: y3 });
  st = snapshot();
  expect(st.keys['reco-jetable']).toBeUndefined();     // partie
  expect(st.keys['reco-import']).toBe(1);              // conservée
});

test.describe('base E2E partagée', () => {
  test.afterAll(() => {
    // Nettoyage : retirer toute trace de clé gérée (external_ref) → baseline seedée restaurée
    // pour les specs suivantes (servers/showcase) qui produisent les captures du manuel.
    runPy(
      `-c "import os,sqlite3;c=sqlite3.connect(os.environ['GATEWAY_DB_PATH']);` +
      `c.execute('DELETE FROM api_keys WHERE external_ref IS NOT NULL');c.commit()"`,
      { GATEWAY_DB_PATH: DB });
  });

  test('reconcile: clé importée acceptée par le proxy, visible au dashboard, désactivée au retrait',
    async ({ page, request }) => {
      // Clé importée sur le serveur PAR DÉFAUT (aucun serveur/cible créé → pas de pollution).
      const yImport = writeYaml('reco-shared.yaml', `
keys:
  - name: reco-e2e
    value: \${RECO_KEY}
    label: Clé déclarative E2E
    rpm_limit: 42
`);
      runPy(`-m app.reconcile apply ${yImport}`, { GATEWAY_DB_PATH: DB, RECO_KEY: IMPORTED });

      const ok = await request.post(`${PROXY}/api/chat`, {
        headers: { Authorization: `Bearer ${IMPORTED}` }, data: { model: 'demo:latest' },
      });
      expect(ok.status()).toBe(200);
      // L'état du quota est exposé (rpm_limit: 42 → limite 42).
      expect(ok.headers()['x-ratelimit-limit-requests']).toBe('42');

      await page.goto('/admin/login');
      await page.fill('#password', 'adminpass');
      await page.click('button[type=submit]');
      const row = page.locator('[data-testid=key-row]', { hasText: 'Clé déclarative E2E' });
      await expect(row).toBeVisible();
      await page.screenshot({ path: `${OUT}/28-reconcile.jpg`, type: 'jpeg', fullPage: true });

      // Retrait du YAML (prune par défaut = désactivation) → le proxy refuse.
      const yEmpty = writeYaml('reco-shared-empty.yaml', 'keys: []\n');
      runPy(`-m app.reconcile apply ${yEmpty}`, { GATEWAY_DB_PATH: DB });
      const off = await request.post(`${PROXY}/api/chat`, {
        headers: { Authorization: `Bearer ${IMPORTED}` }, data: { model: 'demo:latest' },
      });
      expect(off.status()).toBe(401);
    });
});
