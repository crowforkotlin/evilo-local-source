#!/usr/bin/env python3
"""Explicitly build signed synthetic comic plugins; never start an HTTP server.

The positional interface remains: generate.py [count] BASE_URL.
Keys must already exist outside the repositories. Each invocation creates an
isolated, local Git source snapshot, not a commit in this repository.
"""

import argparse
import datetime
import hashlib
import html
import importlib.util
import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "build"
WORK = ROOT / ".fixture-work"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def literal(value):
    return json.dumps(value, ensure_ascii=False).replace("$", "\\$")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("count", type=int, nargs="?", default=10)
    parser.add_argument("base_url", help="Explicit HTTP(S) origin, e.g. http://192.168.1.20:8080")
    parser.add_argument("--template", type=pathlib.Path, default=ROOT.parent / "evilo-plugin-template")
    parser.add_argument("--signing-key-directory", type=pathlib.Path,
                        default=os.environ.get("EVILO_SIGNING_KEY_DIRECTORY"))
    parser.add_argument("--subscription-key-directory", type=pathlib.Path,
                        default=os.environ.get("EVILO_SUBSCRIBE_KEY_DIRECTORY"))
    parser.add_argument("--sdk-path", type=pathlib.Path, help="Opt-in SDK composite build")
    parser.add_argument("--use-local-sdk", action="store_true", help="Resolve the SDK from Maven Local")
    parser.add_argument("--wasmline-path", type=pathlib.Path, help="Opt-in Wasmline composite build")
    parser.add_argument("--auto-download", action="store_true", help="Allow Wasmline tooling downloads")
    parser.add_argument("--configuration-fixtures", action="store_true",
                        help="Cycle legacy, typed, empty, invalid, required-unsupported, and mock-access schemas")
    parser.add_argument("--works", type=int, default=24, help="Comics per plugin (1..100)")
    parser.add_argument("--batch-size", type=int, default=8, help="Guest exports per Gradle invocation (1..32)")
    args = parser.parse_args()
    if not 0 <= args.count <= 600:
        parser.error("count must be between 0 and 600")
    if not 1 <= args.works <= 100 or not 1 <= args.batch_size <= 32:
        parser.error("works must be 1..100 and batch-size must be 1..32")
    parsed = urlsplit(args.base_url)
    try:
        port = parsed.port
    except ValueError as error:
        parser.error(str(error))
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or parsed.path not in ("", "/") or
            any(c <= " " or c in "\\%" for c in args.base_url) or
            parsed.hostname in ("0.0.0.0", "::")):
        parser.error("base_url must be an explicit HTTP(S) origin, without credentials, path, query, or fragment")
    args.base_url = args.base_url.rstrip("/")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        print("Explicit loopback URL: phone access requires port forwarding; LAN URLs are not rewritten.")
    if args.signing_key_directory is None:
        parser.error("supply --signing-key-directory or EVILO_SIGNING_KEY_DIRECTORY; keys are never generated here")
    args.template = args.template.resolve()
    args.signing_key_directory = args.signing_key_directory.expanduser().resolve()
    args.subscription_key_directory = (args.subscription_key_directory or args.signing_key_directory).expanduser().resolve()
    for name in ("sdk_path", "wasmline_path"):
        path = getattr(args, name)
        if path is not None:
            setattr(args, name, path.expanduser().resolve())
    args.port = port or (443 if parsed.scheme == "https" else 80)
    return args


def copy_template(args, workspace):
    # Allowlist only source/build files. Never copy the template's caches or local keys.
    for name in ("gradle", "evilo-plugin-build-logic", "evilo-plugin-core", "evilo-plugin"):
        shutil.copytree(args.template / name, workspace / name,
                        ignore=shutil.ignore_patterns("build", ".gradle", ".kotlin", ".cache", ".git",
                                                     "*.key", "*.pem", "*.keystore", "*.jks", "local.properties"))
    for name in ("gradlew", "gradlew.bat", "gradle.properties", "build.gradle.kts", "LICENSE", ".gitignore"):
        shutil.copy2(args.template / name, workspace / name)

    convention = workspace / "evilo-plugin-build-logic/plugin/src/main/kotlin/evilo.plugin.guest.gradle.kts"
    text = convention.read_text(encoding="utf-8")
    start = text.index('    val sourceArchive = tasks.register<Zip>("pluginSourceArchive") {')
    end = text.index("\n\n    kotlin {", start)
    text = text[:start] + '    val sourceArchive = rootProject.tasks.named<Zip>("fixtureSourceArchive")' + text[end:]
    text = text.replace('packageBaseUrl.set(providers.gradleProperty("plugin.releaseBaseUrl"))',
                        'packageBaseUrl.set(providers.gradleProperty("fixture.baseUrl").map { "$it/${project.name}" })')
    convention.write_text(text, encoding="utf-8")

    # Production export is HTTPS-only. Change only this copied fixture exporter:
    # permit HTTP for exactly the explicitly supplied local origin, not any host.
    exporter = workspace / "evilo-plugin-build-logic/plugin/src/main/kotlin/crow/evilo/plugin/buildlogic/PluginReleaseTasks.kt"
    text = exporter.read_text(encoding="utf-8")
    old = 'value.startsWith("https://") && value.none'
    replacement = f'(value.startsWith({literal(args.base_url + "/")})) && value.none'
    if old not in text:
        raise RuntimeError("Template URL policy changed; update the fixture copy adapter before exporting")
    exporter.write_text(text.replace(old, replacement), encoding="utf-8")

    (workspace / "build.gradle.kts").write_text('''plugins {
    alias(libs.plugins.kotlinMultiplatform) apply false
    alias(libs.plugins.kotlinSerialization) apply false
    alias(libs.plugins.wasmline) apply false
}

tasks.register<Zip>("fixtureSourceArchive") {
    archiveFileName.set("fixture-sources.zip")
    destinationDirectory.set(layout.buildDirectory.dir("source-release"))
    isPreserveFileTimestamps = false
    isReproducibleFileOrder = true
    from(layout.projectDirectory) {
        include("**/src/**", "**/plugin-spec.json", "**/build.gradle.kts", "**/settings.gradle.kts")
        include("gradle/**", "gradlew", "gradlew.bat", "gradle.properties", "LICENSE", ".gitignore", "**/icon.png")
        exclude("**/build/**", "**/.gradle/**", "**/.kotlin/**", "**/.git/**", "**/*.key", "**/*.pem", "**/local.properties")
    }
}
''', encoding="utf-8")
    shutil.copy2(ROOT / "fixtures/FixtureContent.kt",
                 workspace / "evilo-plugin-core/src/commonMain/kotlin/crow/evilo/plugin/template/TemplateContent.kt")
    guest = workspace / "evilo-plugin/src/commonMain/kotlin/crow/evilo/plugin/template/TemplatePlugin.kt"
    guest.write_text('''package crow.evilo.plugin.template

import crow.evilo.plugin.api.EviloPluginService
import crow.evilo.plugin.api.PluginJson
import crow.evilo.plugin.api.PluginOperation
import crow.evilo.plugin.api.PluginStep
import crow.evilo.plugin.build.releaseDescriptor

class TemplatePlugin : EviloPluginService {
    private val content = TemplateContent(releaseDescriptor, fixtureData)
    override fun describe(): String = PluginJson.encodeToString(releaseDescriptor)
    override fun start(operationJson: String): String {
        val operation = PluginJson.decodeFromString<PluginOperation>(operationJson)
        return PluginJson.encodeToString(PluginStep(result = content.execute(operation)))
    }
    override fun resume(operationJson: String, context: String, responseJson: String): String =
        error("Synthetic catalog operations never request network continuations.")
}
''', encoding="utf-8")
    (workspace / "evilo-plugin/src/wasmWasiMain/kotlin/crow/evilo/plugin/template/Main.kt").write_text('''package crow.evilo.plugin.template

import crow.evilo.plugin.api.EviloPluginService
import crow.wasmline.Wasmline
import crow.wasmline.bind

fun main() {
    Wasmline.get().bind(EviloPluginService::class, TemplatePlugin())
}
''', encoding="utf-8")


def configuration_fixture(index):
    """Deterministic source schemas only; no login, dynamic service, or real account."""
    variant = index % 6
    if variant == 0:
        return {}, {}
    fields = [
        {"id": "tags", "label": {"fallback": "Tags"}, "control": "CHOICE", "multiple": True,
         "options": [{"id": "even", "label": {"fallback": "Even works"}},
                     {"id": "odd", "label": {"fallback": "Odd works"}}]},
        {"id": "include-works", "label": {"fallback": "Include works"}, "control": "TOGGLE",
         "defaultValue": {"toggle": True}},
        {"id": "title", "label": {"fallback": "Title contains"}, "control": "TEXT", "maxLength": 80,
         "defaultValue": {"text": ""}, "dependencies": [{"fieldId": "include-works", "value": {"toggle": True}}]},
        {"id": "limit", "label": {"fallback": "Page size"}, "control": "RANGE", "min": 1, "max": 20,
         "defaultValue": {"number": 12}},
        {"id": "local-parity", "label": {"fallback": "Loaded work parity"}, "scope": "LOCAL", "control": "CHOICE",
         "localMetadataKey": "fixture.parity", "options": [{"id": "even", "label": {"fallback": "Even"}},
                                                           {"id": "odd", "label": {"fallback": "Odd"}}]},
    ]
    configuration = {"groups": [{"id": "fixture", "label": {"fallback": "Fixture filters"}, "fields": fields}]}
    protocol = {"optionalCapabilities": ["configuration.filters.v1"]}
    release = {}
    if variant == 1:
        fields[1]["required"] = True
        protocol = {"requiredCapabilities": ["media.catalog.v1", "configuration.filters.v1"]}
        release["minimumHostVersionCode"] = 2
    elif variant == 2:
        fields[0]["options"] = []  # Optional empty choices remain usable; not a dynamic API.
    elif variant == 3:
        fields[0]["defaultValue"] = {"choiceIds": ["not-declared"]}
    elif variant == 4:
        protocol = {"requiredCapabilities": ["media.catalog.v1", "fixture.unsupported.v1"],
                    "optionalCapabilities": ["configuration.filters.v1"]}
        release["minimumHostVersionCode"] = 2
    elif variant == 5:
        configuration["access"] = [{"id": "fixture-account", "label": {"fallback": "Fictional account"},
                                    "kind": "LOGIN", "actionId": "unsupported-login"}]
        configuration["actions"] = [{"id": "unsupported-login", "requirementId": "fixture-account",
                                      "label": {"fallback": "No provider login implemented"}, "kind": "UNSUPPORTED"}]
    return {"configuration": configuration, "protocol": protocol}, release


def make_plugins(args, workspace, run_url, version_code, rng):
    media = load_script("fixture_media")
    data_root = workspace / "evilo-plugin-core/src/commonMain/resources/fixture"
    media.write_pages(data_root / "pages", rng)
    modules = []
    skeleton = workspace / "evilo-plugin"
    for index in range(args.count):
        module = f"plugin-{index:03d}"
        directory = workspace / module
        shutil.copytree(skeleton, directory)
        modules.append(module)
        provider = media.provider_name(rng, index)
        spec = {
            "descriptor": {"id": f"com.example.plugin{index:03d}", "name": provider,
                           "version": f"1.0.{version_code}", "versionCode": version_code,
                           "kinds": ["manga"], "languages": ["en"]},
            "catalog": {"authors": [media.author_name(rng)],
                        "description": "Synthetic comic fixture. Invented titles, authors, and raster artwork; not a real provider."},
        }
        if getattr(args, "configuration_fixtures", False):
            descriptor_fields, release_fields = configuration_fixture(index)
            spec["descriptor"].update(descriptor_fields)
            if release_fields:
                spec["release"] = release_fields
        write_json(directory / "plugin-spec.json", spec)
        data = {"baseUrl": run_url, "works": media.works(rng, args.works)}
        for work in data["works"]:
            work["id"] = f"{module}-{work['id']}"
        write_json(directory / "src/commonMain/resources/fixture-data.json", data)
        generated = directory / "src/commonMain/kotlin/crow/evilo/plugin/template/FixtureData.kt"
        generated.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(data, ensure_ascii=False)
        # Keep individual constants below JVM's 65535-byte UTF-8 constant limit.
        # The fixture core/guest retain JVM targets even though export uses WASI.
        # Joining a list at runtime avoids compile-time concatenation back into
        # one oversized constant when --works=100 is selected.
        chunks = [literal(encoded[start:start + 8000]) for start in range(0, len(encoded), 8000)]
        generated.write_text('package crow.evilo.plugin.template\n\n' +
                             'import crow.evilo.plugin.api.PluginJson\n\n' +
                             'val fixtureData: FixtureData = PluginJson.decodeFromString(\n' +
                             '    listOf(\n        ' + ',\n        '.join(chunks) +
                             '\n    ).joinToString("")\n)\n', encoding="utf-8")
        media.write_icon(data_root / "pages/cover-0.png", directory / "icon.png")
        (directory / "icon.svg").unlink(missing_ok=True)
    shutil.rmtree(skeleton)
    (workspace / "settings.gradle.kts").write_text('''pluginManagement {
    includeBuild("evilo-plugin-build-logic")
    providers.gradleProperty("wasmline.localPath").orNull?.let { includeBuild(it) }
    repositories { mavenCentral(); gradlePluginPortal(); google() }
    plugins { id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0" }
}
plugins { id("org.gradle.toolchains.foojay-resolver-convention") }
rootProject.name = "evilo-local-fixtures"
enableFeaturePreview("TYPESAFE_PROJECT_ACCESSORS")
providers.gradleProperty("evilo.sdkPath").orNull?.let { includeBuild(it) }
providers.gradleProperty("wasmline.localPath").orNull?.let { includeBuild(it) }
dependencyResolutionManagement {
    repositories {
        mavenCentral()
        if (providers.gradleProperty("evilo.useLocalSdk").isPresent) {
            mavenLocal { content { includeGroup("io.github.crowforkotlin.evilo") } }
        }
    }
}
include(":evilo-plugin-core")
''' + "".join(f'include(":{module}")\n' for module in modules), encoding="utf-8")
    return modules, data_root


def snapshot(workspace):
    # This repository's HEAD is not the generated random source. Create and publish
    # the actual generated commit in an isolated ignored workspace instead.
    subprocess.run(["git", "init", "--quiet", str(workspace)], check=True, cwd=ROOT)
    subprocess.run(["git", "-C", str(workspace), "add", "."], check=True, cwd=ROOT)
    subprocess.run(["git", "-C", str(workspace), "-c", "user.name=Fixture generator",
                    "-c", "user.email=fixture@localhost", "-c", "commit.gpgsign=false",
                    "-c", "core.hooksPath=/dev/null",
                    "commit", "--quiet", "-m", "Generate synthetic comic fixture sources"], check=True, cwd=ROOT)
    return subprocess.check_output(["git", "-C", str(workspace), "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def link_or_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def publish_export(directory, target, shared_archive, artifact_pool):
    catalog = json.loads((directory / "catalog.json").read_text(encoding="utf-8"))
    release = catalog["plugins"][0]["availableVersions"][0]
    manifest = directory / "manifest.wlm"
    archive = directory / "fixture-sources.zip"
    for file, expected in ((manifest, release["manifestSha256"]),
                           (archive, release["sourceArchiveSha256"])):
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Exported bytes do not match catalog: {file}")
    target.mkdir(parents=True, exist_ok=False)
    for name in ("manifest.wlm", "catalog.json", "icon.png"):
        shutil.copy2(directory / name, target / name)
    if not shared_archive.exists():
        shutil.copy2(archive, shared_archive)
    if hashlib.sha256(shared_archive.read_bytes()).hexdigest() != release["sourceArchiveSha256"]:
        raise RuntimeError("Plugins did not export the same source snapshot")
    link_or_copy(shared_archive, target / archive.name)
    artifacts = directory / "artifacts"
    if not artifacts.is_dir() or not any(path.is_file() for path in artifacts.rglob("*")):
        raise RuntimeError(f"No real artifacts exported in {directory}")
    for source in artifacts.rglob("*"):
        if source.is_file():
            relative = source.relative_to(artifacts)
            pooled = artifact_pool / relative
            pooled.parent.mkdir(parents=True, exist_ok=True)
            if not pooled.exists():
                shutil.copy2(source, pooled)
            elif hashlib.sha256(pooled.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
                raise RuntimeError(f"Content-addressed artifact collision: {relative}")
            link_or_copy(pooled, target / "artifacts" / relative)
    return catalog


def main():
    args = arguments()
    signing = load_script("build_index")
    # Fail before touching existing fixture output when authority setup is absent.
    signing.read_authority(args.signing_key_directory, extra_repositories=(args.template,))
    signing.read_authority(args.subscription_key_directory, extra_repositories=(args.template,))
    version_code = time.time_ns() // 1_000_000
    run_id = f"{version_code}-{os.urandom(4).hex()}"
    run_url = f"{args.base_url}/runs/{run_id}"
    run_directory = OUT / "runs" / run_id
    workspace = WORK / run_id
    workspace.mkdir(parents=True, exist_ok=False)
    rng = random.Random(int.from_bytes(os.urandom(32), "big"))
    copy_template(args, workspace)
    modules, data_root = make_plugins(args, workspace, run_url, version_code, rng)
    revision = snapshot(workspace)
    run_directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(data_root / "pages", run_directory / "pages")
    # Item/chapter URLs are genuine local pages too, rather than dead placeholders.
    for module in modules:
        data = json.loads((workspace / module / "src/commonMain/resources/fixture-data.json").read_text(encoding="utf-8"))
        for work in data["works"]:
            directory = run_directory / "works" / work["id"]
            directory.mkdir(parents=True)
            links = "".join(f'<li><a href="{chapter["id"]}/">{html.escape(chapter["title"])}</a></li>'
                            for chapter in work["chapters"])
            (directory / "index.html").write_text(
                f'<!doctype html><meta charset="utf-8"><h1>{html.escape(work["title"])}</h1>' +
                f'<p>{html.escape(work["author"])}</p><p>{html.escape(work["description"])}</p><ul>{links}</ul>',
                encoding="utf-8")
            for chapter in work["chapters"]:
                selected = directory / chapter["id"]
                selected.mkdir()
                images = "".join(f'<img style="max-width:100%;display:block" src="{run_url}/{page}" alt="Synthetic comic panel">'
                                 for page in chapter["pages"])
                (selected / "index.html").write_text(
                    f'<!doctype html><meta charset="utf-8"><h1>{html.escape(chapter["title"])}</h1>{images}',
                    encoding="utf-8")
    source_directory = run_directory / "source"
    source_directory.mkdir()
    subprocess.run(["git", "-C", str(workspace), "bundle", "create",
                    str(source_directory / "source.bundle"), "HEAD"], cwd=ROOT, check=True)
    (source_directory / "revision.txt").write_text(revision + "\n", encoding="ascii")
    published_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    options = [f"-Pevilo.signingKeyDirectory={args.signing_key_directory}",
               f"-Pplugin.sourceRevision={revision}", f"-Pplugin.sourceUrl={run_url}/source/",
               f"-Pplugin.publishedAt={published_at}", f"-Pfixture.baseUrl={run_url}", "--no-configuration-cache",
               "--max-workers=2", "--no-parallel"]
    if args.sdk_path:
        options.append(f"-Pevilo.sdkPath={args.sdk_path}")
    if args.use_local_sdk:
        options.append("-Pevilo.useLocalSdk")
    if args.wasmline_path:
        options.append(f"-Pwasmline.localPath={args.wasmline_path}")
    if args.auto_download:
        options.append("-Pwasmline.autoDownload=true")
    catalogs = []
    shared_archive = source_directory / "fixture-sources.zip"
    for offset in range(0, len(modules), args.batch_size):
        batch = modules[offset:offset + args.batch_size]
        subprocess.run([str(workspace / "gradlew"), "-p", str(workspace)] +
                       [f":{module}:exportPluginRelease" for module in batch] + options,
                       cwd=ROOT, check=True)
        for module in batch:
            plugin_id = f"com.example.plugin{int(module.split('-')[1]):03d}"
            exported = workspace / module / "build/release" / f"{plugin_id}-1.0.{version_code}"
            catalog = publish_export(exported, run_directory / module, shared_archive, run_directory / "artifacts")
            catalogs.append((module, catalog))
            # Export copies the shared ZIP; remove that redundant build copy after
            # publishing. Distinct guests/manifests are never relabeled or shared.
            shutil.rmtree(exported)
    # Publish latest catalogs/index only after every guest export succeeds. Keep
    # immutable prior run directories for pinned installed manifests and pages.
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("plugin-*/catalog.json"):
        old.unlink()
    for module, catalog in catalogs:
        write_json(OUT / module / "catalog.json", catalog)
    (OUT / "sources.txt").write_text("".join(f"{args.base_url}/{module}/catalog.json\n" for module, _ in catalogs), encoding="utf-8")
    write_json(OUT / "collection.json", {"name": f"{args.count} synthetic comic plugins",
                                       "indexUrl": f"{args.base_url}/index.json", "keyId": "subscription"})
    subprocess.run([sys.executable, "-I", str(ROOT / "scripts/build_index.py"),
                    "--local-catalogs", args.base_url, "--key-directory", str(args.subscription_key_directory)],
                   cwd=ROOT, env=dict(os.environ, EVILO_BUILD_DIR=str(OUT)), check=True)
    write_json(OUT / "fixture-run.json", {"runId": run_id, "baseUrl": args.base_url,
                                        "pluginCount": args.count, "sourceRevision": revision,
                                        "versionCode": version_code})
    print(f"Exported {args.count} signed plugin packages; source commit {revision}")
    print(f"Serve separately: python3 -I {ROOT / 'serve.py'} {args.port}")
    print(f"Subscription: {args.base_url}/repo.json")
    print("Runtime installation, loading, and PNG decoding still require verification in evilo.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"generate: {error}") from error
