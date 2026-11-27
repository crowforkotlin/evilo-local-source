#!/usr/bin/env python3
"""Run fixture regressions without Gradle, published output, or authority files.

Usage: python3 -I scripts/test_fixtures.py
Template-copy cases use the sibling template when available. HTTP tests bind only
loopback on an ephemeral port and close their server before returning.
"""

import importlib.util
import json
import pathlib
import random
import sys
import tempfile
import threading
import unittest
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load(ROOT / "generate.py", "fixture_generator_test")
media = load(ROOT / "scripts/fixture_media.py", "fixture_media_test")
signing = load(ROOT / "scripts/build_index.py", "fixture_signing_test")
with patch.object(sys, "argv", [str(ROOT / "serve.py")]):
    serving = load(ROOT / "serve.py", "fixture_serving_test")


class FixtureRegressionTest(unittest.TestCase):
    def test_configuration_variants_are_deterministic_and_separate_access(self):
        variants = [generator.configuration_fixture(index) for index in range(6)]
        self.assertEqual(variants, [generator.configuration_fixture(index + 6) for index in range(6)])
        self.assertEqual(variants[0], ({}, {}))
        self.assertEqual(variants[1][1]["minimumHostVersionCode"], 2)
        self.assertIn("configuration.filters.v1", variants[1][0]["protocol"]["requiredCapabilities"])
        self.assertEqual(variants[2][0]["configuration"]["groups"][0]["fields"][0]["options"], [])
        self.assertEqual(variants[3][0]["configuration"]["groups"][0]["fields"][0]["defaultValue"],
                         {"choiceIds": ["not-declared"]})
        self.assertIn("fixture.unsupported.v1", variants[4][0]["protocol"]["requiredCapabilities"])
        self.assertEqual(variants[4][1]["minimumHostVersionCode"], 2)
        self.assertEqual(variants[5][0]["configuration"]["actions"][0]["kind"], "UNSUPPORTED")
        self.assertNotIn("grants", variants[5][0]["configuration"]["actions"][0])

    def test_rfc8032_signing_vector(self):
        # RFC 8032 test vector only; never written to an authority directory.
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        self.assertEqual(signing.public_from_seed(seed).hex(),
                         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        self.assertEqual(signing.sign(b"", seed).hex(),
                         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb"
                         "8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")

    def test_works_100_boundary_is_unique(self):
        works = media.works(random.Random(100), 100)
        self.assertEqual(len(works), 100)
        self.assertEqual(len({work["title"] for work in works}), 100)
        self.assertGreater(len(json.dumps(works).encode()), 65535)
        for work in works:
            self.assertIn(len(work["chapters"]), (2, 3, 4))
            self.assertTrue(all(len(chapter["pages"]) == 4 for chapter in work["chapters"]))

    def test_copied_root_plugins_and_distinct_runs(self):
        template = ROOT.parent / "evilo-plugin-template"
        if not template.is_dir():
            self.skipTest("sibling evilo-plugin-template is required for template-copy regression")
        args = SimpleNamespace(template=template, base_url="http://127.0.0.1:18089", count=2, works=100)
        runs = []
        with tempfile.TemporaryDirectory(prefix="evilo-fixture-regression-") as temporary:
            for seed in (100, 101):
                workspace = pathlib.Path(temporary) / str(seed)
                workspace.mkdir()
                generator.copy_template(args, workspace)
                root_build = (workspace / "build.gradle.kts").read_text()
                for alias in ("kotlinMultiplatform", "kotlinSerialization", "wasmline"):
                    self.assertIn(f"alias(libs.plugins.{alias}) apply false", root_build)
                self.assertIn('tasks.register<Zip>("fixtureSourceArchive")', root_build)
                modules, data_root = generator.make_plugins(args, workspace, f"{args.base_url}/runs/{seed}", seed,
                                                           random.Random(seed))
                self.assertEqual(modules, ["plugin-000", "plugin-001"])
                from PIL import Image
                for module in modules:
                    with Image.open(workspace / module / "icon.png") as icon:
                        icon.load()
                        self.assertEqual(icon.size, (256, 256))
                        self.assertLessEqual(icon.width * icon.height, 262144)
                with Image.open(data_root / "pages/cover-0.png") as cover:
                    self.assertEqual(cover.size, (480, 680))
                data = json.loads((workspace / modules[0] / "src/commonMain/resources/fixture-data.json").read_text())
                self.assertEqual(len(data["works"]), 100)
                generated = (workspace / modules[0] / "src/commonMain/kotlin/crow/evilo/plugin/template/FixtureData.kt").read_text()
                self.assertIn("listOf(", generated)
                self.assertIn(').joinToString("")', generated)
                self.assertTrue(all(work["id"].startswith("plugin-000-") for work in data["works"]))
                runs.append(data)
            self.assertNotEqual(runs[0]["baseUrl"], runs[1]["baseUrl"])
            self.assertNotEqual(runs[0]["works"], runs[1]["works"])

    def test_http_get_head_and_preflight_cors(self):
        with tempfile.TemporaryDirectory(prefix="evilo-fixture-http-") as temporary:
            pathlib.Path(temporary, "index.json").write_text('{"plugins":[]}\n')
            class QuietHandler(serving.FixtureHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=temporary, **kwargs)

                def log_message(self, *args):
                    pass

            server = serving.http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/index.json"
                for method in ("GET", "HEAD", "OPTIONS"):
                    request = urllib.request.Request(url, method=method, headers={"Origin": "http://localhost:8080"})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        self.assertEqual(response.status, 204 if method == "OPTIONS" else 200)
                        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
                        self.assertEqual(response.headers["Access-Control-Allow-Methods"], "GET, HEAD, OPTIONS")
                        self.assertIsNone(response.headers.get("Access-Control-Allow-Credentials"))
                        body = response.read()
                        self.assertEqual(body, b'{"plugins":[]}\n' if method == "GET" else b"")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
