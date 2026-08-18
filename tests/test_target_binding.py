"""Contrôle de la CIBLE (« passerelle ») rattachée à une clé.

Une clé émise pour une passerelle ne doit servir **que** par cette passerelle : le proxy compare
l'hôte (et le port) par lequel la requête est réellement arrivée à l'URL de la cible rattachée, et
refuse 403 sinon. Avant cette unité, `target_id` n'était qu'un libellé documentaire — n'importe
quelle URL menant au proxy servait n'importe quelle clé.

Deux niveaux : la fonction de correspondance pure (`targets.host_allowed`) et le comportement
bout-en-bout du proxy (en-têtes `Host` / `X-Forwarded-Host`, pair de confiance ou non).
"""
import pytest

from app import config, keys, targets
from tests.conftest import proxy_client

PUB = "https://passerelle.example.com:21434"


def _auth(key):
    return {"authorization": f"Bearer {key}"}


def _key_on(base_url: str):
    """Crée une clé rattachée à une cible portant `base_url`."""
    tgt = targets.create_target("cible", base_url)
    rec, secret = keys.create_key("k", [], None, None, target_id=tgt.id)
    return rec, secret


# --- Correspondance pure ------------------------------------------------------------------------

@pytest.mark.parametrize("base_url, host, proto, expected", [
    # Correspondance exacte (port explicite des deux côtés).
    (PUB, "passerelle.example.com:21434", "https", True),
    # Port implicite : `Host` sans port + https → 443, doit matcher une cible en :443.
    ("https://passerelle.example.com", "passerelle.example.com", "https", True),
    ("https://passerelle.example.com:443", "passerelle.example.com", "https", True),
    ("https://passerelle.example.com", "passerelle.example.com:443", "https", True),
    # Casse de l'hôte indifférente.
    (PUB, "PASSERELLE.EXAMPLE.COM:21434", "https", True),
    # PORT différent = passerelle différente (cas réel : edge LAN :11435 vs public :21434).
    (PUB, "passerelle.example.com:11435", "https", False),
    # Hôte différent (rejeu de la clé via une autre passerelle menant au même amont).
    (PUB, "autre.example.com:21434", "https", False),
    # Accès par IP alors que la cible est un nom de domaine.
    (PUB, "192.0.2.10:21434", "https", False),
    # Hôte absent → refus dès lors que la cible est exploitable.
    (PUB, "", "https", False),
    # Schéma implicite : http sans port → 80, ne matche pas une cible https:443.
    ("https://passerelle.example.com", "passerelle.example.com", "http", False),
    ("http://passerelle.example.com", "passerelle.example.com", "http", True),
    # IPv6 entre crochets.
    ("https://[2001:db8::1]:8443", "[2001:db8::1]:8443", "https", True),
    ("https://[2001:db8::1]:8443", "[2001:db8::1]:9999", "https", False),
])
def test_host_allowed_matching(base_url, host, proto, expected):
    assert targets.host_allowed(base_url, host, proto) is expected


@pytest.mark.parametrize("base_url", [None, "", targets.PLACEHOLDER_URL, "pas-une-url::"])
def test_host_allowed_permissive_without_usable_target(base_url):
    """Permissif par ABSENCE de contrainte (pas par échec de comparaison) : sans cible exploitable
    on ne coupe pas le service — une configuration incomplète ne doit pas verrouiller la prod."""
    assert targets.host_allowed(base_url, "n-importe.example.com") is True


# --- Bout en bout via le proxy ------------------------------------------------------------------

async def test_request_through_attached_target_passes(fake_upstream):
    _, key = _key_on(PUB)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers={**_auth(key), "host": "passerelle.example.com:21434"},
                         json={"model": "demo:latest"})
    assert r.status_code == 200


async def test_request_through_other_target_refused_403(fake_upstream):
    """Le cœur de l'unité : même clé, même amont, autre passerelle → refus."""
    _, key = _key_on(PUB)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers={**_auth(key), "host": "autre.example.com:21434"},
                         json={"model": "demo:latest"})
    assert r.status_code == 403 and "passerelle" in r.text


async def test_same_host_wrong_port_refused_403(fake_upstream):
    """Cas concret : la clé est émise pour la passerelle publique (:21434) et la requête arrive par
    l'edge LAN (:11435). Deux passerelles distinctes → refus."""
    _, key = _key_on(PUB)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers={**_auth(key), "host": "passerelle.example.com:11435"},
                         json={"model": "demo:latest"})
    assert r.status_code == 403


async def test_key_without_target_is_unconstrained(fake_upstream):
    """Une clé sans cible exploitable (placeholder) reste servie quelle que soit l'URL."""
    _, key = keys.create_key("libre", [], None, None)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers={**_auth(key), "host": "n-importe.example.com"},
                         json={"model": "demo:latest"})
    assert r.status_code == 200


async def test_refusal_is_logged_as_403(fake_upstream):
    from app import db
    _, key = _key_on(PUB)
    async with proxy_client(fake_upstream) as c:
        await c.post("/api/chat", headers={**_auth(key), "host": "autre.example.com:21434"},
                     json={"model": "demo:latest"})
    conn = db.connect()
    try:
        rows = conn.execute("SELECT status FROM usage_events ORDER BY id").fetchall()
    finally:
        conn.close()
    assert rows and rows[-1]["status"] == 403


# --- Anti-usurpation : X-Forwarded-Host n'est cru que derrière un pair de confiance --------------

async def test_x_forwarded_host_honoured_from_trusted_peer(fake_upstream):
    """Derrière Caddy (pair de confiance), c'est `X-Forwarded-Host` qui fait foi : c'est l'hôte
    réellement demandé par le client, le `Host` pouvant avoir été réécrit par l'edge."""
    _, key = _key_on(PUB)
    async with proxy_client(fake_upstream, source_ip="127.0.0.1") as c:
        r = await c.post("/api/chat",
                         headers={**_auth(key), "host": "127.0.0.1:8787",
                                  "x-forwarded-host": "passerelle.example.com:21434",
                                  "x-forwarded-proto": "https"},
                         json={"model": "demo:latest"})
    assert r.status_code == 200


async def test_x_forwarded_host_ignored_from_untrusted_peer(fake_upstream):
    """Un client NON de confiance ne peut pas se déclarer arrivé par la bonne passerelle : son
    `X-Forwarded-Host` est ignoré, seul son vrai `Host` compte → refus."""
    _, key = _key_on(PUB)
    async with proxy_client(fake_upstream, source_ip="203.0.113.9") as c:
        r = await c.post("/api/chat",
                         headers={**_auth(key), "host": "autre.example.com",
                                  "x-forwarded-host": "passerelle.example.com:21434"},
                         json={"model": "demo:latest"})
    assert r.status_code == 403


async def test_trusted_peer_without_forwarded_host_falls_back_to_host(fake_upstream):
    _, key = _key_on(PUB)
    async with proxy_client(fake_upstream, source_ip="127.0.0.1") as c:
        r = await c.post("/api/chat",
                         headers={**_auth(key), "host": "passerelle.example.com:21434"},
                         json={"model": "demo:latest"})
    assert r.status_code == 200


async def test_placeholder_target_still_unconstrained_end_to_end(fake_upstream, monkeypatch):
    """`PUBLIC_BASE_URL` non configurée → cible au placeholder → aucune contrainte (sinon toute
    installation neuve serait verrouillée dès la première requête)."""
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    _, key = _key_on(targets.PLACEHOLDER_URL)
    async with proxy_client(fake_upstream, source_ip="127.0.0.1") as c:
        r = await c.post("/api/chat", headers={**_auth(key), "host": "quoi.example.com"},
                         json={"model": "demo:latest"})
    assert r.status_code == 200
