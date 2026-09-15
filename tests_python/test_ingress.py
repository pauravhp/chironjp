import io
import tempfile
import unittest
from pathlib import Path

from chironjp.ingress import import_stream
from chironjp.store import Store


def record(source_id: str = "role-1", identity: str = "https://apply.example.invalid/roles/42") -> str:
    import json

    return json.dumps({
        "source": "fictional-source",
        "sourceJobId": source_id,
        "sourceUrl": f"https://jobs.example.invalid/roles/{source_id}",
        "applyUrl": "https://apply.example.invalid/roles/42",
        "officialApplyIdentity": identity,
        "company": "Northstar Robotics (fictional)",
        "title": "Platform Engineer",
        "location": "Remote",
        "description": "Build a fictional reliable service.",
        "postedAt": "2026-09-01T00:00:00Z",
        "scrapedAt": "2026-09-02T00:00:00Z",
    }) + "\n"


class IngressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "runtime" / "chiron.sqlite3"
        self.store = Store(self.database)
        self.store.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_rerun_is_idempotent(self):
        first = import_stream(self.store, io.StringIO(record()))
        second = import_stream(self.store, io.StringIO(record()))
        self.assertEqual(first, {"scanned": 1, "inserted": 1, "updated": 0, "unchanged": 0})
        self.assertEqual(second, {"scanned": 1, "inserted": 0, "updated": 0, "unchanged": 1})
        self.assertEqual(len(self.store.source_jobs()), 1)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_official_apply_identity_collapses_source_alias(self):
        import_stream(self.store, io.StringIO(record()))
        outcome = import_stream(self.store, io.StringIO(record(source_id="alias-2")))
        self.assertEqual(outcome["updated"], 1)
        self.assertEqual(len(self.store.source_jobs()), 1)
        self.assertEqual(self.store.source_jobs()[0]["source_job_id"], "alias-2")

    def test_invalid_records_rollback_without_partial_row(self):
        with self.assertRaisesRegex(ValueError, "applyUrl"):
            import_stream(self.store, io.StringIO(record().replace(
                '"https://apply.example.invalid/roles/42"', '"file:///tmp/not-web"', 1,
            )))
        self.assertEqual(self.store.source_jobs(), [])


if __name__ == "__main__":
    unittest.main()
