#!/usr/bin/env python3
"""Create one local fixture publisher authority, only when explicitly invoked.

Usage: python3 -I scripts/setup_signing.py /external/private/directory
Generation/builds never call this script. Never use fixture keys for production.
"""

import argparse
import hashlib
import importlib.util
import os
import pathlib
import secrets

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=pathlib.Path)
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    # Exclude all neighboring source repositories as well as this one.
    if (directory == ROOT.parent or ROOT.parent in directory.parents or
            any((parent / ".git").exists() for parent in (directory,) + tuple(directory.parents))):
        parser.error("choose a private directory outside all Git repositories and the repository parent directory")
    if directory.exists():
        parser.error("directory already exists; keys are never overwritten")
    spec = importlib.util.spec_from_file_location("build_index", ROOT / "scripts/build_index.py")
    signing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signing)
    seed = secrets.token_bytes(32)
    public = signing.public_from_seed(seed)
    fingerprint = hashlib.sha256(public).hexdigest()
    directory.mkdir(mode=0o700, parents=True)
    values = {
        "private.key": seed.hex() + "\n",
        "public.key": public.hex() + "\n",
        "authority.properties": f"keyId=publisher-{fingerprint}\npublicKeyHex={public.hex()}\n",
    }
    for name, value in values.items():
        descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(value)
    print(f"Created external fixture authority. Public fingerprint: {fingerprint}")
    print("Back up the directory privately. No application key configuration was changed.")


if __name__ == "__main__":
    main()
