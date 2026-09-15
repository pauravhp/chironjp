"""Sanitized SQLite subset of Chiron's durable source-to-Review store.

The public preview intentionally exposes only the records exercised by the
published source and resume paths. It does not implement automatic dispatch or
an employer final-action transition.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


SCHEMA_VERSION = 1
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY,
    installed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    source_url TEXT NOT NULL,
    resolver_url TEXT,
    official_apply_identity TEXT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    scraped_at TEXT NOT NULL,
    disposition TEXT NOT NULL DEFAULT 'waiting'
        CHECK (disposition IN ('waiting','assigned','handled','skipped','closed')),
    application_id TEXT UNIQUE,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_name, source_job_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS source_jobs_official_identity
    ON source_jobs(official_apply_identity)
    WHERE official_apply_identity IS NOT NULL;
CREATE INDEX IF NOT EXISTS source_jobs_newest
    ON source_jobs(disposition, COALESCE(posted_at, scraped_at) DESC);
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE REFERENCES source_jobs(id),
    start_url TEXT NOT NULL,
    tenant_host TEXT NOT NULL,
    ats_family TEXT NOT NULL DEFAULT 'unknown',
    jurisdiction TEXT NOT NULL DEFAULT 'OTHER'
        CHECK (jurisdiction IN ('CA','US','OTHER')),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','review')),
    claimable INTEGER NOT NULL DEFAULT 1 CHECK (claimable IN (0,1)),
    mission_worker_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS packages (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL UNIQUE REFERENCES applications(id),
    resume_path TEXT NOT NULL,
    resume_sha256 TEXT NOT NULL CHECK (length(resume_sha256) = 64),
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
    manifest_path TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
    validation_path TEXT NOT NULL,
    validation_sha256 TEXT NOT NULL CHECK (length(validation_sha256) = 64),
    preview_path TEXT NOT NULL,
    preview_sha256 TEXT NOT NULL CHECK (length(preview_sha256) = 64),
    visual_inspection_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    package_id TEXT NOT NULL REFERENCES packages(id),
    worker_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','failed','review')),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    safe_answers_json TEXT NOT NULL DEFAULT '{}',
    provisional_json TEXT NOT NULL DEFAULT '[]',
    failure_code TEXT,
    failure_detail TEXT,
    retry_of_attempt_id TEXT REFERENCES attempts(id),
    designated_target_id TEXT,
    designated_start_url TEXT,
    designated_at TEXT,
    resolved_ats_family TEXT,
    target_last_url TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS attempts_one_active_application
    ON attempts(application_id) WHERE status = 'running';
CREATE UNIQUE INDEX IF NOT EXISTS attempts_one_active_worker
    ON attempts(worker_id) WHERE status = 'running';
CREATE TABLE IF NOT EXISTS reviews (
    attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
    reached_at TEXT NOT NULL,
    rendered_url TEXT NOT NULL,
    rendered_stage TEXT NOT NULL CHECK (rendered_stage = 'review'),
    expected_resume_sha256 TEXT NOT NULL CHECK (length(expected_resume_sha256) = 64),
    observed_resume_sha256 TEXT NOT NULL CHECK (length(observed_resume_sha256) = 64),
    rendered_json TEXT NOT NULL,
    provisional_json TEXT NOT NULL,
    final_actions_json TEXT NOT NULL,
    submit_untouched INTEGER NOT NULL CHECK (submit_untouched = 1)
);
CREATE TABLE IF NOT EXISTS live_tabs (
    application_id TEXT PRIMARY KEY REFERENCES applications(id),
    worker_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    target_id TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active','missing','submitted','abandoned','parked')),
    last_url TEXT NOT NULL,
    review_version INTEGER NOT NULL DEFAULT 1 CHECK (review_version >= 1),
    closed_at TEXT,
    closed_reason TEXT
);
CREATE TABLE IF NOT EXISTS human_review_sessions (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    review_version INTEGER NOT NULL CHECK (review_version >= 1),
    worker_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    target_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    state TEXT NOT NULL CHECK (state IN (
        'controlling','viewed','edited','form_needs_attention','outcome_uncertain','submitted'
    )),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    screenshot_path TEXT,
    screenshot_sha256 TEXT CHECK (
        screenshot_sha256 IS NULL OR length(screenshot_sha256) = 64
    ),
    transport_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS tailor_requests (
    id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE CHECK (length(request_key) = 64),
    source_row_id INTEGER NOT NULL REFERENCES source_jobs(id),
    role TEXT NOT NULL,
    description TEXT NOT NULL,
    profile_path TEXT NOT NULL,
    profile_sha256 TEXT NOT NULL CHECK (length(profile_sha256) = 64),
    bank_path TEXT NOT NULL,
    bank_sha256 TEXT NOT NULL CHECK (length(bank_sha256) = 64),
    template_path TEXT NOT NULL,
    template_sha256 TEXT NOT NULL CHECK (length(template_sha256) = 64),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tailor_attempts (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES tailor_requests(id),
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    return_code INTEGER,
    workspace_path TEXT NOT NULL,
    usage_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS tailored_artifacts (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE REFERENCES tailor_requests(id),
    generation_key TEXT NOT NULL UNIQUE CHECK (length(generation_key) = 64),
    resume_path TEXT NOT NULL,
    resume_sha256 TEXT NOT NULL CHECK (length(resume_sha256) = 64),
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
    selection_path TEXT NOT NULL,
    selection_sha256 TEXT NOT NULL CHECK (length(selection_sha256) = 64),
    validation_path TEXT NOT NULL,
    validation_sha256 TEXT NOT NULL CHECK (length(validation_sha256) = 64),
    preview_path TEXT NOT NULL,
    preview_sha256 TEXT NOT NULL CHECK (length(preview_sha256) = 64),
    visual_inspection_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def iso(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Store:
    def __init__(self, path: str | Path, *, readonly: bool = False):
        self.path = Path(path).expanduser().resolve()
        self.readonly = readonly

    def connect(self) -> sqlite3.Connection:
        if self.readonly:
            connection = sqlite3.connect(
                f"file:{self.path}?mode=ro", uri=True, timeout=10,
            )
            connection.execute("PRAGMA query_only=ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.path.parent, 0o700)
            connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        if self.readonly:
            raise ValueError("cannot initialize a read-only store")
        connection = self.connect()
        try:
            connection.executescript(SCHEMA)
            installed = connection.execute(
                "SELECT version FROM schema_meta ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if installed and int(installed["version"]) != SCHEMA_VERSION:
                raise ValueError("unsupported ChironJP database schema")
            if not installed:
                connection.execute(
                    "INSERT INTO schema_meta(version,installed_at) VALUES (?,?)",
                    (SCHEMA_VERSION, iso()),
                )
            connection.commit()
        finally:
            connection.close()
        os.chmod(self.path, 0o600)

    @contextmanager
    def immediate(self) -> Iterator[sqlite3.Connection]:
        if self.readonly:
            raise ValueError("cannot write a read-only store")
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_source_job(self, job: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
        """Import one normalized public-source record using Chiron's durable ingress shape."""
        required = ("source", "sourceJobId", "sourceUrl", "company", "title", "scrapedAt")
        missing = [key for key in required if not str(job.get(key) or "").strip()]
        if missing:
            raise ValueError(f"source record is missing: {', '.join(missing)}")
        source_name = str(job["source"]).strip()
        source_job_id = str(job["sourceJobId"]).strip()
        official_identity = str(job.get("officialApplyIdentity") or "").strip() or None
        values = {
            "source_name": source_name,
            "source_job_id": source_job_id,
            "source_url": _http_url(job["sourceUrl"], "sourceUrl"),
            "resolver_url": _http_url(job.get("applyUrl"), "applyUrl", optional=True),
            "official_apply_identity": official_identity,
            "company": str(job["company"]).strip(),
            "role": str(job["title"]).strip(),
            "location": str(job.get("location") or "").strip(),
            "description": str(job.get("description") or "").strip(),
            "posted_at": _timestamp(job.get("postedAt"), "postedAt", optional=True),
            "scraped_at": _timestamp(job["scrapedAt"], "scrapedAt"),
        }
        if official_identity and not values["resolver_url"]:
            raise ValueError("officialApplyIdentity requires applyUrl")
        content_hash = hashlib.sha256(compact_json(values).encode()).hexdigest()
        timestamp = iso()
        with self.immediate() as connection:
            existing = connection.execute(
                """SELECT * FROM source_jobs
                   WHERE (source_name=? AND source_job_id=?)
                      OR (? IS NOT NULL AND official_apply_identity=?)
                   ORDER BY official_apply_identity IS NOT NULL DESC LIMIT 1""",
                (source_name, source_job_id, official_identity, official_identity),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """INSERT INTO source_jobs(
                       source_name,source_job_id,content_hash,source_url,resolver_url,
                       official_apply_identity,company,role,location,description,
                       posted_at,scraped_at,imported_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        values["source_name"], values["source_job_id"], content_hash,
                        values["source_url"], values["resolver_url"],
                        values["official_apply_identity"], values["company"], values["role"],
                        values["location"], values["description"], values["posted_at"],
                        values["scraped_at"], timestamp, timestamp,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM source_jobs WHERE id=?", (cursor.lastrowid,),
                ).fetchone()
                return "inserted", dict(row)
            if existing["content_hash"] == content_hash:
                return "unchanged", dict(existing)
            connection.execute(
                """UPDATE source_jobs SET source_name=?,source_job_id=?,content_hash=?,
                   source_url=?,resolver_url=?,official_apply_identity=?,company=?,role=?,
                   location=?,description=?,posted_at=?,scraped_at=?,updated_at=? WHERE id=?""",
                (
                    values["source_name"], values["source_job_id"], content_hash,
                    values["source_url"], values["resolver_url"],
                    values["official_apply_identity"], values["company"], values["role"],
                    values["location"], values["description"], values["posted_at"],
                    values["scraped_at"], timestamp, existing["id"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM source_jobs WHERE id=?", (existing["id"],),
            ).fetchone()
            return "updated", dict(row)

    def source_jobs(self) -> list[Mapping[str, Any]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                """SELECT * FROM source_jobs
                   ORDER BY COALESCE(posted_at,scraped_at) DESC,id"""
            )]
        finally:
            connection.close()

    def claim_package(self, package_id: str, worker_id: str) -> Mapping[str, Any]:
        """Create one durable browser attempt for an admitted package."""
        attempt_id = "att_" + os.urandom(12).hex()
        with self.immediate() as connection:
            package = connection.execute(
                "SELECT * FROM packages WHERE id=?", (package_id,),
            ).fetchone()
            if package is None:
                raise ValueError("unknown browser package")
            application = connection.execute(
                "SELECT * FROM applications WHERE id=?", (package["application_id"],),
            ).fetchone()
            if application is None:
                raise ValueError("application is not claimable")
            same = connection.execute(
                """SELECT * FROM attempts WHERE package_id=? AND worker_id=?
                   AND status='running' ORDER BY started_at DESC LIMIT 1""",
                (package_id, worker_id),
            ).fetchone()
            if same is not None:
                return dict(same)
            if not application["claimable"]:
                raise ValueError("application is not claimable")
            if application["status"] == "review":
                raise ValueError("application already has a retained Review")
            if application["mission_worker_id"] and application["mission_worker_id"] != worker_id:
                raise ValueError("application remains bound to its designated browser worker")
            conflicting_application = connection.execute(
                "SELECT 1 FROM attempts WHERE application_id=? AND status='running'",
                (package["application_id"],),
            ).fetchone()
            if conflicting_application:
                raise ValueError("application already has an active browser attempt")
            conflicting_worker = connection.execute(
                "SELECT 1 FROM attempts WHERE worker_id=? AND status='running'",
                (worker_id,),
            ).fetchone()
            if conflicting_worker:
                raise ValueError("worker already has an active browser attempt")
            prior = connection.execute(
                """SELECT id FROM attempts WHERE application_id=? AND package_id=?
                   AND worker_id=? AND status='failed' AND designated_target_id IS NOT NULL
                   ORDER BY ended_at DESC,started_at DESC LIMIT 1""",
                (package["application_id"], package_id, worker_id),
            ).fetchone()
            connection.execute(
                """INSERT INTO attempts(
                   id,application_id,package_id,worker_id,status,started_at,retry_of_attempt_id
                   ) VALUES (?,?,?,?,?,?,?)""",
                (
                    attempt_id, package["application_id"], package_id, worker_id,
                    "running", iso(), prior["id"] if prior else None,
                ),
            )
            connection.execute(
                "UPDATE applications SET status='running',claimable=0,mission_worker_id=? WHERE id=?",
                (worker_id, package["application_id"]),
            )
            return dict(connection.execute(
                "SELECT * FROM attempts WHERE id=?", (attempt_id,),
            ).fetchone())

    def running_attempt(self, worker_id: str) -> Mapping[str, Any] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT * FROM attempts WHERE worker_id=? AND status='running'
                   ORDER BY started_at DESC LIMIT 1""",
                (worker_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def fail_attempt(self, attempt_id: str, *, code: str, detail: str) -> Mapping[str, Any]:
        if not code.strip():
            raise ValueError("failure code is required")
        with self.immediate() as connection:
            attempt = connection.execute(
                "SELECT * FROM attempts WHERE id=?", (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["status"] != "running":
                raise ValueError("browser attempt is not running")
            connection.execute(
                """UPDATE attempts SET status='failed',ended_at=?,failure_code=?,failure_detail=?
                   WHERE id=?""",
                (iso(), code[:120], detail[:1000], attempt_id),
            )
            retained_owner = connection.execute(
                """WITH RECURSIVE retry_chain(id,retry_of_attempt_id,worker_id,designated_target_id) AS (
                       SELECT id,retry_of_attempt_id,worker_id,designated_target_id
                       FROM attempts WHERE id=?
                       UNION ALL
                       SELECT prior.id,prior.retry_of_attempt_id,prior.worker_id,
                              prior.designated_target_id
                       FROM attempts prior JOIN retry_chain current
                         ON prior.id=current.retry_of_attempt_id
                   )
                   SELECT worker_id FROM retry_chain
                   WHERE designated_target_id IS NOT NULL LIMIT 1""",
                (attempt_id,),
            ).fetchone()
            connection.execute(
                """UPDATE applications SET status='queued',claimable=1,mission_worker_id=?
                   WHERE id=?""",
                (
                    retained_owner["worker_id"] if retained_owner else None,
                    attempt["application_id"],
                ),
            )
            return dict(connection.execute(
                "SELECT * FROM attempts WHERE id=?", (attempt_id,),
            ).fetchone())

    def bind_attempt_target(
        self, attempt_id: str, *, worker_id: str, target_id: str, start_url: str,
    ) -> Mapping[str, Any]:
        """Immutably designate the one browser page created for an attempt."""
        target_id = str(target_id).strip()
        start_url = _http_url(start_url, "designated start URL") or ""
        if not target_id:
            raise ValueError("designated browser target id is required")
        with self.immediate() as connection:
            row = connection.execute(
                """SELECT t.*,a.start_url FROM attempts t
                   JOIN applications a ON a.id=t.application_id WHERE t.id=?""",
                (attempt_id,),
            ).fetchone()
            if row is None or row["status"] != "running":
                raise ValueError("browser attempt is not running")
            if row["worker_id"] != worker_id:
                raise ValueError("browser target does not belong to the attempt worker")
            if start_url != row["start_url"]:
                raise ValueError("browser target was not created from the admitted start URL")
            if row["designated_target_id"] is not None:
                if (
                    row["designated_target_id"] != target_id
                    or row["designated_start_url"] != start_url
                ):
                    raise ValueError("browser attempt already has a different designated target")
                return dict(row)
            connection.execute(
                """UPDATE attempts SET designated_target_id=?,designated_start_url=?,
                   designated_at=?,target_last_url=? WHERE id=?""",
                (target_id, start_url, iso(), start_url, attempt_id),
            )
            return dict(connection.execute(
                "SELECT * FROM attempts WHERE id=?", (attempt_id,),
            ).fetchone())

    def observe_attempt_target(
        self, attempt_id: str, *, target_id: str, url: str, ats_family: str,
    ) -> Mapping[str, Any]:
        """Bind an observation to the designated page without changing its identity."""
        target_id = str(target_id).strip()
        url = _http_url(url, "observed browser target URL") or ""
        family = str(ats_family or "unknown").strip().casefold()
        if (
            not family or len(family) > 40
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in family)
        ):
            raise ValueError("invalid observed ATS family")
        with self.immediate() as connection:
            row = connection.execute(
                """SELECT t.*,a.ats_family AS application_ats_family
                   FROM attempts t JOIN applications a ON a.id=t.application_id
                   WHERE t.id=?""",
                (attempt_id,),
            ).fetchone()
            if row is None or row["status"] != "running":
                raise ValueError("browser attempt is not running")
            if not row["designated_target_id"] or row["designated_target_id"] != target_id:
                raise ValueError("browser observation is not for the designated attempt target")
            existing_family = str(row["resolved_ats_family"] or "unknown")
            if existing_family != "unknown" and family != "unknown" and existing_family != family:
                raise ValueError("designated target changed ATS family unexpectedly")
            resolved = family if family != "unknown" else existing_family
            connection.execute(
                "UPDATE attempts SET resolved_ats_family=?,target_last_url=? WHERE id=?",
                (resolved, url, attempt_id),
            )
            if row["application_ats_family"] == "unknown" and resolved != "unknown":
                connection.execute(
                    "UPDATE applications SET ats_family=? WHERE id=?",
                    (resolved, row["application_id"]),
                )
            return dict(connection.execute(
                "SELECT * FROM attempts WHERE id=?", (attempt_id,),
            ).fetchone())

    def attempt_context(self, attempt_id: str) -> Mapping[str, Any]:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT t.id AS attempt_id,t.status AS attempt_status,t.worker_id,
                          a.id AS application_id,a.start_url,a.tenant_host,
                          CASE WHEN t.resolved_ats_family IS NULL
                                    OR t.resolved_ats_family='unknown'
                               THEN a.ats_family ELSE t.resolved_ats_family END AS ats_family,
                          a.jurisdiction,p.id AS package_id,p.resume_path,p.resume_sha256,
                          p.manifest_path,p.manifest_sha256,r.profile_path,r.profile_sha256,
                          s.company,s.role,s.location,
                          s.description,s.source_url,s.resolver_url,s.official_apply_identity,
                          t.designated_target_id,t.designated_start_url,t.designated_at,
                          t.target_last_url,t.retry_of_attempt_id,
                          prior.designated_target_id AS retry_target_id,
                          prior.designated_start_url AS retry_start_url,
                          prior.target_last_url AS retry_last_url
                   FROM attempts t JOIN applications a ON a.id=t.application_id
                   JOIN packages p ON p.id=t.package_id
                   JOIN source_jobs s ON s.id=a.source_row_id
                   JOIN tailored_artifacts ta ON ta.selection_path=p.manifest_path
                   JOIN tailor_requests r ON r.id=ta.request_id
                   LEFT JOIN attempts prior ON prior.id=t.retry_of_attempt_id
                   WHERE t.id=?""",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown browser attempt")
            return dict(row)
        finally:
            connection.close()

    def publish_review(
        self, attempt_id: str, artifact: Mapping[str, Any], *, profile_name: str,
    ) -> Mapping[str, Any]:
        """Admit one exact guarded Review and retain its browser target."""
        required = {
            "stage", "url", "target_id", "observed_resume_sha256", "rendered",
            "provisional", "final_actions", "submit_untouched", "final_guard_active",
        }
        if set(artifact) != required:
            raise ValueError("Review artifact has an unexpected top-level contract")
        if artifact["stage"] != "review" or artifact["submit_untouched"] is not True:
            raise ValueError("only an untouched rendered Review is publishable")
        if artifact["final_guard_active"] is not True:
            raise ValueError("final-action guard is not active")
        if not isinstance(artifact["rendered"], Mapping):
            raise ValueError("Review rendered readback must be an object")
        if not isinstance(artifact["provisional"], list) or not isinstance(artifact["final_actions"], list):
            raise ValueError("Review provisional and final-actions fields must be lists")
        with self.immediate() as connection:
            context = connection.execute(
                """SELECT t.*,p.resume_sha256,a.status AS application_status
                   FROM attempts t JOIN packages p ON p.id=t.package_id
                   JOIN applications a ON a.id=t.application_id WHERE t.id=?""",
                (attempt_id,),
            ).fetchone()
            if context is None or context["status"] != "running":
                raise ValueError("Review attempt is not running")
            if (
                not context["designated_target_id"]
                or artifact["target_id"] != context["designated_target_id"]
            ):
                raise ValueError("Review did not use the attempt's designated target")
            if artifact["observed_resume_sha256"] != context["resume_sha256"]:
                raise ValueError("Review resume does not match the admitted package")
            existing = connection.execute(
                "SELECT 1 FROM live_tabs WHERE application_id=?", (context["application_id"],),
            ).fetchone()
            if existing:
                raise ValueError("application already has a retained target")
            now = iso()
            connection.execute(
                """INSERT INTO reviews(
                   attempt_id,reached_at,rendered_url,rendered_stage,
                   expected_resume_sha256,observed_resume_sha256,rendered_json,
                   provisional_json,final_actions_json,submit_untouched
                   ) VALUES (?,?,?,?,?,?,?,?,?,1)""",
                (
                    attempt_id, now, str(artifact["url"]), "review",
                    context["resume_sha256"], artifact["observed_resume_sha256"],
                    compact_json(artifact["rendered"]), compact_json(artifact["provisional"]),
                    compact_json(artifact["final_actions"]),
                ),
            )
            connection.execute(
                """INSERT INTO live_tabs(
                   application_id,worker_id,profile_name,target_id,opened_at,state,last_url
                   ) VALUES (?,?,?,?,?,'active',?)""",
                (
                    context["application_id"], context["worker_id"],
                    profile_name,
                    str(artifact["target_id"]), now, str(artifact["url"]),
                ),
            )
            connection.execute(
                "UPDATE attempts SET status='review',ended_at=? WHERE id=?", (now, attempt_id),
            )
            connection.execute(
                "UPDATE applications SET status='review',claimable=0 WHERE id=?",
                (context["application_id"],),
            )
        return self.retained_review(attempt_id)

    def retained_review(self, review_id: str) -> Mapping[str, Any]:
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT r.attempt_id AS review_id,r.reached_at,r.rendered_url,
                          r.expected_resume_sha256,r.observed_resume_sha256,r.rendered_json,
                          r.provisional_json,r.final_actions_json,r.submit_untouched,
                          t.application_id,t.worker_id,p.resume_path,p.resume_sha256,
                          s.company,s.role,s.location,s.description,s.source_url,
                          a.ats_family,l.profile_name,l.target_id,l.opened_at,l.state AS live_state,
                          l.last_url,l.review_version,l.closed_at
                   FROM reviews r JOIN attempts t ON t.id=r.attempt_id
                   JOIN applications a ON a.id=t.application_id
                   JOIN packages p ON p.id=t.package_id
                   JOIN source_jobs s ON s.id=a.source_row_id
                   JOIN live_tabs l ON l.application_id=a.id
                   WHERE r.attempt_id=?""",
                (review_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown retained Review")
            result = dict(row)
            for key in ("rendered_json", "provisional_json", "final_actions_json"):
                result[key.removesuffix("_json")] = json.loads(result.pop(key))
            return result
        finally:
            connection.close()

    def list_reviews(self) -> list[Mapping[str, Any]]:
        connection = self.connect()
        try:
            ids = [row[0] for row in connection.execute(
                "SELECT attempt_id FROM reviews ORDER BY reached_at DESC",
            )]
        finally:
            connection.close()
        return [self.retained_review(review_id) for review_id in ids]

    def live_tab(self, application_id: str) -> Mapping[str, Any] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT * FROM live_tabs WHERE application_id=?", (application_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def begin_human_review_session(self, application_id: str, *, session_id: str) -> Mapping[str, Any]:
        with self.immediate() as connection:
            tab = connection.execute(
                "SELECT * FROM live_tabs WHERE application_id=? AND state='active' AND closed_at IS NULL",
                (application_id,),
            ).fetchone()
            if tab is None:
                raise ValueError("application has no active retained target")
            connection.execute(
                """INSERT INTO human_review_sessions(
                   id,application_id,review_version,worker_id,profile_name,target_id,
                   started_at,state) VALUES (?,?,?,?,?,?,?,'controlling')""",
                (
                    session_id, application_id, tab["review_version"], tab["worker_id"],
                    tab["profile_name"], tab["target_id"], iso(),
                ),
            )
            return dict(connection.execute(
                "SELECT * FROM human_review_sessions WHERE id=?", (session_id,),
            ).fetchone())

    def finish_human_review_session(
        self, session_id: str, *, state: str, evidence: Mapping[str, Any],
        transport: Mapping[str, Any], screenshot_path: str | None = None,
        screenshot_sha256: str | None = None,
    ) -> Mapping[str, Any]:
        allowed = {"viewed", "edited", "form_needs_attention", "outcome_uncertain", "submitted"}
        if state not in allowed:
            raise ValueError("invalid human Review outcome")
        with self.immediate() as connection:
            current = connection.execute(
                "SELECT * FROM human_review_sessions WHERE id=?", (session_id,),
            ).fetchone()
            if current is None or current["state"] != "controlling":
                raise ValueError("human Review session is not controlling")
            connection.execute(
                """UPDATE human_review_sessions SET ended_at=?,state=?,evidence_json=?,
                   screenshot_path=?,screenshot_sha256=?,transport_json=? WHERE id=?""",
                (
                    iso(), state, compact_json(evidence), screenshot_path, screenshot_sha256,
                    compact_json(transport), session_id,
                ),
            )
            return dict(connection.execute(
                "SELECT * FROM human_review_sessions WHERE id=?", (session_id,),
            ).fetchone())


def _http_url(value: Any, label: str, *, optional: bool = False) -> str | None:
    from urllib.parse import urlsplit

    text = str(value or "").strip()
    if not text and optional:
        return None
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be an absolute HTTP(S) URL")
    return text


def _timestamp(value: Any, label: str, *, optional: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text and optional:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
