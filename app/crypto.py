"""Chiffrement réversible au repos des secrets à réémettre (jetons d'auth des serveurs distants).

Contrairement aux clés API et au mot de passe admin (hachés en sens unique dans `auth.py`), le
jeton d'un serveur distant doit être **redonné** à l'amont → chiffrement réversible (Fernet :
AES-128-CBC + HMAC). La clé Fernet est dérivée de `$P2E_MASTER_KEY` (n'importe quelle chaîne :
on en tire 32 octets via SHA-256). Défaut dev non secret ; en prod, `P2E_MASTER_KEY` est requis.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from . import config


def _fernet() -> Fernet:
    digest = hashlib.sha256(config.P2E_MASTER_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    """Chiffre une chaîne (jeton Bearer distant). Chaîne vide → '' (aucun secret)."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Déchiffre un jeton stocké. '' ou jeton invalide (clé maître changée) → ''."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
