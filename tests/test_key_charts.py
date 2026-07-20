"""Feature « graphes clé » : horizons, usage par modèle par clé, axes + étiquettes de valeur."""
from app import charts, keys, usage


def _seed(key_id: int, model: str, n: int, tokens: int) -> None:
    for _ in range(n):
        usage.record(key_id=key_id, client_ip="1.2.3.4", method="POST", path="/api/chat",
                     model=model, status=200, duration_ms=5, tokens_prompt=tokens,
                     tokens_completion=0)


def test_key_per_model_aggregates_by_model():
    rec, _ = keys.create_key("k", [], None, None)
    _seed(rec.id, "a:1b", 3, 10)
    _seed(rec.id, "b:2b", 1, 100)
    rows = usage.key_per_model(rec.id, "1m")
    by = {r["model"]: r for r in rows}
    assert by["a:1b"]["reqs"] == 3 and by["a:1b"]["tokens"] == 30
    assert by["b:2b"]["reqs"] == 1 and by["b:2b"]["tokens"] == 100
    assert [r["model"] for r in rows] == ["b:2b", "a:1b"]  # trié par tokens desc


def test_horizon_normalization():
    assert usage.horizon_or_default("bogus") == usage.DEFAULT_HORIZON
    assert usage.horizon_or_default(None) == usage.DEFAULT_HORIZON
    assert usage.horizon_or_default("24h") == "24h"
    assert set(usage.HORIZONS) == {"24h", "1w", "2w", "1m", "3m"}


def test_key_series_daily_and_hourly_buckets():
    rec, _ = keys.create_key("k", [], None, None)
    _seed(rec.id, "a:1b", 2, 5)
    daily = usage.key_series(rec.id, "1m")
    assert daily and daily[0]["reqs"] >= 1 and len(daily[0]["bucket"]) == 10  # 'YYYY-MM-DD'
    hourly = usage.key_series(rec.id, "24h")
    assert hourly and hourly[0]["bucket"].endswith(":00")  # bucket horaire


def test_line_chart_has_axes_and_hidden_value_labels():
    svg = charts.line([("07-01", 3), ("07-02", 8), ("07-03", 5)], "Req")
    assert 'class="pt-val"' in svg            # étiquettes de valeur (masquées par défaut)
    assert svg.count("<line ") >= 3           # lignes de repère de l'axe Y (0/milieu/max)
    assert 'text-anchor="end"' in svg         # libellés d'axe (Y + dernier X)
    assert 'text-anchor="start"' in svg       # premier libellé X
