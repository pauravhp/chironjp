import json
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chironjp.ingress import import_stream
from chironjp.paths import REPO_ROOT
from chironjp.registry import load_registry
from chironjp.store import Store
from chironjp.tailor import admit_package, ensure_source_request, finish_request, render_request, run_one, write_brief


class TailorPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        runtime = self.root / "runtime"
        state = self.root / "state"
        self.database = runtime / "chiron.sqlite3"
        self.registry_path = self.root / "workers.json"
        self.registry_path.write_text(json.dumps({
            "schema_version": 3,
            "runtime_root": str(runtime),
            "state_root": str(state),
            "database": str(self.database),
            "hermes_profile_root": str(self.root / "profiles"),
            "tailor": {
                "id": "tailor", "hermes_profile": "tailor",
                "workspace": str(state / "tailor"),
                "provider": "test", "model": "test", "reasoning": "high",
            },
            "workers": [{
                "id": "one", "enabled": True, "hermes_profile": "worker-one",
                "chromium_profile": str(runtime / "browser" / "one"),
                "workspace": str(state / "worker-one"),
                "cdp_port": 29221, "display": 221, "vnc_port": 29521, "novnc_port": 29621,
            }, {
                "id": "two", "enabled": False, "hermes_profile": "worker-two",
                "chromium_profile": str(runtime / "browser" / "two"),
                "workspace": str(state / "worker-two"),
                "cdp_port": 29222, "display": 222, "vnc_port": 29522, "novnc_port": 29622,
            }],
        }), encoding="utf-8")
        self.registry = load_registry(self.registry_path)
        self.store = Store(self.database)
        self.store.initialize()
        record = {
            "source": "fixture",
            "sourceJobId": "fictional-role",
            "sourceUrl": "https://jobs.example.test/fictional-role",
            "applyUrl": "https://ats.example.test/apply/fictional-role",
            "officialApplyIdentity": "ats.example.test:fictional-role",
            "company": "Example Workshop",
            "title": "Software Engineer",
            "location": "Remote",
            "description": "Build reliable Python services with PostgreSQL.",
            "scrapedAt": "2026-01-01T00:00:00Z",
        }
        import_stream(self.store, io.StringIO(json.dumps(record) + "\n"))
        self.source_id = self.store.source_jobs()[0]["id"]
        self.profile = REPO_ROOT / "examples/fictional/canonical-profile-overrides.json"
        self.bank = REPO_ROOT / "examples/fictional/resume-bank.actual.json"
        self.template = REPO_ROOT / "resume/template.tex"
        self.manifest = REPO_ROOT / "examples/fictional/resume-manifest.actual.json"

    def tearDown(self):
        self.temp.cleanup()

    def request(self):
        return ensure_source_request(
            self.store, source_row_id=self.source_id, profile_path=self.profile,
            bank_path=self.bank, template_path=self.template,
        )

    def test_request_binds_profile_bank_and_template_and_brief_uses_argv(self):
        request = self.request()
        self.assertEqual(request["profile_path"], str(self.profile.resolve()))
        self.assertEqual(len(request["profile_sha256"]), 64)
        workspace = write_brief(self.store, self.registry, request["id"])
        brief = json.loads((workspace / "tailor-brief.json").read_text())
        self.assertIsInstance(brief["render_argv"], list)
        self.assertNotIn("render_command", brief)
        self.assertEqual(brief["production_selector"], "agent_only")

    def test_tailor_process_is_bound_to_the_exact_configured_hermes_profile(self):
        request = self.request()
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["env"] = kwargs["env"]
            captured["cwd"] = kwargs["cwd"]
            return type("Completed", (), {"returncode": 1})()

        with patch("chironjp.tailor.hermes_cli", return_value="/fixture/hermes"), patch(
            "chironjp.tailor.subprocess.run", side_effect=fake_run,
        ):
            result = run_one(self.store, self.registry, request["id"], timeout_seconds=1)

        self.assertEqual(result["state"], "unfulfilled")
        self.assertEqual(captured["command"][1:3], ["-p", "tailor"])
        self.assertNotIn("--in", captured["command"])
        self.assertEqual(captured["cwd"], Path(__file__).resolve().parents[1])
        self.assertEqual(captured["env"]["HERMES_HOME"], str(self.registry.tailor.hermes_home))

    @unittest.skipUnless(
        (os.environ.get("CHIRONJP_TECTONIC") or shutil.which("tectonic"))
        and (os.environ.get("CHIRONJP_PDFTOTEXT") or shutil.which("pdftotext"))
        and (os.environ.get("CHIRONJP_PDFTOPPM") or shutil.which("pdftoppm")),
        "Tectonic and Poppler are required for the real package proof",
    )
    def test_real_render_visual_binding_and_package_admission(self):
        request = self.request()
        workspace = write_brief(self.store, self.registry, request["id"])
        selection = workspace / "selection.json"
        selection.write_bytes(self.manifest.read_bytes())
        report = render_request(
            self.store, self.registry, request_id=request["id"],
            selection_path=selection, workspace=workspace,
        )
        self.assertTrue(report["passed"], report.get("errors"))

        other_record = {
            "source": "fixture", "sourceJobId": "different-role",
            "sourceUrl": "https://jobs.example.test/different-role",
            "company": "Another Example", "title": "Different Engineer",
            "description": "A deliberately different whole job description.",
            "scrapedAt": "2026-01-02T00:00:00Z",
        }
        import_stream(self.store, io.StringIO(json.dumps(other_record) + "\n"))
        other = next(row for row in self.store.source_jobs() if row["source_job_id"] == "different-role")
        other_request = ensure_source_request(
            self.store, source_row_id=other["id"], profile_path=self.profile,
            bank_path=self.bank, template_path=self.template,
        )
        other_workspace = write_brief(self.store, self.registry, other_request["id"])
        forged_dir = other_workspace / "renders" / "copied-from-another-request"
        forged_dir.mkdir(parents=True)
        forged = dict(report)
        for path_key, hash_key in (
            ("source_path", "source_sha256"), ("resume_path", "resume_sha256"),
            ("selection_path", "selection_sha256"), ("preview_path", "preview_sha256"),
        ):
            source_path = Path(report[path_key])
            copied_path = forged_dir / source_path.name
            shutil.copy2(source_path, copied_path)
            forged[path_key] = str(copied_path)
            self.assertEqual(len(forged[hash_key]), 64)
        forged_validation = other_workspace / "latest-validation.json"
        forged_validation.write_text(json.dumps(forged), encoding="utf-8")
        forged_visual = other_workspace / "visual-inspection.json"
        forged_visual.write_text(json.dumps({
            "schema_version": 1, "passed": True, "obvious_defects": [],
            "selection_sha256": forged["selection_sha256"],
            "preview_sha256": forged["preview_sha256"],
            "inspected_preview_path": forged["preview_path"],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "selection does not match"):
            finish_request(
                self.store, self.registry, request_id=other_request["id"],
                validation_path=forged_validation, visual_inspection_path=forged_visual,
            )

        visual_path = workspace / "visual-inspection.json"
        visual_path.write_text(json.dumps({
            "schema_version": 1,
            "passed": True,
            "obvious_defects": [],
            "selection_sha256": report["selection_sha256"],
            "preview_sha256": report["preview_sha256"],
            "inspected_preview_path": report["preview_path"],
        }), encoding="utf-8")
        artifact = finish_request(
            self.store, self.registry, request_id=request["id"],
            validation_path=report["latest_validation_path"],
            visual_inspection_path=visual_path,
        )
        package = admit_package(
            self.store, source_row_id=self.source_id, artifact_id=artifact["id"],
        )
        self.assertEqual(package["resume_sha256"], report["resume_sha256"])
        self.assertEqual(package["preview_sha256"], report["preview_sha256"])


if __name__ == "__main__":
    unittest.main()
