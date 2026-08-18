"""Vue « temps réel » du tableau de bord (`usage.realtime_2h` + `GET /admin/realtime`).

Livrée sans aucun test, cette unité était **cassée en production** : la requête sélectionnait une
colonne `api_family` inexistante → `sqlite3.OperationalError`, donc HTTP 500 à chaque appel. Ces
tests verrouillent le contrat effectivement consommé par l'écran (`app/templates/dashboard.html`) :
tranches calées, libellé de clé présent, nom **et** type de modèle par entrée.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import db, keys, usage
from tests.conftest import admin_client  # noqa: F401 (fixture)

PW = "admin-mdp"


def _event(key_id, model, when=None, status=200):
    """Insère un événement d'usage daté (UTC), comme le ferait le proxy."""
    ts = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO usage_events(key_id, ts, client_ip, method, path, model, status, "
            "duration_ms) VALUES (?,?,?,?,?,?,?,?)",
            (key_id, ts, "203.0.113.9", "POST", "/api/chat", model, status, 5))
        conn.commit()
    finally:
        conn.close()


# --- Non-régression du crash --------------------------------------------------------------------

def test_realtime_does_not_crash_on_missing_column():
    """Régression directe : la requête ne doit référencer aucune colonne absente du schéma."""
    rec, _ = keys.create_key("k", [], None, None)
    _event(rec.id, "demo:latest")
    assert usage.realtime_2h()  # levait sqlite3.OperationalError: no such column: api_family


async def test_admin_realtime_endpoint_returns_200(admin_client):  # noqa: F811
    """L'écran appelait `/admin/realtime` toutes les 30 s et recevait 500."""
    keys.set_admin_password(PW)
    rec, _ = keys.create_key("k", [], None, None)
    _event(rec.id, "demo:latest")
    async with admin_client as c:
        await c.post("/admin/login", data={"password": PW})
        r = await c.get("/admin/realtime")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --- Contrat consommé par l'écran ---------------------------------------------------------------

def test_entry_carries_label_model_type_and_colour():
    """`dashboard.html` lit `k.label` (infobulle + légende) et filtre sur `m.model` : les deux
    doivent exister, sans quoi l'écran affiche « undefined » et le filtre ne matche jamais."""
    rec, _ = keys.create_key("ma-clé", [], None, None)
    _event(rec.id, "demo:latest")
    bucket = usage.realtime_2h()[0]
    entry = bucket["keys"][0]
    assert entry["key_id"] == rec.id
    assert entry["label"] == "ma-clé"
    assert "prefix" in entry
    m = entry["models"][0]
    assert m["model"] == "demo:latest"
    assert m["type"] == "text"
    assert m["color"] == usage.type_color("text")
    assert m["count"] == 1


def test_deleted_key_gets_fallback_label_never_none():
    """Clé supprimée depuis : `usage_events.key_id` est `ON DELETE SET NULL`, l'événement survit
    sans clé. Le libellé doit rester lisible — jamais `None`, jamais « clé #None »."""
    rec, _ = keys.create_key("éphémère", [], None, None)
    _event(rec.id, "demo:latest")
    conn = db.connect()
    try:
        conn.execute("DELETE FROM api_keys WHERE id = ?", (rec.id,))
        conn.commit()
    finally:
        conn.close()
    entry = usage.realtime_2h()[0]["keys"][0]
    assert entry["label"] == "clé supprimée"
    assert "None" not in entry["label"]


@pytest.mark.parametrize("model, expected", [
    ("demo:latest", "text"),
    ("x/fakeflux:1b", "image"),          # namespace image d'Ollama
    ("some-image-model", "image"),
    ("llava-vision:7b", "vision"),
    ("qwen-vlm:3b", "vision"),
])
def test_model_type_from_name(model, expected):
    """Aucun type n'est stocké en base : il est déduit du NOM du modèle."""
    assert usage.model_type(model) == expected


# --- Calage des tranches ------------------------------------------------------------------------

def test_events_in_same_quarter_share_one_bucket():
    rec, _ = keys.create_key("k", [], None, None)
    now = datetime.now(timezone.utc).replace(minute=7, second=0, microsecond=0)
    _event(rec.id, "demo:latest", now)
    _event(rec.id, "demo:latest", now + timedelta(minutes=5))   # même quart (0-14)
    data = usage.realtime_2h()
    assert len(data) == 1, [b["ts"] for b in data]
    assert data[0]["ts"].endswith(":00")                        # minute calée sur la tranche
    assert data[0]["keys"][0]["models"][0]["count"] == 2


def test_events_in_different_quarters_are_separate_buckets():
    rec, _ = keys.create_key("k", [], None, None)
    now = datetime.now(timezone.utc).replace(minute=5, second=0, microsecond=0)
    _event(rec.id, "demo:latest", now)
    _event(rec.id, "demo:latest", now + timedelta(minutes=20))  # quart suivant
    data = usage.realtime_2h()
    assert len(data) == 2
    assert [b["ts"][-2:] for b in data] == ["00", "15"]


def test_bucket_minutes_always_land_on_the_scale():
    """Toutes les tranches tombent sur un multiple de la largeur (00/15/30/45), jamais entre."""
    rec, _ = keys.create_key("k", [], None, None)
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for minute in (1, 14, 16, 29, 31, 44, 46, 59):
        _event(rec.id, "demo:latest", base + timedelta(minutes=minute))
    allowed = {f"{m:02d}" for m in range(0, 60, usage.REALTIME_BUCKET_MIN)}
    assert {b["ts"][-2:] for b in usage.realtime_2h()} <= allowed


def test_events_older_than_2h_excluded():
    rec, _ = keys.create_key("k", [], None, None)
    _event(rec.id, "vieux:latest", datetime.now(timezone.utc) - timedelta(hours=3))
    _event(rec.id, "demo:latest")
    models = {m["model"] for b in usage.realtime_2h() for k in b["keys"] for m in k["models"]}
    assert models == {"demo:latest"}


def test_events_without_model_excluded():
    """Les refus (401/403 sans modèle) ne doivent pas peupler l'histogramme."""
    rec, _ = keys.create_key("k", [], None, None)
    _event(rec.id, "", status=401)
    assert usage.realtime_2h() == []


def test_several_keys_and_models_are_grouped_separately():
    a, _ = keys.create_key("clé-A", [], None, None)
    b, _ = keys.create_key("clé-B", [], None, None)
    _event(a.id, "demo:latest")
    _event(a.id, "x/fakeflux:1b")
    _event(b.id, "demo:latest")
    bucket = usage.realtime_2h()[-1]
    by_label = {k["label"]: k for k in bucket["keys"]}
    assert set(by_label) == {"clé-A", "clé-B"}
    assert {m["type"] for m in by_label["clé-A"]["models"]} == {"text", "image"}
    assert len(by_label["clé-B"]["models"]) == 1


def test_empty_when_no_activity():
    assert usage.realtime_2h() == []
