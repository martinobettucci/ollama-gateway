-- Expiration / plafonds de VIE d'une clé (distinct du rate-limit et du plafond MENSUEL qui,
-- lui, se réinitialise). Une fois un plafond de vie atteint (ou la date/inactivité dépassée),
-- la clé est refusée par le proxy. Sert au cas « essai gratuit à coût plafonné ».
--   total_token_cap    : budget ABSOLU de tokens sur toute la vie de la clé (NULL = illimité)
--   total_request_cap  : nombre ABSOLU de requêtes autorisées sur la vie (NULL = illimité)
--   expires_at         : date/heure limite ISO 'YYYY-MM-DD HH:MM:SS' (NULL = jamais)
--   idle_expiry_days   : désactivation après N jours SANS usage (NULL = jamais)

ALTER TABLE api_keys ADD COLUMN total_token_cap   INTEGER;
ALTER TABLE api_keys ADD COLUMN total_request_cap INTEGER;
ALTER TABLE api_keys ADD COLUMN expires_at        TEXT;
ALTER TABLE api_keys ADD COLUMN idle_expiry_days  INTEGER;
