import tempfile
import unittest
from pathlib import Path

from chironjp.store import Store, iso


class ClaimExclusionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name) / "runtime/chiron.sqlite3")
        self.store.initialize()
        with self.store.immediate() as connection:
            for number in (1, 2):
                source = connection.execute(
                    """INSERT INTO source_jobs(
                       source_name,source_job_id,content_hash,source_url,company,role,
                       scraped_at,imported_at,updated_at,application_id,disposition
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,'assigned')""",
                    (
                        "fixture", f"role-{number}", str(number) * 64,
                        f"https://jobs.example.test/{number}", "Example", f"Role {number}",
                        iso(), iso(), iso(), f"app-{number}",
                    ),
                ).lastrowid
                connection.execute(
                    """INSERT INTO applications(id,source_row_id,start_url,tenant_host,created_at)
                       VALUES (?,?,?,?,?)""",
                    (f"app-{number}", source, f"https://ats.example.test/{number}", "ats.example.test", iso()),
                )
                connection.execute(
                    """INSERT INTO packages(
                       id,application_id,resume_path,resume_sha256,source_path,source_sha256,
                       manifest_path,manifest_sha256,validation_path,validation_sha256,
                       preview_path,preview_sha256,visual_inspection_json,created_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"pkg-{number}", f"app-{number}", f"/tmp/resume-{number}.pdf", "a" * 64,
                        f"/tmp/resume-{number}.tex", "b" * 64, f"/tmp/selection-{number}.json", "c" * 64,
                        f"/tmp/validation-{number}.json", "d" * 64, f"/tmp/preview-{number}.png", "e" * 64,
                        "{}", iso(),
                    ),
                )

    def tearDown(self):
        self.temporary.cleanup()

    def test_competing_application_and_worker_claims_are_excluded(self):
        first = self.store.claim_package("pkg-1", "worker-one")
        repeated = self.store.claim_package("pkg-1", "worker-one")
        self.assertEqual(repeated["id"], first["id"])
        with self.assertRaisesRegex(ValueError, "not claimable|active browser"):
            self.store.claim_package("pkg-1", "worker-two")
        with self.assertRaisesRegex(ValueError, "worker already"):
            self.store.claim_package("pkg-2", "worker-one")

        self.store.bind_attempt_target(
            first["id"], worker_id="worker-one", target_id="worker-one-target",
            start_url="https://ats.example.test/1",
        )
        self.store.fail_attempt(first["id"], code="fixture_failure", detail="controlled retry")
        with self.assertRaisesRegex(ValueError, "designated browser worker"):
            self.store.claim_package("pkg-1", "worker-two")
        retried = self.store.claim_package("pkg-1", "worker-one")
        self.assertNotEqual(retried["id"], first["id"])
        self.assertEqual(retried["retry_of_attempt_id"], first["id"])

        # A retry can fail before it rebinds the inherited live target. The
        # application still belongs to the profile that owns the prior target.
        self.store.fail_attempt(
            retried["id"], code="retry_start_failure", detail="failed before target resume",
        )
        with self.assertRaisesRegex(ValueError, "designated browser worker"):
            self.store.claim_package("pkg-1", "worker-two")
        third = self.store.claim_package("pkg-1", "worker-one")
        self.assertEqual(third["retry_of_attempt_id"], first["id"])


if __name__ == "__main__":
    unittest.main()
