"""Cibles publiques (« ingress ») : URL publiques de la passerelle vues par les CLIENTS.

Une cible = l'URL que le client met dans `OLLAMA_HOST` / `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL`
(ex. `https://llm.example:8443`). **Distinct des serveurs d'exécution** (`servers.py`, l'amont
Ollama) : une cible **ne choisit pas l'amont** — l'amont reste déterminé par le serveur d'exécution
rattaché à la clé. Chaque clé pointe vers au plus une cible ; la **cible par défaut** (indélébile)
est seedée depuis `config.PUBLIC_BASE_URL`.

**La cible est CONTRAIGNANTE (depuis 2026-08-18).** Elle ne sert plus seulement à générer les
variables d'environnement : le proxy **refuse (403)** une requête qui n'est pas arrivée par la
cible rattachée à la clé (`host_allowed`). Une clé émise pour une passerelle ne peut donc pas être
rejouée à travers une autre — y compris si les deux passerelles mènent au même amont.
"""
import sqlite3
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import config, db

# Placeholder de base_url quand PUBLIC_BASE_URL n'est pas configurée (l'UI invite à le remplacer).
PLACEHOLDER_URL = "https://PASSERELLE-A-REMPLACER"

# Ports par défaut par schéma : un `Host:` sans port vaut le port par défaut du schéma employé.
_DEFAULT_PORTS = {"https": 443, "http": 80}


def _split_hostport(value: str, scheme: str) -> tuple[str, int | None]:
    """(hôte en minuscules, port) d'un « host[:port] » ou d'une URL complète.

    Passe par `urlsplit` sur une autorité (`//host:port`) pour traiter correctement les formes
    IPv6 entre crochets (`[::1]:8443`). Port absent → port par défaut du schéma."""
    value = (value or "").strip()
    if not value:
        return "", None
    if "//" not in value:
        value = "//" + value
    try:
        parts = urlsplit(value if value.startswith("//") else value)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:          # port non numérique, crochets mal formés…
        return "", None
    if port is None:
        port = _DEFAULT_PORTS.get(scheme)
    return host, port


def host_allowed(base_url: str | None, host_seen: str, proto_seen: str = "") -> bool:
    """La requête est-elle arrivée par la cible `base_url` ?

    Compare l'hôte **et le port** effectifs. `host_seen` est l'en-tête `Host` (ou
    `X-Forwarded-Host` quand le pair est de confiance) ; `proto_seen` est le schéma employé par le
    client (`X-Forwarded-Proto`), qui détermine le port implicite quand `Host` n'en porte pas.

    **Permissif par absence de contrainte** (jamais par échec de comparaison) : renvoie True si la
    clé n'a pas de cible, si la cible est restée au placeholder (non configurée), ou si l'URL de la
    cible est inexploitable — on ne coupe pas un service parce que la configuration est incomplète.
    Dès que la cible est exploitable, la correspondance est **stricte**."""
    if not base_url or base_url == PLACEHOLDER_URL:
        return True
    target_scheme = (urlsplit(base_url).scheme or "https").lower()
    want_host, want_port = _split_hostport(base_url, target_scheme)
    if not want_host:                       # cible illisible → pas de contrainte exploitable
        return True
    seen_scheme = (proto_seen or target_scheme).split(",")[0].strip().lower()
    got_host, got_port = _split_hostport(host_seen, seen_scheme)
    if not got_host:
        return False                        # cible exploitable mais requête sans hôte → refus
    return got_host == want_host and got_port == want_port


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
                    elif config.DECLARATIVE:
                        # Mode déclaratif (headless) : le reconciler crée les cibles depuis le YAML.
                        return 0
                    else:
                        cur = conn.execute(
                            "INSERT INTO targets(name, base_url, is_default) VALUES (?,?,1)",
                            ("Passerelle publique", config.PUBLIC_BASE_URL or PLACEHOLDER_URL))
                        did = cur.lastrowid
                # Auto-réparation : si la cible par défaut est restée sur le placeholder (seed sans
                # PUBLIC_BASE_URL) et qu'une URL publique est désormais configurée, on l'adopte.
                if config.PUBLIC_BASE_URL:
                    conn.execute(
                        "UPDATE targets SET base_url = ? WHERE id = ? AND base_url = ?",
                        (config.PUBLIC_BASE_URL, did, PLACEHOLDER_URL))
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
