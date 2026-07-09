"""Journal d'usage : écriture d'un événement par requête + agrégats pour le dashboard/quotas."""
import sqlite3

from . import db


def record(
    *, key_id: int | None, client_ip: str, method: str, path: str, model: str,
    status: int, duration_ms: int, tokens_prompt: int = 0, tokens_completion: int = 0,
    bytes_in: int = 0, bytes_out: int = 0, conn: sqlite3.Connection | None = None,
) -> None:
    """Insère un événement d'usage (append-only)."""
    own = conn is None
    conn = conn or db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO usage_events(key_id, client_ip, method, path, model, status, "
                "duration_ms, tokens_prompt, tokens_completion, bytes_in, bytes_out) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (key_id, client_ip, method, path, model, status, duration_ms,
                 tokens_prompt, tokens_completion, bytes_in, bytes_out),
            )
    finally:
        if own:
            conn.close()


def month_tokens(key_id: int, conn: sqlite3.Connection | None = None) -> int:
    """Somme des tokens (prompt+complétion) du mois calendaire courant pour la clé."""
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(tokens_prompt + tokens_completion), 0) AS t FROM usage_events "
            "WHERE key_id = ? AND ts >= strftime('%Y-%m-01 00:00:00', 'now')",
            (key_id,),
        ).fetchone()
        return int(row["t"])
    finally:
        if own:
            conn.close()


def recent_request_count(key_id: int, seconds: int = 60, conn: sqlite3.Connection | None = None) -> int:
    """Nombre de requêtes de la clé sur la fenêtre glissante (défaut 60 s) — pour le rate-limit."""
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events "
            "WHERE key_id = ? AND ts >= datetime('now', ?)",
            (key_id, f"-{int(seconds)} seconds"),
        ).fetchone()
        return int(row["n"])
    finally:
        if own:
            conn.close()


def key_summary(key_id: int, conn: sqlite3.Connection | None = None) -> dict:
    """Agrégats d'affichage pour une clé (30 derniers jours + total)."""
    own = conn is None
    conn = conn or db.connect()
    try:
        totals = conn.execute(
            "SELECT COUNT(*) AS reqs, "
            "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens, "
            "SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors "
            "FROM usage_events WHERE key_id = ?", (key_id,)
        ).fetchone()
        per_day = conn.execute(
            "SELECT substr(ts,1,10) AS day, COUNT(*) AS reqs, "
            "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens "
            "FROM usage_events WHERE key_id = ? AND ts >= datetime('now','-30 days') "
            "GROUP BY day ORDER BY day DESC", (key_id,)
        ).fetchall()
        recent_errors = conn.execute(
            "SELECT ts, client_ip, path, status FROM usage_events "
            "WHERE key_id = ? AND status >= 400 ORDER BY ts DESC LIMIT 10", (key_id,)
        ).fetchall()
        return {
            "requests": int(totals["reqs"] or 0),
            "tokens": int(totals["tokens"] or 0),
            "errors": int(totals["errors"] or 0),
            "month_tokens": month_tokens(key_id, conn),
            "per_day": [dict(r) for r in per_day],
            "recent_errors": [dict(r) for r in recent_errors],
        }
    finally:
        if own:
            conn.close()


def recent_events(limit: int = 500, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Journal complet des dernières requêtes (console de logs admin), la plus récente d'abord.

    Le label de la clé est joint (LEFT JOIN : NULL si clé absente/supprimée ou requête non
    authentifiée). Le journal `usage_events` est append-only et intégralement conservé ; `limit`
    ne borne QUE l'affichage, pas la rétention.
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT e.id, e.ts, e.client_ip, e.method, e.path, e.model, e.status, "
            "e.tokens_prompt, e.tokens_completion, e.duration_ms, k.label AS key_label "
            "FROM usage_events e LEFT JOIN api_keys k ON k.id = e.key_id "
            "ORDER BY e.id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def origins_seen(key_id: int, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Origines (IP) uniques ayant utilisé la clé : compte + dernier vu, plus fréquentes d'abord.

    Alimente la liste « Origines vues » du panel (recherche + bouton WHOIS).
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT client_ip AS ip, COUNT(*) AS hits, MAX(ts) AS last_seen "
            "FROM usage_events WHERE key_id = ? AND client_ip <> '' "
            "GROUP BY client_ip ORDER BY hits DESC, last_seen DESC", (key_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def total_events(conn: sqlite3.Connection | None = None) -> int:
    """Nombre total d'événements conservés (le journal n'est jamais purgé)."""
    own = conn is None
    conn = conn or db.connect()
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM usage_events").fetchone()["n"])
    finally:
        if own:
            conn.close()


def global_summary(conn: sqlite3.Connection | None = None) -> dict:
    """Totaux globaux (bandeau du dashboard)."""
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS reqs, "
            "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens, "
            "SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors, "
            "SUM(CASE WHEN ts >= datetime('now','-24 hours') THEN 1 ELSE 0 END) AS reqs_24h "
            "FROM usage_events"
        ).fetchone()
        return {
            "requests": int(row["reqs"] or 0),
            "tokens": int(row["tokens"] or 0),
            "errors": int(row["errors"] or 0),
            "requests_24h": int(row["reqs_24h"] or 0),
        }
    finally:
        if own:
            conn.close()
