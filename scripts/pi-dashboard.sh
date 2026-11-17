#!/usr/bin/env bash
# House Lights on a Raspberry Pi (or any Linux with systemd): set up, start, stop, check.
# Run it from anywhere:  scripts/pi-dashboard.sh COMMAND     (or: bash scripts/pi-dashboard.sh COMMAND)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/_setup.sh"

SERVICE=houselights
UNIT="/etc/systemd/system/$SERVICE.service"

usage() {
    cat <<EOF
House Lights on a Raspberry Pi.

Usage: scripts/pi-dashboard.sh COMMAND

  start      Set up if needed (checks Python 3.10+, makes venv/, installs requirements.txt),
             then start the dashboard now, and again at every boot
  stop       Stop it now (it still starts at the next boot)
  restart    Stop and start it again (use after git pull or a settings change)
  status     Running? Starts at boot? What address to open?
  boot-off   Stop it now AND don't start it at the next boot
  boot-on    Start it at every boot (without starting it now)
  logs       Follow the log (Ctrl+C to leave)
  run [...]  Run it in this terminal instead, for a first try: Ctrl+C stops it.
             Extra words go to the program: run --dry  is practice mode (nothing is sent to
             the lights; commands are only logged), run --port 8091 uses another port
  setup      Only the setup part of start (Python, venv/, requirements)

Settings are kept in data/ (config.json and more); this script never touches them.
EOF
}

need_systemd() { command -v systemctl >/dev/null 2>&1 || die "systemd was not found on this computer. Use 'run' instead, or see README_Raspberry.md."; }
need_installed() { [ -f "$UNIT" ] || die "House Lights is not installed as a service yet. Run: scripts/pi-dashboard.sh start"; }
is_active() { systemctl is-active --quiet "$SERVICE"; }

lan_ip() { hostname -I 2>/dev/null | awk '{print $1}'; }
where_to_open() {
    local port; port="$(configured_port)"
    say "Open on your phone or computer:  http://$(lan_ip):$port/   (or http://$(hostname).local:$port/)"
}

unit_text() {
    cat <<EOF
[Unit]
Description=House Lights dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
ExecStart="$VPY" -m houselights
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

# Write the service file when it is missing or out of date (a moved folder, an older copy).
install_unit() {
    local new; new="$(unit_text)"
    if [ ! -f "$UNIT" ] || [ "$(cat "$UNIT")" != "$new" ]; then
        say "Installing the $SERVICE service (it may ask for your password) ..."
        printf '%s\n' "$new" | run_sudo tee "$UNIT" >/dev/null
        run_sudo systemctl daemon-reload
    fi
}

# After starting: give it a few seconds, then say plainly whether it is up.
confirm_up() {
    local i
    for i in 1 2 3 4 5 6; do sleep 1; done
    if is_active; then
        say "House Lights is running."
        where_to_open
    else
        say "House Lights did not stay up. The last lines of its log:" >&2
        journalctl -u "$SERVICE" -n 15 --no-pager >&2 || true
        die "The lines above say why. (A copy started with 'run' in another terminal would also be a reason: stop it with Ctrl+C.)"
    fi
}

cmd_start() {
    need_systemd
    ensure_env
    install_unit
    if ! run_sudo systemctl enable "$SERVICE" >/dev/null 2>&1; then say "(Could not set it to start at boot.)"; fi
    if is_active; then
        say "House Lights is already running."
        where_to_open
    else
        run_sudo systemctl start "$SERVICE"
        confirm_up
    fi
    say "It will also start by itself at every boot ('boot-off' to stop that)."
}

cmd_restart() {
    need_systemd
    ensure_env
    install_unit
    run_sudo systemctl restart "$SERVICE"
    confirm_up
}

cmd_stop() {
    need_systemd; need_installed
    run_sudo systemctl stop "$SERVICE"
    say "Stopped. It will start again at the next boot; use 'boot-off' to stop that too."
}

cmd_boot_off() {
    need_systemd; need_installed
    run_sudo systemctl stop "$SERVICE"
    run_sudo systemctl disable "$SERVICE" >/dev/null 2>&1 || true
    say "Stopped, and it will not start at the next boot. 'start' turns it all back on."
}

cmd_boot_on() {
    need_systemd; need_installed
    run_sudo systemctl enable "$SERVICE" >/dev/null 2>&1 || die "Could not set it to start at boot."
    say "It will start at every boot."
}

cmd_status() {
    need_systemd
    if [ ! -f "$UNIT" ]; then
        say "House Lights is not installed as a service yet. 'start' does it."
        return 0
    fi
    local active enabled
    active="$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
    enabled="$(systemctl is-enabled "$SERVICE" 2>/dev/null || true)"
    if [ "$active" = active ]; then say "Running:          yes"; else say "Running:          no ($active)"; fi
    if [ "$enabled" = enabled ]; then say "Starts at boot:   yes"; else say "Starts at boot:   no ($enabled)"; fi
    if [ "$active" = active ]; then where_to_open; fi
    echo
    journalctl -u "$SERVICE" -n 5 --no-pager 2>/dev/null || true
}

cmd_logs() { need_systemd; need_installed; exec journalctl -u "$SERVICE" -f; }

cmd_run() {
    ensure_env
    if command -v systemctl >/dev/null 2>&1 && is_active; then
        say "Note: the House Lights service is already running, so this copy cannot use the same port."
        say "      Run 'scripts/pi-dashboard.sh stop' first, or add --port 8091."
    fi
    cd "$ROOT"
    exec "$VPY" -m houselights "$@"
}

cmd="${1:-help}"
[ $# -gt 0 ] && shift
case "$cmd" in
    start)    cmd_start ;;
    stop)     cmd_stop ;;
    restart)  cmd_restart ;;
    status)   cmd_status ;;
    boot-off) cmd_boot_off ;;
    boot-on)  cmd_boot_on ;;
    logs)     cmd_logs ;;
    run)      cmd_run "$@" ;;
    setup)    ensure_env; say "Ready: Python, venv/ and requirements are in place." ;;
    help|-h|--help) usage ;;
    *)        printf 'Unknown command: %s\n\n' "$cmd" >&2; usage >&2; exit 2 ;;
esac
