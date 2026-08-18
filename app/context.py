"""Limite de CONTEXTE par clé : comptage de tokens (tiktoken), refus avant l'amont, `num_ctx`.

Deux effets, complémentaires, pour empêcher une requête démesurée d'asphyxier le serveur
d'exécution (prefill interminable, cache KV géant, échec d'allocation mémoire) :

1. **Garde-fou d'entrée** — le proxy compte les tokens du corps AVANT de relayer et **refuse
   (413)** si le total dépasse la limite de la clé. On échoue en quelques millisecondes plutôt
   qu'après une heure de prefill amont.
2. **Contrainte à l'amont** — la limite est **injectée** dans la requête (`options.num_ctx` côté
   Ollama natif) pour que le serveur n'alloue pas un contexte plus grand que nécessaire.

**Marge de sécurité de 15 %.** Le comptage utilise `tiktoken` (encodage `cl100k_base`), qui n'est
PAS le tokenizer exact des modèles servis (Qwen, Gemma, Llama… ont chacun le leur). Le nombre réel
peut donc dépasser l'estimation ; on majore l'estimation de 15 % avant de la comparer à la limite,
de sorte qu'un écart de tokenisation ne fasse pas passer une requête qui déborderait réellement.

**Hors-ligne.** Le fichier BPE de `tiktoken` est mis en cache dans l'image au build
(`TIKTOKEN_CACHE_DIR`, cf. Dockerfile) : aucun téléchargement au runtime. Si l'encodage est
malgré tout indisponible, on **replie sur une estimation** (≈ 4 octets/token) plutôt que d'échouer :
la passerelle ne doit jamais casser à cause du tokenizer.
"""
import json
import math
import os

# ÉCHELLE DE PALIERS (« tailles de contexte »), en k tokens. C'est l'ENSEMBLE des valeurs
# autorisées : un plafond de clé est toujours l'un de ces paliers, et chaque requête est classée
# dans le **plus petit palier qui la contient** (cf. `bucket`) pour la statistique d'usage.
# Paliers usuels des modèles servis (2k → 1M), 112k inclus (valeur par défaut historique).
CONTEXT_SIZES_K = (2, 4, 8, 12, 24, 36, 48, 64, 72, 96, 108, 112, 128, 144, 180, 224, 256,
                   384, 512, 640, 768, 1024)
CONTEXT_SIZES = tuple(k * 1024 for k in CONTEXT_SIZES_K)   # en tokens

CONTEXT_MIN = CONTEXT_SIZES[0]     # 2k (2 048)
CONTEXT_MAX = CONTEXT_SIZES[-1]    # 1M (1 048 576)
CONTEXT_DEFAULT = 112 * 1024       # 112k (114 688) — valeur par défaut imposée, jamais vide

# Majoration appliquée à l'estimation avant comparaison (écart de tokenizer, cf. docstring).
MARGIN = 1.15

# Clés JSON porteuses de TEXTE (toutes APIs confondues : Ollama, OpenAI, Anthropic).
_TEXT_KEYS = {"content", "prompt", "input", "system", "text", "query", "suffix"}
# Clés porteuses de BINAIRE encodé (images base64) : exclues du comptage — leur coût en tokens
# relève de la tokenisation visuelle, pas du texte, et les compter fausserait tout.
_SKIP_KEYS = {"images", "image", "image_url", "source", "data", "b64_json", "audio"}

_ENCODER = None
_ENCODER_TRIED = False


def _encoder():
    """Encodage tiktoken partagé (chargé une seule fois, depuis le cache local). None si absent."""
    global _ENCODER, _ENCODER_TRIED
    if not _ENCODER_TRIED:
        _ENCODER_TRIED = True
        try:
            import tiktoken
            _ENCODER = tiktoken.get_encoding(os.environ.get("TIKTOKEN_ENCODING", "cl100k_base"))
        except Exception:  # noqa: BLE001 — jamais bloquant : repli sur l'estimation
            _ENCODER = None
    return _ENCODER


# --- Validation de la limite ------------------------------------------------------------------

def is_valid(value: int) -> bool:
    """True si `value` est l'un des paliers de l'échelle (`CONTEXT_SIZES`)."""
    return (isinstance(value, int) and not isinstance(value, bool)
            and value in CONTEXT_SIZES)


def bucket(tokens: int) -> int:
    """**Plus petit palier qui CONTIENT** `tokens` (classement d'une requête sur l'échelle).

    C'est la taille de contexte qu'il faudrait réellement provisionner pour servir la requête :
    27 734 tokens ne tiennent pas dans 24k → palier **36k** ; 2 096 tokens ne tiennent pas dans
    2k → palier **4k**. Au-delà du dernier palier, on renvoie le plus grand (1M)."""
    for size in CONTEXT_SIZES:
        if tokens <= size:
            return size
    return CONTEXT_MAX


def normalize(value) -> int:
    """Ramène une saisie quelconque à une limite VALIDE (la valeur ne peut jamais être vide).

    Accepte un entier ou une chaîne (« 112k », « 114688 », « 112 »). Toute valeur inutilisable
    retombe sur `CONTEXT_DEFAULT` ; une valeur hors bornes est bornée ; une valeur qui ne tombe pas
    sur un palier est **remontée au palier supérieur** (on ne rétrécit jamais silencieusement le
    contexte demandé en dessous du besoin exprimé)."""
    if isinstance(value, str):
        s = value.strip().lower().replace(" ", "")
        if not s:
            return CONTEXT_DEFAULT
        try:
            if s.endswith("k"):
                num = int(float(s[:-1]) * 1024)
            elif s.endswith("m"):
                num = int(float(s[:-1]) * 1024 * 1024)
            else:
                num = int(float(s))
                if num <= 1024:          # saisie en « k » sans suffixe (ex. « 112 »)
                    num *= 1024
        except ValueError:
            return CONTEXT_DEFAULT
    elif isinstance(value, int) and not isinstance(value, bool):
        num = value
    else:
        return CONTEXT_DEFAULT
    # Une valeur ≤ 1024 ne peut pas être un nombre de tokens valide (le minimum est 4096) : on
    # l'interprète comme des « k » (saisie « 112 » ou YAML `max_context_tokens: 112` = 112k).
    if 0 < num <= 1024:
        num *= 1024
    num = max(CONTEXT_MIN, min(CONTEXT_MAX, num))
    return bucket(num)          # cale sur l'échelle (palier ≥ valeur demandée)


def label(value: int) -> str:
    """Libellé court d'une limite : 114688 → « 112k »."""
    return f"{value // 1024}k"


def choices() -> list[int]:
    """Paliers proposés dans l'UI = l'échelle complète."""
    return list(CONTEXT_SIZES)


# --- Budget entrée/sortie annonçable à un client --------------------------------------------

# Part de la fenêtre réservée à la SORTIE quand l'amont n'annonce qu'un contexte TOTAL (cas
# d'Ollama : `/api/show` ne publie que `<arch>.context_length`). Bornée : au moins 1k (une réponse
# utile reste possible), au plus 32k (au-delà, réserver davantage amputerait le prompt pour rien).
OUTPUT_SHARE = 4
OUTPUT_MIN = 1024
OUTPUT_MAX = 32 * 1024


def _declared(value) -> int | None:
    """Borne déclarée par l'amont, en entier strictement positif — sinon None (= non déclarée)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value > 0 else None


def io_budget(total_context: int | None, key_limit: int,
              declared_input: int | None = None,
              declared_output: int | None = None) -> tuple[int, int]:
    """(max_entrée, max_sortie) en tokens à annoncer pour un modèle donné, sur une clé donnée.

    Un client type VS Code veut DEUX bornes. **Si l'amont les déclare, elles priment** : lui seul
    sait ce qu'il accepte réellement (`num_predict` du Modelfile, `max_input_tokens`/
    `max_output_tokens` d'un amont OpenAI-compatible…). Le calcul ci-dessous n'est qu'un **repli**
    pour les amonts qui ne publient qu'une fenêtre totale — le cas d'Ollama nu.

    Trois contraintes, dans cet ordre :

    1. **Fenêtre effective** = min(fenêtre du modèle, plafond de la clé). `num_ctx` étant borné au
       plafond (`inject_num_ctx`), servir au-delà est impossible même si le modèle sait faire plus.
       Fenêtre amont inconnue (`None`) ⇒ on s'en tient au plafond de la clé.
    2. **Sortie** — déclarée si l'amont la donne, sinon un quart de la fenêtre (borné
       `OUTPUT_MIN`…`OUTPUT_MAX`) : entrée et sortie partagent la même fenêtre, tout annoncer en
       entrée ne laisserait rien à générer. Dans les deux cas elle reste dans la fenêtre.
    3. **Entrée** — déclarée si l'amont la donne, sinon le reste de la fenêtre. Elle est ensuite
       **plafonnée quoi qu'il arrive** : par la fenêtre effective, et par `plafond / MARGIN` — le
       garde-fou d'entrée compare une estimation MAJORÉE de `MARGIN` au plafond (cf. `exceeds`),
       donc un prompt de `plafond` tokens réels serait refusé en 413. Une borne déclarée plus large
       que ce que la passerelle laissera passer serait un mensonge : on la redescend.
    """
    limit = key_limit if isinstance(key_limit, int) and not isinstance(key_limit, bool) else 0
    limit = max(limit, CONTEXT_MIN)
    total = limit
    if (window := _declared(total_context)) is not None:
        total = min(limit, window)

    out = _declared(declared_output)
    if out is None:
        out = max(OUTPUT_MIN, min(OUTPUT_MAX, total // OUTPUT_SHARE))
    out = min(out, total - 1)                  # toujours laisser de la place à l'entrée

    inp = _declared(declared_input)
    if inp is None:
        inp = total - out
    inp = min(inp, total, int(limit / MARGIN))
    return max(1, inp), max(1, out)


# --- Comptage de tokens -----------------------------------------------------------------------

def _collect_text(node, out: list[str], depth: int = 0) -> None:
    """Parcourt le JSON et collecte le TEXTE des champs connus (toutes APIs), en sautant les
    charges binaires (images base64). Robuste aux formes imbriquées (`content` en liste de parts
    OpenAI/Anthropic)."""
    if depth > 12:
        return
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for item in node:
            _collect_text(item, out, depth + 1)
    elif isinstance(node, dict):
        for key, val in node.items():
            if key in _SKIP_KEYS:
                continue
            if key in _TEXT_KEYS:
                _collect_text(val, out, depth + 1)
            elif isinstance(val, (dict, list)):
                _collect_text(val, out, depth + 1)


def count_tokens(body: bytes) -> int:
    """Estime le nombre de tokens du corps d'une requête (0 si corps vide/non-JSON).

    Agnostique de l'API : le texte est extrait des champs porteurs (`messages[].content`,
    `prompt`, `input`, `system`…) quelle que soit la famille (Ollama, OpenAI, Anthropic)."""
    if not body:
        return 0
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return 0
    parts: list[str] = []
    _collect_text(obj, parts)
    if not parts:
        return 0
    text = "\n".join(parts)
    enc = _encoder()
    if enc is None:                       # repli : ~4 octets par token (ordre de grandeur usuel)
        return len(text.encode("utf-8")) // 4
    return len(enc.encode(text, disallowed_special=()))


def with_margin(tokens: int) -> int:
    """Estimation majorée de la marge de sécurité (arrondi supérieur)."""
    return math.ceil(tokens * MARGIN)


def exceeds(body: bytes, limit: int) -> tuple[bool, int, int]:
    """(dépassement ?, tokens estimés, tokens majorés) du corps face à `limit`."""
    tokens = count_tokens(body)
    billed = with_margin(tokens)
    return billed > limit, tokens, billed


# --- Contrainte à l'amont (num_ctx) -----------------------------------------------------------

# Chemins Ollama NATIFS acceptant `options.num_ctx`. Les APIs OpenAI-compat et Anthropic n'ont pas
# d'équivalent standard de fenêtre de contexte par requête (leur `max_tokens` borne la SORTIE) :
# injecter un champ non standard risquerait un 400 sur un amont strict. Pour ces familles, la
# limite reste appliquée par le REFUS en entrée (garde-fou 1).
_NUM_CTX_PATHS = ("/api/chat", "/api/generate", "/api/embed", "/api/embeddings")


def supports_num_ctx(path: str) -> bool:
    return path.rstrip("/") in _NUM_CTX_PATHS


def inject_num_ctx(body: bytes, path: str, limit: int) -> bytes:
    """Force `options.num_ctx = limit` sur les chemins Ollama natifs (corps renvoyé inchangé
    ailleurs, ou si le corps n'est pas un objet JSON).

    Si le client a déjà demandé un `num_ctx`, on garde le **plus petit** des deux : la limite de la
    clé est un PLAFOND, elle ne doit pas gonfler un contexte que le client voulait plus court."""
    if not supports_num_ctx(path) or not body:
        return body
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(obj, dict):
        return body
    opts = obj.get("options")
    if not isinstance(opts, dict):
        opts = {}
    current = opts.get("num_ctx")
    if isinstance(current, int) and not isinstance(current, bool) and current > 0:
        opts["num_ctx"] = min(current, limit)
    else:
        opts["num_ctx"] = limit
    obj["options"] = opts
    return json.dumps(obj).encode("utf-8")
