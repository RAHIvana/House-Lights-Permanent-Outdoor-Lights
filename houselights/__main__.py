"""Start the House Lights server:

    python -m houselights [--home DIR] [--host HOST] [--port PORT] [--dry]
    python -m houselights --set-password | --remove-password     (the optional dashboard password)

On the first start there are no settings yet: open the page and the setup wizard appears.
--dry is practice mode: commands are logged and nothing is sent to the lights.
"""
import argparse
import logging
import os
import sys


def main():
    ap = argparse.ArgumentParser(prog="python -m houselights", description="House Lights server")
    ap.add_argument("--home", help="folder for settings, schedules and logs (default: ./data next to the code)")
    ap.add_argument("--host", help="address to listen on (default from settings, else 0.0.0.0)")
    ap.add_argument("--port", type=int, help="port to listen on (default from settings, else 8090)")
    ap.add_argument("--dry", action="store_true", help="practice mode: log commands, send nothing to the lights")
    pw = ap.add_mutually_exclusive_group()
    pw.add_argument("--set-password", action="store_true", help="set or change the dashboard password, then exit")
    pw.add_argument("--remove-password", action="store_true",
                    help="turn the dashboard password off (also the way back in if you forgot it), then exit")
    args = ap.parse_args()

    if args.home:
        os.environ["HOUSELIGHTS_HOME"] = os.path.abspath(args.home)
    if args.dry:
        os.environ["HOUSELIGHTS_DRY"] = "1"

    if args.set_password or args.remove_password:
        from . import auth
        sys.exit(auth.cli(set_it=args.set_password))

    import uvicorn
    from . import runtime, settings

    os.makedirs(settings.path("logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(settings.path("logs", "houselights.log"), encoding="utf-8"),
                                  logging.StreamHandler()])
    try:
        raw = settings.read_raw() or {}
    except ValueError:                            # broken file: the app opens the wizard and says why
        raw = {}
    listen = raw.get("listen") or {}
    host = args.host or listen.get("host") or "0.0.0.0"
    port = args.port or listen.get("port") or 8090
    logging.getLogger("houselights").info("settings in %s; open http://%s:%s/", settings.home(),
                                          "localhost" if host in ("0.0.0.0", "::") else host, port)

    server = uvicorn.Server(uvicorn.Config("houselights.app:app", host=host, port=port,
                                           log_level="info", access_log=False))
    runtime.server = server
    try:
        server.run()
    except KeyboardInterrupt:                     # Ctrl+C: uvicorn has shut down cleanly, then passes
        logging.getLogger("houselights").info("stopped")    # the Ctrl+C on; no traceback
        return

    if runtime.restart:                           # settings saved: start again with them
        logging.getLogger("houselights").info("restarting with the new settings")
        pkg_parent = os.path.dirname(settings.PKG)
        os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [pkg_parent, os.environ.get("PYTHONPATH")]))
        cmd = [sys.executable, "-m", "houselights", *sys.argv[1:]]
        if os.name != "nt":
            os.execv(sys.executable, cmd)         # same process: the terminal or service sees no change
        # Windows has no exec: os.execv starts a new process and ends this one, so the terminal
        # (or service) thinks the server stopped while the new one runs on, out of Ctrl+C's reach.
        # Instead this process stays as a small supervisor that runs the server as its child.
        if os.environ.get(SUPERVISED) == "1":
            sys.exit(RESTART_EXIT)                # the supervisor starts us again
        os.environ[SUPERVISED] = "1"
        sys.exit(_supervise(cmd))


SUPERVISED = "HOUSELIGHTS_SUPERVISED"
RESTART_EXIT = 75                                 # a supervised server asking to be started again


def _supervise(cmd):
    """Windows: run the server as a child until it stops for another reason than a restart."""
    import subprocess
    while True:
        child = subprocess.Popen(cmd)
        while True:
            try:
                code = child.wait()
                break
            except KeyboardInterrupt:             # Ctrl+C reaches the child too (same console):
                continue                          # let it shut down cleanly, then stop with it
        if code != RESTART_EXIT:
            return code


if __name__ == "__main__":
    main()
