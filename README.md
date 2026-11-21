# evilo-local-source

Explicitly generate signed Wasmline comic plugins and an Ed25519-signed
subscription for local evilo development. Each plugin has a distinct signed ID
and compiled guest descriptor. Titles, authors, descriptions, chapters, and PNG
artwork are invented fixtures, not scraped or copied from a content provider.

This replaces the old catalog-only generator, whose manifest/source URLs did not
exist and whose provenance values were fabricated. The new pipeline uses the
plugin template's actual `exportPluginRelease` output. Implementation alone is
not evidence that an export, installation, or reader session has succeeded.

## Prerequisites

- Python 3.10+ and Pillow 10.1+ (`python3 -m pip install 'Pillow>=10.1'`). Pillow
  must be installed for the interpreter used by `python3 -I`; a user-site-only
  installation is not visible in isolated mode. An activated virtual environment
  is suitable.
- Git, JDK 21, and the template's Gradle wrapper/toolchain. Kotlin, Wasmline, SDK,
  and Gradle versions come from the copied template, not this Python project.
- A local `evilo-plugin-template` repository, by default beside this repository.
  Override it with `--template PATH`. It is read-only input; no tasks run in it.
- Maven access to its pinned SDK/Wasmline artifacts, or an explicit
  `--sdk-path PATH`, `--wasmline-path PATH`, or `--use-local-sdk` for development.
  `--use-local-sdk` means the SDK was already published to Maven Local; it does
  not publish it. Composite builds are opt-in and may themselves build dependencies.
- Wasmline's release tooling for the template's Pulley 32/64 targets. Pass
  `--auto-download` explicitly to permit its automatic tooling downloads.
- An existing external Ed25519 authority directory containing `private.key`,
  `public.key`, and matching `authority.properties`.
- For a phone, a computer LAN address reachable from the phone and permission to
  access that local network. HTTP source consent is required in evilo for HTTP URLs.

## Signing setup: separate, one-time command

The generator never creates keys. No application build calls this setup script
or this fixture generator. Use a new private directory outside all repositories:

```sh
python3 -I scripts/setup_signing.py "$HOME/.evilo/local-fixture-signing"
```

This explicitly invoked command writes a random seed, its derived public key,
metadata, and prints only the public fingerprint. It refuses an existing directory
and uses owner-only directory/file permissions. Back up all three files privately.
Use these keys only for fixtures; do not use a public test seed for release signing.

Generation requires `--signing-key-directory DIR` or
`EVILO_SIGNING_KEY_DIRECTORY`. By default that authority also signs the subscription
index; use `--subscription-key-directory DIR` or
`EVILO_SUBSCRIBE_KEY_DIRECTORY` to select another existing authority.

Private keys remain external. `.gitignore` excludes key files and generated
workspaces; template copying and source ZIP inputs also exclude private keys and
caches. Nothing changes the application's embedded official key: these are
third-party signed packages whose fingerprint/version the user reviews in evilo.
A public-key declaration in a catalog does not grant trust.

## Generate, then serve separately

From this repository, explicitly invoke the fixture builds:

```sh
bash gen.sh --ip 192.168.1.20 --port 8080 --count 10 \
  --signing-key-directory "$HOME/.evilo/local-fixture-signing" \
  --auto-download
```

Replace `192.168.1.20` with the computer's reachable LAN address. The old
`--ip`, `--port`, and `--count` options remain supported. There is no implicit
`127.0.0.1` address. The Python positional interface also remains:

```sh
python3 -I generate.py 10 http://192.168.1.20:8080 \
  --signing-key-directory "$HOME/.evilo/local-fixture-signing" \
  --auto-download
```

Then start a foreground server in a separate terminal:

```sh
python3 -I serve.py 8080
```

Add `http://192.168.1.20:8080/repo.json` in evilo and consent to HTTP. Installation
still requires reviewing the publisher fingerprint and exact release. Open an
installed manga plugin, search its invented titles/authors, choose a comic,
choose a chapter, and open its PNG pages.

`serve.py` listens on all IPv4 interfaces. Its loopback request is only an internal
port probe, never a published URL. It reuses an existing listener only when the
served run marker matches this output directory; it never kills a process.
Its optional second positional argument selects another directory. Public fixture
files include `Access-Control-Allow-Origin: *` without credential support, and
`OPTIONS` returns HTTP 204, so a browser host can fetch signed bytes and PNGs from
this separately started server. Do not serve private authority directories.

For a computer-only session, explicitly choose `http://localhost:8080` as the base
URL (`--base-url` in `gen.sh`). That address points to the phone itself on a phone;
use a LAN address instead, or explicitly set up port forwarding yourself. The
app and generator do not rewrite hosts. Only origin URLs are accepted: no path,
credentials, query, fragment, or wildcard bind address. HTTPS is accepted when
served separately by a suitable TLS server.

## Options

| Option | Default | Behavior |
| --- | --- | --- |
| `--count` / positional count | `10` | `0..600` distinct plugins; zero publishes an empty signed index and source bundle/pages without invoking Gradle or producing a release source ZIP |
| `--ip` / `--base-url` / positional URL | required | Explicit published address, not detected or defaulted |
| `--port` (shell wrapper) | `8080` | Used with `--ip` |
| `--template` | sibling `evilo-plugin-template` | Read-only build-logic/guest skeleton input |
| `--signing-key-directory` | environment, otherwise required | Existing external publisher authority |
| `--subscription-key-directory` | publisher directory | Existing subscription signing authority |
| `--works` | `24` | `1..100` invented comics per plugin |
| `--batch-size` | `8` | `1..32` guest exports per Gradle invocation |
| `--sdk-path`, `--wasmline-path` | none | Explicit composite builds |
| `--use-local-sdk` | off | Enable template Maven Local SDK resolution |
| `--auto-download` | off | Permit Wasmline tooling downloads |

## What generation does

1. Require existing matching external authority files before changing output.
2. Copy only template source/build inputs into `.fixture-work/<run-id>/`. Replace
   its demonstration novel with `fixtures/FixtureContent.kt` and a generated guest
   for each plugin. The SDK is consumed, not copied. The copied exporter allows
   exactly the explicit fixture origin (including HTTP); the original template's
   HTTPS publication policy is unchanged.
3. Choose fresh random content once. Each guest embeds that fixed data and implements
   search with pagination, details, chapters, and content. IDs are plugin-qualified.
   The guest makes no host calls or network continuations; the host fetches PNG
   cover/page URLs supplied in its results. Chapters reuse simple synthetic panels.
4. Create an actual Git commit **only in the isolated ignored fixture workspace**.
   The generated source, guest specs, embedded data, raster assets, and adapted
   build logic are in that commit. Publish a Git bundle and actual source ZIP;
   the generator never commits, branches, or pushes this repository or its siblings.
5. Run each guest's `exportPluginRelease`, using that real source revision. The
   template generates `evilo.descriptor`, compiles the WASI guest and release
   artifacts, signs the manifest including the source archive hash, and exports
   the catalog with real `signing`, `manifestSha256`, and source archive provenance.
6. Copy exported catalogs/manifests unchanged, check their recorded manifest/archive
   hashes against exported bytes, and publish their referenced artifact files.
   Build/export errors stop generation; there is no catalog-only fallback.
7. After all exports succeed, write the latest catalogs and build/sign the
   subscription index from those local files, without HTTP requests or a server.

A new invocation uses new version/code and immutable `runs/<run-id>/` URLs, so
changed random source is not silently published over an installed version's pinned
manifest. Data is stable within that run, including across plugin reopen/restart.
The latest subscription catalogs are replaced, not extended with old versions.
Existing older installations need release review/reinstallation after refreshing
the new catalog; keeping old files does not override evilo's withdrawal rules.

## Output and the 600-plugin stress option

```text
.fixture-work/<run-id>/       Isolated source snapshot, Git history, and Gradle outputs (not served)
build/
  plugin-000/catalog.json     Latest per-plugin catalog, copied from export
  plugin-001/catalog.json
  sources.txt
  collection.json
  index.json                 Exact signed index bytes
  index.json.sig
  index.json.pub
  repo.json                  Subscription entry
  fixture-run.json           Published run/version/revision summary
  runs/<run-id>/
    plugin-000/
      catalog.json
      manifest.wlm           Exact signed exported bytes
      artifacts/...          Real content-addressed build outputs
      fixture-sources.zip    Shared source ZIP, hard-linked when supported
      icon.png
    pages/...                Bounded pool: 6 covers and 24 illustrated reader PNGs
    works/...                Local HTML destinations for item/chapter URLs
    source/
      source.bundle          Actual generated Git commit/history
      revision.txt
      fixture-sources.zip
    artifacts/...            Deduplicated identical artifacts, hard-linked to packages
```

Use the same invocation with `--count 600` for stress data. Each ID requires its
own signed manifest **and guest module** because evilo compares both signed and
runtime descriptors. One compiled guest is never relabeled as 600 identities.
The shared core and raster pool are bounded/shared; one source ZIP covers all
plugins. The ZIP grows with plugin/work count, but its data is not embedded in
manifest metadata: `evilo.descriptor` contains only each plugin's small identity
object and the manifest carries the archive's SHA-256, not the archive or comic
JSON. Generated comic JSON constants are split into 8,000-character chunks and
joined at runtime to avoid the JVM constant-size limit on the retained JVM target.
Each plugin gets a dedicated 256×256 PNG icon, separate from the 480×680 comic
covers, to stay within evilo's 512-pixel-per-side / 262,144-total-pixel icon limits.
Only byte-identical content-addressed artifacts are deduplicated. Hard links fall back to copies on
filesystems that do not support them. Source archiving uses one reproducible ZIP
for the entire generated source commit, not 600 different source trees.

Gradle exports are batched, use at most two workers, disable parallel project
execution and the configuration cache, and remove redundant exported build ZIP
copies after publication. Distinct guest compilation still costs time and disk;
600 plugins is not a cheap metadata-only operation.

Old run directories and workspaces are retained, including after failed builds;
no previous artifact files are deleted automatically. Remove obsolete
`build/runs/<run-id>/` and `.fixture-work/<run-id>/` manually when no installation
needs them. Changing the computer IP requires a new generation because guest
image URLs and catalogs contain the explicit base URL.

## Rebuild only the subscription index

No guest builds are needed to sign an unchanged local set of exported catalogs:

```sh
python3 -I scripts/build_index.py \
  --local-catalogs http://192.168.1.20:8080 \
  --key-directory "$HOME/.evilo/local-fixture-signing"
```

Omit `--local-catalogs` to retain the old behavior of fetching the HTTP(S) URLs in
`sources.txt`. `EVILO_BUILD_DIR` overrides `build/`. The legacy
`EVILO_SUBSCRIBE_KEY_HEX` environment input remains supported for index-only signing;
no fixed seed is supplied by the generator. Without any key, index-only execution
writes an unsigned index and removes stale signature/public-key/pointer files.
The index keeps each plugin's newest release and preserves its exported metadata.

## Verification status

On 2026-11-21, an explicitly authorized validation used a fresh external test
authority and `--use-local-sdk`, without SDK publishing, dependency composites,
or tooling downloads. Zero-plugin generation and two distinct guest exports with
`--works 100 --batch-size 2` succeeded. The first multi-guest build revealed that
the copied root must retain the template's `apply false` plugin declarations;
the generator now retains those declarations. A subsequent desktop check rejected
the original 480×680 plugin icon under the host's icon-size limits; the generator
now creates a dedicated 256×256 icon without reducing comic covers or host limits.
A fresh two-plugin signed export with the corrected icons succeeded in 24 seconds;
the prior signed run remained unchanged.

Independent Ed25519 checks verified the exact subscription bytes and both signed
manifest payloads, all six artifact hashes/sizes, the source ZIP hash, and ZIP file
contents against the published Git bundle revision. The resolved Wasmline beta1
tooling emits manifest envelope version 1; the resolved beta1 host loader accepted
those packages. The online latest AOT catalog check reported `WLAOT002` unavailable;
the local compatibility profiles were validated.

An external JVM harness used evilo's actual `WasmlinePluginLoader` and native
Pulley runtime to load both signed guests. Each returned 100 unique works across
nine search pages and title/author/tag search results. All 200 detail results,
612 chapters in the corrected-icon run, and each chapter's four image references
were exercised. Sample
cover/reader PNGs decoded through ImageIO; reopening preserved the results.
Wrong signing keys, plugin IDs, source revisions, and manifest digests were rejected.
A separate JVM compile exercised the 100-work chunked constants and all chapters
for one guest. Local HTTP checks
verified all 812 generated work/chapter destinations and all 30 PNGs, as well as
CORS, signed local/fetched index rebuilds, unsigned cleanup, and listener reuse.

Run the permanent regression checks without Gradle or authority files:

```sh
python3 -I scripts/test_fixtures.py
```

They cover the RFC 8032 signing vector, the 100-work boundary, copied root plugin
declarations, bounded 256×256 icons with unchanged comic covers, different generated
data across runs, and GET/HEAD/OPTIONS CORS.
Template-copy coverage skips when the sibling template is absent. All four tests
passed during validation.

The 600-plugin full export was not run: the measured two-plugin workspace and
output occupied approximately 179 MB and exported in 29 seconds. Linear scaling
would require roughly 53 GB and 2.4 hours before additional batch/configuration
costs; these are estimates, not measured 600-plugin results. Desktop/browser UI,
Android installation, and publisher-approval interaction are separate app checks,
not established by the headless signed-host harness.
