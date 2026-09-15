from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/chiron-setup/scripts/setup_state.py"
TEMPLATES = ROOT / "templates"
RESUME_ASSETS = ROOT / "resume"


class SetupStateTests(unittest.TestCase):
    def run_tool(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_init_is_non_clobbering_and_rerunnable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "runtime"
            arguments = (
                "init", "--workspace", str(workspace), "--templates", str(TEMPLATES),
                "--resume-assets", str(RESUME_ASSETS),
            )
            first = self.run_tool(*arguments)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(
                (workspace / "resume/template.tex").read_bytes(),
                (RESUME_ASSETS / "template.tex").read_bytes(),
            )
            self.assertIn("@@FULL_NAME@@", (workspace / "resume/template.tex").read_text(encoding="utf-8"))
            profile = workspace / "config/canonical-profile-overrides.json"
            profile.write_text('{"owner":"preserved"}\n', encoding="utf-8")
            state_before = (workspace / ".chiron-setup/state.json").read_bytes()

            second = self.run_tool(*arguments)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(profile.read_text(encoding="utf-8"), '{"owner":"preserved"}\n')
            self.assertEqual((workspace / ".chiron-setup/state.json").read_bytes(), state_before)
            self.assertIn(f"kept: {profile}", second.stdout)

    def test_prescribed_proof_and_stale_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "runtime"
            self.assertEqual(
                self.run_tool(
                    "init", "--workspace", str(workspace), "--templates", str(TEMPLATES),
                    "--resume-assets", str(RESUME_ASSETS),
                ).returncode,
                0,
            )
            wrong = self.run_tool(
                "mark",
                "--workspace",
                str(workspace),
                "--stage",
                "isolated-browser",
                "--proof",
                "harmless-hermes-request",
            )
            self.assertEqual(wrong.returncode, 2)

            marked = self.run_tool(
                "mark",
                "--workspace",
                str(workspace),
                "--stage",
                "isolated-browser",
                "--proof",
                "cdp-fill-reconnect",
            )
            self.assertEqual(marked.returncode, 0, marked.stderr)
            stale = self.run_tool(
                "stale",
                "--workspace",
                str(workspace),
                "--stage",
                "isolated-browser",
                "--reason",
                "behavior-check-failed",
            )
            self.assertEqual(stale.returncode, 0, stale.stderr)
            state = json.loads((workspace / ".chiron-setup/state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stages"]["isolated-browser"]["status"], "stale")

    def test_only_owner_deselected_photon_can_be_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "runtime"
            self.run_tool(
                "init", "--workspace", str(workspace), "--templates", str(TEMPLATES),
                "--resume-assets", str(RESUME_ASSETS),
            )
            rejected = self.run_tool(
                "skip",
                "--workspace",
                str(workspace),
                "--stage",
                "remote-access",
                "--reason",
                "owner-not-selected",
            )
            self.assertEqual(rejected.returncode, 2)
            accepted = self.run_tool(
                "skip",
                "--workspace",
                str(workspace),
                "--stage",
                "photon",
                "--reason",
                "owner-not-selected",
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_init_rejects_symlinked_target_without_touching_external_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "runtime"
            target_parent = workspace / "config"
            target_parent.mkdir(parents=True)
            external = root / "external.json"
            external.write_text("owner data\n", encoding="utf-8")
            os.symlink(external, target_parent / "canonical-profile-overrides.json")

            result = self.run_tool(
                "init", "--workspace", str(workspace), "--templates", str(TEMPLATES),
                "--resume-assets", str(RESUME_ASSETS),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("must not be a symlink", result.stderr)
            self.assertEqual(external.read_text(encoding="utf-8"), "owner data\n")

    def test_init_rejects_symlinked_ancestor_and_dangling_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            external.mkdir()

            ancestor_workspace = root / "ancestor-runtime"
            ancestor_workspace.mkdir()
            os.symlink(external, ancestor_workspace / "config")
            ancestor = self.run_tool(
                "init", "--workspace", str(ancestor_workspace), "--templates", str(TEMPLATES),
                "--resume-assets", str(RESUME_ASSETS),
            )
            self.assertEqual(ancestor.returncode, 2)
            self.assertIn("ancestor must not be a symlink", ancestor.stderr)
            self.assertEqual(list(external.iterdir()), [])

            dangling_workspace = root / "dangling-runtime"
            (dangling_workspace / "config").mkdir(parents=True)
            os.symlink(root / "absent.json", dangling_workspace / "config/canonical-profile-overrides.json")
            dangling = self.run_tool(
                "init", "--workspace", str(dangling_workspace), "--templates", str(TEMPLATES),
                "--resume-assets", str(RESUME_ASSETS),
            )
            self.assertEqual(dangling.returncode, 2)
            self.assertIn("must not be a symlink", dangling.stderr)
            self.assertFalse((root / "absent.json").exists())


if __name__ == "__main__":
    unittest.main()
