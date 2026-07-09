-- Allowlist SÉPARÉE de modèles d'IMAGE par clé (namespace `x/…`, ex. x/flux2-klein:4b).
-- Distincte de `key_models` (modèles texte) : une requête de génération d'image est gatée par
-- CETTE liste ; aucune ligne = tous les modèles d'image autorisés (si la capability image l'est).
-- La capability image elle-même (ollama-image / openai-image) est portée par `key_apis`.

CREATE TABLE IF NOT EXISTS key_image_models (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id  INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    model   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_key_image_models_key ON key_image_models(key_id);
