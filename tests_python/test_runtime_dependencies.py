import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_runtime_dependencies.py"
SPEC = importlib.util.spec_from_file_location("check_runtime_dependencies", SCRIPT)
runtime_dependencies = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = runtime_dependencies
SPEC.loader.exec_module(runtime_dependencies)


class FakeRuntime:
    def __init__(
        self, *, packages=None, apis=None, hermes_help=None, profile_output=None,
        hermes_version="0.20.0", hermes_release="2026.8.3",
    ):
        self.packages = packages or {
            "browser-harness": "0.1.9",
            "browser-use": "0.13.8",
            "websockets": "15.0.1",
            "bcrypt": "5.0.0",
            "websockify": "0.13.0",
        }
        self.hermes_help = hermes_help or " ".join(runtime_dependencies.HERMES_FLAGS)
        self.apis = apis or {
            "browser_harness_helpers": True,
            "browser_use_module": True,
            "websockets_sync": True,
            "bcrypt_hash": True,
            "websockify_websocket": True,
        }
        self.profile_output = profile_output or "Profile 'chironjp-dependency-probe' does not exist"
        self.hermes_version = hermes_version
        self.hermes_release = hermes_release
        self.commands = []

    @staticmethod
    def locate(name):
        return f"/mock/bin/{name}"

    def run(self, command):
        self.commands.append(tuple(command))
        name = Path(command[0]).name
        if "-I" in command:
            return runtime_dependencies.ProbeResult(0, json.dumps({
                "python": [3, 11, 16], "packages": self.packages, "apis": self.apis,
            }))
        if name == "hermes" and command[-1] == "--version":
            return runtime_dependencies.ProbeResult(
                0, f"Hermes Agent v{self.hermes_version} ({self.hermes_release})\n",
            )
        if name == "hermes" and command[1:] == ["--help"]:
            return runtime_dependencies.ProbeResult(0, self.hermes_help)
        if name == "hermes" and "-p" in command:
            return runtime_dependencies.ProbeResult(1, self.profile_output)
        if name == "browser-use":
            return runtime_dependencies.ProbeResult(0, "Commands: browser-use --reload")
        if name == "tectonic" and "--help" in command:
            return runtime_dependencies.ProbeResult(0, "Usage: tectonic [OPTIONS] <INPUT> --outdir")
        if name == "pdftotext" and "-h" in command:
            return runtime_dependencies.ProbeResult(0, "Usage: pdftotext -bbox-layout")
        if name == "pdftoppm" and "-h" in command:
            return runtime_dependencies.ProbeResult(0, "Usage: pdftoppm -png -r")
        outputs = {
            "chromium": "Chromium 151.0.7922.169",
            "Xvfb": "X.Org X Server 21.1.16",
            "x11vnc": "x11vnc: 0.9.17",
            "websockify": "usage: websockify [options]",
            "tectonic": "Tectonic 0.16.9",
            "pdftotext": "pdftotext version 26.05.0",
            "pdftoppm": "pdftoppm version 26.05.0",
        }
        return runtime_dependencies.ProbeResult(0, outputs.get(name, ""))


class RuntimeDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.novnc = Path(self.temporary.name) / "novnc"
        (self.novnc / "core").mkdir(parents=True)
        (self.novnc / "vnc.html").write_text("fixture", encoding="utf-8")
        (self.novnc / "core" / "rfb.js").write_text("fixture", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def report(self, fake):
        return runtime_dependencies.inventory(
            browser_python="python3", novnc_web=str(self.novnc),
            locate=fake.locate, run=fake.run,
        )

    def test_complete_pinned_inventory_is_ready_but_never_live_proof(self):
        fake = FakeRuntime()
        report = self.report(fake)
        self.assertTrue(report["ok"])
        self.assertEqual(report["proof"], "installed_surface_smoke_only")
        self.assertTrue(report["secret_free"])
        self.assertTrue(all(not item["live_proof"] for item in report["checks"]))
        hermes = next(item for item in report["checks"] if item["id"] == "hermes")
        self.assertEqual(hermes["observed"], "0.20.0 (2026.8.3)")
        self.assertIn("-p", hermes["required"])

    def test_newer_python_package_is_untested_warning_not_incompatible(self):
        fake = FakeRuntime(packages={
            "browser-harness": "0.1.10",
            "browser-use": "0.13.8",
            "websockets": "15.0.1",
            "bcrypt": "5.0.0",
            "websockify": "0.13.0",
        })
        report = self.report(fake)
        item = next(value for value in report["checks"] if value["id"] == "browser-harness")
        self.assertTrue(report["ok"])
        self.assertEqual(item["status"], "untested")
        self.assertEqual(item["required"], "tested default 0.1.9")

    def test_missing_required_browser_api_is_blocking(self):
        fake = FakeRuntime(apis={
            "browser_harness_helpers": False,
            "browser_use_module": True,
            "websockets_sync": True,
            "bcrypt_hash": True,
            "websockify_websocket": True,
        })
        report = self.report(fake)
        item = next(value for value in report["checks"] if value["id"] == "runtime-python-api")
        self.assertFalse(report["ok"])
        self.assertTrue(item["blocking"])
        self.assertEqual(item["status"], "incompatible")

    def test_missing_review_auth_api_is_blocking(self):
        fake = FakeRuntime(apis={
            "browser_harness_helpers": True,
            "browser_use_module": True,
            "websockets_sync": True,
            "bcrypt_hash": False,
            "websockify_websocket": True,
        })
        report = self.report(fake)
        item = next(value for value in report["checks"] if value["id"] == "runtime-python-api")
        self.assertFalse(report["ok"])
        self.assertTrue(item["blocking"])
        self.assertIn("bcrypt_hash", item["detail"])

    def test_hermes_requires_every_flag_and_hidden_profile_selector(self):
        fake = FakeRuntime(
            hermes_help="--skills --usage-file --reasoning",
            profile_output="error: unrecognized arguments: -p",
        )
        report = self.report(fake)
        item = next(value for value in report["checks"] if value["id"] == "hermes")
        self.assertEqual(item["status"], "incompatible")
        self.assertIn("--oneshot", item["detail"])
        self.assertIn("-p", item["detail"])

    def test_newer_hermes_with_required_surface_does_not_require_replacement(self):
        report = self.report(FakeRuntime(
            hermes_version="0.21.0", hermes_release="2026.8.31",
        ))
        item = next(value for value in report["checks"] if value["id"] == "hermes")
        self.assertTrue(report["ok"])
        self.assertEqual(item["status"], "untested")
        self.assertFalse(item["blocking"])

    def test_novnc_requires_the_actual_viewer_asset(self):
        (self.novnc / "core" / "rfb.js").unlink()
        report = self.report(FakeRuntime())
        item = next(value for value in report["checks"] if value["id"] == "novnc-assets")
        self.assertEqual(item["status"], "missing")
        self.assertFalse(report["ok"])

    def test_safe_environment_does_not_copy_credentials_or_profile_selectors(self):
        safe = runtime_dependencies._safe_environment(Path("/isolated"), {
            "PATH": "/bin", "API_TOKEN": "not-for-child",
            "HERMES_PROFILE": "existing-owner-profile",
            "HERMES_HOME": "/shared/state", "HOME": "/shared/home",
            "OP_SERVICE_ACCOUNT_TOKEN": "not-for-child",
        })
        self.assertEqual(safe["PATH"], "/bin")
        self.assertEqual(safe["HOME"], "/isolated")
        self.assertEqual(safe["HERMES_HOME"], "/isolated/hermes")
        self.assertNotIn("API_TOKEN", safe)
        self.assertNotIn("HERMES_PROFILE", safe)
        self.assertNotIn("OP_SERVICE_ACCOUNT_TOKEN", safe)

    def test_report_does_not_emit_executable_or_home_paths(self):
        fake = FakeRuntime()
        rendered = runtime_dependencies._text(self.report(fake))
        self.assertNotIn("/mock/bin", rendered)
        self.assertNotIn(str(self.novnc), rendered)
        self.assertIn("Surface smoke only", rendered)

    def test_untrusted_metadata_text_is_not_reflected(self):
        fake = FakeRuntime(packages={
            "browser-harness": "/private/layout/value",
            "browser-use": "0.13.8",
            "websockets": "15.0.1",
        })
        rendered = json.dumps(self.report(fake))
        self.assertNotIn("/private/layout/value", rendered)


if __name__ == "__main__":
    unittest.main()
