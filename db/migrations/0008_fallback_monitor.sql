-- Serveur de repli (fallback) par clé + attribution serveur des événements d'usage (monitoring).
--
-- 1) fallback_server_id : sur ERREUR SERVEUR de l'amont primaire (5xx ou erreur de connexion), le
--    proxy rejoue la requête de façon transparente vers ce serveur (NULL = pas de repli).
-- 2) usage_events.server_id : serveur ayant RÉELLEMENT traité la requête (repli inclus) — sert au
--    monitoring par serveur/clé. Pas de FK (le journal d'usage est append-only et doit survivre à
--    la suppression d'un serveur).

ALTER TABLE api_keys ADD COLUMN fallback_server_id INTEGER REFERENCES servers(id) ON DELETE SET NULL;
ALTER TABLE usage_events ADD COLUMN server_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_usage_server ON usage_events(server_id);
