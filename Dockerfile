# Image de la passerelle (rôles proxy ET admin — sélection par $GATEWAY_ROLE dans l'entrypoint).
# Pur Python → multi-arch (build identique sur x86 de dev et aarch64 de la Jetson).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY db ./db
COPY devfixtures ./devfixtures
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh && mkdir -p /data

# /data : volume du fichier SQLite (partagé proxy/admin). Ports par défaut : proxy 8787, admin 8788.
ENTRYPOINT ["./entrypoint.sh"]
