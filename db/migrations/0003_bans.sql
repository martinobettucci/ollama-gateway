-- Liste de bannissement GLOBALE d'origines (IP/CIDR), appliquée par le proxy AVANT toute
-- authentification de clé. Distincte des allowlists d'origine par clé (key_origins) : ici c'est
-- un DENY global, opéré depuis la console de logs de l'admin. Le journal d'usage complet
-- (usage_events, append-only) est déjà conservé par la migration initiale — rien à ajouter côté log.

CREATE TABLE IF NOT EXISTS banned_origins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cidr       TEXT    NOT NULL UNIQUE,           -- IP normalisée (/32,/128) ou CIDR banni
    reason     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
