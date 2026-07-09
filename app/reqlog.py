"""Journal de CONTENU complet des requêtes, sur le SYSTÈME DE FICHIERS (jamais en base).

Disposition : `$REQUEST_LOG_DIR/key-<id>/<YYYY-MM-DD_HH>.jsonl` (une ligne JSON par requête,
un fichier par heure, un dossier par clé). Les **secrets** (`Authorization`, `x-api-key`,
`cookie`) sont retirés avant écriture — jamais de clé en clair au repos.

Le cron `python -m app.reqlog compact` :
- **compacte** en gzip les fichiers `.jsonl` des heures passées (l'heure courante reste ouverte) ;
- **purge** les fichiers au-delà de la rétention, lue **par clé** (`api_keys.log_retention_days`,
  NULL → `REQUEST_LOG_RETENTION_DAYS`).

Aucune écriture ne doit jamais faire échouer une requête proxy : toute erreur d'E/S est avalée.
"""
import base64
import gzip
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, db

_SECRET_HEADERS = {"authorization", "x-api-key", "cookie"}
_HOUR_FMT = "%Y-%m-%d_%H"


def _base_dir() -> Path | None:
    return Path(config.REQUEST_LOG_DIR) if config.REQUEST_LOG_DIR else None


def _key_dirname(key_id: int | None) -> str:
    return f"key-{key_id}" if key_id is not None else "unauthenticated"


def _sanitize_headers(headers) -> dict:
    out = {}
    for k, v in dict(headers).items():
        out[k] = "«masqué»" if k.lower() in _SECRET_HEADERS else v
    return out


def _decode_body(body: bytes):
    if not body:
        return None
    try:
        return json.loads(body)  # JSON inline (lisible) quand c'est du JSON
    except (ValueError, UnicodeDecodeError):
        pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return {"_b64": base64.b64encode(body).decode("ascii")}


def record(*, key_id, ip, method, path, headers, body, status, model, ts=None) -> None:
    """Écrit une ligne de contenu complet pour une requête (best-effort ; ne lève jamais)."""
    base = _base_dir()
    if base is None:
        return
    try:
        now = ts or datetime.now(timezone.utc)
        d = base / _key_dirname(key_id)
        d.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": now.isoformat(timespec="seconds"),
            "ip": ip, "method": method, "path": path, "status": status, "model": model,
            "headers": _sanitize_headers(headers),
            "body": _decode_body(body if isinstance(body, (bytes, bytearray)) else b""),
        }
        line = json.dumps(rec, ensure_ascii=False)
        with open(d / f"{now.strftime(_HOUR_FMT)}.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# --- Cron : compaction (gzip) + purge (rétention par clé) --------------------------------------

def _file_hour(name: str) -> datetime | None:
    """Extrait l'heure (UTC) du nom de fichier `YYYY-MM-DD_HH.jsonl[.gz]`, ou None."""
    stem = name.split(".", 1)[0]
    try:
        return datetime.strptime(stem, _HOUR_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _retention_days_for(dirname: str) -> int | None:
    """Rétention (jours) pour un dossier `key-<id>` : valeur de la clé, sinon défaut global.

    Renvoie None pour « conserver indéfiniment » (jamais le cas ici : le défaut global est un
    entier), mais on garde le type pour la lisibilité de l'appelant.
    """
    default = config.REQUEST_LOG_RETENTION_DAYS
    if not dirname.startswith("key-"):
        return default
    try:
        key_id = int(dirname[len("key-"):])
    except ValueError:
        return default
    try:
        conn = db.connect()
    except sqlite3.Error:
        return default
    try:
        row = conn.execute(
            "SELECT log_retention_days FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    finally:
        conn.close()
    if row is None or row["log_retention_days"] is None:
        return default
    return int(row["log_retention_days"])


def compact_and_purge(now: datetime | None = None) -> dict:
    """Compacte (gzip) les heures passées et purge au-delà de la rétention par clé.

    Renvoie un récap `{compacted, purged}`. Idempotent ; sûr à relancer.
    """
    base = _base_dir()
    if base is None or not base.exists():
        return {"compacted": 0, "purged": 0}
    now = now or datetime.now(timezone.utc)
    cur_hour = now.strftime(_HOUR_FMT)
    compacted = purged = 0
    for key_dir in sorted(base.iterdir()):
        if not key_dir.is_dir():
            continue
        retention = _retention_days_for(key_dir.name)
        cutoff = now - timedelta(days=retention) if retention is not None else None
        for f in sorted(key_dir.iterdir()):
            if not f.is_file():
                continue
            hour = _file_hour(f.name)
            # Purge d'abord (supprime aussi les .gz trop vieux).
            if cutoff is not None and hour is not None and hour < cutoff:
                f.unlink()
                purged += 1
                continue
            # Compaction : gzip les .jsonl des heures passées (l'heure courante reste ouverte).
            if f.name.endswith(".jsonl") and f.name[:-len(".jsonl")] != cur_hour:
                gz = f.with_suffix(".jsonl.gz")
                with open(f, "rb") as src, gzip.open(gz, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                f.unlink()
                compacted += 1
    return {"compacted": compacted, "purged": purged}


if __name__ == "__main__":  # `python -m app.reqlog compact`
    if len(sys.argv) >= 2 and sys.argv[1] == "compact":
        db.init_db()
        result = compact_and_purge()
        print(f"reqlog compact: {result['compacted']} compacté(s), {result['purged']} purgé(s) "
              f"(dir={config.REQUEST_LOG_DIR or '—'})")
    else:
        print("usage: python -m app.reqlog compact")
        sys.exit(2)
