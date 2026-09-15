from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chironjp.ingress import import_path
from chironjp.store import Store


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "examples/fictional/jobs.ndjson"


class FictionalJobsTests(unittest.TestCase):
    def test_fixture_uses_real_ingress_and_deduplicates_on_apply_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "chiron.sqlite3"
            counts = import_path(database, FIXTURE)
            jobs = Store(database, readonly=True).source_jobs()
        self.assertEqual(counts, {"scanned": 2, "inserted": 1, "updated": 1, "unchanged": 0})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["official_apply_identity"], "url:https://apply.example.invalid/clockwork/automation-engineer")

    def test_fixture_contains_reserved_domains_only(self) -> None:
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(len(text.strip().splitlines()), 2)
        for host in ("source-a.example.invalid", "source-b.example.invalid", "apply.example.invalid"):
            self.assertIn(host, text)
        self.assertNotIn("@", text)


if __name__ == "__main__":
    unittest.main()
