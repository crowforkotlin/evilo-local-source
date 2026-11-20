#!/usr/bin/env python3
"""Fetch every listed plugin repository and build a signed subscription index.

Inputs:
    sources.txt           One plugin catalog URL per line; '#' starts a comment.
    collection.json       The collection name and its public identity.
    --key-directory / EVILO_SUBSCRIBE_KEY_DIRECTORY   External preserved authority.
    EVILO_SUBSCRIBE_KEY_HEX   Legacy 64-hex Ed25519 seed environment input.

Outputs (written next to sources.txt):
    index.json            Merged plugin records, the exact bytes that get signed.
    index.json.sig        Ed25519 signature over index.json, lowercase hex.
    index.json.pub        Raw Ed25519 public key, lowercase hex.
    repo.json             The signed subscription pointer.

The index is rebuilt from scratch on every run. It never accumulates state, so a
plugin repository that removes a release or changes a description is reflected
on the next build without any manual editing here.
"""

import argparse
import copy
import hashlib
import json
import os
import pathlib
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = pathlib.Path(os.environ.get("EVILO_BUILD_DIR") or (ROOT / "build")).resolve()
SOURCES = BUILD / "sources.txt"
COLLECTION = BUILD / "collection.json"
INDEX = BUILD / "index.json"
SIGNATURE = BUILD / "index.json.sig"
PUBLIC = BUILD / "index.json.pub"
POINTER = BUILD / "repo.json"

SCHEMA_VERSION = 1
FETCH_TIMEOUT = 30
MAX_BYTES = 10 * 1024 * 1024


def fail(message):
    raise SystemExit(f"build_index: {message}")


def read_sources():
    if not SOURCES.exists():
        fail(f"missing {SOURCES}")
    entries = []
    for number, raw in enumerate(SOURCES.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if not line.startswith(("https://", "http://")):
            fail(f"sources.txt line {number} is not an absolute HTTP(S) URL: {line}")
        if line in entries:
            fail(f"sources.txt line {number} repeats an earlier entry: {line}")
        entries.append(line)
    # An empty list is the template's initial state: it still publishes an empty index so
    # the workflow stays green until a repository is added.
    return entries


def fetch_json(url):
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "evilo-subscribe"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            if response.status != 200:
                fail(f"{url} returned HTTP {response.status}")
            payload = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        fail(f"{url} returned HTTP {error.code}")
    except (urllib.error.URLError, ssl.SSLError, TimeoutError) as error:
        fail(f"{url} is unreachable: {error}")
    if len(payload) > MAX_BYTES:
        fail(f"{url} exceeds {MAX_BYTES} bytes")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as error:
        fail(f"{url} is not JSON: {error}")


def plugin_record(url, plugin):
    """Keep the plugin entry a catalog would publish, narrowed to its newest release.

    The entry is passed through unchanged apart from the release list, so the app applies
    the same defaults to an indexed plugin as to a published one. Carrying that newest
    release is what lets a subscriber install without fetching every plugin catalog.
    """
    versions = plugin.get("availableVersions") or []
    if not versions:
        fail(f"{url} plugin {plugin.get('id')} lists no versions")
    newest = max(versions, key=lambda release: int(release.get("versionCode", 0)))
    entry = copy.deepcopy(plugin)
    entry["availableVersions"] = [newest]
    return {"catalogUrl": url, "plugin": entry}


def read_authority(directory, extra_repositories=()):
    """Read existing external key material; never create keys or print their seed."""
    directory = pathlib.Path(directory).expanduser().resolve()
    if any((parent / ".git").exists() for parent in (directory,) + tuple(directory.parents)):
        fail("signing directories must stay outside Git repositories")
    for repository in (ROOT,) + tuple(extra_repositories):
        if directory == repository.resolve() or repository.resolve() in directory.parents:
            fail("signing directories must stay outside source repositories")
    files = [directory / name for name in ("private.key", "public.key", "authority.properties")]
    if any(not file.is_file() or file.is_symlink() for file in files):
        fail("authority requires regular private.key, public.key, and authority.properties files")
    private = files[0].read_text(encoding="ascii").strip().lower()
    public = files[1].read_text(encoding="ascii").strip().lower()
    if any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in (private, public)):
        fail("authority private/public keys must contain 64 hexadecimal characters")
    metadata = dict(line.split("=", 1) for line in files[2].read_text(encoding="ascii").splitlines()
                    if "=" in line and not line.lstrip().startswith(("#", "!")))
    key_id = metadata.get("keyId", "")
    if (metadata.get("publicKeyHex") != public or not 1 <= len(key_id) <= 128 or
            any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in key_id)):
        fail("authority metadata must match its public key and declare a valid keyId")
    seed = bytes.fromhex(private)
    if public_from_seed(seed).hex() != public:
        fail("authority private/public keys do not match")
    return seed


def local_json(url, base_url):
    """Read this run's catalogs without contacting or starting an HTTP server."""
    base, parsed = urlsplit(base_url.rstrip("/")), urlsplit(url)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc) or parsed.query or parsed.fragment:
        fail(f"local catalog URL is outside the explicit base URL: {url}")
    relative = unquote(parsed.path).lstrip("/")
    path = (BUILD / relative).resolve()
    if BUILD not in path.parents or path.name != "catalog.json":
        fail(f"local catalog URL does not resolve to a fixture catalog: {url}")
    payload = path.read_bytes()
    if len(payload) > MAX_BYTES:
        fail(f"{url} exceeds {MAX_BYTES} bytes")
    return json.loads(payload)


def build_index(sources, local_base=None):
    records = []
    seen = {}
    for url in sources:
        document = local_json(url, local_base) if local_base else fetch_json(url)
        plugins = document.get("plugins")
        if not isinstance(plugins, list):
            fail(f"{url} is not a plugin catalog: it declares no plugins list")
        for plugin in plugins:
            record = plugin_record(url, plugin)
            plugin_id = record["plugin"].get("id")
            if not plugin_id:
                fail(f"{url} contains a plugin without an id")
            previous = seen.get(plugin_id)
            if previous is not None:
                fail(f"plugin id {plugin_id} appears in both {previous} and {url}; an id must have one publisher")
            seen[plugin_id] = url
            records.append(record)
    records.sort(key=lambda record: record["plugin"]["id"])
    updated_at = os.environ.get("EVILO_SUBSCRIBE_UPDATED_AT") or newest_publication(records)
    collection = json.loads(COLLECTION.read_text(encoding="utf-8"))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "name": collection["name"],
        "updatedAt": updated_at,
        "plugins": records,
    }


def newest_publication(records):
    """The newest release date seen, so the field reflects the source data, not the clock."""
    dates = [
        release.get("publishedAt", "")
        for record in records
        for release in record["plugin"]["availableVersions"]
        if release.get("publishedAt")
    ]
    if not dates:
        return "1970-01-01T00:00:00Z"
    newest = max(dates)
    return newest if "T" in newest else f"{newest}T00:00:00Z"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-catalogs", metavar="BASE_URL", help="Read generated catalogs from EVILO_BUILD_DIR; no HTTP calls")
    parser.add_argument("--key-directory", type=pathlib.Path, default=os.environ.get("EVILO_SUBSCRIBE_KEY_DIRECTORY"))
    args = parser.parse_args()
    key_hex = os.environ.get("EVILO_SUBSCRIBE_KEY_HEX", "").strip()
    if key_hex and not (len(key_hex) == 64 and all(character in "0123456789abcdef" for character in key_hex.lower())):
        fail("EVILO_SUBSCRIBE_KEY_HEX must be 64 hexadecimal characters")
    seed = read_authority(args.key_directory) if args.key_directory else (bytes.fromhex(key_hex) if key_hex else None)

    sources = read_sources()
    index = build_index(sources, args.local_catalogs)
    body = (json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(body) > MAX_BYTES:
        fail(f"index exceeds {MAX_BYTES} bytes")
    INDEX.write_bytes(body)

    if seed is None:
        for stale in (SIGNATURE, PUBLIC, POINTER):
            stale.unlink(missing_ok=True)
        print("build_index: no signing key supplied; wrote index.json without a signature")
        return 0

    signature = sign(body, seed)
    public_key = public_from_seed(seed)
    SIGNATURE.write_text(signature.hex() + "\n", encoding="ascii")
    PUBLIC.write_text(public_key.hex() + "\n", encoding="ascii")

    collection = json.loads(COLLECTION.read_text(encoding="utf-8"))
    pointer = {
        "name": collection["name"],
        "indexUrl": collection["indexUrl"],
        "signingKeyFingerprint": hashlib.sha256(public_key).hexdigest(),
        "keyId": collection.get("keyId", "subscription"),
    }
    POINTER.write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"build_index: {len(index['plugins'])} plugins from {len(sources)} repositories")
    print(f"build_index: fingerprint {pointer['signingKeyFingerprint']}")
    return 0


def public_from_seed(seed):
    """Derive the Ed25519 public key from its 32-byte seed, per RFC 8032 section 5.1.5."""
    if len(seed) != 32:
        fail("the signing seed must be 32 bytes")
    digest = hashlib.sha512(seed).digest()
    scalar = bytearray(digest[:32])
    scalar[0] &= 248
    scalar[31] &= 127
    scalar[31] |= 64
    return point_encode(scalar_mult_base(bytes(scalar)))


def sign(message, seed):
    digest = hashlib.sha512(seed).digest()
    scalar = bytearray(digest[:32])
    scalar[0] &= 248
    scalar[31] &= 127
    scalar[31] |= 64
    prefix = digest[32:]
    public_key = point_encode(scalar_mult_base(bytes(scalar)))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % GROUP_ORDER
    r_encoded = point_encode(scalar_mult_base(r.to_bytes(32, "little")))
    h = int.from_bytes(hashlib.sha512(r_encoded + public_key + message).digest(), "little") % GROUP_ORDER
    s = (r + h * int.from_bytes(scalar, "little")) % GROUP_ORDER
    return r_encoded + s.to_bytes(32, "little")


# The Edwards25519 arithmetic below is the minimum needed to derive a public key and
# sign. It is not a general-purpose curve library.

P = 2 ** 255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P
GROUP_ORDER = 2 ** 252 + 27742317777372353535851937790883648493


def point_add(a, b):
    x1, y1 = a
    x2, y2 = b
    denominator = D * x1 * x2 * y1 * y2 % P
    x3 = (x1 * y2 + x2 * y1) * pow(1 + denominator, P - 2, P) % P
    y3 = (y1 * y2 + x1 * x2) * pow(1 - denominator, P - 2, P) % P
    return x3, y3


def point_mul(point, scalar):
    result = (0, 1)
    while scalar:
        if scalar & 1:
            result = point_add(result, point)
        point = point_add(point, point)
        scalar >>= 1
    return result


def recover_x(y):
    value = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    x = pow(value, (P + 3) // 8, P)
    if (x * x - value) % P != 0:
        x = x * pow(2, (P - 1) // 4, P) % P
    if x % 2:
        x = P - x
    return x


BASE_Y = 4 * pow(5, P - 2, P) % P
BASE = (recover_x(BASE_Y), BASE_Y)


def scalar_mult_base(scalar):
    return point_mul(BASE, int.from_bytes(scalar, "little"))


def point_encode(point):
    x, y = point
    encoded = bytearray(y.to_bytes(32, "little"))
    encoded[31] |= (x & 1) << 7
    return bytes(encoded)


if __name__ == "__main__":
    sys.exit(main())
