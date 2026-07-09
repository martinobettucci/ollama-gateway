-- Rétention (en jours) du journal de CONTENU des requêtes, PAR CLÉ. Le contenu complet des
-- requêtes est stocké hors base (fichiers JSONL par heure, un dossier par clé) ; ce champ ne
-- pilote QUE la purge/compaction opérée par le cron `app.reqlog`. NULL = rétention globale par
-- défaut (`REQUEST_LOG_RETENTION_DAYS`). 0 = purge immédiate des heures passées.

ALTER TABLE api_keys ADD COLUMN log_retention_days INTEGER;
