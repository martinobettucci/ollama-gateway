#!/bin/sh
# Point d'entrée commun : migrations + amorçage, puis lancement du rôle demandé.
set -e

python -m app.bootstrap init
python -m app.bootstrap ensure-admin || true
if [ "${APP_ENV:-dev}" = "dev" ]; then
    python -m app.bootstrap seed-dev || true
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
