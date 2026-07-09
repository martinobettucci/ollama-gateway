"""Cibles publiques (« ingress ») : URL publiques de la passerelle vues par les CLIENTS.

Une cible = l'URL que le client met dans `OLLAMA_HOST` / `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL`
(ex. `https://llm.example:21434`). **Distinct des serveurs d'exécution** (`servers.py`, l'amont
Ollama) : une cible **ne change pas le routage** du proxy — elle ne sert qu'à **générer les
variables d'environnement** de la clé rattachée. Chaque clé pointe vers au plus une cible ; la
**cible par défaut** (indélébile) est seedée depuis `config.PUBLIC_BASE_URL`.
"""
import sqlite3
from dataclasses import dataclass

from . import config, db

# Placeholder de base_url quand PUBLIC_BASE_URL n'est pas configurée (l'UI invite à le remplacer).
PLACEHOLDER_URL = "https://PASSERELLE-A-REMPLACER"


@dataclass
class TargetRecord:
    id: int
    name: str
    base_url: str
    is_default: bool
    created_at: str


def _row(r: sqlite3.Row) -> TargetRecord:
    return TargetRecord(id=r["id"], name=r["name"], base_url=r["base_url"],
                        is_default=bool(r["is_default"]), created_at=r["created_at"])


def ensure_default() -> int:
    """Garantit UNE cible par défaut (seedée depuis `PUBLIC_BASE_URL`) et réassigne toute clé
    orpheline (`target_id` NULL) à cette cible. Sérialisé par verrou fichier + auto-réparateur
    (collapse des doublons de défaut), à l'image de `servers.ensure_default`."""
    with db.file_lock("reconcile-targets"):
        conn = db.connect()
        try:
            with conn:
                defaults = conn.execute(
                    "SELECT id FROM targets WHERE is_default = 1 ORDER BY id").fetchall()
                if defaults:
                    did = defaults[0]["id"]
                    for extra in defaults[1:]:
                        conn.execute("UPDATE api_keys SET target_id = ? WHERE target_id = ?",
                                     (did, extra["id"]))
                        conn.execute("DELETE FROM targets WHERE id = ?", (extra["id"],))
                else:
                    any_row = conn.execute(
                        "SELECT id FROM targets ORDER BY id LIMIT 1").fetchone()
                    if any_row:
                        did = any_row["id"]
                        conn.execute("UPDATE targets SET is_default = 1 WHERE id = ?", (did,))
                    else:
                        cur = conn.execute(
                            "INSERT INTO targets(name, base_url, is_default) VALUES (?,?,1)",
                            ("Passerelle publique", config.PUBLIC_BASE_URL or PLACEHOLDER_URL))
                        did = cur.lastrowid
                conn.execute("UPDATE api_keys SET target_id = ? WHERE target_id IS NULL", (did,))
            return did
        finally:
            conn.close()


def default_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM targets WHERE is_default = 1").fetchone()
    return row["id"] if row else ensure_default()


def list_targets(conn: sqlite3.Connection | None = None) -> list[TargetRecord]:
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM targets ORDER BY is_default DESC, name COLLATE NOCASE, id").fetchall()
        return [_row(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_target(target_id: int, conn: sqlite3.Connection | None = None) -> TargetRecord | None:
    own = conn is None
    conn = conn or db.connect()
    try:
        r = conn.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()
        return _row(r) if r else None
    finally:
        if own:
            conn.close()


def keys_count(target_id: int, conn: sqlite3.Connection | None = None) -> int:
    own = conn is None
    conn = conn or db.connect()
    try:
        r = conn.execute(
            "SELECT COUNT(*) AS n FROM api_keys WHERE target_id = ?", (target_id,)).fetchone()
        return int(r["n"])
    finally:
        if own:
            conn.close()


def create_target(name: str, base_url: str) -> TargetRecord:
    conn = db.connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO targets(name, base_url) VALUES (?,?)",
                (name.strip() or "cible", base_url.strip().rstrip("/")))
            tid = cur.lastrowid
        return get_target(tid)
    finally:
        conn.close()


def update_target(target_id: int, name: str, base_url: str) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE targets SET name = ?, base_url = ? WHERE id = ?",
                         (name.strip() or "cible", base_url.strip().rstrip("/"), target_id))
    finally:
        conn.close()


def delete_target(target_id: int) -> str | None:
    """Supprime une cible. Renvoie un message d'erreur si refus (défaut, ou clés rattachées)."""
    conn = db.connect()
    try:
        t = get_target(target_id, conn)
        if t is None:
            return "cible introuvable"
        if t.is_default:
            return "cible par défaut : suppression interdite"
        n = keys_count(target_id, conn)
        if n:
            return f"{n} clé(s) rattachée(s) — réattribuez-les à une autre cible d'abord"
        with conn:
            conn.execute("DELETE FROM targets WHERE id = ?", (target_id,))
        return None
    finally:
        conn.close()
