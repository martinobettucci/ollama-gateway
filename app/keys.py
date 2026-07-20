"""CRUD des clés API + validation (lookup par hash, état, allowlist d'origine) + auth admin.

Toutes les fonctions ouvrent une connexion courte si aucune n'est fournie. L'origine est
comparée en IP/CIDR via le module `ipaddress` (IPv4 et IPv6).
"""
import ipaddress
import sqlite3
from dataclasses import dataclass, field

from . import apis, auth, db, servers, targets


@dataclass
class KeyRecord:
    id: int
    label: str
    key_prefix: str
    enabled: bool
    note: str
    created_at: str
    last_used_at: str | None
    origins: list[str]
    monthly_token_cap: int | None
    rpm_limit: int | None
    server_id: int | None = None
    server_name: str | None = None
    fallback_server_id: int | None = None
    fallback_server_name: str | None = None
    target_id: int | None = None
    target_name: str | None = None
    target_base_url: str | None = None
    models: list[str] = field(default_factory=list)
    image_models: list[str] = field(default_factory=list)  # allowlist modèles image x/ (vide=tous)
    apis: list[str] = field(default_factory=list)  # allowlist de familles d'API (vide = toutes)
    log_retention_days: int | None = None  # NULL → rétention globale par défaut
    # Plafonds/expiration de VIE (distinct du rate-limit et du plafond mensuel) ; NULL = aucun.
    total_token_cap: int | None = None
    total_request_cap: int | None = None
    expires_at: str | None = None
    idle_expiry_days: int | None = None
    external_ref: str | None = None  # identité stable si clé gérée par la config déclarative (YAML)


# --- Lookup / validation (chemin proxy) -------------------------------------------------------

def find_by_key(key: str, conn: sqlite3.Connection | None = None) -> sqlite3.Row | None:
    """Ligne api_keys correspondant à la clé (par hash), ou None."""
    own = conn is None
    conn = conn or db.connect()
    try:
        return conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ?", (auth.hash_key(key),)
        ).fetchone()
    finally:
        if own:
            conn.close()


def origins_for(key_id: int, conn: sqlite3.Connection) -> list[str]:
    return [r["cidr"] for r in conn.execute(
        "SELECT cidr FROM key_origins WHERE key_id = ? ORDER BY id", (key_id,))]


def models_for(key_id: int, conn: sqlite3.Connection) -> list[str]:
    """Allowlist de modèles de la clé (vide = tous les modèles du serveur autorisés)."""
    return [r["model"] for r in conn.execute(
        "SELECT model FROM key_models WHERE key_id = ? ORDER BY id", (key_id,))]


def apis_for(key_id: int, conn: sqlite3.Connection) -> list[str]:
    """Allowlist de familles d'API de la clé (vide = toutes les familles autorisées)."""
    return [r["api"] for r in conn.execute(
        "SELECT api FROM key_apis WHERE key_id = ? ORDER BY id", (key_id,))]


def image_models_for(key_id: int, conn: sqlite3.Connection) -> list[str]:
    """Allowlist de modèles d'IMAGE de la clé (vide = tous les modèles image autorisés)."""
    return [r["model"] for r in conn.execute(
        "SELECT model FROM key_image_models WHERE key_id = ? ORDER BY id", (key_id,))]


def origin_allowed(client_ip: str, cidrs: list[str]) -> bool:
    """True si aucune restriction (liste vide) ou si client_ip ∈ l'un des CIDR."""
    if not cidrs:
        return True
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def touch_last_used(key_id: int, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or db.connect()
    try:
        with conn:
            conn.execute("UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?", (key_id,))
    finally:
        if own:
            conn.close()


# --- CRUD (chemin admin) ----------------------------------------------------------------------

def create_key(label: str, origins: list[str], monthly_token_cap: int | None,
               rpm_limit: int | None, note: str = "", key_value: str | None = None,
               server_id: int | None = None, models: list[str] | None = None,
               key_apis: list[str] | None = None, target_id: int | None = None,
               fallback_server_id: int | None = None, image_models: list[str] | None = None,
               total_token_cap: int | None = None, total_request_cap: int | None = None,
               expires_at: str | None = None, idle_expiry_days: int | None = None,
               log_retention_days: int | None = None,
               external_ref: str | None = None) -> tuple[KeyRecord, str]:
    """Crée une clé. Renvoie (record, clé_en_clair). La clé n'est visible qu'ici (jamais restockée).

    `key_value` permet d'injecter une clé existante (migration) au lieu d'en générer une neuve.
    `server_id` = serveur d'exécution rattaché (None → serveur par défaut). `models` = allowlist
    de modèles (None/vide → tous les modèles du serveur autorisés). `external_ref` = identité
    stable si la clé est gérée par la configuration déclarative (YAML, cf. app/reconcile.py).
    """
    key = key_value or auth.generate_key()
    conn = db.connect()
    try:
        sid = server_id if server_id is not None else servers.default_id(conn)
        tid = target_id if target_id is not None else targets.default_id(conn)
        with conn:
            cur = conn.execute(
                "INSERT INTO api_keys(label, key_prefix, key_hash, note, server_id, target_id, "
                "fallback_server_id, total_token_cap, total_request_cap, expires_at, "
                "idle_expiry_days, log_retention_days, external_ref) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (label, auth.key_prefix(key), auth.hash_key(key), note, sid, tid,
                 fallback_server_id, total_token_cap, total_request_cap, expires_at,
                 idle_expiry_days, log_retention_days, external_ref),
            )
            kid = cur.lastrowid
            for c in origins:
                conn.execute("INSERT INTO key_origins(key_id, cidr) VALUES (?,?)", (kid, c.strip()))
            for m in (models or []):
                if m.strip():
                    conn.execute("INSERT INTO key_models(key_id, model) VALUES (?,?)",
                                 (kid, m.strip()))
            for a in (key_apis or []):
                if a.strip() in apis.FAMILIES:
                    conn.execute("INSERT INTO key_apis(key_id, api) VALUES (?,?)",
                                 (kid, a.strip()))
            for m in (image_models or []):
                if m.strip():
                    conn.execute("INSERT INTO key_image_models(key_id, model) VALUES (?,?)",
                                 (kid, m.strip()))
            if monthly_token_cap is not None or rpm_limit is not None:
                conn.execute(
                    "INSERT INTO key_quotas(key_id, monthly_token_cap, rpm_limit) VALUES (?,?,?)",
                    (kid, monthly_token_cap, rpm_limit),
                )
    finally:
        conn.close()
    return get_key(kid), key


def get_key(key_id: int, conn: sqlite3.Connection | None = None) -> KeyRecord | None:
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            return None
        q = conn.execute(
            "SELECT monthly_token_cap, rpm_limit FROM key_quotas WHERE key_id = ?", (key_id,)
        ).fetchone()
        server_id = row["server_id"]
        srv = conn.execute(
            "SELECT name FROM servers WHERE id = ?", (server_id,)).fetchone() if server_id else None
        fb_id = row["fallback_server_id"] if "fallback_server_id" in row.keys() else None
        fb = conn.execute(
            "SELECT name FROM servers WHERE id = ?", (fb_id,)).fetchone() if fb_id else None
        target_id = row["target_id"] if "target_id" in row.keys() else None
        tgt = conn.execute(
            "SELECT name, base_url FROM targets WHERE id = ?", (target_id,)
        ).fetchone() if target_id else None
        return KeyRecord(
            id=row["id"], label=row["label"], key_prefix=row["key_prefix"],
            enabled=bool(row["enabled"]), note=row["note"], created_at=row["created_at"],
            last_used_at=row["last_used_at"], origins=origins_for(key_id, conn),
            monthly_token_cap=q["monthly_token_cap"] if q else None,
            rpm_limit=q["rpm_limit"] if q else None,
            server_id=server_id, server_name=srv["name"] if srv else None,
            fallback_server_id=fb_id, fallback_server_name=fb["name"] if fb else None,
            target_id=target_id, target_name=tgt["name"] if tgt else None,
            target_base_url=tgt["base_url"] if tgt else None,
            models=models_for(key_id, conn),
            image_models=image_models_for(key_id, conn),
            apis=apis_for(key_id, conn),
            log_retention_days=row["log_retention_days"],
            total_token_cap=row["total_token_cap"] if "total_token_cap" in row.keys() else None,
            total_request_cap=(row["total_request_cap"]
                               if "total_request_cap" in row.keys() else None),
            expires_at=row["expires_at"] if "expires_at" in row.keys() else None,
            idle_expiry_days=(row["idle_expiry_days"]
                              if "idle_expiry_days" in row.keys() else None),
            external_ref=(row["external_ref"]
                          if "external_ref" in row.keys() else None),
        )
    finally:
        if own:
            conn.close()


def managed_refs(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Map `external_ref` → `key_id` des clés gérées par la config déclarative (external_ref non
    NULL). Les clés UI (external_ref NULL) en sont absentes : la réconciliation ne les touche
    jamais (ni mise à jour ni élagage)."""
    own = conn is None
    conn = conn or db.connect()
    try:
        return {r["external_ref"]: r["id"] for r in conn.execute(
            "SELECT id, external_ref FROM api_keys WHERE external_ref IS NOT NULL")}
    finally:
        if own:
            conn.close()


def list_keys() -> list[KeyRecord]:
    conn = db.connect()
    try:
        ids = [r["id"] for r in conn.execute("SELECT id FROM api_keys ORDER BY created_at DESC, id DESC")]
        return [get_key(i, conn) for i in ids]
    finally:
        conn.close()


def set_enabled(key_id: int, enabled: bool) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE api_keys SET enabled = ? WHERE id = ?", (1 if enabled else 0, key_id))
    finally:
        conn.close()


def update_key(key_id: int, label: str, origins: list[str],
               monthly_token_cap: int | None, rpm_limit: int | None, note: str,
               server_id: int | None = None, models: list[str] | None = None,
               key_apis: list[str] | None = None, target_id: int | None = None,
               fallback_server_id: int | None = None, clear_fallback: bool = False,
               image_models: list[str] | None = None,
               total_token_cap: int | None = None, total_request_cap: int | None = None,
               expires_at: str | None = None, idle_expiry_days: int | None = None,
               log_retention_days: int | None = None) -> None:
    """Met à jour une clé. `server_id`/`models`/`key_apis`/`target_id` non fournis (None) → inchangés.

    `log_retention_days` est toujours appliqué (le formulaire l'inclut ; vide = NULL = défaut).
    """
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE api_keys SET label = ?, note = ?, log_retention_days = ?, "
                "total_token_cap = ?, total_request_cap = ?, expires_at = ?, "
                "idle_expiry_days = ? WHERE id = ?",
                (label, note, log_retention_days, total_token_cap, total_request_cap,
                 expires_at, idle_expiry_days, key_id))
            if server_id is not None:
                conn.execute("UPDATE api_keys SET server_id = ? WHERE id = ?",
                             (server_id, key_id))
            if target_id is not None:
                conn.execute("UPDATE api_keys SET target_id = ? WHERE id = ?",
                             (target_id, key_id))
            if clear_fallback:
                conn.execute("UPDATE api_keys SET fallback_server_id = NULL WHERE id = ?",
                             (key_id,))
            elif fallback_server_id is not None:
                conn.execute("UPDATE api_keys SET fallback_server_id = ? WHERE id = ?",
                             (fallback_server_id, key_id))
            conn.execute("DELETE FROM key_origins WHERE key_id = ?", (key_id,))
            for c in origins:
                if c.strip():
                    conn.execute("INSERT INTO key_origins(key_id, cidr) VALUES (?,?)",
                                 (key_id, c.strip()))
            if models is not None:
                conn.execute("DELETE FROM key_models WHERE key_id = ?", (key_id,))
                for m in models:
                    if m.strip():
                        conn.execute("INSERT INTO key_models(key_id, model) VALUES (?,?)",
                                     (key_id, m.strip()))
            if key_apis is not None:
                conn.execute("DELETE FROM key_apis WHERE key_id = ?", (key_id,))
                for a in key_apis:
                    if a.strip() in apis.FAMILIES:
                        conn.execute("INSERT INTO key_apis(key_id, api) VALUES (?,?)",
                                     (key_id, a.strip()))
            if image_models is not None:
                conn.execute("DELETE FROM key_image_models WHERE key_id = ?", (key_id,))
                for m in image_models:
                    if m.strip():
                        conn.execute("INSERT INTO key_image_models(key_id, model) VALUES (?,?)",
                                     (key_id, m.strip()))
            conn.execute("DELETE FROM key_quotas WHERE key_id = ?", (key_id,))
            if monthly_token_cap is not None or rpm_limit is not None:
                conn.execute(
                    "INSERT INTO key_quotas(key_id, monthly_token_cap, rpm_limit) VALUES (?,?,?)",
                    (key_id, monthly_token_cap, rpm_limit),
                )
    finally:
        conn.close()


def delete_key(key_id: int) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    finally:
        conn.close()


# --- Auth admin -------------------------------------------------------------------------------

def get_admin_hash(conn: sqlite3.Connection | None = None) -> str | None:
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute("SELECT password_hash FROM admin_auth WHERE id = 1").fetchone()
        return row["password_hash"] if row else None
    finally:
        if own:
            conn.close()


def set_admin_password(password: str) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO admin_auth(id, password_hash, updated_at) VALUES (1, ?, datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET password_hash = excluded.password_hash, "
                "updated_at = datetime('now')",
                (auth.hash_password(password),),
            )
    finally:
        conn.close()
