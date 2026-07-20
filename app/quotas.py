"""Application des quotas par clé : rate-limit + plafond mensuel + plafonds/expiration de VIE.

Deux natures distinctes :
- **Rate-limit / mensuel** : fenêtres qui se réinitialisent (débit et conso du mois).
- **Vie de la clé** (« essai à coût plafonné ») : plafonds ABSOLUS (tokens/requêtes cumulés),
  **date d'expiration** et **expiration par inactivité** — une fois franchis, la clé est refusée
  définitivement (pas de réinitialisation).
"""
import sqlite3
from datetime import datetime, timezone

from . import usage
from .keys import KeyRecord

# --- Compteur « en vol » par clé (rate-limit anti-concurrence) --------------------------------
# L'usage n'est journalisé qu'à la FIN de la requête (BackgroundTask du proxy). Sans correctif, N
# requêtes lentes concurrentes passent toutes le contrôle rpm avant qu'aucune ne soit journalisée.
# On compte donc les requêtes ACTUELLEMENT en vol pour la clé et on les ajoute au débit observé.
# État MÉMOIRE : suffisant car le proxy tourne en mono-process (entrypoint sans --workers) ; en
# multi-process il faudrait un compteur partagé (ex. Redis).
_INFLIGHT: dict[int, int] = {}


def enter(key_id: int) -> None:
    """Marque une requête de la clé comme « en vol » (à appeler à l'admission, avant l'amont)."""
    _INFLIGHT[key_id] = _INFLIGHT.get(key_id, 0) + 1


def leave(key_id: int) -> None:
    """Libère une requête « en vol » (à appeler en fin de flux, exactement une fois)."""
    n = _INFLIGHT.get(key_id, 0) - 1
    if n > 0:
        _INFLIGHT[key_id] = n
    else:
        _INFLIGHT.pop(key_id, None)


def inflight(key_id: int) -> int:
    """Nombre de requêtes de la clé actuellement en vol (non encore journalisées)."""
    return _INFLIGHT.get(key_id, 0)


def _seconds_to_month_end() -> int:
    """Secondes jusqu'au 1er du mois suivant (UTC) : reset du plafond mensuel de tokens."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        nxt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0,
                          second=0, microsecond=0)
    else:
        nxt = now.replace(month=now.month + 1, day=1, hour=0, minute=0,
                          second=0, microsecond=0)
    return int((nxt - now).total_seconds())


def rate_limit_headers(rec: KeyRecord, conn: sqlite3.Connection) -> dict[str, str]:
    """En-têtes d'état de quota (style OpenAI/Groq) renvoyés au client, pour qu'il se rythme sans
    percuter les 429 (utile surtout aux boucles d'agents : lire/décider avant l'appel qui échoue).
    Seuls les plafonds DÉFINIS produisent des en-têtes (une clé illimitée n'en reçoit aucun).
    Réutilise `conn` (déjà ouvert par le proxy) → coût négligeable.

    - `x-ratelimit-{limit,remaining,reset}-requests` : rate-limit rpm (fenêtre glissante 60 s ;
      `remaining` inclut la requête courante ; `reset` = secondes avant qu'un créneau se libère).
    - `x-ratelimit-{limit,remaining,reset}-tokens` : plafond MENSUEL de tokens (`reset` = secondes
      jusqu'au 1er du mois suivant, UTC)."""
    h: dict[str, str] = {}
    if rec.rpm_limit is not None:
        used = usage.recent_request_count(rec.id, 60, conn) + inflight(rec.id) + 1
        h["x-ratelimit-limit-requests"] = str(rec.rpm_limit)
        h["x-ratelimit-remaining-requests"] = str(max(0, rec.rpm_limit - used))
        h["x-ratelimit-reset-requests"] = str(usage.rpm_window_reset(rec.id, 60, conn))
    if rec.monthly_token_cap is not None:
        used_t = usage.month_tokens(rec.id, conn)
        h["x-ratelimit-limit-tokens"] = str(rec.monthly_token_cap)
        h["x-ratelimit-remaining-tokens"] = str(max(0, rec.monthly_token_cap - used_t))
        h["x-ratelimit-reset-tokens"] = str(_seconds_to_month_end())
    return h


def check(rec: KeyRecord, conn: sqlite3.Connection) -> tuple[bool, str | None]:
    """Renvoie (autorisé, motif). Motif renseigné seulement si refus.

    - Plafond mensuel : vérifié AVANT la requête sur la conso déjà enregistrée du mois. La requête
      qui franchit le plafond peut légèrement le dépasser (ses tokens ne sont connus qu'après) ;
      la suivante sera refusée. Comportement volontaire (simple et sûr).
    - Rate-limit : nombre de requêtes de la clé sur les 60 dernières secondes.
    - Vie de la clé : expiration (date), inactivité (N jours sans usage), plafonds absolus de
      tokens et de requêtes cumulés.
    """
    # --- Expiration / inactivité (vie de la clé) : refus AVANT tout comptage coûteux ---
    if rec.expires_at:
        row = conn.execute(
            "SELECT (datetime('now') >= datetime(?)) AS expired", (rec.expires_at,)).fetchone()
        if row and row["expired"]:
            return False, f"clé expirée (depuis {rec.expires_at})"
    if rec.idle_expiry_days is not None and rec.last_used_at:
        row = conn.execute(
            "SELECT (datetime('now') >= datetime(?, ?)) AS idle",
            (rec.last_used_at, f"+{int(rec.idle_expiry_days)} days")).fetchone()
        if row and row["idle"]:
            return False, f"clé expirée par inactivité ({rec.idle_expiry_days} j sans usage)"

    if rec.rpm_limit is not None:
        # Débit journalisé (60 s) + requêtes en vol non encore journalisées (anti-concurrence).
        recent = usage.recent_request_count(rec.id, 60, conn) + inflight(rec.id)
        if recent >= rec.rpm_limit:
            return False, f"rate-limit dépassé ({rec.rpm_limit} req/min)"
    if rec.monthly_token_cap is not None:
        if usage.month_tokens(rec.id, conn) >= rec.monthly_token_cap:
            return False, f"plafond mensuel de tokens atteint ({rec.monthly_token_cap})"

    # --- Plafonds ABSOLUS de vie ---
    if rec.total_request_cap is not None:
        if usage.lifetime_requests(rec.id, conn) >= rec.total_request_cap:
            return False, f"plafond de requêtes atteint ({rec.total_request_cap})"
    if rec.total_token_cap is not None:
        if usage.lifetime_tokens(rec.id, conn) >= rec.total_token_cap:
            return False, f"plafond de tokens atteint ({rec.total_token_cap})"
    return True, None
