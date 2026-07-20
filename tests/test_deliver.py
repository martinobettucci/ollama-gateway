"""Tests de la livraison du secret (app/deliver.py) : env valorisé, presets/template webhook,
dialogue SMTP (smtplib monkeypatché), best-effort multi-canal."""
import json

import pytest

from app import deliver


def test_client_env_mapping():
    env = deliver.client_env("https://gw.example:8443", "sk-secret")
    assert env["OLLAMA_HOST"] == "https://gw.example:8443"
    assert env["OPENAI_BASE_URL"] == "https://gw.example:8443/v1"
    assert env["OLLAMA_API_KEY"] == "sk-secret" and env["ANTHROPIC_API_KEY"] == "sk-secret"


def test_webhook_body_slack_substitutes_tokens():
    body = deliver._webhook_body({"preset": "slack"}, label="ACME",
                                 secret="sk-xyz", url="https://gw:8443")
    payload = json.loads(body)
    assert "ACME" in payload["text"] and "sk-xyz" in payload["text"]
    assert "https://gw:8443" in payload["text"]


def test_webhook_body_generic_embeds_env():
    body = deliver._webhook_body({"preset": "generic"}, label="ACME",
                                 secret="sk-xyz", url="https://gw:8443")
    payload = json.loads(body)
    assert payload["key"] == "sk-xyz" and payload["url"] == "https://gw:8443"
    assert payload["env"]["OPENAI_BASE_URL"] == "https://gw:8443/v1"


def test_webhook_body_custom_template():
    body = deliver._webhook_body(
        {"template": '{"msg": "clé #OllamaKey sur #OllamaUrl (#OllamaLabel)"}'},
        label="ACME", secret="sk-xyz", url="https://gw:8443")
    assert json.loads(body)["msg"] == "clé sk-xyz sur https://gw:8443 (ACME)"


class _FakeResp:
    def raise_for_status(self):
        return None


def test_send_webhook_posts_rendered_body(monkeypatch):
    seen = {}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def request(self, method, url, content=None, headers=None):
            seen.update(method=method, url=url, content=content, headers=headers)
            return _FakeResp()

    monkeypatch.setattr(deliver.httpx, "Client", _FakeClient)
    deliver.send_webhook({"url": "http://hook.local/x", "preset": "discord"},
                         label="ACME", secret="sk-xyz", url="https://gw:8443")
    assert seen["method"] == "POST" and seen["url"] == "http://hook.local/x"
    assert seen["headers"]["Content-Type"] == "application/json"
    assert b"sk-xyz" in seen["content"]


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, pwd):
        self.logged_in = (user, pwd)

    def send_message(self, msg):
        self.sent = msg


def test_send_email_starttls_and_content(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(deliver.smtplib, "SMTP", _FakeSMTP)
    smtp = {"host": "mail.local", "port": 2500, "from": "gw@local",
            "tls": "starttls", "username": "u", "password": "p"}
    deliver.send_email(smtp, "ops@acme.example", label="ACME",
                       secret="sk-xyz", url="https://gw:8443")
    inst = _FakeSMTP.instances[-1]
    assert inst.started_tls and inst.logged_in == ("u", "p")
    assert inst.sent["To"] == "ops@acme.example" and "ACME" in inst.sent["Subject"]
    body = inst.sent.get_content()
    assert "OLLAMA_API_KEY=sk-xyz" in body and "OPENAI_BASE_URL=https://gw:8443/v1" in body


def test_send_email_tls_none_no_starttls(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(deliver.smtplib, "SMTP", _FakeSMTP)
    smtp = {"host": "mail.local", "port": 2500, "from": "gw@local", "tls": "none"}
    deliver.send_email(smtp, "ops@acme.example", label="ACME", secret="s", url="https://gw")
    inst = _FakeSMTP.instances[-1]
    assert inst.started_tls is False and inst.logged_in is None


def test_deliver_key_best_effort_collects_errors(monkeypatch):
    calls = []

    def _ok_email(smtp, to, **kw):
        calls.append(("email", to))

    def _boom_webhook(wh, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(deliver, "send_email", _ok_email)
    monkeypatch.setattr(deliver, "send_webhook", _boom_webhook)
    errors = deliver.deliver_key(
        [{"email": {"to": "a@b.c"}}, {"webhook": {"url": "http://x"}}],
        {"host": "m", "port": 25, "from": "f"}, label="L", secret="s", url="u")
    assert ("email", "a@b.c") in calls          # le 1er canal est passé
    assert len(errors) == 1 and "boom" in errors[0]  # le 2e a échoué sans interrompre
