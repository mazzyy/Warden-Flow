#!/usr/bin/env bash
#
# Warden Flow — one-command setup & run
# ------------------------------------------------------------------
# Creates the virtualenv, installs dependencies, prepares .env, and runs
# a free offline smoke test (scripted models — no API key, no cloud, no spend).
#
#   ./setup.sh            # set up + run the offline demo (default)
#   ./setup.sh --test     # set up + run the test suite and policy probe
#   ./setup.sh --live     # set up + run against real Gemini (needs GOOGLE_API_KEY in .env)
#   ./setup.sh --dashboard# set up + build and serve the dashboard on :8080
#   ./setup.sh --setup    # set up only, run nothing
#   ./setup.sh --help
#
# Safe to re-run: it skips work that is already done.
# ------------------------------------------------------------------

set -euo pipefail

# --- locate the repo (this script lives at the repo root) -------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

# --- pretty output ----------------------------------------------------------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; DIM=""; RESET=""
fi
say()  { printf "%s\n" "${BOLD}▸ $*${RESET}"; }
ok()   { printf "%s\n" "${GREEN}✓ $*${RESET}"; }
warn() { printf "%s\n" "${YELLOW}! $*${RESET}"; }
die()  { printf "%s\n" "${RED}✗ $*${RESET}" >&2; exit 1; }

MODE="demo"
case "${1:-}" in
  --test)       MODE="test" ;;
  --live)       MODE="live" ;;
  --bench)      MODE="bench" ;;
  --deliver)    MODE="deliver" ;;
  --bench-deliver) MODE="bench_deliver" ;;
  --dashboard)  MODE="dashboard" ;;
  --setup)      MODE="setup" ;;
  --help|-h)
    cat <<'EOF'
Warden Flow — one-command setup & run

  ./setup.sh             set up + run the offline demo (default, free)
  ./setup.sh --test      set up + run the test suite and policy probe
  ./setup.sh --bench     set up + run the incident workflow-vs-single-prompt benchmark (free)
  ./setup.sh --deliver   set up + run the DELIVER workflow (assess -> Dockerfile -> pipeline -> plan)
  ./setup.sh --bench-deliver  set up + run the containerize workflow-vs-single-prompt benchmark
  ./setup.sh --live      set up + run against real Gemini (needs GOOGLE_API_KEY in .env)
  ./setup.sh --dashboard set up + build and serve the dashboard on :8080
  ./setup.sh --setup     set up only, run nothing
  ./setup.sh --help      this message

Safe to re-run: it skips work that is already done.
EOF
    exit 0 ;;
  "" )          MODE="demo" ;;
  * )           die "unknown option: $1  (try --help)" ;;
esac

# --- 1. python check --------------------------------------------------------
say "Checking Python (need >= 3.11)"
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.11+ and re-run."
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PYMAJ="${PYV%%.*}"; PYMIN="${PYV##*.}"
if [ "$PYMAJ" -lt 3 ] || { [ "$PYMAJ" -eq 3 ] && [ "$PYMIN" -lt 11 ]; }; then
  die "Python $PYV is too old. Need 3.11+."
fi
ok "Python $PYV"

# --- 2. virtualenv ----------------------------------------------------------
if [ ! -d "$VENV" ]; then
  say "Creating virtualenv (.venv)"
  python3 -m venv "$VENV"
  ok "virtualenv created"
else
  ok "virtualenv already exists"
fi

# --- 3. dependencies --------------------------------------------------------
say "Installing dependencies"
"$PIP" install -U pip -q
if [ -f requirements-dev.txt ]; then
  "$PIP" install -r requirements-dev.txt -q
else
  "$PIP" install -r requirements.txt -q
fi
ok "dependencies installed"

# --- 4. .env ----------------------------------------------------------------
if [ ! -f .env ]; then
  say "Creating .env from .env.example"
  cp .env.example .env
  ok ".env created  ${DIM}(offline runs need nothing more; live runs need GOOGLE_API_KEY)${RESET}"
else
  ok ".env already present"
fi

echo
ok "Setup complete."
echo

# --- 5. run -----------------------------------------------------------------
case "$MODE" in
  setup)
    cat <<EOF
${BOLD}Next:${RESET}
  ./setup.sh            one incident, offline & free (scripted models)
  ./setup.sh --test     run the test suite + policy probe
  ./setup.sh --live     run against real Gemini (add GOOGLE_API_KEY to .env first)
  ./setup.sh --dashboard build + serve the dashboard on http://localhost:8080
EOF
    ;;

  test)
    say "Policy probe (agent × tool matrix)"
    "$PY" -m warden.probe --explain || warn "probe returned non-zero"
    echo
    say "Test suite (offline, no key, no spend)"
    "$PY" -m pytest -q
    echo
    ok "Green suite = 'no agent can write to the cluster' still holds."
    ;;

  demo)
    say "Running ONE incident end to end — offline, scripted models, free"
    echo "${DIM}  triage → diagnose → remediate (dry-run PR). No API key used.${RESET}"
    echo
    "$PY" -m warden.agents.demo
    echo
    ok "That was the scripted run. For real Gemini: ./setup.sh --live"
    ;;

  bench)
    say "Benchmark — structured workflow vs a single prompt, scored + reflection"
    echo "${DIM}  offline, deterministic, free. For real Gemini: make bench-live${RESET}"
    echo
    "$PY" -m warden.bench
    ;;

  deliver)
    say "DELIVER workflow — assess a repo, generate a Dockerfile + pipeline + deploy plan"
    echo "${DIM}  offline, free. For real models (incl. Azure GPT-5.6): make deliver-live${RESET}"
    echo
    "$PY" -m warden.deliver
    ;;

  bench_deliver)
    say "Benchmark — containerize a service, workflow vs single prompt (scored on best practices)"
    echo "${DIM}  offline, free. For real models: make bench-deliver-live${RESET}"
    echo
    "$PY" -m warden.bench_deliver
    ;;

  live)
    # Live mode needs a model credential. Offline needs none.
    if ! grep -Eq '^GOOGLE_API_KEY=.+' .env && ! grep -Eq '^GOOGLE_GENAI_USE_ENTERPRISE=1' .env; then
      warn "Live mode needs a model credential and none is set in .env."
      cat <<EOF
${DIM}Pick one path in .env:
  PATH A (Gemini API, free tier): set GOOGLE_GENAI_USE_ENTERPRISE=0 and
          GOOGLE_API_KEY=...   (get a key at https://aistudio.google.com/apikey)
  PATH B (Vertex AI):            set GOOGLE_GENAI_USE_ENTERPRISE=1 and run
          gcloud auth application-default login${RESET}
EOF
      die "Add a credential to .env, then re-run ./setup.sh --live"
    fi
    say "Running ONE incident against REAL Gemini (this spends tokens)"
    echo
    "$PY" -m warden.agents.demo --live
    echo
    ok "After you merge the opened PR, close the loop with:"
    echo "   $PY -m warden.agents.demo --verify-only"
    ;;

  dashboard)
    say "Building + serving the dashboard on http://localhost:8080"
    if [ ! -d warden/dashboard/web/dist ]; then
      command -v npm >/dev/null 2>&1 || die "npm not found — needed to build the dashboard UI."
      ( cd warden/dashboard/web && npm install && npm run build )
    fi
    ok "Open http://localhost:8080  (Ctrl-C to stop)"
    exec "$PY" -m uvicorn warden.dashboard.api:app --port 8080 --reload
    ;;
esac
