#!/usr/bin/env python3
"""Serve this fixture over HTTP without the http.server traceback.

Usage:
    python3 serve.py [port] [directory]

Defaults: port 8080, the build/ directory.

If the port already answers with this directory's run marker, it reports that and exits 0.
If the port is free, it serves in the foreground. If another process holds the port,
it prints one line and exits 1 instead of printing a traceback.
"""

import http.server
import pathlib
import socket
import sys
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
DIRECTORY = pathlib.Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else SCRIPT_DIR / "build"


def fixture_answers(port):
    # Loopback is only an internal port probe, never a published download URL.
    marker = DIRECTORY / "fixture-run.json"
    if not marker.is_file():
        return False
    expected = marker.read_bytes()
    url = f"http://127.0.0.1:{port}/fixture-run.json"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            return response.status == 200 and response.read(len(expected) + 1) == expected
    except Exception:
        return False


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main():
    if fixture_answers(PORT):
        print(f"server already serving on port {PORT}; nothing to do")
        return 0
    if port_in_use(PORT):
        print(f"port {PORT} is held by another process; stop it or pass a different port", file=sys.stderr)
        return 1
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(
        *args, directory=str(DIRECTORY), **kwargs
    )
    try:
        server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), handler)
    except OSError as error:
        print(f"cannot listen on port {PORT}: {error}", file=sys.stderr)
        return 1
    print(f"serving {DIRECTORY}; listening on all interfaces, port {PORT}")
    print("Use the explicit base URL selected during generation, not the bind address, in evilo.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
