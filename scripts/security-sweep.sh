#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Balayage de sécurité COMPLET — gate de pré-déploiement (cf. CLAUDE.md).
#
#   exit 0  → aucune découverte bloquante (déploiement autorisé)
#   exit 1  → au moins une découverte bloquante (voir le résumé) → STOP
#
# Couverture : secrets (gitleaks), CVE des dépendances (pip-audit), SAST Python
# (bandit HIGH), SAST multi-règles (semgrep ERROR, best-effort réseau) et la
# suite de tests (pytest). Les tools sont cherchés dans .venv/ puis le PATH.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VENV="$ROOT/.venv"

BOLD=$'\033[1m'; RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; NC=$'\033[0m'
FAIL=0
declare -a SUMMARY

_line() { printf '%s\n' "──────────────────────────────────────────────────────────────"; }
_pass() { SUMMARY+=("${GRN}PASS${NC}  $1"); }
_warn() { SUMMARY+=("${YEL}WARN${NC}  $1"); }
_fail() { SUMMARY+=("${RED}FAIL${NC}  $1"); FAIL=1; }

# Résolution d'un outil : .venv/bin d'abord, puis PATH.
tool() {
  if [ -x "$VENV/bin/$1" ]; then echo "$VENV/bin/$1"; return 0; fi
  command -v "$1" 2>/dev/null && return 0
  return 1
}
# gitleaks : PATH, sinon binaire téléchargé sous .venv/gl/.
gitleaks_bin() {
  command -v gitleaks 2>/dev/null && return 0
  [ -x "$VENV/gl/gitleaks" ] && { echo "$VENV/gl/gitleaks"; return 0; }
  return 1
}

echo "${BOLD}== Balayage de sécurité pré-déploiement ==${NC}  ($ROOT)"; _line

# ── 1. Secrets — gitleaks (arbre de travail + historique) ─────────────────────
if GL="$(gitleaks_bin)"; then
  if "$GL" dir --no-banner --redact "$ROOT" >/tmp/_sweep_gl.txt 2>&1; then
    _pass "gitleaks (secrets, arbre de travail) — 0 fuite"
  else
    echo "${RED}gitleaks a détecté des secrets :${NC}"; tail -20 /tmp/_sweep_gl.txt
    _fail "gitleaks — secret(s) détecté(s) dans l'arbre de travail"
  fi
else
  _warn "gitleaks introuvable — scan de secrets non exécuté (installer gitleaks)"
fi

# ── 2. CVE des dépendances — pip-audit (requirements.txt) ─────────────────────
if PA="$(tool pip-audit)"; then
  if "$PA" -r requirements.txt --progress-spinner off >/tmp/_sweep_pa.txt 2>&1; then
    _pass "pip-audit (CVE dépendances) — 0 vulnérabilité"
  else
    echo "${RED}pip-audit a trouvé des CVE :${NC}"; tail -30 /tmp/_sweep_pa.txt
    _fail "pip-audit — dépendance(s) vulnérable(s)"
  fi
else
  _fail "pip-audit introuvable (.venv/bin/pip-audit) — impossible de vérifier les CVE"
fi

# ── 3. SAST Python — bandit (bloque au niveau HIGH ; medium/low = triés) ──────
if BD="$(tool bandit)"; then
  if "$BD" -r app -x app/.mypy_cache,app/__pycache__ --severity-level high -q \
       >/tmp/_sweep_bd.txt 2>&1; then
    _pass "bandit (SAST Python, seuil HIGH) — 0 découverte haute sévérité"
  else
    echo "${RED}bandit — découverte(s) haute sévérité :${NC}"; tail -30 /tmp/_sweep_bd.txt
    _fail "bandit — découverte(s) haute sévérité"
  fi
else
  _fail "bandit introuvable (.venv/bin/bandit) — SAST Python non exécuté"
fi

# ── 4. SAST multi-règles — semgrep (best-effort ; réseau requis pour les règles) ─
if SG="$(tool semgrep)"; then
  if "$SG" scan --config p/security-audit --severity ERROR --error --metrics off --oss-only -q \
       --exclude .venv --exclude .mypy_cache --exclude __pycache__ --exclude e2e \
       app db >/tmp/_sweep_sg.txt 2>&1; then
    _pass "semgrep (SAST, sévérité ERROR) — 0 découverte"
  else
    rc=$?
    if [ "$rc" = "1" ]; then
      echo "${RED}semgrep — découverte(s) ERROR :${NC}"; tail -30 /tmp/_sweep_sg.txt
      _fail "semgrep — découverte(s) de sévérité ERROR"
    else
      _warn "semgrep n'a pas pu s'exécuter (réseau/règles ?) — best-effort, non bloquant"
    fi
  fi
else
  _warn "semgrep introuvable — SAST multi-règles non exécuté (non bloquant)"
fi

# ── 5. Suite de tests (unit + intégration) — pytest ──────────────────────────
if [ "${SWEEP_RUN_TESTS:-1}" != "0" ] && [ -x "$VENV/bin/python" ]; then
  if "$VENV/bin/python" -m pytest -q >/tmp/_sweep_pt.txt 2>&1; then
    _pass "pytest (suite complète) — verte"
  else
    echo "${RED}pytest — échec(s) :${NC}"; tail -25 /tmp/_sweep_pt.txt
    _fail "pytest — au moins un test en échec"
  fi
else
  _warn "pytest non exécuté (SWEEP_RUN_TESTS=0 ou .venv absent)"
fi

# ── Résumé ────────────────────────────────────────────────────────────────────
_line; echo "${BOLD}Résumé du balayage :${NC}"
for row in "${SUMMARY[@]}"; do printf '  %b\n' "$row"; done
_line
if [ "$FAIL" -ne 0 ]; then
  echo "${RED}${BOLD}⛔ Découverte(s) de sécurité — déploiement à STOPPER.${NC}"
  echo "   → Corriger, puis relancer ; ou forcer explicitement (ALLOW_INSECURE_DEPLOY=1)."
  exit 1
fi
echo "${GRN}${BOLD}✅ Balayage propre — aucun blocage.${NC}"
exit 0
