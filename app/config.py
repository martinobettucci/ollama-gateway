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

# Secret de signature des sessions admin (cookie). OBLIGATOIRE en prod ; défaut dev non secret.
ADMIN_SESSION_SECRET = os.environ.get("ADMIN_SESSION_SECRET", "dev-insecure-session-secret")

# Clé maître de chiffrement au repos (jetons d'auth des serveurs distants, cf. crypto.py).
# OBLIGATOIRE en prod ; défaut dev non secret. Changer cette clé rend les jetons stockés illisibles.
P2E_MASTER_KEY = os.environ.get("P2E_MASTER_KEY", "dev-insecure-master-key")

# Délai max d'un test de disponibilité d'un serveur d'exécution (GET /api/tags).
SERVER_PROBE_TIMEOUT_S = float(os.environ.get("SERVER_PROBE_TIMEOUT_S", "5"))

# Préfixe lisible des clés générées (compat OpenAI : Authorization: Bearer <clé>).
KEY_PREFIX = os.environ.get("KEY_PREFIX", "sk-ollama-")

# URL publique de la passerelle telle que vue par les CLIENTS (celle servie par Caddy),
# ex. https://passerelle.example.com — sans slash final. Sert à générer les variables
# d'environnement prêtes à copier dans la modale post-création de clé. Vide = l'admin
# affiche un placeholder à remplacer à la main.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

# Chemins amont explicitement proxifiables. Tout le reste → 404 (défense en profondeur ; Caddy
# filtre déjà, mais le proxy re-vérifie). Préfixes, pas exact-match.
ALLOWED_PATH_PREFIXES = ("/api/", "/v1/")

IS_PROD = APP_ENV == "prod"
