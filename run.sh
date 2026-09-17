#!/usr/bin/env bash
#
# One-stop wrapper for transferring liked YouTube videos between accounts.
#
# Handles the virtualenv + dependencies automatically, so for repeated daily
# use you just run:
#
#     ./run.sh status          # see progress
#     ./run.sh import          # resume liking (safe to re-run every day)
#
# First-time setup:
#     ./run.sh setup /path/to/client_secret.json
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

CLIENT_SECRET="client_secret.json"
OLD_TOKEN="tokens/old_account.token.json"
NEW_TOKEN="tokens/new_account.token.json"
LIKED="liked.json"
STATE="liked_state.json"

# --- pretty output -----------------------------------------------------------
info() { printf '\033[1;34m[info]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ ok ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[err ]\033[0m %s\n' "$*" >&2; }

usage() {
    cat <<'EOF'
Usage: ./run.sh <command> [options]

Commands:
  setup [CLIENT_SECRET_JSON]   Create venv, install deps, (optionally) copy
                               your client_secret.json into place.
  export [options]             Log in as the OLD account and save liked videos.
  import [options]             Log in as the NEW account and like them.
                               Safe to re-run daily; resumes automatically.
  status                       Show progress (no API calls, no login).
  help                         Show this message.

Common options (passed through to the Python script):
  --limit N      Process at most N videos this run.
  --delay SEC    Seconds between like calls on import (default 1).
EOF
}

ensure_venv() {
    if [[ ! -x "$PY" ]]; then
        info "Creating virtual environment (.venv)..."
        python3 -m venv "$VENV"
    fi
    if ! "$PY" -c 'import googleapiclient' >/dev/null 2>&1; then
        info "Installing dependencies (one-time)..."
        "$PIP" install --quiet --upgrade pip
        "$PIP" install --quiet -r requirements.txt
    fi
}

ensure_secrets() {
    [[ -f "$CLIENT_SECRET" ]] && return 0
    err "Missing $CLIENT_SECRET"
    cat <<'EOF'

You need a Google Cloud OAuth client first. Steps:
  1. https://console.cloud.google.com/  -> create/select a project
  2. Enable "YouTube Data API v3" (APIs & Services -> Library)
  3. OAuth consent screen -> External -> add yourself as a test user
  4. Credentials -> Create credentials -> OAuth client ID -> Desktop app
  5. Download the JSON, then run:

       ./run.sh setup /path/to/your/client_secret.json
EOF
    exit 1
}

# The client secret is only an argument to `setup`. If someone passes it (or
# any client-secret-looking filename) to export/import, explain instead of
# letting argparse print an opaque "unrecognized arguments" error.
reject_secret_arg() {
    local a
    for a in "$@"; do
        case "$a" in
            *client_secret*)
                err "You passed '$a', but the client secret is only needed for 'setup'."
                err "Run these without any filename argument:"
                err "  ./run.sh export"
                err "  ./run.sh import"
                return 1
                ;;
        esac
    done
}

do_setup() {
    ensure_venv
    if [[ $# -gt 0 ]]; then
        cp "$1" "$CLIENT_SECRET"
        ok "Copied client secret to $CLIENT_SECRET"
    fi
    ensure_secrets
    ok "Setup complete."
    echo
    cat <<'EOF'
Next steps:
  ./run.sh export    # once, as your OLD account
  ./run.sh import    # as your NEW account (re-run daily to resume)
  ./run.sh status    # check progress
EOF
}

cmd="${1:-help}"
shift || true

case "$cmd" in
    setup)
        do_setup "$@"
        ;;
    export)
        reject_secret_arg "$@" || exit 1
        ensure_venv
        ensure_secrets
        info "Exporting liked videos from the OLD account..."
        "$PY" transfer_likes.py export \
            --secrets "$CLIENT_SECRET" \
            --token "$OLD_TOKEN" \
            --out "$LIKED" \
            "$@"
        ok "Export done. Now run: ./run.sh import"
        ;;
    import)
        reject_secret_arg "$@" || exit 1
        ensure_venv
        ensure_secrets
        info "Importing likes into the NEW account..."
        "$PY" transfer_likes.py import \
            --secrets "$CLIENT_SECRET" \
            --token "$NEW_TOKEN" \
            --in "$LIKED" \
            --state "$STATE" \
            "$@"
        ok "Import finished. Re-run: ./run.sh import (or ./run.sh status) anytime."
        ;;
    status)
        python3 transfer_likes.py status \
            --in "$LIKED" \
            --state "$STATE" \
            "$@"
        ;;
    help|-h|--help)
        usage
        ;;
    *)
        err "Unknown command: $cmd"
        usage
        exit 1
        ;;
esac
