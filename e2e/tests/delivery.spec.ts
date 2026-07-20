import { test, expect } from '@playwright/test';
import { execSync, spawn, ChildProcess } from 'child_process';
import fs from 'fs';
import path from 'path';

// Livraison déclarative (phase 2) : le secret d'une clé GÉNÉRÉE est poussé vers l'e-mail et le
// webhook configurés. E-mail → puits SMTP local (devfixtures/smtp_sink, aucun service externe) ;
// webhook → capteur du faux Ollama (/webhook). On prouve que le MÊME secret arrive sur les deux
// canaux, avec les variables d'environnement valorisées.

const ROOT = path.resolve(__dirname, '..', '..');
const PY = path.join(ROOT, '.venv', 'bin', 'python');
const DATA = path.join(__dirname, '..', 'e2e-data');
const DB = path.join(DATA, 'gateway.db');
const OUT = 'output';
const FAKE = 'http://127.0.0.1:11533';
const SINK_FILE = path.join(DATA, 'smtp-sink.jsonl');
const SINK_PORT = '12571';

function runPy(args: string, env: Record<string, string>) {
  execSync(`${PY} ${args}`, {
    cwd: ROOT, stdio: 'inherit',
    env: { ...process.env, P2E_MASTER_KEY: 'e2e-master', ...env },
  });
}

test.describe('livraison déclarative', () => {
  let sink: ChildProcess;

  test.beforeAll(async () => {
    fs.mkdirSync(OUT, { recursive: true });
    fs.rmSync(SINK_FILE, { force: true });
    sink = spawn(PY, ['-m', 'devfixtures.smtp_sink'], {
      cwd: ROOT, stdio: 'inherit',
      env: { ...process.env, SMTP_SINK_FILE: SINK_FILE, SMTP_SINK_PORT: SINK_PORT,
             SMTP_SINK_HOST: '127.0.0.1' },
    });
    await new Promise((r) => setTimeout(r, 900));  // laisser le socket se lier
  });

  test.afterAll(() => {
    sink?.kill();
    // Baseline restaurée pour les specs suivantes : retirer la clé gérée ET la cible créée.
    runPy(
      `-c "import os,sqlite3;c=sqlite3.connect(os.environ['GATEWAY_DB_PATH']);` +
      `c.execute('DELETE FROM api_keys WHERE external_ref IS NOT NULL');` +
      `c.execute(\\"DELETE FROM targets WHERE name='cible-livraison'\\");c.commit()"`,
      { GATEWAY_DB_PATH: DB });
  });

  test('secret d\'une clé générée livré par e-mail ET webhook (même secret, env valorisé)',
    async ({ page, request }) => {
      const yaml = `
smtp:
  host: 127.0.0.1
  port: ${SINK_PORT}
  tls: none
  from: gateway@local
targets:
  - name: cible-livraison
    base_url: https://gw.demo:8443
keys:
  - name: livree-e2e
    label: Clé livrée E2E
    target: cible-livraison
    deliver:
      - email: { to: ops@acme.example }
      - webhook: { url: ${FAKE}/webhook, preset: generic }
`;
      const ypath = path.join(DATA, 'reco-deliver.yaml');
      fs.writeFileSync(ypath, yaml);
      runPy(`-m app.reconcile apply ${ypath}`, { GATEWAY_DB_PATH: DB });

      // 1) E-mail capté par le puits SMTP.
      const lines = fs.readFileSync(SINK_FILE, 'utf-8').trim().split('\n');
      const mail = JSON.parse(lines[lines.length - 1]);
      expect(mail.rcpts.join()).toContain('ops@acme.example');
      expect(mail.subject).toContain('Clé livrée E2E');
      expect(mail.body).toContain('OLLAMA_API_KEY=sk-');
      expect(mail.body).toContain('OLLAMA_HOST=https://gw.demo:8443');
      const mailKey = (mail.body.match(/OLLAMA_API_KEY=(\S+)/) || [])[1];

      // 2) Webhook capté par le faux Ollama (preset generic → {label,key,url,env}).
      const last = await (await request.get(`${FAKE}/webhook/last`)).json();
      expect(last.headers['content-type']).toContain('application/json');
      const hook = JSON.parse(last.body);
      expect(hook.label).toBe('Clé livrée E2E');
      expect(hook.key).toMatch(/^sk-/);
      expect(hook.url).toBe('https://gw.demo:8443');
      expect(hook.env.OPENAI_BASE_URL).toBe('https://gw.demo:8443/v1');

      // 3) Le MÊME secret a été livré aux deux canaux.
      expect(hook.key).toBe(mailKey);

      // 4) Horodatage de livraison posé en base.
      const delivered = execSync(
        `${PY} -c "import os,sqlite3;c=sqlite3.connect(os.environ['GATEWAY_DB_PATH']);` +
        `print(c.execute(\\"select secret_delivered_at from api_keys where external_ref='livree-e2e'\\").fetchone()[0])"`,
        { cwd: ROOT, env: { ...process.env, GATEWAY_DB_PATH: DB } }).toString().trim();
      expect(delivered).not.toBe('None');

      // 5) Vision : rendu de ce que le client a reçu (e-mail + webhook).
      await page.setContent(`
        <html><body style="font-family:system-ui;background:#f7f8fa;color:#0D0D0D;padding:24px">
        <h1 style="color:#23468C">Livraison déclarative — clé « ${hook.label} »</h1>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
          <div style="background:#fff;border-radius:12px;padding:16px;border-top:4px solid #238C33">
            <h2>✉️ E-mail livré (ops@acme.example)</h2>
            <pre style="white-space:pre-wrap;font-size:13px">${mail.body
              .replace(/</g, '&lt;').slice(0, 900)}</pre>
          </div>
          <div style="background:#fff;border-radius:12px;padding:16px;border-top:4px solid #D9CF4A">
            <h2>🔗 Webhook livré (preset generic)</h2>
            <pre style="white-space:pre-wrap;font-size:13px">${JSON
              .stringify(hook, null, 2).replace(/</g, '&lt;')}</pre>
          </div>
        </div></body></html>`);
      await page.screenshot({ path: `${OUT}/29-delivery.jpg`, type: 'jpeg', fullPage: true });
    });
});
