"""Journal de contenu sur fichiers : écriture (secrets strippés) + cron compaction/purge."""
import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import config, keys, reqlog

UTC = timezone.utc


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    d = tmp_path / "reqlogs"
    monkeypatch.setattr(config, "REQUEST_LOG_DIR", str(d))
    return d


def _write(key_id, ts, **kw):
    reqlog.record(key_id=key_id, ip=kw.get("ip", "1.2.3.4"), method="POST",
                  path=kw.get("path", "/api/chat"), headers=kw.get("headers", {}),
                  body=kw.get("body", b"{}"), status=200, model="demo:latest", ts=ts)


def test_record_writes_jsonl_and_strips_secrets(logdir):
    ts = datetime(2026, 7, 8, 14, 30, tzinfo=UTC)
    _write(3, ts, headers={"Authorization": "Bearer sk-secret", "Content-Type": "application/json"},
           body=b'{"model":"demo:latest"}')
    f = logdir / "key-3" / "2026-07-08_14.jsonl"
    assert f.exists()
    text = f.read_text(encoding="utf-8")
    rec = json.loads(text.strip())
    assert rec["ip"] == "1.2.3.4" and rec["status"] == 200
    assert rec["body"] == {"model": "demo:latest"}          # JSON inline
    assert rec["headers"]["Authorization"] == "«masqué»"    # secret retiré
    assert "sk-secret" not in text                          # aucune clé en clair au repos


def test_record_disabled_when_no_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "REQUEST_LOG_DIR", "")
    reqlog.record(key_id=1, ip="1.2.3.4", method="GET", path="/api/tags",
                  headers={}, body=b"", status=200, model="")  # ne lève pas
    assert not (tmp_path / "reqlogs").exists()


def test_compact_gzips_past_hours_keeps_current(logdir):
    now = datetime(2026, 7, 8, 15, 5, tzinfo=UTC)
    past = now - timedelta(hours=1)
    _write(1, past)
    _write(1, now)
    res = reqlog.compact_and_purge(now=now)
    assert res["compacted"] == 1
    kd = logdir / "key-1"
    assert (kd / "2026-07-08_14.jsonl.gz").exists()
    assert not (kd / "2026-07-08_14.jsonl").exists()
    assert (kd / "2026-07-08_15.jsonl").exists()            # heure courante intacte
    with gzip.open(kd / "2026-07-08_14.jsonl.gz", "rt", encoding="utf-8") as g:
        assert '"path": "/api/chat"' in g.read()


def test_purge_respects_per_key_retention(logdir):
    rec, _ = keys.create_key("k", [], None, None, log_retention_days=1)
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    _write(rec.id, now - timedelta(days=3))   # au-delà de la rétention → purgé
    _write(rec.id, now - timedelta(hours=2))  # dans la rétention, heure passée → compacté
    res = reqlog.compact_and_purge(now=now)
    assert res["purged"] == 1
    names = sorted(p.name for p in (logdir / f"key-{rec.id}").iterdir())
    assert not any(n.startswith("2026-07-05") for n in names)          # -3j purgé
    assert names == ["2026-07-08_10.jsonl.gz"]                          # -2h compacté


def test_global_default_retention_when_key_null(logdir, monkeypatch):
    monkeypatch.setattr(config, "REQUEST_LOG_RETENTION_DAYS", 2)
    rec, _ = keys.create_key("k", [], None, None)  # log_retention_days NULL → défaut global
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    _write(rec.id, now - timedelta(days=5))
    res = reqlog.compact_and_purge(now=now)
    assert res["purged"] == 1
    assert list((logdir / f"key-{rec.id}").iterdir()) == []
