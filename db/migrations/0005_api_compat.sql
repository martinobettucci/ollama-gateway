-- Compatibilité d'API : matrice de compatibilité par serveur + allowlist d'API par clé.
--
-- 1) Matrice stockée par serveur (comme `last_models`) : résultat JSON du dernier test de
--    compatibilité (accessibilité des chemins par famille d'API), affiché dans le panel.
-- 2) Allowlist d'API par clé (comme `key_models`) : aucune ligne = toutes les familles autorisées.
--    Le proxy applique un allow/forbid de CHEMIN (aucune validation de schéma).

ALTER TABLE servers ADD COLUMN last_compat TEXT NOT NULL DEFAULT '{}';   -- JSON : {famille:[{path,status,served}]}
ALTER TABLE servers ADD COLUMN last_compat_at TEXT;                      -- horodatage du dernier test de compat

CREATE TABLE IF NOT EXISTS key_apis (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id  INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    api     TEXT    NOT NULL                          -- 'ollama' | 'openai' | 'anthropic'
);
CREATE INDEX IF NOT EXISTS idx_key_apis_key ON key_apis(key_id);
