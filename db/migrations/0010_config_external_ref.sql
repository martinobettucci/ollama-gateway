-- Configuration DÉCLARATIVE (mode headless / YAML, cf. app/reconcile.py).
-- `external_ref` = identifiant STABLE d'une clé gérée par le fichier de configuration : il fait le
-- lien YAML ⇄ base pour que la réconciliation sache « cette clé existe déjà, ne pas la recréer ».
-- NULL = clé gérée par l'UI (jamais touchée par la réconciliation ni son élagage/prune).
ALTER TABLE api_keys ADD COLUMN external_ref TEXT;

-- Unicité de l'external_ref PARMI les clés gérées (NULL non contraint : les clés UI restent libres).
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_external_ref
    ON api_keys(external_ref) WHERE external_ref IS NOT NULL;
