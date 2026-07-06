import { defineConfig } from '@playwright/test';
import path from 'path';

const ROOT = path.resolve(__dirname, '..');
const PY = path.join(ROOT, '.venv', 'bin', 'python');
const DB = path.join(__dirname, 'e2e-data', 'gateway.db');

// Env partagé par les 3 serveurs uvicorn (proxy, admin, faux Ollama) — même fichier SQLite.
const baseEnv = { ...process.env, GATEWAY_DB_PATH: DB, PYTHONUNBUFFERED: '1' } as Record<string, string>;

export default defineConfig({
  testDir: './tests',
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,                       // état partagé (activer/désactiver la clé démo) → série
  outputDir: './output/results',
  reporter: [['list']],
  globalSetup: './global-setup.ts',
  use: {
    baseURL: 'http://127.0.0.1:8792',
    screenshot: 'only-on-failure',
    video: 'on',                    // .webm pour l'observation en vision
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `${PY} -m uvicorn devfixtures.fake_ollama:app --host 127.0.0.1 --port 11533`,
      cwd: ROOT, url: 'http://127.0.0.1:11533/', env: baseEnv, reuseExistingServer: false,
    },
    {
      command: `${PY} -m uvicorn app.proxy:app --host 127.0.0.1 --port 8791`,
      cwd: ROOT, url: 'http://127.0.0.1:8791/_proxy_health', reuseExistingServer: false,
      env: { ...baseEnv, OLLAMA_UPSTREAM: 'http://127.0.0.1:11533', TRUSTED_PROXY_IPS: '127.0.0.1,::1' },
    },
    {
      command: `${PY} -m uvicorn app.admin:app --host 127.0.0.1 --port 8792`,
      cwd: ROOT, url: 'http://127.0.0.1:8792/admin/login', reuseExistingServer: false,
      env: { ...baseEnv, ADMIN_SESSION_SECRET: 'e2e-secret' },
    },
  ],
});
