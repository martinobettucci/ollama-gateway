-- Livraison du secret d'une clé GÉNÉRÉE en mode déclaratif (webhook/e-mail, cf. app/deliver.py).
-- Le secret n'existe en clair qu'à la création : il est livré DANS le même passage de
-- réconciliation, puis cet horodatage est posé. Sur les passages suivants, la clé existe déjà
-- (pas de nouveau secret) → aucune relivraison. NULL = jamais livré (clé importée, ou sans canal).
ALTER TABLE api_keys ADD COLUMN secret_delivered_at TEXT;
