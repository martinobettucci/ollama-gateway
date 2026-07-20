import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

// Amorce la base SQLite E2E (admin de démo + clé de démo déterministe) avant les tests.
// La base est SUPPRIMÉE puis re-seedée à chaque run (dev self-seeded, aucun résidu inter-runs).
export default async function globalSetup() {
  const ROOT = path.resolve(__dirname, '..');
  const PY = path.join(ROOT, '.venv', 'bin', 'python');
  const DB = path.join(__dirname, 'e2e-data', 'gateway.db');
  for (const f of [DB, `${DB}-wal`, `${DB}-shm`]) fs.rmSync(f, { force: true });
  // OLLAMA_UPSTREAM = faux Ollama (port 11533) : le serveur d'exécution par défaut créé au seed
  // pointe dessus (sinon il viserait 127.0.0.1:11434, un éventuel vrai Ollama de la machine dev).
  execSync(`${PY} -m app.bootstrap seed-dev`, {
    cwd: ROOT,
    env: { ...process.env, GATEWAY_DB_PATH: DB, ADMIN_PASSWORD: 'adminpass', APP_ENV: 'dev',
           OLLAMA_UPSTREAM: 'http://127.0.0.1:11533', P2E_MASTER_KEY: 'e2e-master' },
    stdio: 'inherit',
  });
  // Historique d'usage rétro-daté (15 j, 2 modèles) : les graphes des captures du manuel montrent
  // de vraies courbes (page clé + monitoring) plutôt que « Aucune donnée » sur données du jour.
  execSync(`${PY} ${path.join(__dirname, 'seed-usage.py')}`, {
    cwd: ROOT, env: { ...process.env, GATEWAY_DB_PATH: DB }, stdio: 'inherit',
  });
}
