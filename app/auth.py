"""Primitives de sécurité : génération/hachage des clés API et du mot de passe admin.

- **Clés API** : secrets à haute entropie (`secrets.token_hex`) → un sha-256 suffit (pas besoin
  d'un KDF lent : rien à brute-forcer sur 128+ bits aléatoires). On ne stocke jamais la clé en clair.
- **Mot de passe admin** : potentiellement à faible entropie → pbkdf2-hmac-sha256 avec sel.
"""
import hashlib
import hmac
import os
import secrets

from . import config

# --- Clés API ---------------------------------------------------------------------------------

def generate_key() -> str:
    """Nouvelle clé API opaque : <prefix><hex(32 octets)>."""
    return config.KEY_PREFIX + secrets.token_hex(32)


def hash_key(key: str) -> str:
    """sha-256 hex de la clé complète (identifiant stocké/recherché)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_prefix(key: str, n: int = 18) -> str:
    """Début lisible de la clé pour l'affichage admin (n premiers caractères)."""
    return key[:n]


# --- Mot de passe admin -----------------------------------------------------------------------

# ≥ 600 000 tours (recommandation OWASP courante). `verify_password` lit le nombre de tours DANS le
# hash stocké → augmenter ici est rétro-compatible (anciens hachages toujours vérifiables ; ré-encodés
# au prochain changement de mot de passe).
_PBKDF2_ROUNDS = 600_000


def hash_password(password: str) -> str:
    """Renvoie 'pbkdf2_sha256$rounds$salt_hex$hash_hex'."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Vérifie un mot de passe contre son encodage pbkdf2 (comparaison à temps constant)."""
    try:
        algo, rounds_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(dk, expected)


def extract_bearer(authorization_header: str | None) -> str | None:
    """Extrait la clé d'un en-tête 'Authorization: Bearer <clé>'. None si absent/malformé."""
    if not authorization_header:
        return None
    parts = authorization_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def extract_api_key(headers) -> str | None:
    """Extrait la clé cliente : 'Authorization: Bearer' (Ollama/OpenAI) ou, à défaut,
    'x-api-key' (SDK Anthropic configuré via ANTHROPIC_API_KEY)."""
    key = extract_bearer(headers.get("authorization"))
    if key:
        return key
    return (headers.get("x-api-key") or "").strip() or None
