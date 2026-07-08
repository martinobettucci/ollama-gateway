"""Serveurs d'exécution (« executors ») : registre des upstreams Ollama (local + distants).

Chaque clé API est rattachée à exactement un serveur. Le serveur **par défaut** (local) est créé
automatiquement à partir de `$OLLAMA_UPSTREAM` et ne peut être ni supprimé ni laissé sans clés
orphelines (le reconciler `ensure_default` réassigne toute clé au serveur par défaut). Le jeton
d'auth d'un serveur distant est chiffré au repos (`crypto.py`) et **jamais réaffiché** en clair.
"""
import json
import sqlite3
from dataclasses import dataclass

import httpx

from . import config, crypto, db


@dataclass
class ServerRecord:
    id: int
    name: str
    base_url: str
    has_auth: bool
    is_default: bool
    enabled: bool
    created_at: str
    last_checked_at: str | None
    last_online: bool
    last_models: list[str]


def _row_to_record(row: sqlite3.Row) -> ServerRecord:
    try:
        models = json.loads(row["last_models"] or "[]")
    except (ValueError, TypeError):
        models = []
    return ServerRecord(
        id=row["id"], name=row["name"], base_url=row["base_url"],
        has_auth=bool(row["auth_token_enc"]), is_default=bool(row["is_default"]),
        enabled=bool(row["enabled"]), created_at=row["created_at"],
        last_checked_at=row["last_checked_at"], last_online=bool(row["last_online"]),
        last_models=[m for m in models if isinstance(m, str)] if isinstance(models, list) else [],
    )


# --- Reconciler / défaut ----------------------------------------------------------------------

def ensure_default() -> int:
    """Garantit l'existence d'UN serveur par défaut (local, `$OLLAMA_UPSTREAM`) et réassigne toute
    clé orpheline (server_id NULL) à ce serveur. Idempotent ; appelé au démarrage de chaque rôle."""
    conn = db.connect()
    try:
        with conn:
            row = conn.execute("SELECT id FROM servers WHERE is_default = 1").fetchone()
            if row:
                did = row["id"]
            else:
                any_row = conn.execute("SELECT id FROM servers ORDER BY id LIMIT 1").fetchone()
                if any_row:  # legacy : promeut le premier serveur en défaut
                    did = any_row["id"]
                    conn.execute("UPDATE servers SET is_default = 1 WHERE id = ?", (did,))
                else:
                    cur = conn.execute(
                        "INSERT INTO servers(name, base_url, is_default, enabled) "
                        "VALUES ('Ollama local', ?, 1, 1)", (config.OLLAMA_UPSTREAM,))
                    did = cur.lastrowid
            conn.execute("UPDATE api_keys SET server_id = ? WHERE server_id IS NULL", (did,))
        return did
    finally:
        conn.close()


def default_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM servers WHERE is_default = 1").fetchone()
    return row["id"] if row else ensure_default()


# --- Lecture ----------------------------------------------------------------------------------

def list_servers(conn: sqlite3.Connection | None = None) -> list[ServerRecord]:
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM servers ORDER BY is_default DESC, name COLLATE NOCASE, id"
        ).fetchall()
        return [_row_to_record(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_server(server_id: int, conn: sqlite3.Connection | None = None) -> ServerRecord | None:
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
        return _row_to_record(row) if row else None
    finally:
        if own:
            conn.close()


def keys_count(server_id: int, conn: sqlite3.Connection | None = None) -> int:
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM api_keys WHERE server_id = ?", (server_id,)).fetchone()
        return int(row["n"])
    finally:
        if own:
            conn.close()


def auth_header_for(server_id: int, conn: sqlite3.Connection) -> dict:
    """En-tête `Authorization` à envoyer à l'amont (jeton distant déchiffré), {} si aucun."""
    row = conn.execute("SELECT auth_token_enc FROM servers WHERE id = ?", (server_id,)).fetchone()
    if row and row["auth_token_enc"]:
        token = crypto.decrypt(row["auth_token_enc"])
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {}


# --- Écriture ---------------------------------------------------------------------------------

def create_server(name: str, base_url: str, auth_token: str = "",
                  enabled: bool = True) -> ServerRecord:
    conn = db.connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO servers(name, base_url, auth_token_enc, enabled) VALUES (?,?,?,?)",
                (name.strip() or "serveur", base_url.strip().rstrip("/"),
                 crypto.encrypt(auth_token.strip()), 1 if enabled else 0),
            )
            sid = cur.lastrowid
        return get_server(sid)
    finally:
        conn.close()


def update_server(server_id: int, name: str, base_url: str, enabled: bool,
                  auth_token: str | None = None, clear_auth: bool = False) -> None:
    """Met à jour un serveur. `auth_token` non vide → remplace le jeton ; `clear_auth` → l'efface ;
    sinon le jeton existant est conservé (le champ vide du formulaire ne l'écrase pas)."""
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE servers SET name = ?, base_url = ?, enabled = ? WHERE id = ?",
                (name.strip() or "serveur", base_url.strip().rstrip("/"),
                 1 if enabled else 0, server_id),
            )
            if clear_auth:
                conn.execute("UPDATE servers SET auth_token_enc = '' WHERE id = ?", (server_id,))
            elif auth_token is not None and auth_token.strip():
                conn.execute("UPDATE servers SET auth_token_enc = ? WHERE id = ?",
                             (crypto.encrypt(auth_token.strip()), server_id))
    finally:
        conn.close()


def set_enabled(server_id: int, enabled: bool) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE servers SET enabled = ? WHERE id = ?",
                         (1 if enabled else 0, server_id))
    finally:
        conn.close()


def delete_server(server_id: int) -> str | None:
    """Supprime un serveur. Renvoie un message d'erreur (str) si refus, None si succès.

    Interdit : serveur par défaut, ou serveur avec des clés rattachées (à réattribuer d'abord).
    """
    conn = db.connect()
    try:
        srv = get_server(server_id, conn)
        if srv is None:
            return "serveur introuvable"
        if srv.is_default:
            return "serveur par défaut : suppression interdite"
        n = keys_count(server_id, conn)
        if n:
            return f"{n} clé(s) rattachée(s) — réattribuez-les à un autre serveur d'abord"
        with conn:
            conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        return None
    finally:
        conn.close()


# --- Test de disponibilité --------------------------------------------------------------------

async def probe(base_url: str, auth_token_enc: str = "") -> tuple[bool, list[str], str]:
    """Sonde `GET {base_url}/api/tags`. Renvoie (en_ligne, modèles, message_d_erreur)."""
    headers = {}
    if auth_token_enc:
        token = crypto.decrypt(auth_token_enc)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    url = base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=config.SERVER_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, headers=headers)
        if r.status_code != 200:
            return False, [], f"HTTP {r.status_code}"
        data = r.json()
        raw = data.get("models", []) if isinstance(data, dict) else []
        models = [m.get("name") or m.get("model") for m in raw if isinstance(m, dict)]
        return True, [m for m in models if m], ""
    except (httpx.HTTPError, ValueError) as exc:
        return False, [], exc.__class__.__name__


def record_probe(server_id: int, online: bool, models: list[str]) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE servers SET last_checked_at = datetime('now'), last_online = ?, "
                "last_models = ? WHERE id = ?",
                (1 if online else 0, json.dumps(models), server_id),
            )
    finally:
        conn.close()


async def test_server(server_id: int) -> tuple[bool, list[str], str]:
    """Sonde un serveur enregistré (jeton chiffré lu en base) et persiste le résultat."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT base_url, auth_token_enc FROM servers WHERE id = ?", (server_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return False, [], "serveur introuvable"
    online, models, err = await probe(row["base_url"], row["auth_token_enc"])
    record_probe(server_id, online, models)
    return online, models, err


# --- Chat de test (« Essayer maintenant » du panel) -------------------------------------------

async def chat_once(server_id: int, model: str, message: str) -> tuple[str, str]:
    """Envoie un unique message de chat (non-streamé) au serveur et renvoie (réponse, erreur).

    Relais **LAN-only** derrière l'admin (jamais exposé publiquement) : sert au bouton
    « Essayer maintenant » pour vérifier qu'une clé/serveur/modèle répond réellement. Le jeton
    distant est déchiffré et injecté vers l'amont ; il n'apparaît jamais côté navigateur.
    """
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT base_url, auth_token_enc, enabled FROM servers WHERE id = ?",
            (server_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return "", "serveur introuvable"
    if not row["enabled"]:
        return "", "serveur désactivé"
    headers = {}
    if row["auth_token_enc"]:
        token = crypto.decrypt(row["auth_token_enc"])
        if token:
            headers["Authorization"] = f"Bearer {token}"
    url = row["base_url"].rstrip("/") + "/api/chat"
    payload = {"model": model, "stream": False,
               "messages": [{"role": "user", "content": message}]}
    try:
        async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as c:
            r = await c.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            return "", f"HTTP {r.status_code}"
        data = r.json()
        reply = (data.get("message") or {}).get("content", "") if isinstance(data, dict) else ""
        return (reply, "") if reply else ("", "réponse vide du serveur")
    except (httpx.HTTPError, ValueError) as exc:
        return "", exc.__class__.__name__
