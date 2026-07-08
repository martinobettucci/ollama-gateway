"""Accès SQLite : connexions courtes (WAL), application idempotente des migrations.

WAL permet un writer + plusieurs readers concurrents → le proxy journalise l'usage pendant que
l'admin lit, sans blocage notable à notre échelle. `foreign_keys=ON` pour les CASCADE.
"""
import fcntl
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

# Répertoire des migrations : db/migrations/*.sql, appliquées par ordre alphabétique.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


@contextmanager
def file_lock(suffix: str = "migrate", db_path: str | None = None):
    """Verrou fichier inter-process (`flock`) partagé via le volume : sérialise une section
    critique entre les rôles proxy/admin qui démarrent en parallèle sur le même SQLite.
    Utilisé pour les migrations ET les reconcilers check-then-write (ex. `ensure_default`)."""
    path = db_path or config.DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(f"{path}.{suffix}.lock", "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Nouvelle connexion configurée (WAL, FK, row factory). À fermer par l'appelant."""
    path = db_path or config.DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # busy_timeout AVANT journal_mode : passer en WAL prend un verrou d'écriture bref ; si un autre
    # process (rôle proxy/admin démarrant en parallèle) tient la base, on doit attendre, pas échouer.
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )


def apply_migrations(db_path: str | None = None) -> list[str]:
    """Applique toutes les migrations non encore appliquées. Renvoie la liste des versions posées.

    Idempotent ET concurrent-safe : les rôles proxy/admin démarrent en parallèle sur le même
    fichier SQLite. Un verrou fichier (`flock`, partagé via le volume) sérialise l'application ;
    le second process attend, relit `schema_migrations` et ne réapplique rien.
    """
    path = db_path or config.DB_PATH
    with file_lock("migrate", path):
        return _apply_migrations_locked(path)


def _apply_migrations_locked(db_path: str) -> list[str]:
    conn = connect(db_path)
    applied: list[str] = []
    try:
        _ensure_migrations_table(conn)
        seen = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = sql_file.name
            if version in seen:
                continue
            sql = sql_file.read_text(encoding="utf-8")
            with conn:  # transaction
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
            applied.append(version)
    finally:
        conn.close()
    return applied


def init_db(db_path: str | None = None) -> None:
    """Crée le fichier et applique les migrations (appelé au démarrage de chaque rôle)."""
    apply_migrations(db_path)
