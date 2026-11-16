"""Start the House Lights server:

    python -m houselights [--home DIR] [--host HOST] [--port PORT] [--dry]

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
    args = ap.parse_args()

    if args.home:
        os.environ["HOUSELIGHTS_HOME"] = os.path.abspath(args.home)
    if args.dry:
        os.environ["HOUSELIGHTS_DRY"] = "1"

    import uvicorn
    from . import runtime, settings

    os.makedirs(settings.path("logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(settings.path("logs", "houselights.log")),
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
    server.run()

    if runtime.restart:                           # settings saved: start again with them
        logging.getLogger("houselights").info("restarting with the new settings")
        pkg_parent = os.path.dirname(settings.PKG)
        os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [pkg_parent, os.environ.get("PYTHONPATH")]))
        os.execv(sys.executable, [sys.executable, "-m", "houselights", *sys.argv[1:]])


if __name__ == "__main__":
    main()
