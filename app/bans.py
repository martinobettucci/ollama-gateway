"""Liste de bannissement GLOBALE d'origines (IP/CIDR).

Appliquée par le proxy **avant l'authentification de clé** : une requête issue d'une origine
bannie est refusée (403) quelle que soit la clé. Distincte des allowlists d'origine *par clé*
(`key_origins`, un ALLOW positif) : ici c'est un **DENY global**, piloté depuis la console de
logs de l'admin (bouton « Bannir cette IP » sur une ligne, ou saisie manuelle d'un CIDR).
"""
import ipaddress
import sqlite3

from . import db


def normalize_cidr(raw: str) -> str | None:
    """Normalise une IP ou un CIDR en forme réseau canonique, ou None si invalide.

    Une IP simple devient un hôte unique : `/32` (IPv4) ou `/128` (IPv6).
    """
    s = (raw or "").strip()
    if not s:
        return None
    try:
        if "/" in s:
            return str(ipaddress.ip_network(s, strict=False))
        ip = ipaddress.ip_address(s)
        return f"{ip}/{ip.max_prefixlen}"
    except ValueError:
        return None


def list_bans(conn: sqlite3.Connection | None = None) -> list[dict]:
    own = conn is None
    conn = conn or db.connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, cidr, reason, created_at FROM banned_origins "
            "ORDER BY created_at DESC, id DESC")]
    finally:
        if own:
            conn.close()


def add_ban(cidr_or_ip: str, reason: str = "") -> str | None:
    """Bannit une IP/CIDR (normalisée). Renvoie la forme ajoutée, ou None si entrée invalide.

    Idempotent : un CIDR déjà présent n'est pas dupliqué (contrainte UNIQUE).
    """
    norm = normalize_cidr(cidr_or_ip)
    if norm is None:
        return None
    conn = db.connect()
    try:
        with conn:
            conn.execute("INSERT OR IGNORE INTO banned_origins(cidr, reason) VALUES (?,?)",
                         (norm, (reason or "").strip()))
    finally:
        conn.close()
    return norm


def remove_ban(ban_id: int) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM banned_origins WHERE id = ?", (ban_id,))
    finally:
        conn.close()


def banned_cidrs(conn: sqlite3.Connection | None = None) -> list[str]:
    own = conn is None
    conn = conn or db.connect()
    try:
        return [r["cidr"] for r in conn.execute("SELECT cidr FROM banned_origins")]
    finally:
        if own:
            conn.close()


def is_banned(client_ip: str, conn: sqlite3.Connection | None = None) -> bool:
    """True si `client_ip` appartient à l'un des réseaux bannis."""
    return _match(client_ip, banned_cidrs(conn))


def _match(client_ip: str, cidrs: list[str]) -> bool:
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


def banned_among(ips, conn: sqlite3.Connection | None = None) -> set[str]:
    """Sous-ensemble des `ips` couvertes par un bannissement (une requête à la table de bans).

    Sert à marquer les lignes déjà bannies dans la console de logs sans une requête par ligne.
    """
    cidrs = banned_cidrs(conn)
    return {ip for ip in set(ips) if ip and _match(ip, cidrs)}
