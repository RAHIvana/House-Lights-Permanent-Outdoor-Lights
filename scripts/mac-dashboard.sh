#!/usr/bin/env bash
# House Lights on a Mac (also works on Linux without systemd): set up, start, stop, check.
# Run it from anywhere:  scripts/mac-dashboard.sh COMMAND     (or: bash scripts/mac-dashboard.sh COMMAND)
# It runs the dashboard as a background process; it does not start by itself when the Mac starts.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/_setup.sh"

PIDFILE="$DATA/dashboard.pid"
LOG="$DATA/logs/houselights.log"          # the program's own log file
CONSOLE="$DATA/logs/console.log"          # what it prints in the terminal (start-up and errors)

usage() {
    cat <<EOF
House Lights on a Mac.

Usage: scripts/mac-dashboard.sh COMMAND

  start [...]  Set up if needed (checks Python 3.10+, makes venv/, installs requirements.txt),
               then start the dashboard in the background.
               Extra words go to the program: start --dry  is practice mode (nothing is sent
               to the lights; commands are only logged), start --port 8091 uses another port
  stop         Stop it
  restart      Stop and start it again (use after git pull or a settings change)
  status       Running? What address to open?
  logs         Follow the log (Ctrl+C to leave)
  run [...]    Run it in this terminal instead: Ctrl+C stops it. Same extra words as start.
  setup        Only the setup part of start (Python, venv/, requirements)

Settings are kept in data/ (config.json and more); this script never touches them.
EOF
}

# Is the process in the pid file alive, and really House Lights (not a number that was reused)?
is_running() {
    [ -f "$PIDFILE" ] || return 1
    local pid cmd; pid="$(cat "$PIDFILE")"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    [[ "$cmd" == *houselights* ]]
}

# The port it listens on: the one it was started with (--port N), else the one in the settings.
running_port() {
    local c; c="$(ps -p "$(cat "$PIDFILE")" -o command= 2>/dev/null || true)"
    case "$c" in
        *"--port "*) c="${c##*--port }"; echo "${c%% *}" ;;
        *)           configured_port ;;
    esac
}

where_to_open() {
    local port ip name
    port="$(running_port)"
    ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)"
    name="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
    say "Open:  http://localhost:$port/"
    if [ -n "$ip" ]; then say "From your phone on the same Wi-Fi:  http://$ip:$port/   (or http://$name.local:$port/)"; fi
}

cmd_start() {
    ensure_env
    if is_running; then
        say "House Lights is already running (process $(cat "$PIDFILE"))."
        where_to_open
        return 0
    fi
    mkdir -p "$DATA/logs"
    cd "$ROOT"
    nohup "$VPY" -m houselights "$@" >>"$CONSOLE" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 4
    if is_running; then
        say "House Lights is running."
        where_to_open
    else
        rm -f "$PIDFILE"
        say "House Lights did not stay up. The last lines it printed:" >&2
        tail -n 15 "$CONSOLE" >&2 || true
        die "The lines above say why. (A copy started with 'run' in another terminal would also be a reason: stop it with Ctrl+C.)"
    fi
}

cmd_stop() {
    if ! is_running; then
        rm -f "$PIDFILE"
        say "House Lights is not running."
        return 0
    fi
    local pid i; pid="$(cat "$PIDFILE")"
    kill -TERM "$pid" 2>/dev/null || true           # a clean stop: animations are taken off the controllers
    for i in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
        say "It did not stop by itself within 10 seconds, so it was ended."
    fi
    rm -f "$PIDFILE"
    say "Stopped."
}

cmd_status() {
    if is_running; then
        say "Running:  yes (process $(cat "$PIDFILE"))"
        where_to_open
    else
        say "Running:  no"
    fi
    if [ -f "$LOG" ]; then echo; tail -n 5 "$LOG"; fi
}

cmd_logs() {
    [ -f "$LOG" ] || die "No log yet: $LOG. Start it first."
    exec tail -n 50 -f "$LOG"
}

cmd_run() {
    ensure_env
    if is_running; then
        say "Note: House Lights is already running in the background, so this copy cannot use the same port."
        say "      Run 'scripts/mac-dashboard.sh stop' first, or add --port 8091."
    fi
    cd "$ROOT"
    exec "$VPY" -m houselights "$@"
}

cmd="${1:-help}"
[ $# -gt 0 ] && shift
case "$cmd" in
    start)    cmd_start "$@" ;;
    stop)     cmd_stop ;;
    restart)  cmd_stop; cmd_start "$@" ;;
    status)   cmd_status ;;
    logs)     cmd_logs ;;
    run)      cmd_run "$@" ;;
    setup)    ensure_env; say "Ready: Python, venv/ and requirements are in place." ;;
    help|-h|--help) usage ;;
    *)        printf 'Unknown command: %s\n\n' "$cmd" >&2; usage >&2; exit 2 ;;
esac
