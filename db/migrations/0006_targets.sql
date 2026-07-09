-- Cibles publiques (« ingress ») : URL publiques de la passerelle telles que vues par les CLIENTS
-- (ex. https://passerelle.example:port). Distinct des serveurs d'exécution (amont) : une cible
-- ne change PAS le routage du proxy — elle sert uniquement à générer les variables d'environnement
-- (OLLAMA_HOST / OPENAI_BASE_URL / ANTHROPIC_BASE_URL) de la clé rattachée.

CREATE TABLE IF NOT EXISTS targets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    base_url    TEXT    NOT NULL,                    -- URL publique, ex. https://llm.example:21434
    is_default  INTEGER NOT NULL DEFAULT 0,          -- cible par défaut (rattachement des clés sans cible)
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Rattachement clé → cible publique (au plus une ; NULL → cible par défaut via le reconciler).
ALTER TABLE api_keys ADD COLUMN target_id INTEGER REFERENCES targets(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_api_keys_target ON api_keys(target_id);
