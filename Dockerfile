# Image de la passerelle (rôles proxy ET admin — sélection par $GATEWAY_ROLE dans l'entrypoint).
# Pur Python → multi-arch (build identique sur x86 de dev et ARM64 de l'hôte self-hosted).
# Base épinglée par DIGEST (intégrité/reproductibilité supply-chain). Le digest est celui de la
# LISTE de manifestes `python:3.12-slim` (multi-arch : Docker résout amd64/arm64 depuis la liste).
# Rafraîchir périodiquement (nouvelle CVE base) : docker-content-digest de `python:3.12-slim`.
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY db ./db
COPY devfixtures ./devfixtures
COPY docs ./docs
COPY entrypoint.sh .
# Utilisateur non-root (défense en profondeur, d'autant que la prod tourne en network_mode: host).
# Il possède /data (volume SQLite + reqlogs) et /app. Les ports par défaut (>1024) sont bindables
# sans privilège. NB : un volume /data PRÉEXISTANT créé en root doit être `chown`é une fois vers
# cet UID lors de la bascule (cf. docs/DAT.md).
RUN chmod +x entrypoint.sh && mkdir -p /data \
    && groupadd -r app && useradd -r -g app -d /app app \
    && chown -R app:app /data /app
USER app

# /data : volume du fichier SQLite (partagé proxy/admin). Ports par défaut : proxy 8787, admin 8788.
ENTRYPOINT ["./entrypoint.sh"]
