"""CRUD des clés API + validation (lookup par hash, état, allowlist d'origine) + auth admin.

Toutes les fonctions ouvrent une connexion courte si aucune n'est fournie. L'origine est
comparée en IP/CIDR via le module `ipaddress` (IPv4 et IPv6).
"""
import ipaddress
import sqlite3
from dataclasses import dataclass

from . import auth, db


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
               rpm_limit: int | None, note: str = "",
               key_value: str | None = None) -> tuple[KeyRecord, str]:
    """Crée une clé. Renvoie (record, clé_en_clair). La clé n'est visible qu'ici (jamais restockée).

    `key_value` permet d'injecter une clé existante (migration) au lieu d'en générer une neuve.
    """
    key = key_value or auth.generate_key()
    conn = db.connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO api_keys(label, key_prefix, key_hash, note) VALUES (?,?,?,?)",
                (label, auth.key_prefix(key), auth.hash_key(key), note),
            )
            kid = cur.lastrowid
            for c in origins:
                conn.execute("INSERT INTO key_origins(key_id, cidr) VALUES (?,?)", (kid, c.strip()))
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
        return KeyRecord(
            id=row["id"], label=row["label"], key_prefix=row["key_prefix"],
            enabled=bool(row["enabled"]), note=row["note"], created_at=row["created_at"],
            last_used_at=row["last_used_at"], origins=origins_for(key_id, conn),
            monthly_token_cap=q["monthly_token_cap"] if q else None,
            rpm_limit=q["rpm_limit"] if q else None,
        )
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
               monthly_token_cap: int | None, rpm_limit: int | None, note: str) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE api_keys SET label = ?, note = ? WHERE id = ?", (label, note, key_id))
            conn.execute("DELETE FROM key_origins WHERE key_id = ?", (key_id,))
            for c in origins:
                if c.strip():
                    conn.execute("INSERT INTO key_origins(key_id, cidr) VALUES (?,?)", (key_id, c.strip()))
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
