"""WHOIS/RDAP : court-circuit des adresses locales (déterministe) + résumé RDAP mocké."""
from app import whois


async def test_loopback_shortcircuit_no_network():
    r = await whois.lookup("127.0.0.1")
    assert r["ok"] and r["kind"] == "local" and "loopback" in r["summary"]


async def test_private_shortcircuit():
    r = await whois.lookup("192.168.1.5")
    assert r["ok"] and r["kind"] == "local" and "privée" in r["summary"]


async def test_invalid_ip():
    r = await whois.lookup("pas-une-ip")
    assert not r["ok"] and r["kind"] == "invalide"


async def test_public_ip_rdap_summary(monkeypatch):
    sample = {
        "name": "EXAMPLE-NET", "country": "US", "handle": "NET-1",
        "entities": [{"vcardArray": ["vcard", [["fn", {}, "text", "Example Org"]]]}],
        "cidr0_cidrs": [{"v4prefix": "8.8.8.0", "length": 24}],
    }

    class FakeResp:
        status_code = 200

        def json(self):
            return sample

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(whois.httpx, "AsyncClient", FakeClient)
    r = await whois.lookup("8.8.8.8")
    assert r["ok"] and r["kind"] == "public"
    assert "Example Org" in r["summary"] and "EXAMPLE-NET" in r["summary"]
    assert r["fields"]["country"] == "US" and r["fields"]["cidr"] == "8.8.8.0/24"


async def test_public_ip_rdap_http_error(monkeypatch):
    class FakeResp:
        status_code = 404

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(whois.httpx, "AsyncClient", FakeClient)
    r = await whois.lookup("8.8.8.8")
    assert not r["ok"] and "404" in r["summary"]
