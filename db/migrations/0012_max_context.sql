-- Limite de CONTEXTE par clé (cf. app/context.py) : plafond de tokens accepté pour une requête.
-- Le proxy compte les tokens du corps (tiktoken + marge de 15 %) et REFUSE (413) au-delà, AVANT
-- d'atteindre l'amont ; il injecte aussi `options.num_ctx` (Ollama natif) pour que le serveur
-- d'exécution n'alloue pas un contexte plus grand.
--
-- Valeur OBLIGATOIRE (jamais NULL/vide) : multiple de 4096, entre 4096 (4k) et 1048576 (1M).
-- Défaut 114688 = 112k — appliqué aussi aux clés existantes par ce DEFAULT.
ALTER TABLE api_keys ADD COLUMN max_context_tokens INTEGER NOT NULL DEFAULT 114688;

-- Filet de sécurité : normalise d'éventuelles valeurs héritées hors bornes/non alignées.
UPDATE api_keys SET max_context_tokens = 114688
 WHERE max_context_tokens IS NULL
    OR max_context_tokens < 4096
    OR max_context_tokens > 1048576
    OR max_context_tokens % 4096 <> 0;
