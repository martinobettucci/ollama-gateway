-- Palier de contexte « réellement nécessaire » pour servir la requête (cf. app/context.py::bucket) :
-- le PLUS PETIT palier de l'échelle qui contient le nombre de tokens de la requête
-- (27 734 tokens → 36k ; 2 096 tokens → 4k). Alimente la statistique « tailles de contexte
-- réellement utilisées » par clé et par serveur (camembert + compte + dernier usage), qui sert à
-- dimensionner le plafond de chaque clé au plus juste.
--
-- NULL = événement antérieur à cette migration, ou requête sans contexte mesurable (refus avant
-- lecture du corps : auth, origine, ban…). Ces lignes sont exclues des agrégats par palier.
ALTER TABLE usage_events ADD COLUMN ctx_bucket INTEGER;

CREATE INDEX IF NOT EXISTS idx_usage_ctx_bucket ON usage_events(ctx_bucket);
