from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from chironjp.resume import render_agent_manifest, tailor_contract, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "examples" / "fictional" / "resume-bank.actual.json"
MANIFEST = ROOT / "examples" / "fictional" / "resume-manifest.actual.json"
TEMPLATE = ROOT / "resume" / "template.tex"
PROFILE = ROOT / "examples" / "fictional" / "canonical-profile-overrides.json"
ROLE = "Backend Engineer"
DESCRIPTION = "Build reliable services with Python and PostgreSQL."


class ResumeContractTests(unittest.TestCase):
    def manifest(self):
        return json.loads(MANIFEST.read_text(encoding="utf-8"))

    def validate(self, manifest):
        return validate_manifest(
            manifest,
            role=ROLE,
            description=DESCRIPTION,
            bank_path=BANK,
            template_path=TEMPLATE,
            profile_path=PROFILE,
        )

    def test_contract_exposes_actual_finite_bank_and_project_variants(self):
        contract = tailor_contract(
            role=ROLE,
            description=DESCRIPTION,
            bank_path=BANK,
            template_path=TEMPLATE,
            profile_path=PROFILE,
        )
        self.assertEqual(contract["fixed_experience_order"], ["northwind_labs", "maple_studio"])
        queue_garden = next(item for item in contract["projects"] if item["id"] == "queue_garden")
        self.assertEqual([item["id"] for item in queue_garden["variants"]], ["broad", "detailed"])
        self.assertEqual(contract["jd_technology_hints"], ["Python", "PostgreSQL"])
        self.assertIn("fictional-owner-interview:2026-01", contract["skill_sources"])
        self.assertEqual(len(contract["bank_sha256"]), 64)
        self.assertEqual(len(contract["template_sha256"]), 64)

    def test_valid_manifest_composes_verbatim_canonical_content(self):
        result = self.validate(self.manifest())
        self.assertTrue(result["passed"], result["errors"])
        source = result["source"]
        self.assertIn("Defined typed service contracts", source)
        self.assertIn("Built a local job-queue laboratory", source)
        self.assertNotIn("Added deterministic failure scenarios", source)
        self.assertIn("Harbor Town, XY", source)
        self.assertIn("Sep 2021 -- May 2025", source)
        self.assertNotIn("Example City, ZZ", source)
        self.assertEqual(result["selection"]["project_variants"], {"queue_garden": "broad"})
        self.assertEqual(result["selection"]["owner_confirmation_needed"], [])

    def test_education_uses_row_location_and_status_specific_end_date(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        row = profile["education"][0]
        row.update({
            "location": "School City, AA",
            "current": False,
            "completed_end": "2024-06",
            "expected_end": "2099-12",
        })
        profile["location"]["city"] = "Candidate City"
        profile["location"]["region"] = "BB"
        with tempfile.TemporaryDirectory(prefix="chironjp-profile-") as raw:
            profile_path = Path(raw) / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            completed = validate_manifest(
                self.manifest(), role=ROLE, description=DESCRIPTION,
                bank_path=BANK, template_path=TEMPLATE, profile_path=profile_path,
            )
            self.assertTrue(completed["passed"], completed["errors"])
            self.assertIn("School City, AA", completed["source"])
            self.assertIn("Sep 2021 -- Jun 2024", completed["source"])
            self.assertNotIn("Candidate City", completed["source"])
            self.assertNotIn("Dec 2099", completed["source"])

            row["current"] = True
            row["expected_end"] = "2027-08"
            row["completed_end"] = "1999-01"
            row["location"] = ""
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            current = validate_manifest(
                self.manifest(), role=ROLE, description=DESCRIPTION,
                bank_path=BANK, template_path=TEMPLATE, profile_path=profile_path,
            )
            self.assertTrue(current["passed"], current["errors"])
            self.assertIn("Sep 2021 -- Aug 2027", current["source"])
            self.assertNotIn("Jan 1999", current["source"])
            self.assertNotIn("Candidate City", current["source"])

    def test_detailed_project_variant_is_explicit_and_verbatim(self):
        manifest = self.manifest()
        manifest["project_variants"]["queue_garden"] = "detailed"
        result = self.validate(manifest)
        self.assertTrue(result["passed"], result["errors"])
        self.assertIn("Added deterministic failure scenarios", result["source"])
        manifest["project_variants"]["queue_garden"] = "invented"
        errors = self.validate(manifest)["errors"]
        self.assertIn("project_variant", {item["code"] for item in errors})

    def test_unknown_claim_three_projects_and_missing_award_are_rejected(self):
        manifest = self.manifest()
        manifest["experience_bullets"]["northwind_labs"].append("rewritten_claim")
        manifest["projects"].append("catalog_compass")
        manifest["awards"] = []
        errors = self.validate(manifest)["errors"]
        codes = {item["code"] for item in errors}
        self.assertTrue({"unknown_bullet", "project_count", "required_award"} <= codes)

    def test_skills_are_inventory_bound_and_whole_jd_evidence_is_required(self):
        manifest = self.manifest()
        manifest["skills"]["Delivery"].append("Unverified Vendor Tool")
        manifest["jd_coverage"] = manifest["jd_coverage"][:1]
        errors = self.validate(manifest)["errors"]
        codes = {item["code"] for item in errors}
        self.assertIn("owner_denied_skill", codes)
        self.assertIn("missing_jd_analysis", codes)

    def test_qualified_owner_denial_is_not_reconfirmed(self):
        description = DESCRIPTION + " Familiarity with Unverified Vendor Tool components is helpful."
        manifest = self.manifest()
        manifest["jd_coverage"].append({
            "term": "Unverified Vendor Tool components",
            "jd_quote": "Unverified Vendor Tool components",
            "skill": None,
            "reason": "The underlying vendor tool is explicitly excluded by the owner.",
        })
        result = validate_manifest(
            manifest,
            role=ROLE,
            description=description,
            bank_path=BANK,
            template_path=TEMPLATE,
            profile_path=PROFILE,
        )
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["selection"]["owner_confirmation_needed"], [])

    def test_real_renderer_when_host_tools_are_available(self):
        tectonic = os.environ.get("CHIRONJP_TECTONIC") or shutil.which("tectonic")
        pdftotext = os.environ.get("CHIRONJP_PDFTOTEXT") or shutil.which("pdftotext")
        pdftoppm = os.environ.get("CHIRONJP_PDFTOPPM") or shutil.which("pdftoppm")
        if not all((tectonic, pdftotext, pdftoppm)):
            self.skipTest("Tectonic and Poppler are not available")
        with tempfile.TemporaryDirectory(prefix="chironjp-render-") as raw:
            detailed_manifest = self.manifest()
            detailed_manifest["project_variants"]["queue_garden"] = "detailed"
            detailed_path = Path(raw) / "manifest.json"
            detailed_path.write_text(json.dumps(detailed_manifest), encoding="utf-8")
            report = render_agent_manifest(
                selection_path=detailed_path,
                role=ROLE,
                description=DESCRIPTION,
                output_dir=raw,
                bank_path=BANK,
                template_path=TEMPLATE,
                profile_path=PROFILE,
                tectonic=tectonic,
                pdftotext=pdftotext,
                pdftoppm=pdftoppm,
            )
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["page_count"], 1)
            self.assertGreater(report["word_count"], 0)
            self.assertEqual(report["skills_line_count"], 4)
            self.assertEqual(report["clipped_text_count"], 0)
            self.assertEqual(report["text_intersection_count"], 0)
            self.assertFalse(report["overflow"])
            self.assertEqual(len(report["resume_sha256"]), 64)
            self.assertEqual(len(report["preview_sha256"]), 64)
            self.assertTrue(Path(report["preview_path"]).is_file())
            self.assertIn(
                "Added deterministic failure scenarios",
                Path(report["source_path"]).read_text(encoding="utf-8"),
            )
            self.assertTrue(report["vision_inspection_required"])
            self.assertEqual(
                report["vision_contract"]["preview_sha256"], report["preview_sha256"]
            )


if __name__ == "__main__":
    unittest.main()
