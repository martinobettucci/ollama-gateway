-- Serveurs d'exécution (« executors ») : registre des upstreams Ollama (local + distants).
-- Une clé API est rattachée à exactement un serveur ; restriction optionnelle des modèles par clé.

CREATE TABLE IF NOT EXISTS servers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    base_url        TEXT    NOT NULL,                 -- ex. http://192.168.0.42:11434
    auth_token_enc  TEXT    NOT NULL DEFAULT '',      -- jeton Bearer distant CHIFFRÉ (Fernet) ; '' = aucun
    is_default      INTEGER NOT NULL DEFAULT 0,       -- serveur local par défaut (indélébile)
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    last_checked_at TEXT,                             -- dernier test de disponibilité
    last_online     INTEGER NOT NULL DEFAULT 0,       -- résultat 0/1 du dernier test
    last_models     TEXT    NOT NULL DEFAULT '[]'     -- JSON : modèles détectés au dernier test
);

-- Rattachement clé → serveur (exactement un). NULL transitoire (legacy/serveur supprimé) : le
-- reconciler (servers.ensure_default) réassigne toute clé orpheline au serveur par défaut.
ALTER TABLE api_keys ADD COLUMN server_id INTEGER REFERENCES servers(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_api_keys_server ON api_keys(server_id);

-- Allowlist de modèles par clé (sur son serveur). Aucune ligne = tous les modèles autorisés.
CREATE TABLE IF NOT EXISTS key_models (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id  INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    model   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_key_models_key ON key_models(key_id);
