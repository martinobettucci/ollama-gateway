-- Schéma initial de la passerelle de clés Ollama (SQLite).
-- Event-log d'usage append-only + clés/origines/quotas + auth admin.

CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT    NOT NULL,
    key_prefix  TEXT    NOT NULL,               -- début lisible de la clé (affichage admin)
    key_hash    TEXT    NOT NULL UNIQUE,        -- sha-256 hex de la clé complète (jamais la clé en clair)
    enabled     INTEGER NOT NULL DEFAULT 1,
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT
);

-- Allowlist d'origine par clé : IP ou CIDR autorisés. Aucune ligne = aucune restriction d'origine.
CREATE TABLE IF NOT EXISTS key_origins (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id  INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    cidr    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_key_origins_key ON key_origins(key_id);

-- Plafonds optionnels par clé (NULL = illimité).
CREATE TABLE IF NOT EXISTS key_quotas (
    key_id            INTEGER PRIMARY KEY REFERENCES api_keys(id) ON DELETE CASCADE,
    monthly_token_cap INTEGER,   -- somme tokens (prompt+complétion) sur le mois calendaire
    rpm_limit         INTEGER    -- requêtes max sur une fenêtre glissante de 60 s
);

-- Journal d'usage append-only : une ligne par requête proxifiée (autorisée ou refusée).
CREATE TABLE IF NOT EXISTS usage_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id            INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    ts                TEXT    NOT NULL DEFAULT (datetime('now')),
    client_ip         TEXT    NOT NULL DEFAULT '',
    method            TEXT    NOT NULL DEFAULT '',
    path              TEXT    NOT NULL DEFAULT '',
    model             TEXT    NOT NULL DEFAULT '',
    status            INTEGER NOT NULL DEFAULT 0,
    duration_ms       INTEGER NOT NULL DEFAULT 0,
    tokens_prompt     INTEGER NOT NULL DEFAULT 0,
    tokens_completion INTEGER NOT NULL DEFAULT 0,
    bytes_in          INTEGER NOT NULL DEFAULT 0,
    bytes_out         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_key_ts ON usage_events(key_id, ts);
CREATE INDEX IF NOT EXISTS idx_usage_ts     ON usage_events(ts);

-- Authentification admin : une seule ligne (id=1), mot de passe haché (pbkdf2).
CREATE TABLE IF NOT EXISTS admin_auth (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    password_hash TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
