from __future__ import annotations

import json
import unittest
from pathlib import Path

from chironjp.registry import load_registry
from chironjp.resume import validate_manifest


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "templates/config"


class ConfigTemplateTests(unittest.TestCase):
    def test_profile_keeps_actual_typed_shape_with_answers_unset(self) -> None:
        profile = json.loads((CONFIG / "canonical-profile-overrides.json").read_text(encoding="utf-8"))
        self.assertTrue(profile["learning_and_inspiration"]["source_question"])
        self.assertEqual(profile["learning_and_inspiration"]["narrative"], "")
        self.assertEqual(len(profile["education"]), 1)
        self.assertEqual(
            set(profile["education"][0]),
            {
                "id", "current", "degree", "completed_end", "expected_end", "field", "gpa",
                "location", "school", "source_completeness", "source_path", "start",
            },
        )
        self.assertEqual(len(profile["canonical_answers"]), 29)
        self.assertTrue(all(value == "" for value in profile["canonical_answers"].values()))
        self.assertIsNone(profile["work_authorization"]["Canada"]["legally_authorized"])
        self.assertIsNone(profile["work_authorization"]["Canada"]["future_employer_sponsorship_required"])
        self.assertIsNone(profile["work_authorization"]["United States"]["legally_authorized"])
        self.assertIsNone(profile["work_authorization"]["United States"]["future_employer_sponsorship_required"])

    def test_worker_template_keeps_runtime_and_model_values_blank(self) -> None:
        registry = json.loads((CONFIG / "chiron-workers.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["schema_version"], 3)
        self.assertEqual(
            (
                registry["runtime_root"], registry["state_root"],
                registry["database"], registry["hermes_profile_root"],
            ),
            ("", "", "", ""),
        )
        self.assertEqual(
            (registry["tailor"]["hermes_profile"], registry["tailor"]["provider"], registry["tailor"]["model"], registry["tailor"]["reasoning"]),
            ("", "", "", ""),
        )
        self.assertGreaterEqual(len(registry["workers"]), 2)
        self.assertTrue(all(not worker["enabled"] for worker in registry["workers"]))
        self.assertTrue(all(worker["hermes_profile"] == "" for worker in registry["workers"]))
        self.assertTrue(all(worker["chromium_profile"] == "" for worker in registry["workers"]))

    def test_fictional_profile_bank_and_manifest_use_real_resume_contract(self) -> None:
        fictional = ROOT / "examples/fictional"
        manifest = json.loads((fictional / "resume-manifest.actual.json").read_text(encoding="utf-8"))
        result = validate_manifest(
            manifest,
            role="Backend Engineer",
            description="Build reliable services with Python and PostgreSQL.",
            profile_path=fictional / "canonical-profile-overrides.json",
            bank_path=fictional / "resume-bank.actual.json",
            template_path=ROOT / "resume/template.tex",
        )
        self.assertTrue(result["passed"], result["errors"])
        self.assertIn("Avery Example", result["source"])
        self.assertNotIn("@@FULL_NAME@@", result["source"])

    def test_fictional_worker_registry_uses_the_runtime_schema(self) -> None:
        registry = load_registry(ROOT / "examples/fictional/chiron-workers.json")
        self.assertEqual(
            registry.worker("worker-a").hermes_home,
            Path("/srv/chiron-example/runtime/hermes/profiles/chiron-example-a"),
        )
        self.assertEqual(
            registry.tailor.hermes_home,
            Path("/srv/chiron-example/runtime/hermes/profiles/chiron-example-tailor"),
        )


if __name__ == "__main__":
    unittest.main()
