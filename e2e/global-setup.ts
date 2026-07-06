import { execSync } from 'child_process';
import path from 'path';

// Amorce la base SQLite E2E (admin de démo + clé de démo déterministe) avant les tests.
export default async function globalSetup() {
  const ROOT = path.resolve(__dirname, '..');
  const PY = path.join(ROOT, '.venv', 'bin', 'python');
  const DB = path.join(__dirname, 'e2e-data', 'gateway.db');
  execSync(`${PY} -m app.bootstrap seed-dev`, {
    cwd: ROOT,
    env: { ...process.env, GATEWAY_DB_PATH: DB, ADMIN_PASSWORD: 'adminpass', APP_ENV: 'dev' },
    stdio: 'inherit',
  });
}
