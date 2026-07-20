#!/bin/sh
# Point d'entrée commun : migrations + amorçage, puis lancement du rôle demandé.
set -e

python -m app.bootstrap init
python -m app.bootstrap ensure-admin || true
if [ "${APP_ENV:-dev}" = "dev" ]; then
    python -m app.bootstrap seed-dev || true
fi

# Mode DÉCLARATIF (headless) : si GATEWAY_CONFIG pointe vers un YAML, on réconcilie l'état
# (serveurs/cibles/clés) AVANT uvicorn — équivalent des migrations, mais pour la configuration
# métier. Sérialisé par verrou fichier ; idempotent. Absent → mode UI classique (YAML ignoré).
if [ -n "${GATEWAY_CONFIG:-}" ]; then
    if [ -f "${GATEWAY_CONFIG}" ]; then
        python -m app.reconcile apply "${GATEWAY_CONFIG}"
    else
        echo "GATEWAY_CONFIG=${GATEWAY_CONFIG} : fichier introuvable" >&2
        exit 2
    fi
fi

case "${GATEWAY_ROLE:-proxy}" in
  proxy)
    exec uvicorn app.proxy:app --host "${PROXY_HOST:-127.0.0.1}" --port "${PROXY_PORT:-8787}" \
         --timeout-keep-alive 75 --no-access-log
    ;;
  admin)
    exec uvicorn app.admin:app --host "${ADMIN_HOST:-0.0.0.0}" --port "${ADMIN_PORT:-8788}"
    ;;
  *)
    echo "GATEWAY_ROLE inconnu: ${GATEWAY_ROLE}" >&2
    exit 2
    ;;
esac
