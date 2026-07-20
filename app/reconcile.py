"""Réconciliation DÉCLARATIVE (mode headless) : applique un fichier de configuration YAML à la base.

Quand la variable d'environnement `GATEWAY_CONFIG` pointe vers un fichier YAML (cf. `config.py`),
la passerelle démarre en mode « déclaratif » : l'entrypoint appelle `reconcile apply <fichier>`
AVANT de lancer uvicorn, et l'état (serveurs d'exécution, cibles publiques, clés API) est aligné
sur le fichier. C'est l'équivalent GitOps de la console d'admin : on décrit l'infrastructure dans
un fichier versionné plutôt que de cliquer dans l'UI.

Principes (durs) :

- **Le drapeau vit dans l'ENVIRONNEMENT, jamais dans le YAML** (`GATEWAY_CONFIG`). Sinon couplage
  circulaire : il faudrait lire le fichier pour savoir s'il faut le lire.
- **Aucun secret en clair dans le YAML.** Les valeurs sensibles (jeton d'un serveur distant, plus
  tard SMTP) s'écrivent `${NOM_DE_VARIABLE}` et sont **interpolées depuis l'environnement** au
  chargement. Le fichier reste donc versionnable ; les secrets restent en `.env`.
- **Identité stable des clés** via `external_ref` (le champ `name` du YAML). La réconciliation
  reconnaît une clé déjà créée et ne la recrée pas — elle met seulement sa config à jour.
- **Élagage conservateur.** Une clé gérée retirée du YAML est **désactivée** par défaut (accès
  révocable sans perte), et seulement **supprimée** si `prune: true` en tête de fichier. Les clés
  créées par l'UI (`external_ref` NULL) ne sont JAMAIS touchées.

La **livraison** du secret d'une clé nouvellement générée (webhook/email) est traitée séparément
(cf. app/deliver.py, phase ultérieure) : ce module se contente de réconcilier l'état.
"""
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import apis, db, deliver, keys, servers, targets

# ${NOM} → valeur d'environnement. Nom façon shell : lettre/underscore puis alphanumériques.
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """Configuration YAML invalide (structure, référence, ou variable d'env manquante)."""


# --- Chargement + interpolation ---------------------------------------------------------------

def interpolate(value):
    """Remplace récursivement `${VAR}` par `os.environ['VAR']` dans toutes les chaînes.

    Fail-closed : une variable référencée mais absente de l'environnement lève `ConfigError`
    (on ne veut pas écrire une chaîne littérale « ${SMTP_PASSWORD} » comme jeton par mégarde)."""
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            name = m.group(1)
            if name not in os.environ:
                raise ConfigError(f"variable d'environnement manquante : ${{{name}}}")
            return os.environ[name]
        return _ENV_RE.sub(repl, value)
    if isinstance(value, list):
        return [interpolate(v) for v in value]
    if isinstance(value, dict):
        return {k: interpolate(v) for k, v in value.items()}
    return value


def load(path: str) -> dict:
    """Lit le YAML, interpole les `${VAR}` et renvoie le mapping racine (dict)."""
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("racine du YAML : un objet (mapping) est attendu")
    return interpolate(raw)


# --- Validation / normalisation ---------------------------------------------------------------

def _req_str(d: dict, key: str, where: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"{where} : champ « {key} » manquant ou vide")
    return v.strip()


def _opt_bool(d: dict, key: str, default: bool) -> bool:
    v = d.get(key, default)
    if not isinstance(v, bool):
        raise ConfigError(f"champ « {key} » : booléen attendu")
    return v


def _opt_int(d: dict, key: str, where: str) -> int | None:
    v = d.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ConfigError(f"{where} : champ « {key} » : entier attendu")
    return v


def _opt_str_list(d: dict, key: str, where: str) -> list[str] | None:
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{where} : champ « {key} » : liste de chaînes attendue")
    return [x.strip() for x in v if x.strip()]


def _validate_servers(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ConfigError("« servers » : liste attendue")
    out, names = [], set()
    for i, s in enumerate(raw):
        where = f"servers[{i}]"
        if not isinstance(s, dict):
            raise ConfigError(f"{where} : objet attendu")
        name = _req_str(s, "name", where)
        if name in names:
            raise ConfigError(f"{where} : nom de serveur en double « {name} »")
        names.add(name)
        base_url = _req_str(s, "base_url", where)
        try:
            servers.validate_base_url(base_url)
        except ValueError as exc:
            raise ConfigError(f"{where} : base_url invalide ({exc})") from exc
        entry = {"name": name, "base_url": base_url,
                 "enabled": _opt_bool(s, "enabled", True),
                 "default": _opt_bool(s, "default", False),
                 "models": _opt_str_list(s, "models", where)}
        if "token" in s:  # présent (même vide) → géré ; absent → jeton inchangé
            tok = s["token"]
            if not isinstance(tok, str):
                raise ConfigError(f"{where} : « token » : chaîne attendue")
            entry["token"] = tok.strip()
        out.append(entry)
    if sum(1 for s in out if s["default"]) > 1:
        raise ConfigError("« servers » : un seul serveur peut être « default: true »")
    return out


def _validate_targets(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ConfigError("« targets » : liste attendue")
    out, names = [], set()
    for i, t in enumerate(raw):
        where = f"targets[{i}]"
        if not isinstance(t, dict):
            raise ConfigError(f"{where} : objet attendu")
        name = _req_str(t, "name", where)
        if name in names:
            raise ConfigError(f"{where} : nom de cible en double « {name} »")
        names.add(name)
        base_url = _req_str(t, "base_url", where)
        if not base_url.startswith(("http://", "https://")):
            raise ConfigError(f"{where} : base_url doit commencer par http(s)://")
        out.append({"name": name, "base_url": base_url,
                    "default": _opt_bool(t, "default", False)})
    if sum(1 for t in out if t["default"]) > 1:
        raise ConfigError("« targets » : une seule cible peut être « default: true »")
    return out


def _validate_smtp(raw: object) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("« smtp » : objet attendu")
    cfg = {
        "host": _req_str(raw, "host", "smtp"),
        "port": _opt_int(raw, "port", "smtp") or 587,
        "from": _req_str(raw, "from", "smtp"),
        "tls": raw.get("tls", "starttls"),
        "username": raw.get("username") or "",
        "password": raw.get("password") or "",
    }
    if cfg["tls"] not in ("none", "starttls", "tls"):
        raise ConfigError("smtp.tls : « none », « starttls » ou « tls » attendu")
    return cfg


def _validate_deliver(raw: object, where: str) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{where} : « deliver » : liste attendue")
    out = []
    for j, ch in enumerate(raw):
        w = f"{where}.deliver[{j}]"
        if not isinstance(ch, dict) or len(ch) != 1 or next(iter(ch)) not in ("email", "webhook"):
            raise ConfigError(f"{w} : un canal « email » OU « webhook » attendu")
        kind, spec = next(iter(ch.items()))
        if not isinstance(spec, dict):
            raise ConfigError(f"{w} : objet attendu pour « {kind} »")
        if kind == "email":
            out.append({"email": {"to": _req_str(spec, "to", w)}})
        else:
            url = _req_str(spec, "url", w)
            if not url.startswith(("http://", "https://")):
                raise ConfigError(f"{w} : webhook.url doit commencer par http(s)://")
            preset = spec.get("preset")
            template = spec.get("template")
            if preset is not None and preset not in deliver.WEBHOOK_PRESETS:
                raise ConfigError(f"{w} : preset inconnu « {preset} » "
                                  f"(attendu : {', '.join(deliver.WEBHOOK_PRESETS)})")
            if template is not None and not isinstance(template, str):
                raise ConfigError(f"{w} : webhook.template : chaîne attendue")
            headers = spec.get("headers")
            if headers is not None and not isinstance(headers, dict):
                raise ConfigError(f"{w} : webhook.headers : objet attendu")
            wh = {"url": url}
            if preset is not None:
                wh["preset"] = preset
            if template is not None:
                wh["template"] = template
            if headers:
                wh["headers"] = {str(k): str(v) for k, v in headers.items()}
            if spec.get("method"):
                wh["method"] = str(spec["method"])
            out.append({"webhook": wh})
    return out


def _validate_keys(raw: object, server_names: set[str], target_names: set[str]) -> list[dict]:
    if not isinstance(raw, list):
        raise ConfigError("« keys » : liste attendue")
    out, refs = [], set()
    for i, k in enumerate(raw):
        where = f"keys[{i}]"
        if not isinstance(k, dict):
            raise ConfigError(f"{where} : objet attendu")
        name = _req_str(k, "name", where)
        if name in refs:
            raise ConfigError(f"{where} : nom de clé en double « {name} »")
        refs.add(name)
        srv = k.get("server")
        if srv is not None and srv not in server_names:
            raise ConfigError(f"{where} : serveur « {srv} » non défini dans « servers »")
        tgt = k.get("target")
        if tgt is not None and tgt not in target_names:
            raise ConfigError(f"{where} : cible « {tgt} » non définie dans « targets »")
        key_apis = _opt_str_list(k, "apis", where)
        for a in (key_apis or []):
            if a not in apis.FAMILIES:
                raise ConfigError(f"{where} : famille d'API inconnue « {a} »")
        value = k.get("value")
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ConfigError(f"{where} : « value » : chaîne non vide attendue")
        out.append({
            "name": name, "label": (k.get("label") or name),
            "value": value.strip() if isinstance(value, str) else None,
            "server": srv, "target": tgt,
            "enabled": _opt_bool(k, "enabled", True),
            "origins": _opt_str_list(k, "origins", where) or [],
            "models": _opt_str_list(k, "models", where),
            "apis": key_apis,
            "image_models": _opt_str_list(k, "image_models", where),
            "rpm_limit": _opt_int(k, "rpm_limit", where),
            "monthly_token_cap": _opt_int(k, "monthly_token_cap", where),
            "total_token_cap": _opt_int(k, "total_token_cap", where),
            "total_request_cap": _opt_int(k, "total_request_cap", where),
            "expires_at": (k.get("expires_at") or None),
            "idle_expiry_days": _opt_int(k, "idle_expiry_days", where),
            "log_retention_days": _opt_int(k, "log_retention_days", where),
            "deliver": _validate_deliver(k.get("deliver"), where),
        })
    return out


# --- Rapport ----------------------------------------------------------------------------------

@dataclass
class DeliveryJob:
    """Livraison en attente du secret d'une clé GÉNÉRÉE : effectuée HORS verrou (I/O réseau)."""
    key_id: int
    ref: str
    label: str
    secret: str
    url: str
    channels: list[dict]


@dataclass
class Report:
    """Résumé d'une réconciliation (sans aucun secret)."""
    servers_created: list[str] = field(default_factory=list)
    servers_updated: list[str] = field(default_factory=list)
    targets_created: list[str] = field(default_factory=list)
    targets_updated: list[str] = field(default_factory=list)
    keys_created: list[str] = field(default_factory=list)
    keys_updated: list[str] = field(default_factory=list)
    keys_disabled: list[str] = field(default_factory=list)
    keys_deleted: list[str] = field(default_factory=list)
    keys_delivered: list[str] = field(default_factory=list)          # secret livré (webhook/e-mail)
    delivery_errors: list[str] = field(default_factory=list)         # "ref: erreur"
    generated_without_delivery: list[str] = field(default_factory=list)  # secret irrécupérable

    def summary(self) -> str:
        return (
            f"serveurs: +{len(self.servers_created)} ~{len(self.servers_updated)} | "
            f"cibles: +{len(self.targets_created)} ~{len(self.targets_updated)} | "
            f"clés: +{len(self.keys_created)} ~{len(self.keys_updated)} "
            f"⊘{len(self.keys_disabled)} ✗{len(self.keys_deleted)} | "
            f"livrées: {len(self.keys_delivered)}")


# --- Écriture (helpers directs SQLite) --------------------------------------------------------

def _set_server_default(server_id: int) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE servers SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END",
                (server_id,))
    finally:
        conn.close()


def _set_server_models(server_id: int, models: list[str]) -> None:
    """Fixe la liste de modèles STATIQUE d'un serveur (sans sonde). Utile en headless où l'amont
    n'est pas interrogeable : peuple `last_models` pour l'allowlist par clé et l'affichage."""
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE servers SET last_models = ?, last_checked_at = datetime('now') "
                "WHERE id = ?", (json.dumps(models), server_id))
    finally:
        conn.close()


def _set_target_default(target_id: int) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE targets SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END",
                (target_id,))
    finally:
        conn.close()


def _has_default_server() -> bool:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT 1 FROM servers WHERE is_default = 1 LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def _has_default_target() -> bool:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT 1 FROM targets WHERE is_default = 1 LIMIT 1").fetchone() is not None
    finally:
        conn.close()


# --- Application ------------------------------------------------------------------------------

def _apply_servers(cfg: list[dict], report: Report) -> dict[str, int]:
    existing = {s.name: s for s in servers.list_servers()}
    ids: dict[str, int] = {}
    default_name = None
    for s in cfg:
        name, base_url, enabled = s["name"], s["base_url"], s["enabled"]
        if name in existing:
            rec = existing[name]
            token = s.get("token")  # None = absent → inchangé ; "" = vider ; sinon remplacer
            servers.update_server(rec.id, name, base_url, enabled,
                                  auth_token=token, clear_auth=(token == ""))
            sid = rec.id
            report.servers_updated.append(name)
        else:
            rec = servers.create_server(name, base_url, s.get("token") or "", enabled)
            sid = rec.id
            report.servers_created.append(name)
        ids[name] = sid
        if s["models"] is not None:
            _set_server_models(sid, s["models"])
        if s["default"]:
            default_name = name
    if default_name is not None:
        _set_server_default(ids[default_name])
    elif cfg and not _has_default_server():
        _set_server_default(ids[cfg[0]["name"]])  # aucun défaut marqué ni présent → 1er serveur
    return ids


def _apply_targets(cfg: list[dict], report: Report) -> dict[str, int]:
    existing = {t.name: t for t in targets.list_targets()}
    ids: dict[str, int] = {}
    default_name = None
    for t in cfg:
        name, base_url = t["name"], t["base_url"]
        if name in existing:
            targets.update_target(existing[name].id, name, base_url)
            tid = existing[name].id
            report.targets_updated.append(name)
        else:
            tid = targets.create_target(name, base_url).id
            report.targets_created.append(name)
        ids[name] = tid
        if t["default"]:
            default_name = name
    if default_name is not None:
        _set_target_default(ids[default_name])
    elif cfg and not _has_default_target():
        _set_target_default(ids[cfg[0]["name"]])
    return ids


def _apply_keys(cfg: list[dict], server_ids: dict[str, int], target_ids: dict[str, int],
                prune: bool, report: Report) -> list[DeliveryJob]:
    conn = db.connect()
    try:
        default_sid = servers.default_id(conn)
        default_tid = targets.default_id(conn)
    finally:
        conn.close()
    managed = keys.managed_refs()
    seen: set[str] = set()
    jobs: list[DeliveryJob] = []
    for k in cfg:
        ref = k["name"]
        seen.add(ref)
        sid = server_ids[k["server"]] if k["server"] else default_sid
        tid = target_ids[k["target"]] if k["target"] else default_tid
        common = dict(
            label=k["label"], origins=k["origins"],
            monthly_token_cap=k["monthly_token_cap"], rpm_limit=k["rpm_limit"],
            server_id=sid, target_id=tid,
            models=k["models"] if k["models"] is not None else [],
            key_apis=k["apis"] if k["apis"] is not None else [],
            image_models=k["image_models"] if k["image_models"] is not None else [],
            total_token_cap=k["total_token_cap"], total_request_cap=k["total_request_cap"],
            expires_at=k["expires_at"], idle_expiry_days=k["idle_expiry_days"],
            log_retention_days=k["log_retention_days"],
        )
        if ref in managed:
            keys.update_key(managed[ref], note="clé déclarative (YAML)", **common)
            keys.set_enabled(managed[ref], k["enabled"])
            report.keys_updated.append(ref)
        else:
            rec, secret = keys.create_key(
                note="clé déclarative (YAML)", key_value=k["value"],
                external_ref=ref, **common)
            if not k["enabled"]:
                keys.set_enabled(rec.id, False)
            report.keys_created.append(ref)
            if not k["value"]:  # clé GÉNÉRÉE → secret à livrer (importée : l'opérateur le connaît)
                if k["deliver"]:
                    jobs.append(DeliveryJob(
                        key_id=rec.id, ref=ref, label=k["label"], secret=secret,
                        url=rec.target_base_url or "", channels=k["deliver"]))
                else:
                    report.generated_without_delivery.append(ref)
    # Élagage : clés gérées absentes du YAML → désactivées (défaut) ou supprimées (prune).
    for ref, kid in managed.items():
        if ref in seen:
            continue
        if prune:
            keys.delete_key(kid)
            report.keys_deleted.append(ref)
        else:
            keys.set_enabled(kid, False)
            report.keys_disabled.append(ref)
    return jobs


def apply(path: str) -> Report:
    """Réconcilie l'état de la base avec le fichier YAML `path`. Sérialisé par verrou fichier
    (`db.file_lock`) : proxy et admin peuvent démarrer en parallèle sur le même SQLite. Idempotent :
    relancé sur le même fichier, il ne recrée rien et ne relivre rien."""
    cfg = load(path)
    if not isinstance(cfg.get("prune", False), bool):
        raise ConfigError("« prune » : booléen attendu")
    prune = bool(cfg.get("prune", False))
    smtp_cfg = _validate_smtp(cfg.get("smtp"))
    servers_cfg = _validate_servers(cfg.get("servers") or [])
    targets_cfg = _validate_targets(cfg.get("targets") or [])
    keys_cfg = _validate_keys(cfg.get("keys") or [],
                              {s["name"] for s in servers_cfg},
                              {t["name"] for t in targets_cfg})
    # Un canal e-mail exige une configuration SMTP.
    needs_smtp = any("email" in ch for k in keys_cfg for ch in k["deliver"])
    if needs_smtp and smtp_cfg is None:
        raise ConfigError("un canal « email » est configuré mais le bloc « smtp » est absent")
    report = Report()
    with db.file_lock("reconcile-config"):
        server_ids = _apply_servers(servers_cfg, report)
        target_ids = _apply_targets(targets_cfg, report)
        jobs = _apply_keys(keys_cfg, server_ids, target_ids, prune, report)
    # Livraison HORS verrou (I/O réseau SMTP/HTTP) : le secret n'existe qu'en mémoire ici — la
    # livraison a lieu dans CE passage, juste après la génération. Succès → horodatage posé ;
    # échec → erreur rapportée (secret irrécupérable : faire tourner la clé pour relivrer).
    for job in jobs:
        errs = deliver.deliver_key(job.channels, smtp_cfg, label=job.label,
                                   secret=job.secret, url=job.url)
        if errs:
            report.delivery_errors.extend(f"{job.ref}: {e}" for e in errs)
        else:
            keys.mark_delivered(job.key_id)
            report.keys_delivered.append(job.ref)
    return report


# --- CLI --------------------------------------------------------------------------------------

def main(argv: list[str]) -> None:
    if len(argv) < 1 or argv[0] not in ("apply", "validate"):
        print("usage : python -m app.reconcile {apply|validate} <fichier.yaml>", file=sys.stderr)
        sys.exit(2)
    cmd = argv[0]
    path = argv[1] if len(argv) > 1 else os.environ.get("GATEWAY_CONFIG", "")
    if not path:
        print("chemin du fichier de configuration manquant", file=sys.stderr)
        sys.exit(2)
    try:
        if cmd == "validate":
            cfg = load(path)  # lève ConfigError si structure/interpolation invalide
            s = _validate_servers(cfg.get("servers") or [])
            t = _validate_targets(cfg.get("targets") or [])
            _validate_keys(cfg.get("keys") or [],
                           {x["name"] for x in s}, {x["name"] for x in t})
            print(f"configuration valide : {path}")
            return
        report = apply(path)
    except (ConfigError, FileNotFoundError) as exc:
        print(f"configuration invalide : {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"réconciliation appliquée — {report.summary()}")
    # On n'imprime JAMAIS de secret. On signale les clés GÉNÉRÉES sans canal (secret irrécupérable)
    # et les échecs de livraison (le secret est perdu → faire tourner la clé pour relivrer).
    if report.generated_without_delivery:
        refs = ", ".join(report.generated_without_delivery)
        print(f"ATTENTION : {len(report.generated_without_delivery)} clé(s) générée(s) sans "
              f"livraison configurée — secret irrécupérable : {refs}", file=sys.stderr)
    if report.delivery_errors:
        print(f"ÉCHEC de livraison ({len(report.delivery_errors)}) : "
              f"{'; '.join(report.delivery_errors)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
