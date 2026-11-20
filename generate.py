#!/usr/bin/env python3
"""Generate N single-plugin repositories plus a signed subscription index.

Usage:
    python3 generate.py [count] [base-url]

Defaults: 100 plugins at http://127.0.0.1:8080.

Generated repositories and the index are written to build/.

The signing seed is a fixed test value so the fingerprint is stable between runs.
Never use it for a real collection.
"""

import json
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 100
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8080"
TEST_SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "build"


def base_port(base):
    """The TCP port a base URL listens on, defaulting per scheme."""
    parsed = urlparse(base)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def reachable(url, timeout=2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def listener_pid(port):
    """PID holding the TCP port, or None when it cannot be determined."""
    try:
        result = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"],
                                capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"pid=(\d+)", result.stdout)
    return int(match.group(1)) if match else None


def is_fixture_server(pid):
    """True when pid is an http.server started for this project."""
    try:
        cmdline = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        cwd = pathlib.Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        return False
    return "http.server" in cmdline and (cwd == ROOT or str(ROOT) in cmdline)


def ensure_server():
    """Serve OUT over HTTP so build_index can fetch the catalogs.

    Reuses a server that is already answering BASE (a previous run's) and otherwise
    starts a detached one serving OUT. A leftover server from the old layout, which
    serves ROOT instead of OUT, is stopped and replaced automatically.
    """
    if COUNT == 0:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    probe_url = f"{BASE.rstrip('/')}/plugin-000/catalog.json"
    if reachable(probe_url):
        print(f"server already serving {OUT} at {BASE}")
        return
    port = base_port(BASE)
    if port_in_use(port):
        pid = listener_pid(port)
        if pid is not None and is_fixture_server(pid):
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + 5.0
            while time.time() < deadline and port_in_use(port):
                time.sleep(0.1)
            print(f"stopped stale server pid {pid} that served the previous layout")
        else:
            raise SystemExit(
                f"port {port} is held by another process; stop it or pass a different base URL"
            )
    with open(OUT / "server.log", "ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0", "--directory", str(OUT)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if reachable(probe_url):
            print(f"started server pid {process.pid} on port {port} serving {OUT}")
            return
        if process.poll() is not None:
            break
        time.sleep(0.2)
    raise SystemExit(
        f"could not serve {BASE}: port {port} is held by another process that does not "
        f"serve {OUT}. Stop it, then rerun."
    )


ARTIFACTS = ("index.json", "index.json.sig", "index.json.pub", "repo.json",
             "sources.txt", "collection.json")


def clean():
    """Remove a previous run, including the old root-level layout."""
    for parent in (ROOT, OUT):
        if not parent.exists():
            continue
        for directory in parent.iterdir():
            if directory.is_dir() and re.fullmatch(r"plugin-\d{3,}", directory.name):
                shutil.rmtree(directory)
        for name in ARTIFACTS:
            (parent / name).unlink(missing_ok=True)


def write_repos():
    OUT.mkdir(parents=True, exist_ok=True)
    for i in range(COUNT):
        entry = {
            "version": "1.0.0",
            "versionCode": 1,
            "publishedAt": "2026-11-19",
            "manifestUrl": f"{BASE}/plugin-{i:03d}/manifest.wlm",
            "sourceRevision": "a" * 39 + str(i % 10),
            "sourceArchiveUrl": f"{BASE}/plugin-{i:03d}/sources.zip",
            "sourceArchiveSha256": f"{i:064x}"[-64:],
        }
        plugin = {
            "id": f"com.example.plugin{i:03d}",
            "name": f"Example Plugin {i:03d}",
            "authors": [f"Author {i:03d}"],
            "description": f"Demonstration provider {i:03d}.",
            "languages": ["en"],
            "kinds": ["manga" if i % 2 == 0 else "novel"],
            "sourceUrl": f"{BASE}/plugin-{i:03d}/",
            "availableVersions": [entry],
        }
        directory = OUT / f"plugin-{i:03d}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "catalog.json").write_text(
            json.dumps({"name": f"Plugin {i:03d}", "plugins": [plugin]}, indent=2) + "\n")


def write_sources():
    (OUT / "sources.txt").write_text("\n".join(
        f"{BASE}/plugin-{i:03d}/catalog.json" for i in range(COUNT)) + "\n")


def write_collection():
    (OUT / "collection.json").write_text(json.dumps({
        "name": f"{COUNT} plugin test",
        "indexUrl": f"{BASE}/index.json",
        "keyId": "subscription",
    }, indent=2) + "\n")


def build_index():
    write_collection()
    environment = dict(os.environ, EVILO_SUBSCRIBE_KEY_HEX=TEST_SEED, EVILO_BUILD_DIR=str(OUT))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_index.py")],
                   cwd=ROOT, env=environment, check=True)


if __name__ == "__main__":
    clean()
    write_repos()
    write_sources()
    write_collection()
    print(f"wrote {COUNT} repositories under {OUT}")
    ensure_server()
    build_index()
