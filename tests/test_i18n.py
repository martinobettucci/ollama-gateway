"""i18n : complétude des 24 locales UE, préservation des {placeholders} et du code `mono`
(noms de variables d'env, chemins), comportement de `translate()` (repli fr → clé, interpolation),
route de bascule de langue (`POST /admin/lang`) et négociation `Accept-Language`.

Règle « chaque tâche a SES tests » : ces tests sont propres à l'unité i18n (fichiers YAML par
langue + sélecteur de langue du panel)."""
import re

from app import i18n, keys
from tests.conftest import admin_client  # noqa: F401 (fixture)

PW = "admin-mdp"
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
MONO = re.compile(r'<span class="mono">(.*?)</span>')
STRONG = re.compile(r"<strong>")


async def _login(c):
    keys.set_admin_password(PW)
    await c.post("/admin/login", data={"password": PW})


def _catalog():
    return i18n.load_catalog()


def test_all_eu_languages_present():
    """Les 24 langues officielles de l'UE ont un fichier de locale chargé."""
    cat = _catalog()
    assert set(cat.keys()) == set(i18n.SUPPORTED)
    assert len(cat) == 24


def test_every_locale_is_key_complete():
    """Chaque locale définit EXACTEMENT le même jeu de clés que la source fr (ni manquante ni en trop)."""
    cat = _catalog()
    fr_keys = set(cat[i18n.DEFAULT_LANG])
    assert len(fr_keys) >= 275
    for code, entries in cat.items():
        missing = fr_keys - set(entries)
        extra = set(entries) - fr_keys
        assert not missing, f"{code} : {len(missing)} clés manquantes, ex. {sorted(missing)[:5]}"
        assert not extra, f"{code} : {len(extra)} clés en trop, ex. {sorted(extra)[:5]}"


def test_placeholders_preserved_across_locales():
    """Chaque valeur traduite conserve exactement les mêmes {placeholders} que le français."""
    cat = _catalog()
    fr = cat[i18n.DEFAULT_LANG]
    for code, entries in cat.items():
        if code == i18n.DEFAULT_LANG:
            continue
        for key, fr_val in fr.items():
            fr_ph = set(PLACEHOLDER.findall(fr_val))
            tr_ph = set(PLACEHOLDER.findall(entries[key]))
            assert fr_ph == tr_ph, f"{code}:{key} placeholders {tr_ph} != fr {fr_ph}"


def test_mono_code_tokens_never_translated():
    """Les identifiants en <span class=mono> (noms d'env, chemins, URLs) sont préservés tels quels."""
    cat = _catalog()
    fr = cat[i18n.DEFAULT_LANG]
    for code, entries in cat.items():
        if code == i18n.DEFAULT_LANG:
            continue
        for key, fr_val in fr.items():
            for token in MONO.findall(fr_val):
                assert token in entries[key], f"{code}:{key} : code `{token}` absent/traduit"


def test_html_strong_preserved():
    """Le balisage <strong> minimal est conservé dans toutes les traductions."""
    cat = _catalog()
    fr = cat[i18n.DEFAULT_LANG]
    for code, entries in cat.items():
        for key, fr_val in fr.items():
            fr_n = len(STRONG.findall(fr_val))
            if fr_n:
                assert len(STRONG.findall(entries[key])) == fr_n, f"{code}:{key} <strong> perdu"


def test_translate_fallback_and_interpolation():
    _catalog()
    # langue inconnue → repli fr
    assert i18n.translate("nav.dashboard", "xx") == i18n.translate("nav.dashboard", "fr")
    # clé inconnue → clé brute renvoyée
    assert i18n.translate("does.not.exist", "en") == "does.not.exist"
    # interpolation d'un paramètre
    out = i18n.translate("dash.keys.title", "en", count=7)
    assert "7" in out and "{count}" not in out
    # placeholder non fourni → laissé intact (jamais d'exception)
    raw = i18n.translate("dash.keys.title", "en")
    assert "{count}" in raw


def test_translate_uses_target_language():
    _catalog()
    assert i18n.translate("nav.dashboard", "de") == "Dashboard"
    assert i18n.translate("common.save", "fr") == "Enregistrer"
    assert i18n.translate("common.save", "es") == "Guardar"


def test_languages_list_has_french_first():
    langs = i18n.languages()
    assert langs[0][0] == "fr"
    codes = [c for c, _ in langs]
    assert set(codes) == set(i18n.ENABLED)


async def test_lang_switch_route_renders_target_language(admin_client):
    """POST /admin/lang mémorise la langue en session ; la page suivante est rendue dans cette langue."""
    async with admin_client as c:
        await _login(c)
        # FR par défaut
        fr_page = await c.get("/admin")
        assert "Tableau de bord" in fr_page.text
        # bascule EN
        r = await c.post("/admin/lang", data={"lang": "en", "next": "/admin"})
        assert r.status_code == 303
        en_page = await c.get("/admin")
        assert "Dashboard" in en_page.text and "Tableau de bord" not in en_page.text
        assert '<html lang="en">' in en_page.text
        # bascule DE
        await c.post("/admin/lang", data={"lang": "de", "next": "/admin"})
        de_page = await c.get("/admin")
        assert 'lang="de"' in de_page.text


async def test_lang_switch_rejects_unknown_and_bad_next(admin_client):
    """Langue inconnue ignorée ; redirection `next` bornée au périmètre /admin (anti-open-redirect)."""
    async with admin_client as c:
        await _login(c)
        r = await c.post("/admin/lang", data={"lang": "zz", "next": "https://evil.example"})
        assert r.status_code == 303
        assert r.headers["location"] == "/admin"  # next hors /admin → forcé sur /admin
        # langue inchangée (toujours fr)
        page = await c.get("/admin")
        assert "Tableau de bord" in page.text


async def test_language_selector_present_in_page(admin_client):
    async with admin_client as c:
        await _login(c)
        page = await c.get("/admin")
    assert 'action="/admin/lang"' in page.text
    # toutes les langues activées sont proposées dans le sélecteur
    for code in i18n.ENABLED:
        assert f'value="{code}"' in page.text


def test_negotiate_prefers_session_then_cookie_then_header():
    class Req:
        def __init__(self, session=None, cookies=None, headers=None):
            self.session = session or {}
            self.cookies = cookies or {}
            self.headers = headers or {}

    _catalog()
    assert i18n.negotiate(Req(session={"lang": "de"})) == "de"
    assert i18n.negotiate(Req(cookies={"lang": "es"})) == "es"
    assert i18n.negotiate(Req(headers={"accept-language": "pt-PT,pt;q=0.9,en;q=0.8"})) == "pt"
    # rien de reconnaissable → défaut fr
    assert i18n.negotiate(Req(headers={"accept-language": "zz"})) == "fr"
