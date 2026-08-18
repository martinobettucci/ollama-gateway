"""Journal d'usage : écriture d'un événement par requête + agrégats pour le dashboard/quotas."""
import sqlite3

from . import db


def record(
    *, key_id: int | None, client_ip: str, method: str, path: str, model: str,
    status: int, duration_ms: int, tokens_prompt: int = 0, tokens_completion: int = 0,
    bytes_in: int = 0, bytes_out: int = 0, server_id: int | None = None,
    ctx_bucket: int | None = None, conn: sqlite3.Connection | None = None,
) -> None:
    """Insère un événement d'usage (append-only). `server_id` = serveur ayant réellement traité
    (repli inclus ; None si la requête n'a pas atteint d'amont)."""
    own = conn is None
    conn = conn or db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO usage_events(key_id, client_ip, method, path, model, status, "
                "duration_ms, tokens_prompt, tokens_completion, bytes_in, bytes_out, "
                "server_id, ctx_bucket) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key_id, client_ip, method, path, model, status, duration_ms,
                 tokens_prompt, tokens_completion, bytes_in, bytes_out, server_id,
                 ctx_bucket),
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


def lifetime_tokens(key_id: int, conn: sqlite3.Connection | None = None) -> int:
    """Somme de TOUS les tokens (prompt+complétion) de la clé, sans fenêtre — plafond de vie."""
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(tokens_prompt + tokens_completion), 0) AS t "
            "FROM usage_events WHERE key_id = ?", (key_id,),
        ).fetchone()
        return int(row["t"])
    finally:
        if own:
            conn.close()


def lifetime_requests(key_id: int, conn: sqlite3.Connection | None = None) -> int:
    """Nombre TOTAL de requêtes journalisées de la clé, sans fenêtre — plafond de vie."""
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_events WHERE key_id = ?", (key_id,)).fetchone()
        return int(row["n"])
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


def rpm_window_reset(key_id: int, seconds: int = 60,
                     conn: sqlite3.Connection | None = None) -> int:
    """Secondes avant qu'un créneau de la fenêtre glissante rpm se libère (la requête la plus
    ancienne de la fenêtre en sort). 0 si aucune requête en fenêtre. Sert à l'en-tête
    `x-ratelimit-reset-requests`."""
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT CAST(strftime('%s','now') AS INTEGER) - "
            "CAST(strftime('%s', MIN(ts)) AS INTEGER) AS age "
            "FROM usage_events WHERE key_id = ? AND ts >= datetime('now', ?)",
            (key_id, f"-{int(seconds)} seconds")).fetchone()
        age = row["age"] if row and row["age"] is not None else None
        return 0 if age is None else max(0, int(seconds) - int(age))
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


# --- Horizons temporels (sélecteur de graphe : clé & monitoring serveur) ----------------------
# Fenêtre glissante + granularité de bucket par horizon. 24h → buckets HORAIRES ; au-delà → JOUR.
DEFAULT_HORIZON = "1m"
HORIZONS = ("24h", "1w", "2w", "1m", "3m")
_HORIZON: dict[str, tuple[str, str]] = {
    "24h": ("-24 hours", "hour"),
    "1w": ("-7 days", "day"),
    "2w": ("-14 days", "day"),
    "1m": ("-30 days", "day"),
    "3m": ("-90 days", "day"),
}


def horizon_or_default(h: str | None) -> str:
    """Normalise un horizon fourni (query param) → l'un de HORIZONS, défaut DEFAULT_HORIZON."""
    return h if h in HORIZONS else DEFAULT_HORIZON


def key_series(key_id: int, horizon: str,
               conn: sqlite3.Connection | None = None) -> list[dict]:
    """Série (bucket, reqs, tokens) d'une clé selon l'horizon (buckets horaires pour 24h)."""
    since, bucket = _HORIZON[horizon_or_default(horizon)]
    own = conn is None
    conn = conn or db.connect()
    try:
        if bucket == "hour":
            rows = conn.execute(
                "SELECT strftime('%Y-%m-%d %H:00', ts) AS bucket, COUNT(*) AS reqs, "
                "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens "
                "FROM usage_events WHERE key_id = ? AND ts >= datetime('now', ?) "
                "GROUP BY bucket ORDER BY bucket", (key_id, since)).fetchall()
        else:
            rows = conn.execute(
                "SELECT substr(ts,1,10) AS bucket, COUNT(*) AS reqs, "
                "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens "
                "FROM usage_events WHERE key_id = ? AND ts >= datetime('now', ?) "
                "GROUP BY bucket ORDER BY bucket", (key_id, since)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def key_per_model(key_id: int, horizon: str,
                  conn: sqlite3.Connection | None = None) -> list[dict]:
    """Consommation PAR MODÈLE d'une clé sur l'horizon : requêtes, tokens (prompt+complétion),
    erreurs, dernier usage — les modèles les plus consommateurs d'abord."""
    since, _ = _HORIZON[horizon_or_default(horizon)]
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT model, COUNT(*) AS reqs, "
            "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens, "
            "COALESCE(SUM(tokens_prompt),0) AS tokens_prompt, "
            "COALESCE(SUM(tokens_completion),0) AS tokens_completion, "
            "SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors, MAX(ts) AS last_seen "
            "FROM usage_events WHERE key_id = ? AND ts >= datetime('now', ?) AND model <> '' "
            "GROUP BY model ORDER BY tokens DESC, reqs DESC", (key_id, since)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def server_series(server_id: int, horizon: str,
                  conn: sqlite3.Connection | None = None) -> list[dict]:
    """Série (bucket, reqs, tokens) d'un serveur selon l'horizon (buckets horaires pour 24h)."""
    since, bucket = _HORIZON[horizon_or_default(horizon)]
    own = conn is None
    conn = conn or db.connect()
    try:
        if bucket == "hour":
            rows = conn.execute(
                "SELECT strftime('%Y-%m-%d %H:00', ts) AS bucket, COUNT(*) AS reqs, "
                "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens "
                "FROM usage_events WHERE server_id = ? AND ts >= datetime('now', ?) "
                "GROUP BY bucket ORDER BY bucket", (server_id, since)).fetchall()
        else:
            rows = conn.execute(
                "SELECT substr(ts,1,10) AS bucket, COUNT(*) AS reqs, "
                "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens "
                "FROM usage_events WHERE server_id = ? AND ts >= datetime('now', ?) "
                "GROUP BY bucket ORDER BY bucket", (server_id, since)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


# --- Monitoring par serveur d'exécution (attribution réelle, repli inclus) --------------------

def server_summary(server_id: int, conn: sqlite3.Connection | None = None) -> dict:
    """Totaux d'un serveur : requêtes, tokens, erreurs (≥400), clés distinctes, requêtes 24 h."""
    own = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS reqs, "
            "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens, "
            "SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors, "
            "COUNT(DISTINCT key_id) AS key_count, "
            "SUM(CASE WHEN ts >= datetime('now','-24 hours') THEN 1 ELSE 0 END) AS reqs_24h "
            "FROM usage_events WHERE server_id = ?", (server_id,)).fetchone()
        return {
            "requests": int(row["reqs"] or 0), "tokens": int(row["tokens"] or 0),
            "errors": int(row["errors"] or 0), "key_count": int(row["key_count"] or 0),
            "requests_24h": int(row["reqs_24h"] or 0),
        }
    finally:
        if own:
            conn.close()


def server_per_key(server_id: int, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Consommation et erreurs PAR CLÉ sur un serveur : requêtes, tokens, erreurs, dernier usage."""
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT e.key_id AS key_id, COALESCE(k.label, '(clé supprimée)') AS label, "
            "k.key_prefix AS key_prefix, COUNT(*) AS reqs, "
            "COALESCE(SUM(e.tokens_prompt + e.tokens_completion),0) AS tokens, "
            "SUM(CASE WHEN e.status >= 400 THEN 1 ELSE 0 END) AS errors, MAX(e.ts) AS last_seen "
            "FROM usage_events e LEFT JOIN api_keys k ON k.id = e.key_id "
            "WHERE e.server_id = ? GROUP BY e.key_id "
            "ORDER BY tokens DESC, reqs DESC", (server_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def server_per_model(server_id: int, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Traçage de l'usage PAR MODÈLE sur un serveur : pour CHAQUE modèle réellement invoqué,
    requêtes, tokens, erreurs, premier et **dernier** usage. Le plus récemment utilisé d'abord.

    Alimente la table « Usage par modèle » du monitoring : quels modèles tournent réellement sur ce
    serveur et quand chacun a servi pour la dernière fois. Les requêtes sans modèle résolu
    (`model = ''` : erreurs d'auth/quota avant lecture du corps) sont exclues du traçage par modèle.
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT model, COUNT(*) AS reqs, "
            "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens, "
            "SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors, "
            "MIN(ts) AS first_seen, MAX(ts) AS last_seen "
            "FROM usage_events WHERE server_id = ? AND model <> '' "
            "GROUP BY model ORDER BY last_seen DESC, tokens DESC", (server_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def server_status_breakdown(server_id: int, conn: sqlite3.Connection | None = None) -> dict:
    """Répartition des statuts d'un serveur par classe : 2xx / 3xx / 4xx / 5xx (camembert)."""
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT (status/100) AS cls, COUNT(*) AS n FROM usage_events "
            "WHERE server_id = ? GROUP BY cls", (server_id,)).fetchall()
        out = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        for r in rows:
            key = f"{int(r['cls'])}xx"
            if key in out:
                out[key] += int(r["n"])
        return out
    finally:
        if own:
            conn.close()


def server_daily(server_id: int, days: int = 30,
                 conn: sqlite3.Connection | None = None) -> list[dict]:
    """Série journalière (N derniers jours) d'un serveur : requêtes et tokens par jour."""
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT substr(ts,1,10) AS day, COUNT(*) AS reqs, "
            "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens "
            "FROM usage_events WHERE server_id = ? AND ts >= datetime('now', ?) "
            "GROUP BY day ORDER BY day", (server_id, f"-{int(days)} days")).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


# --- Tailles de contexte réellement utilisées (paliers) ---------------------------------------

def _ctx_buckets(where: str, param, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Agrégat par PALIER de contexte : nombre de requêtes et **dernier usage**, du palier le plus
    grand au plus petit. Les événements sans palier mesuré (`ctx_bucket` NULL : refus avant lecture
    du corps, ou antérieurs à la migration 0013) sont exclus."""
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT ctx_bucket AS bucket, COUNT(*) AS reqs, "
            "COALESCE(SUM(tokens_prompt + tokens_completion),0) AS tokens, "
            "MIN(ts) AS first_seen, MAX(ts) AS last_seen "
            f"FROM usage_events WHERE ctx_bucket IS NOT NULL AND {where} "
            "GROUP BY ctx_bucket ORDER BY ctx_bucket DESC", (param,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def key_ctx_buckets(key_id: int, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Tailles de contexte réellement utilisées par une CLÉ (compte + dernier usage par palier)."""
    return _ctx_buckets("key_id = ?", key_id, conn)


def server_ctx_buckets(server_id: int, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Tailles de contexte réellement utilisées sur un SERVEUR (compte + dernier usage)."""
    return _ctx_buckets("server_id = ?", server_id, conn)


# --- Temps réel : dernières 2 h par clé et modèle ---------------------------------------------

# Largeur d'une tranche de l'histogramme temps réel, en minutes (doit diviser 60).
REALTIME_BUCKET_MIN = 15

# Palette P2Enjoy par TYPE de modèle (couleur de la portion empilée).
_TYPE_COLORS = {
    "text": "#23468C",    # bleu
    "image": "#238C33",   # vert
    "vision": "#D9CF4A",  # jaune
}
_TYPE_FALLBACK = "#8A94A6"


def model_type(model: str) -> str:
    """Type d'un modèle d'après son nom : `image` (namespace `x/…` ou « image »), `vision`, sinon
    `text`. Déduit du NOM car aucun type n'est stocké dans `usage_events`."""
    m = (model or "").lower()
    if m.startswith("x/") or "image" in m:
        return "image"
    if "vision" in m or "vlm" in m:
        return "vision"
    return "text"


def type_color(mtype: str) -> str:
    return _TYPE_COLORS.get(mtype, _TYPE_FALLBACK)


def realtime_2h(conn: sqlite3.Connection | None = None) -> list[dict]:
    """Activité des 2 dernières heures, en tranches de `REALTIME_BUCKET_MIN` minutes.

    Renvoie une liste de tranches triées par horodatage :
    `{ts, keys: [{key_id, label, prefix, models: [{model, type, count, color}]}]}`.

    `ts` est en UTC, au format `YYYY-MM-DD HH:MM` avec les minutes calées sur la tranche
    (`00`/`15`/`30`/`45`) — cohérent avec `usage_events.ts` (`datetime('now')`, UTC).

    Chaque entrée porte le **nom du modèle** (le filtre de l'écran propose des noms de modèles)
    ET son **type** (qui donne la couleur de la portion empilée).
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        # Calage sur la tranche : on remplace les minutes par le multiple inférieur de la largeur
        # de tranche. `strftime('%M')` donne les minutes sur 2 chiffres → division entière.
        bucket_expr = (
            "strftime('%Y-%m-%d %H:', ts) || "
            f"printf('%02d', (CAST(strftime('%M', ts) AS INTEGER) / {REALTIME_BUCKET_MIN})"
            f" * {REALTIME_BUCKET_MIN})"
        )
        rows = conn.execute(
            f"SELECT {bucket_expr} AS bucket, e.key_id AS key_id, e.model AS model, "
            "COUNT(*) AS cnt, k.label AS label, k.key_prefix AS prefix "
            "FROM usage_events e LEFT JOIN api_keys k ON k.id = e.key_id "
            "WHERE e.ts >= datetime('now', '-2 hours') AND e.model <> '' "
            "GROUP BY bucket, e.key_id, e.model "
            "ORDER BY bucket, e.key_id, e.model"
        ).fetchall()

        # bucket → key_id → agrégat de la clé
        buckets: dict[str, dict[int, dict]] = {}
        for r in rows:
            per_key = buckets.setdefault(r["bucket"], {})
            entry = per_key.setdefault(r["key_id"], {
                "key_id": r["key_id"],
                # Clé supprimée depuis : `usage_events.key_id` est `ON DELETE SET NULL`, donc
                # `key_id` vaut NULL et la jointure ne ramène aucun libellé. Repli explicite —
                # jamais `None` ni « clé #None » : l'écran affiche ce libellé tel quel.
                "label": (r["label"] or (f"clé #{r['key_id']}" if r["key_id"] is not None
                                         else "clé supprimée")),
                "prefix": r["prefix"] or "",
                "models": [],
            })
            mtype = model_type(r["model"])
            entry["models"].append({
                "model": r["model"], "type": mtype,
                "count": r["cnt"], "color": type_color(mtype),
            })

        return [
            {"ts": bkt, "keys": [buckets[bkt][kid] for kid in sorted(buckets[bkt])]}
            for bkt in sorted(buckets)
        ]
    finally:
        if own:
            conn.close()
