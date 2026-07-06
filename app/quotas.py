"""Application des quotas par clé : plafond mensuel de tokens + rate-limit (req/min)."""
import sqlite3

from . import usage
from .keys import KeyRecord


def check(rec: KeyRecord, conn: sqlite3.Connection) -> tuple[bool, str | None]:
    """Renvoie (autorisé, motif). Motif renseigné seulement si refus (429).

    - Plafond mensuel : vérifié AVANT la requête sur la conso déjà enregistrée du mois. La requête
      qui franchit le plafond peut légèrement le dépasser (ses tokens ne sont connus qu'après) ;
      la suivante sera refusée. Comportement volontaire (simple et sûr).
    - Rate-limit : nombre de requêtes de la clé sur les 60 dernières secondes.
    """
    if rec.rpm_limit is not None:
        if usage.recent_request_count(rec.id, 60, conn) >= rec.rpm_limit:
            return False, f"rate-limit dépassé ({rec.rpm_limit} req/min)"
    if rec.monthly_token_cap is not None:
        if usage.month_tokens(rec.id, conn) >= rec.monthly_token_cap:
            return False, f"plafond mensuel de tokens atteint ({rec.monthly_token_cap})"
    return True, None
