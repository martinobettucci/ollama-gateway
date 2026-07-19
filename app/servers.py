"""Serveurs d'exécution (« executors ») : registre des upstreams Ollama (local + distants).

Chaque clé API est rattachée à exactement un serveur. Le serveur **par défaut** (local) est créé
automatiquement à partir de `$OLLAMA_UPSTREAM` et ne peut être ni supprimé ni laissé sans clés
orphelines (le reconciler `ensure_default` réassigne toute clé au serveur par défaut). Le jeton
d'auth d'un serveur distant est chiffré au repos (`crypto.py`) et **jamais réaffiché** en clair.
"""
import asyncio
import ipaddress
import json
import sqlite3
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from . import apis, config, crypto, db


def validate_base_url(url: str) -> None:
    """Lève `ValueError` si l'URL amont est inutilisable/dangereuse.

    Refuse : schéma non `http`/`https`, hôte absent, et hôtes en plage **link-local**
    (169.254.0.0/16, fe80::/10 — endpoints de métadonnées cloud). Les cibles **loopback/LAN
    privées** restent AUTORISÉES : un serveur d'exécution Ollama légitime est souvent local
    (127.0.0.1) ou sur le LAN (RFC 1918). Défense en profondeur contre une SSRF post-auth de
    l'admin (bouton « Essayer » / sonde) qui viserait les métadonnées de l'hébergeur.
    """
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError("schéma d'URL invalide (http/https requis)")
    host = parts.hostname or ""
    if not host:
        raise ValueError("hôte d'URL manquant")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and ip.is_link_local:
        raise ValueError("hôte en plage link-local interdite (métadonnées cloud)")


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
    last_compat: dict = field(default_factory=dict)   # {famille: [{path,status,served}]}
    last_compat_at: str | None = None


def _row_to_record(row: sqlite3.Row) -> ServerRecord:
    try:
        models = json.loads(row["last_models"] or "[]")
    except (ValueError, TypeError):
        models = []
    try:
        compat = json.loads(row["last_compat"] or "{}")
    except (ValueError, TypeError, IndexError):
        compat = {}
    return ServerRecord(
        id=row["id"], name=row["name"], base_url=row["base_url"],
        has_auth=bool(row["auth_token_enc"]), is_default=bool(row["is_default"]),
        enabled=bool(row["enabled"]), created_at=row["created_at"],
        last_checked_at=row["last_checked_at"], last_online=bool(row["last_online"]),
        last_models=[m for m in models if isinstance(m, str)] if isinstance(models, list) else [],
        last_compat=compat if isinstance(compat, dict) else {},
        last_compat_at=row["last_compat_at"] if "last_compat_at" in row.keys() else None,
    )


# --- Reconciler / défaut ----------------------------------------------------------------------

def ensure_default() -> int:
    """Garantit l'existence d'UN SEUL serveur par défaut (local, `$OLLAMA_UPSTREAM`) et réassigne
    toute clé orpheline (server_id NULL) à ce serveur.

    **Sérialisé par verrou fichier** (`db.file_lock`) : les rôles proxy/admin démarrent en
    parallèle sur le même SQLite ; sans verrou, un check-then-insert concurrent crée DEUX défauts.
    **Auto-réparateur** : collapse d'éventuels doublons de défaut hérités d'une course antérieure
    (les clés des doublons sont réaffectées au défaut conservé, puis les doublons supprimés).
    Idempotent ; appelé au démarrage de chaque rôle."""
    with db.file_lock("reconcile"):
        conn = db.connect()
        try:
            with conn:
                defaults = conn.execute(
                    "SELECT id FROM servers WHERE is_default = 1 ORDER BY id").fetchall()
                if defaults:
                    did = defaults[0]["id"]
                    for extra in defaults[1:]:  # collapse des doublons (course antérieure)
                        conn.execute("UPDATE api_keys SET server_id = ? WHERE server_id = ?",
                                     (did, extra["id"]))
                        conn.execute("DELETE FROM servers WHERE id = ?", (extra["id"],))
                else:
                    any_row = conn.execute(
                        "SELECT id FROM servers ORDER BY id LIMIT 1").fetchone()
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


# --- Test de compatibilité d'API (matrice stockée) --------------------------------------------

async def _probe_endpoint(client: httpx.AsyncClient, base: str, method: str, path: str,
                          headers: dict) -> dict:
    """Sonde UN endpoint : accessibilité du chemin uniquement (servi vs 404), sans valider le
    schéma. Corps `{}` pour les POST → l'amont répond 400 avant toute génération. `served` = le
    chemin est routé (tout sauf 404) ; 404 = absent ; erreur réseau = non concluant."""
    url = base.rstrip("/") + path
    try:
        if method == "GET":
            r = await client.get(url, headers=headers)
        else:
            r = await client.post(url, json={}, headers=headers)
    except httpx.HTTPError as exc:
        return {"path": path, "method": method, "status": None,
                "served": False, "error": exc.__class__.__name__}
    return {"path": path, "method": method, "status": r.status_code,
            "served": r.status_code != 404, "error": ""}


async def run_compat(server_id: int) -> dict:
    """Rejoue le catalogue d'endpoints (`apis.CATALOG`) contre un serveur enregistré et **persiste**
    la matrice de compatibilité (accessibilité des chemins par famille). Les endpoints d'une même
    famille sont sondés en parallèle. Renvoie la matrice {famille: [{path,method,status,served}]}."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT base_url, auth_token_enc, enabled FROM servers WHERE id = ?",
            (server_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    headers = {}
    if row["auth_token_enc"]:
        token = crypto.decrypt(row["auth_token_enc"])
        if token:
            headers["Authorization"] = f"Bearer {token}"
    base = row["base_url"]
    matrix: dict[str, list[dict]] = {}
    timeout = httpx.Timeout(config.SERVER_PROBE_TIMEOUT_S, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for family, endpoints in apis.CATALOG.items():
            results = await asyncio.gather(*[
                _probe_endpoint(client, base, method, path, headers)
                for method, path, _label in endpoints
            ])
            labels = {p: lbl for _m, p, lbl in endpoints}
            for res in results:
                res["label"] = labels.get(res["path"], "")
            matrix[family] = list(results)
    record_compat(server_id, matrix)
    return matrix


def record_compat(server_id: int, matrix: dict) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE servers SET last_compat = ?, last_compat_at = datetime('now') "
                "WHERE id = ?", (json.dumps(matrix), server_id))
    finally:
        conn.close()


# --- Chat de test (« Essayer maintenant » du panel) -------------------------------------------

# APIs proposées par le bouton « Essayer maintenant » : chemin amont, fabrique du corps, et
# extracteur de la réponse. Le serveur d'exécution (Ollama ou compatible) doit servir le chemin
# choisi ; sinon le relais renvoie l'erreur telle quelle (utile pour tester la config cliente).
def _body_ollama(model, msg):
    return {"model": model, "stream": False,
            "messages": [{"role": "user", "content": msg}]}


def _body_openai_chat(model, msg):
    return {"model": model, "stream": False,
            "messages": [{"role": "user", "content": msg}]}


def _body_openai_responses(model, msg):
    return {"model": model, "stream": False, "input": msg}


def _body_anthropic(model, msg):
    return {"model": model, "max_tokens": 1024,
            "messages": [{"role": "user", "content": msg}]}


def _reply_ollama(d):
    return (d.get("message") or {}).get("content", "") if isinstance(d, dict) else ""


def _reply_openai_chat(d):
    try:
        return d["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _reply_openai_responses(d):
    if not isinstance(d, dict):
        return ""
    if isinstance(d.get("output_text"), str) and d["output_text"]:
        return d["output_text"]
    try:  # forme structurée : output[].content[].text
        for item in d.get("output", []):
            for c in item.get("content", []):
                if c.get("text"):
                    return c["text"]
    except (AttributeError, TypeError):
        pass
    return ""


def _reply_anthropic(d):
    try:
        for c in d.get("content", []):
            if c.get("text"):
                return c["text"]
    except (AttributeError, TypeError):
        pass
    return ""


TRY_APIS = {
    "ollama": ("/api/chat", _body_ollama, _reply_ollama, "Ollama (chat)"),
    "openai-chat": ("/v1/chat/completions", _body_openai_chat, _reply_openai_chat,
                    "OpenAI Chat Completions"),
    "openai-responses": ("/v1/responses", _body_openai_responses, _reply_openai_responses,
                         "OpenAI Responses"),
    "anthropic": ("/v1/messages", _body_anthropic, _reply_anthropic, "Anthropic Messages"),
}


async def try_call(server_id: int, api: str, model: str, message: str) -> tuple[str, str]:
    """Envoie un unique message au serveur via l'API choisie, renvoie (réponse, erreur).

    Relais **LAN-only** derrière l'admin (jamais exposé publiquement) : sert au bouton
    « Essayer maintenant » pour vérifier qu'une clé/serveur/modèle/API répond réellement. Le
    jeton distant est déchiffré et injecté vers l'amont ; il n'apparaît jamais côté navigateur.
    """
    spec = TRY_APIS.get(api)
    if spec is None:
        return "", "API inconnue"
    path, make_body, extract, _label = spec
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
    url = row["base_url"].rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as c:
            r = await c.post(url, json=make_body(model, message), headers=headers)
        if r.status_code != 200:
            return "", f"HTTP {r.status_code}"
        reply = extract(r.json())
        return (reply, "") if reply else ("", "réponse vide du serveur")
    except (httpx.HTTPError, ValueError) as exc:
        return "", exc.__class__.__name__


# --- Génération d'image de test (onglet « Image » du « Essayer maintenant ») -------------------

def _imgbody_ollama(model, prompt, image_b64):
    # Ollama : génération via /api/generate ; image d'entrée optionnelle (image-to-image) en base64.
    b = {"model": model, "prompt": prompt, "stream": False}
    if image_b64:
        b["images"] = [image_b64]
    return b


def _imgbody_openai(model, prompt, image_b64):
    # OpenAI-compat : /v1/images/generations (pas d'image d'entrée sur cet endpoint).
    return {"model": model, "prompt": prompt, "n": 1}


def _img_reply_ollama(d):
    """Extrait la base64 PNG d'une réponse /api/generate d'un modèle d'image (`image` ou `images`)."""
    if not isinstance(d, dict):
        return ""
    if isinstance(d.get("image"), str) and d["image"]:
        return d["image"]
    imgs = d.get("images")
    if isinstance(imgs, list) and imgs and isinstance(imgs[0], str):
        return imgs[0]
    return ""


def _img_reply_openai(d):
    """Extrait la base64 d'une réponse /v1/images/generations (`data[0].b64_json`)."""
    try:
        item = d["data"][0]
        return item.get("b64_json") or ""
    except (KeyError, IndexError, TypeError):
        return ""


# api → (chemin, fabrique du corps, extracteur base64, libellé).
IMAGE_TRY_APIS = {
    "ollama-image": ("/api/generate", _imgbody_ollama, _img_reply_ollama, "Ollama image"),
    "openai-image": ("/v1/images/generations", _imgbody_openai, _img_reply_openai, "OpenAI image"),
}


async def try_image(server_id: int, api: str, model: str, prompt: str,
                    image_b64: str = "") -> tuple[str, str]:
    """Génère une image de test via l'API choisie ; renvoie (base64_png, erreur).

    `image_b64` (optionnel) = image d'entrée jointe (image-to-image, Ollama). Relais LAN-only,
    même sécurité que `try_call` (jeton distant déchiffré, jamais côté navigateur)."""
    spec = IMAGE_TRY_APIS.get(api)
    if spec is None:
        return "", "API image inconnue"
    path, make_body, extract, _label = spec
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
    url = row["base_url"].rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as c:
            r = await c.post(url, json=make_body(model, prompt, image_b64), headers=headers)
        if r.status_code != 200:
            return "", f"HTTP {r.status_code}"
        b64 = extract(r.json())
        return (b64, "") if b64 else ("", "aucune image renvoyée par le serveur")
    except (httpx.HTTPError, ValueError) as exc:
        return "", exc.__class__.__name__
