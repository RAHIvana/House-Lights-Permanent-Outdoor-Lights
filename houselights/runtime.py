"""Process-wide state shared by __main__ and the app: the running server, so saving the
settings can restart it with the new configuration."""
import threading
import time

server = None           # the uvicorn.Server, set by __main__
restart = False         # set when the settings were saved: __main__ starts a fresh process


def request_restart(delay=1.0):
    """Finish the current request, then stop the server; __main__ starts it again."""
    global restart
    restart = True

    def go():
        time.sleep(delay)
        if server is not None:
            server.should_exit = True
    threading.Thread(target=go, name="restart", daemon=True).start()
    return server is not None
