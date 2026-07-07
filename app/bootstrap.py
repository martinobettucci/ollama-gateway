"""Bootstrap CLI : migrations, mot de passe admin, seed dev, import d'une clé existante.

Usage :
    python -m app.bootstrap init          # applique les migrations SQLite
    python -m app.bootstrap ensure-admin  # pose le mdp admin depuis $ADMIN_PASSWORD s'il n'existe pas
    python -m app.bootstrap seed-dev      # dev : admin de démo + clé de démo déterministe
    python -m app.bootstrap import-key    # importe une clé existante depuis l'environnement

Variables d'import (import-key) — la clé n'apparaît jamais dans le repo, seulement en env :
    IMPORT_KEY_VALUE    (obligatoire)  clé en clair à importer (ex. la clé Gram historique)
    IMPORT_KEY_LABEL    (défaut 'gram')
    IMPORT_KEY_ORIGINS  (défaut '')    CIDR/IP séparés par des virgules
    IMPORT_KEY_CAP      (défaut vide)  plafond mensuel de tokens
    IMPORT_KEY_RPM      (défaut vide)  rate-limit req/min
"""
import os
import sys

from . import auth, db, keys, servers

# Clé de démo dev DÉTERMINISTE (non secrète, jamais en prod) : sert aux tests E2E du proxy.
DEV_DEMO_KEY = "sk-ollama-devdemokey000000000000000000000000000000000000000000000000"


def cmd_init() -> None:
    applied = db.apply_migrations()
    print(f"migrations appliquées: {applied or 'aucune (à jour)'}")
    servers.ensure_default()  # serveur local par défaut + réassignation des clés orphelines
    print("serveur d'exécution par défaut garanti (local)")


def cmd_ensure_admin() -> None:
    if keys.get_admin_hash() is not None:
        print("mot de passe admin déjà défini — inchangé")
        return
    pw = os.environ.get("ADMIN_PASSWORD", "")
    if not pw:
        print("ADMIN_PASSWORD non défini — admin à initialiser via la page /admin/setup")
        return
    keys.set_admin_password(pw)
    print("mot de passe admin défini depuis ADMIN_PASSWORD")


def cmd_seed_dev() -> None:
    db.apply_migrations()
    if keys.get_admin_hash() is None:
        keys.set_admin_password(os.environ.get("ADMIN_PASSWORD", "adminpass"))
        print("admin de démo défini")
    if keys.find_by_key(DEV_DEMO_KEY) is None:
        keys.create_key(label="demo (dev)", origins=[], monthly_token_cap=None,
                        rpm_limit=None, note="clé de démo self-seed", key_value=DEV_DEMO_KEY)
        print(f"clé de démo créée: {DEV_DEMO_KEY[:18]}…")
    else:
        print("clé de démo déjà présente")


def cmd_import_key() -> None:
    db.apply_migrations()
    value = os.environ.get("IMPORT_KEY_VALUE", "").strip()
    if not value:
        print("IMPORT_KEY_VALUE manquant", file=sys.stderr)
        sys.exit(2)
    if keys.find_by_key(value) is not None:
        print(f"clé déjà présente ({auth.key_prefix(value)}…) — rien à faire")
        return
    origins = [o.strip() for o in os.environ.get("IMPORT_KEY_ORIGINS", "").split(",") if o.strip()]
    cap = os.environ.get("IMPORT_KEY_CAP", "").strip()
    rpm = os.environ.get("IMPORT_KEY_RPM", "").strip()
    keys.create_key(
        label=os.environ.get("IMPORT_KEY_LABEL", "gram"),
        origins=origins,
        monthly_token_cap=int(cap) if cap else None,
        rpm_limit=int(rpm) if rpm else None,
        note="clé importée (migration)", key_value=value,
    )
    print(f"clé importée: label={os.environ.get('IMPORT_KEY_LABEL', 'gram')} "
          f"prefix={auth.key_prefix(value)}… origines={origins or 'toutes'}")


_COMMANDS = {
    "init": cmd_init, "ensure-admin": cmd_ensure_admin,
    "seed-dev": cmd_seed_dev, "import-key": cmd_import_key,
}


def main(argv: list[str]) -> None:
    if len(argv) != 1 or argv[0] not in _COMMANDS:
        print(f"commandes: {', '.join(_COMMANDS)}", file=sys.stderr)
        sys.exit(2)
    _COMMANDS[argv[0]]()


if __name__ == "__main__":
    main(sys.argv[1:])
