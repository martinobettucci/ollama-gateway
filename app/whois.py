"""Résolution WHOIS d'une IP pour le panel (bouton « WHOIS » sur les origines d'une clé).

Utilise **RDAP over HTTPS** (`https://rdap.org/ip/<ip>`, remplaçant moderne du whois:43),
donc aucune dépendance binaire. Les adresses **privées/loopback/réservées** court-circuitent
sans appel réseau (déterministe et testable) : une origine LAN n'a pas de WHOIS public.
"""
import ipaddress

import httpx

_RDAP_URL = "https://rdap.org/ip/{}"
_TIMEOUT = 8.0


def _local_kind(addr) -> str | None:
    if addr.is_loopback:
        return "loopback"
    if addr.is_private:
        return "privée (RFC 1918 / ULA)"
    if addr.is_link_local:
        return "link-local"
    if addr.is_reserved or addr.is_multicast or addr.is_unspecified:
        return "réservée"
    return None


def _summarize(data: dict) -> tuple[str, dict]:
    """Extrait un résumé lisible + quelques champs d'un objet RDAP IP."""
    name = data.get("name") or ""
    country = data.get("country") or ""
    handle = data.get("handle") or ""
    org = ""
    for ent in data.get("entities", []) or []:
        for v in (ent.get("vcardArray") or [None, []])[1] or []:
            if isinstance(v, list) and len(v) >= 4 and v[0] == "fn":
                org = v[3]
                break
        if org:
            break
    cidr = ""
    for c in data.get("cidr0_cidrs", []) or []:
        pref = c.get("v4prefix") or c.get("v6prefix")
        if pref:
            cidr = f"{pref}/{c.get('length')}"
            break
    parts = [p for p in [name or handle, org, country] if p]
    summary = " · ".join(parts) if parts else "Aucune information RDAP."
    fields = {"name": name, "handle": handle, "org": org, "country": country, "cidr": cidr}
    return summary, {k: v for k, v in fields.items() if v}


async def lookup(ip: str) -> dict:
    """Renvoie `{ip, ok, kind, summary, fields}`. Ne lève jamais."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return {"ip": ip, "ok": False, "kind": "invalide",
                "summary": "IP invalide.", "fields": {}}
    local = _local_kind(addr)
    if local is not None:
        return {"ip": ip, "ok": True, "kind": "local",
                "summary": f"Adresse {local} — pas de WHOIS public.", "fields": {}}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
            r = await c.get(_RDAP_URL.format(ip),
                            headers={"Accept": "application/rdap+json"})
        if r.status_code != 200:
            return {"ip": ip, "ok": False, "kind": "public",
                    "summary": f"RDAP HTTP {r.status_code}.", "fields": {}}
        summary, fields = _summarize(r.json())
        return {"ip": ip, "ok": True, "kind": "public", "summary": summary, "fields": fields}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ip": ip, "ok": False, "kind": "public",
                "summary": f"WHOIS indisponible ({exc.__class__.__name__}).", "fields": {}}
