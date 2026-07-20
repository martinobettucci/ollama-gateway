"""Livraison du secret d'une clé GÉNÉRÉE en mode déclaratif : e-mail (SMTP) ou webhook.

Une clé déclarative sans `value` est **générée** ; son secret n'est visible qu'une fois, à la
création. Sans WebUI pour le copier, il faut le **pousser** vers un canal choisi par l'opérateur —
c'est le rôle de ce module, appelé par `app/reconcile.py` juste après la génération, dans le même
passage de réconciliation.

Canaux :

- **e-mail** — `smtplib` (stdlib), TLS `none`/`starttls`/`tls`. La configuration SMTP vient du YAML
  (secrets par `${NOM}`). Le corps porte les **variables d'environnement valorisées** prêtes à
  coller (OLLAMA_HOST/OPENAI_BASE_URL/ANTHROPIC_BASE_URL + clé).
- **webhook** — `POST` httpx. **Template libre** OU **preset** (`slack`/`discord`/`generic`) pour
  s'adapter à la forme de charge utile de chaque service. Jetons substitués dans le template :
  `#OllamaKey` (secret), `#OllamaUrl` (URL publique), `#OllamaLabel` (libellé de la clé).

Best-effort : un canal en échec n'interrompt pas les autres ; l'erreur remonte au rapport de
réconciliation (le secret étant irrécupérable, l'opérateur devra faire tourner la clé pour relivrer).
"""
import json
import smtplib
import ssl
from email.message import EmailMessage

import httpx

_TIMEOUT_S = 15.0

# Presets webhook (chaîne JSON, jetons #Ollama* substitués). `generic` est construit par programme
# (il embarque tout le bloc d'environnement), les autres sont des gabarits texte.
WEBHOOK_PRESETS = {
    "slack": '{"text": ":key: Nouvelle clé Ollama Gateway — *#OllamaLabel*\\n'
             '`OLLAMA_HOST=#OllamaUrl`\\n`OLLAMA_API_KEY=#OllamaKey`"}',
    "discord": '{"content": ":key: Nouvelle clé Ollama Gateway — **#OllamaLabel**\\n'
               '`OLLAMA_HOST=#OllamaUrl`\\n`OLLAMA_API_KEY=#OllamaKey`"}',
    "generic": None,  # payload construit dynamiquement (cf. _webhook_body)
}


def client_env(base_url: str, secret: str) -> dict[str, str]:
    """Variables d'environnement valorisées prêtes à coller côté client (miroir serveur du bloc
    généré par la modale « configurer le client » du panel)."""
    return {
        "OLLAMA_HOST": base_url, "OLLAMA_API_KEY": secret,
        "OPENAI_BASE_URL": base_url + "/v1", "OPENAI_API_KEY": secret,
        "ANTHROPIC_BASE_URL": base_url, "ANTHROPIC_API_KEY": secret,
    }


def _render(tpl: str, *, label: str, secret: str, url: str) -> str:
    return (tpl.replace("#OllamaKey", secret)
               .replace("#OllamaUrl", url)
               .replace("#OllamaLabel", label))


def _webhook_body(webhook: dict, *, label: str, secret: str, url: str) -> str:
    template = webhook.get("template")
    if template:
        return _render(template, label=label, secret=secret, url=url)
    preset = webhook.get("preset", "generic")
    if preset == "generic":
        return json.dumps({"label": label, "key": secret, "url": url,
                           "env": client_env(url, secret)})
    return _render(WEBHOOK_PRESETS[preset], label=label, secret=secret, url=url)


def send_webhook(webhook: dict, *, label: str, secret: str, url: str) -> None:
    body = _webhook_body(webhook, label=label, secret=secret, url=url)
    headers = {"Content-Type": "application/json", **(webhook.get("headers") or {})}
    method = (webhook.get("method") or "POST").upper()
    with httpx.Client(timeout=_TIMEOUT_S) as c:
        r = c.request(method, webhook["url"], content=body.encode("utf-8"), headers=headers)
    r.raise_for_status()


def send_email(smtp: dict, to: str, *, label: str, secret: str, url: str) -> None:
    env = client_env(url, secret)
    body = ("Une nouvelle clé API a été provisionnée pour « " + label + " ».\n\n"
            "Variables d'environnement à configurer côté client :\n\n"
            + "\n".join(f"{k}={v}" for k, v in env.items())
            + "\n\nConservez ce secret en lieu sûr : il n'est affiché qu'une seule fois.\n")
    msg = EmailMessage()
    msg["Subject"] = f"Votre clé Ollama Gateway — {label}"
    msg["From"] = smtp["from"]
    msg["To"] = to
    msg.set_content(body)

    tls = smtp.get("tls", "starttls")
    host, port = smtp["host"], int(smtp["port"])
    if tls == "tls":
        client = smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT_S,
                                  context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=_TIMEOUT_S)
    with client:
        if tls == "starttls":
            client.starttls(context=ssl.create_default_context())
        if smtp.get("username"):
            client.login(smtp["username"], smtp.get("password", ""))
        client.send_message(msg)


def deliver_key(channels: list[dict], smtp: dict | None, *,
                label: str, secret: str, url: str) -> list[str]:
    """Livre `secret` sur chaque canal. Renvoie la liste des erreurs (vide = tout est passé).
    Best-effort : un canal en échec n'empêche pas les suivants."""
    errors: list[str] = []
    for ch in channels:
        try:
            if "email" in ch:
                send_email(smtp or {}, ch["email"]["to"], label=label, secret=secret, url=url)
            elif "webhook" in ch:
                send_webhook(ch["webhook"], label=label, secret=secret, url=url)
        except Exception as exc:  # noqa: BLE001 — best-effort, on rapporte sans interrompre
            errors.append(f"{exc.__class__.__name__}: {exc}")
    return errors
