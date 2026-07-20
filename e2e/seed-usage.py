"""Seed d'historique d'usage RÉTRO-DATÉ pour la clé démo (E2E).

Sans cela, l'usage E2E ne couvre que le jour courant : les graphes en courbe (qui exigent ≥ 2
buckets temporels) afficheraient « Aucune donnée ». On insère 15 jours d'événements sur deux
modèles pour que les captures du manuel montrent de vraies courbes (page clé + monitoring serveur).
Déterministe (seed fixe) → captures stables. N'affecte que la base E2E dédiée.
"""
import datetime
import os
import random
import sqlite3

db = os.environ["GATEWAY_DB_PATH"]
conn = sqlite3.connect(db)
try:
    kid = conn.execute("SELECT id FROM api_keys ORDER BY id LIMIT 1").fetchone()[0]
    sid = conn.execute("SELECT id FROM servers WHERE is_default = 1").fetchone()[0]
    rng = random.Random(42)
    now = datetime.datetime.utcnow()
    for d in range(15, -1, -1):
        day = now - datetime.timedelta(days=d)
        for model in ("demo:latest", "autre:latest"):
            for _ in range(rng.randint(2, 6)):
                ts = day.replace(hour=rng.randint(6, 22), minute=rng.randint(0, 59),
                                 second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO usage_events(key_id, client_ip, method, path, model, status, "
                    "duration_ms, tokens_prompt, tokens_completion, server_id, ts) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (kid, "203.0.113.9", "POST", "/api/chat", model, 200,
                     rng.randint(80, 900), rng.randint(30, 300), rng.randint(80, 700), sid, ts))
    conn.commit()
finally:
    conn.close()
