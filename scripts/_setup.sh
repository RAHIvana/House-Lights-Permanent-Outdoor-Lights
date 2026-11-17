# Shared by pi-dashboard.sh and mac-dashboard.sh: find Python 3.10 or newer, make the virtual
# environment (venv/) and install requirements.txt, each only when needed. Not run by itself:
# the other scripts "source" it (. _setup.sh), so it has no #! line and needs no execute bit.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/venv"
VPY="$VENV/bin/python"
STAMP="$VENV/.requirements-stamp"           # what was installed last: a hash of requirements.txt (+ tinytuya)
DATA="${HOUSELIGHTS_HOME:-$ROOT/data}"      # the settings folder (config.json, logs/), as the program finds it

say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
run_sudo() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi; }

python_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }

# The first Python (3.10 or newer) found: $PYTHON if you set it, else python3, python3.13 ... python3.10.
find_python() {
    local c
    for c in "${PYTHON:-}" python3 python3.13 python3.12 python3.11 python3.10 python; do
        if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 && python_ok "$c"; then
            command -v "$c"
            return 0
        fi
    done
    return 1
}

hash_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1; else shasum -a 256 | cut -d' ' -f1; fi
}

# Tuya / Smart Life lights need the optional tinytuya package; install it when the settings use one.
uses_tuya() { [ -f "$DATA/config.json" ] && grep -q '"type"[[:space:]]*:[[:space:]]*"tuya"' "$DATA/config.json"; }

fingerprint() {
    { cat "$ROOT/requirements.txt"; if uses_tuya; then echo tinytuya; fi; } | hash_of
}

# The port the dashboard listens on, from the settings (8090 when there are none yet).
configured_port() {
    "$VPY" - "$DATA/config.json" <<'PY' 2>/dev/null || echo 8090
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8-sig")).get("listen", {}).get("port") or 8090)
except Exception:
    print(8090)
PY
}

# Everything the dashboard needs before it can start. Safe to run any number of times.
ensure_env() {
    cd "$ROOT"
    [ -f requirements.txt ] || die "requirements.txt not found in $ROOT. Run this script from a House Lights folder."

    local py
    if ! py="$(find_python)"; then
        die "House Lights needs Python 3.10 or newer, and none was found ($(python3 --version 2>&1 || echo 'python3 is not installed')).
  Raspberry Pi OS: sudo apt install python3 python3-venv   (the Bookworm release or newer; Bullseye has Python 3.9)
  Mac: install Python from python.org, or with: brew install python
  Then run this again. To use a Python in another place: PYTHON=/path/to/python3 $0 ..."
    fi

    # A venv/ that is incomplete (its Python is missing or a dangling link) or has an old Python is made
    # again, but only when it really is a virtual environment (it has pyvenv.cfg); anything else is yours.
    if [ -e "$VENV" ] || [ -L "$VENV" ]; then
        if [ ! -x "$VPY" ] || ! python_ok "$VPY"; then
            [ -f "$VENV/pyvenv.cfg" ] || die "$VENV exists but is not a Python virtual environment. Move or delete it, then run this again."
            say "The virtual environment in venv/ is broken or has an old Python: making it again."
            rm -rf "$VENV"
        fi
    fi
    if [ ! -x "$VPY" ]; then
        say "Making the virtual environment (venv/) with $("$py" --version 2>&1) ..."
        if ! "$py" -m venv "$VENV" >/dev/null 2>&1; then
            rm -rf "$VENV"
            command -v apt-get >/dev/null 2>&1 || die "Could not make the virtual environment. Install Python's venv module and try again."
            say "Python's venv module is missing: installing python3-venv (it may ask for your password) ..."
            run_sudo apt-get install -y python3-venv || die "Could not install python3-venv. Try: sudo apt update, then run this again."
            "$py" -m venv "$VENV" || die "Could not make the virtual environment."
        fi
        python_ok "$VPY" || die "The virtual environment was made, but its Python does not run: $VPY"
    fi

    local want have=""
    want="$(fingerprint)"
    [ -f "$STAMP" ] && have="$(cat "$STAMP")"
    if [ "$want" != "$have" ]; then
        say "Installing what House Lights needs (first time, or requirements.txt changed; a Pi 3 can take a few minutes) ..."
        "$VPY" -m pip install --disable-pip-version-check -r requirements.txt
        if uses_tuya; then
            say "Your settings use Tuya / Smart Life lights: installing tinytuya too."
            "$VPY" -m pip install --disable-pip-version-check tinytuya
        fi
        printf '%s\n' "$want" > "$STAMP"
    fi
}
