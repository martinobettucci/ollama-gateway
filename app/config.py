"""Configuration centrale de la passerelle (lecture d'environnement uniquement).

Aucun secret en dur : tout vient de l'environnement. Les valeurs par défaut visent le mode
`dev` self-contained (SQLite jetable, faux upstream Ollama). En staging/prod, chaque variable
est posée dans un `.env` dédié (cf. .env.example) et commentée.
"""
import os

APP_ENV = os.environ.get("APP_ENV", "dev")  # dev | staging | prod

# Rôle du process ASGI lancé par l'entrypoint : "proxy" (exposé via Caddy) ou "admin" (LAN-only).
GATEWAY_ROLE = os.environ.get("GATEWAY_ROLE", "proxy")

# Fichier SQLite partagé par les deux rôles (montage volume en conteneur). WAL activé (cf. db.py).
DB_PATH = os.environ.get("GATEWAY_DB_PATH", "/data/gateway.db")

# Upstream Ollama réel (prod : http://127.0.0.1:11434 ; dev : le faux upstream seedé).
OLLAMA_UPSTREAM = os.environ.get("OLLAMA_UPSTREAM", "http://127.0.0.1:11434").rstrip("/")

# Délai max d'un appel amont (inférence longue / streaming). Aligne le comportement nginx (3600s).
UPSTREAM_TIMEOUT_S = float(os.environ.get("UPSTREAM_TIMEOUT_S", "3600"))

# Binds. Le proxy n'écoute qu'en loopback (seul Caddy l'atteint) ; l'admin sur l'IP LAN.
PROXY_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8787"))
ADMIN_HOST = os.environ.get("ADMIN_HOST", "0.0.0.0")
ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "8788"))

# IP autorisées à poser un X-Forwarded-For de confiance (Caddy en loopback). Le proxy ne fait
# confiance au XFF QUE si le pair immédiat est dans cette liste, sinon il prend l'IP du pair.
TRUSTED_PROXY_IPS = {
    ip.strip() for ip in os.environ.get("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",") if ip.strip()
}

# Défauts dev NON SECRETS (publics dans le dépôt) : refusés en prod par `check_runtime_secrets`.
DEV_SESSION_SECRET = "dev-insecure-session-secret"
DEV_MASTER_KEY = "dev-insecure-master-key"

# Secret de signature des sessions admin (cookie). OBLIGATOIRE en prod ; défaut dev non secret.
ADMIN_SESSION_SECRET = os.environ.get("ADMIN_SESSION_SECRET", DEV_SESSION_SECRET)

# Clé maître de chiffrement au repos (jetons d'auth des serveurs distants, cf. crypto.py).
# OBLIGATOIRE en prod ; défaut dev non secret. Changer cette clé rend les jetons stockés illisibles.
P2E_MASTER_KEY = os.environ.get("P2E_MASTER_KEY", DEV_MASTER_KEY)

# Délai max d'un test de disponibilité d'un serveur d'exécution (GET /api/tags).
SERVER_PROBE_TIMEOUT_S = float(os.environ.get("SERVER_PROBE_TIMEOUT_S", "5"))

# Préfixe lisible des clés générées (compat OpenAI : Authorization: Bearer <clé>).
KEY_PREFIX = os.environ.get("KEY_PREFIX", "sk-ollama-")

# URL publique de la passerelle telle que vue par les CLIENTS (celle servie par Caddy),
# ex. https://passerelle.example.com — sans slash final. Sert à générer les variables
# d'environnement prêtes à copier dans la modale post-création de clé. Vide = l'admin
# affiche un placeholder à remplacer à la main.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

# Journal de CONTENU complet des requêtes, sur le SYSTÈME DE FICHIERS (jamais en base) : un
# dossier par clé, un fichier JSONL par heure. Vide = journalisation de contenu désactivée.
# Rétention globale par défaut (jours), surchargée par clé (`api_keys.log_retention_days`).
# Le cron `python -m app.reqlog compact` gzip les heures passées et purge au-delà de la rétention.
REQUEST_LOG_DIR = os.environ.get("REQUEST_LOG_DIR", "").rstrip("/")
REQUEST_LOG_RETENTION_DAYS = int(os.environ.get("REQUEST_LOG_RETENTION_DAYS", "30"))

# Chemins amont explicitement proxifiables. Tout le reste → 404 (défense en profondeur ; Caddy
# filtre déjà, mais le proxy re-vérifie). Préfixes, pas exact-match.
ALLOWED_PATH_PREFIXES = ("/api/", "/v1/")

# Taille max d'un corps de requête proxifié (octets). Défense en profondeur anti-DoS mémoire
# (le corps est bufferisé pour appliquer la restriction de modèle). Généreux par défaut (100 Mio)
# pour l'image-to-image (base64) ; 0 = illimité. Caddy peut aussi borner en amont (`request_body`).
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", str(100 * 1024 * 1024)))

IS_PROD = APP_ENV == "prod"


def check_runtime_secrets() -> None:
    """Fail-closed en prod : refuse de démarrer si un secret critique est absent ou laissé au
    défaut dev (ces défauts sont publics dans le dépôt open-source). Sans ce garde-fou, une prod
    mal configurée signerait ses sessions admin avec un secret connu de tous → forge du cookie
    `{"admin": true}` et prise de contrôle du panel. No-op hors prod (dev/staging self-contained).

    Appelé au démarrage (`bootstrap init`, avant uvicorn) et dans le lifespan des deux rôles.
    """
    if not IS_PROD:
        return
    missing = []
    if ADMIN_SESSION_SECRET in ("", DEV_SESSION_SECRET):
        missing.append("ADMIN_SESSION_SECRET")
    if P2E_MASTER_KEY in ("", DEV_MASTER_KEY):
        missing.append("P2E_MASTER_KEY")
    if missing:
        raise RuntimeError(
            "Secret(s) de production absent(s) ou laissé(s) au défaut dev (publics) : "
            + ", ".join(missing)
            + ". Renseignez-les dans .env.prod (ex. `openssl rand -hex 32`) avant de démarrer.")
