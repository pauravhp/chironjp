import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chironjp.registry import load_registry
from chironjp.takeover import surface_commands


class RegistryTakeoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        runtime = self.root / "runtime"
        state = self.root / "state"
        profiles = self.root / "profiles"
        self.config = self.root / "workers.json"
        self.config.write_text(json.dumps({
            "schema_version": 3,
            "runtime_root": str(runtime),
            "state_root": str(state),
            "database": str(runtime / "chiron.sqlite3"),
            "hermes_profile_root": str(profiles),
            "tailor": {
                "id": "tailor", "hermes_profile": "chironjp-tailor",
                "workspace": str(state / "workers" / "tailor"),
                "provider": "openai-codex", "model": "gpt-5.6-terra", "reasoning": "high",
            },
            "workers": [{
                "id": "worker-one", "enabled": True, "hermes_profile": "chironjp-worker-one",
                "chromium_profile": str(runtime / "browser" / "worker-one"),
                "workspace": str(state / "workers" / "worker-one"),
                "cdp_port": 19221, "display": 121, "vnc_port": 19521, "novnc_port": 19621,
            }, {
                "id": "worker-two", "enabled": False, "hermes_profile": "chironjp-worker-two",
                "chromium_profile": str(runtime / "browser" / "worker-two"),
                "workspace": str(state / "workers" / "worker-two"),
                "cdp_port": 19222, "display": 122, "vnc_port": 19522, "novnc_port": 19622,
            }],
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_generic_registry_confines_worker_paths(self):
        registry = load_registry(self.config)
        worker = registry.worker("worker-one")
        self.assertTrue(worker.chromium_profile.is_relative_to(registry.runtime_root))
        self.assertTrue(worker.workspace.is_relative_to(registry.state_root))
        self.assertEqual(worker.cdp_url, "http://127.0.0.1:19221")

    def test_registry_rejects_path_escape(self):
        data = json.loads(self.config.read_text())
        data["workers"][0]["workspace"] = str(self.root / "outside")
        self.config.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "escapes"):
            load_registry(self.config)

    def test_surface_is_loopback_and_view_only(self):
        worker = load_registry(self.config).worker("worker-one")
        web = self.root / "novnc"
        web.mkdir()
        with patch("chironjp.takeover.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"):
            commands = surface_commands(worker, novnc_web=web)
        self.assertIn("-localhost", commands["x11vnc"])
        self.assertIn("-viewonly", commands["x11vnc"])
        self.assertIn("127.0.0.1:19621", commands["websockify"])
        self.assertIn("127.0.0.1:19521", commands["websockify"])


if __name__ == "__main__":
    unittest.main()
