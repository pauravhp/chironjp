from __future__ import annotations

import json
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from chironjp import browser_tools
from chironjp.runner import (
    _EMPLOYER_CONSTRAINTS_JS,
    _IDENTITY_JS,
    _browser_daemon_name,
    _browser_environment,
    _browser_runtime_dir,
    _ensure_application_target,
    _preflight_browser_transport,
    _validated_employer_constraints,
    claim_and_run,
    finish_review,
    run_attempt,
)
from chironjp.store import file_sha256
from tests_python import test_review_flow as review_flow_fixtures


class ScriptedCDP:
    def __init__(self, url: str, responses: dict[str, object]):
        self.url = url
        self.responses = responses

    def evaluate(self, expression: str):
        if expression == _IDENTITY_JS:
            return {
                "url": self.url,
                "title": "Engineer — Example Co",
                "heading": "Engineer",
                "body": "Example Co Engineer application",
            }
        return self.responses.get(expression)

    def close(self):
        return None


class RunnerIntegrityTests(unittest.TestCase):
    def test_browser_daemon_identity_binds_worker_application_and_attempt(self):
        baseline = _browser_daemon_name("worker-one", "app-one", "att-one")
        self.assertRegex(baseline, r"^chironjp_[0-9a-f]{32}$")
        self.assertNotEqual(baseline, _browser_daemon_name("worker-two", "app-one", "att-one"))
        self.assertNotEqual(baseline, _browser_daemon_name("worker-one", "app-two", "att-one"))
        self.assertNotEqual(baseline, _browser_daemon_name("worker-one", "app-one", "att-two"))
        runtime = _browser_runtime_dir(
            Path("/srv/chironjp/runtime"), "worker-one", "app-one", "att-one",
        )
        self.assertEqual(runtime.parent, Path("/srv/chironjp/runtime/bh"))
        self.assertRegex(runtime.name, r"^[0-9a-f]{16}$")
        self.assertLess(len(str(runtime / "bu.sock").encode()), 108)

    def setUp(self):
        self.fixture = review_flow_fixtures.ReviewFlowTests(
            "test_controller_readback_publishes_exact_retained_review"
        )
        self.fixture.setUp()
        self.store = self.fixture.store
        self.registry = self.fixture.registry
        self.review_path = self.fixture.review_path
        self.worker = self.registry.worker("worker-one")

    def tearDown(self):
        self.fixture.tearDown()

    def test_browser_preflight_binds_exact_target_and_proves_runtime(self):
        context = self.store.attempt_context("att-one")
        workspace = self.worker.workspace / "attempts" / "att-one"
        workspace.mkdir(parents=True, exist_ok=True)
        environment = _browser_environment(
            self.registry, self.worker, context, "att-one", workspace,
        )
        marker = "CHIRONJP_BROWSER_PREFLIGHT_OK:target-one:2"
        completed = subprocess.CompletedProcess(
            [environment["CHIRONJP_BROWSER_HARNESS"]], 0, stdout=marker + "\n",
        )
        with patch("chironjp.runner.subprocess.run", return_value=completed) as invoked:
            _preflight_browser_transport(workspace, environment, "target-one")
        command = invoked.call_args.args[0]
        self.assertEqual(command, [environment["CHIRONJP_BROWSER_HARNESS"]])
        script = invoked.call_args.kwargs["input"]
        self.assertIn("switch_tab(expected)", script)
        self.assertIn("value = js('1+1')", script)
        self.assertIn("current.get('targetId') != expected", script)
        self.assertEqual(
            (workspace / "browser-preflight.log").read_text(encoding="utf-8"),
            marker + "\n",
        )

    def test_failed_browser_preflight_stops_exact_daemon_and_preserves_retry_owner(self):
        context = self.store.attempt_context("att-one")
        target = {"id": "target-one", "url": context["start_url"], "type": "page"}
        with patch("chironjp.runner.start_chromium"), \
             patch("chironjp.runner._ensure_application_target", return_value=target), \
             patch(
                 "chironjp.runner._preflight_browser_transport",
                 side_effect=RuntimeError("transport unhealthy"),
             ), \
             patch("chironjp.runner.hermes_cli") as hermes:
            with self.assertRaisesRegex(RuntimeError, "transport unhealthy"):
                run_attempt(self.store, self.registry, "att-one", timeout_seconds=3)
        hermes.assert_not_called()
        failed = self.store.attempt_context("att-one")
        self.assertEqual(failed["attempt_status"], "failed")
        connection = self.store.connect()
        try:
            failure_code = connection.execute(
                "SELECT failure_code FROM attempts WHERE id='att-one'",
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(failure_code, "browser_transport_unhealthy")
        self.assertEqual(failed["designated_target_id"], "target-one")
        retried = self.store.claim_package("pkg-one", "worker-one")
        self.assertEqual(retried["retry_of_attempt_id"], "att-one")
        retry_context = self.store.attempt_context(retried["id"])
        self.assertEqual(retry_context["retry_target_id"], "target-one")

    def test_browser_preflight_failure_reloads_only_its_named_daemon(self):
        context = self.store.attempt_context("att-one")
        workspace = self.worker.workspace / "attempts" / "att-one"
        workspace.mkdir(parents=True, exist_ok=True)
        environment = _browser_environment(
            self.registry, self.worker, context, "att-one", workspace,
        )
        failed = subprocess.CompletedProcess(
            [environment["CHIRONJP_BROWSER_HARNESS"]], 1,
            stdout="Runtime.evaluate timed out\n",
        )
        stopped = subprocess.CompletedProcess(
            [environment["CHIRONJP_BROWSER_HARNESS"], "--reload"], 0,
        )
        with patch(
            "chironjp.runner.subprocess.run", side_effect=[failed, stopped],
        ) as invoked:
            with self.assertRaisesRegex(RuntimeError, "transport is unhealthy"):
                _preflight_browser_transport(workspace, environment, "target-one")
        self.assertEqual(invoked.call_count, 2)
        self.assertEqual(
            invoked.call_args_list[1].args[0],
            [environment["CHIRONJP_BROWSER_HARNESS"], "--reload"],
        )
        self.assertEqual(
            invoked.call_args_list[1].kwargs["env"]["BU_NAME"],
            environment["BU_NAME"],
        )
        self.assertEqual(
            invoked.call_args_list[1].kwargs["env"]["BH_RUNTIME_DIR"],
            environment["BH_RUNTIME_DIR"],
        )

    def _retarget(self, start_url: str, review_url: str, official_identity: str) -> dict[str, object]:
        with self.store.immediate() as connection:
            connection.execute(
                """UPDATE applications SET start_url=?,tenant_host=?,ats_family='unknown'
                   WHERE id='app-one'""",
                (start_url, urlsplit(start_url).hostname),
            )
            connection.execute(
                "UPDATE source_jobs SET official_apply_identity=? WHERE application_id='app-one'",
                (official_identity,),
            )
            connection.execute(
                """UPDATE attempts SET designated_target_id=NULL,designated_start_url=NULL,
                   designated_at=NULL,resolved_ats_family=NULL,target_last_url=NULL
                   WHERE id='att-one'""",
            )
        self.store.bind_attempt_target(
            "att-one", worker_id="worker-one", target_id="target-one", start_url=start_url,
        )
        artifact = json.loads(self.review_path.read_text(encoding="utf-8"))
        artifact["url"] = review_url
        self.review_path.write_text(json.dumps(artifact), encoding="utf-8")
        return {
            "id": "target-one", "type": "page", "url": review_url,
            "webSocketDebuggerUrl": "ws://fixture",
        }

    def test_new_attempt_creates_exact_target_and_resume_reuses_only_its_id(self):
        with self.store.immediate() as connection:
            connection.execute(
                """UPDATE attempts SET designated_target_id=NULL,designated_start_url=NULL,
                   designated_at=NULL,resolved_ats_family=NULL,target_last_url=NULL
                   WHERE id='att-one'""",
            )
        context = self.store.attempt_context("att-one")
        target = {
            "id": "new-exact-target", "type": "page",
            "url": context["start_url"], "webSocketDebuggerUrl": "ws://new",
        }
        with patch("chironjp.runner._create_application_target", return_value=target) as created, \
             patch("chironjp.runner._target", return_value=target):
            first = _ensure_application_target(self.store, self.worker, context)
        self.assertEqual(first["id"], "new-exact-target")
        created.assert_called_once_with(self.worker, context["start_url"])
        persisted = self.store.attempt_context("att-one")
        self.assertEqual(persisted["designated_target_id"], "new-exact-target")

        with patch("chironjp.runner._create_application_target") as no_create, \
             patch("chironjp.runner._target", return_value=target):
            resumed = _ensure_application_target(self.store, self.worker, persisted)
        self.assertEqual(resumed["id"], "new-exact-target")
        no_create.assert_not_called()

    def test_finish_rejects_another_same_profile_target(self):
        artifact = json.loads(self.review_path.read_text(encoding="utf-8"))
        artifact["target_id"] = "old-same-host-target"
        self.review_path.write_text(json.dumps(artifact), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "designated target"):
            finish_review(
                self.store, self.registry, attempt_id="att-one", review_path=self.review_path,
            )

    def test_official_cross_host_redirect_requires_rendered_employer_and_role(self):
        start = "https://careers.example.test/requisitions/42/apply"
        review = "https://job-boards.greenhouse.io/example/jobs/42"
        target = self._retarget(start, review, "url:" + start)
        observed = {
            "stage": "review", "url": review, "final_actions": ["Submit Application"],
            "submit_untouched": True, "final_guard_active": True,
        }
        client = ScriptedCDP(review, {})
        with patch("chironjp.runner._target", return_value=target), \
             patch("chironjp.runner._CDP", return_value=client), \
             patch("chironjp.runner.browser_tools.review_readback", return_value=observed):
            retained = finish_review(
                self.store, self.registry, attempt_id="att-one", review_path=self.review_path,
            )
        self.assertEqual(retained["target_id"], "target-one")

    def test_cross_host_redirect_with_wrong_requisition_identity_is_rejected(self):
        start = "https://careers.example.test/requisitions/42/apply"
        review = "https://job-boards.greenhouse.io/other/jobs/99"
        target = self._retarget(start, review, "url:" + start)
        client = ScriptedCDP(review, {})
        client.evaluate = lambda expression: (
            {"url": review, "title": "Different role", "heading": "Other Co", "body": "Other Co"}
            if expression == _IDENTITY_JS else None
        )
        with patch("chironjp.runner._target", return_value=target), \
             patch("chironjp.runner._CDP", return_value=client):
            with self.assertRaisesRegex(ValueError, "employer and requisition role"):
                finish_review(
                    self.store, self.registry, attempt_id="att-one", review_path=self.review_path,
                )

    def test_same_ats_host_cannot_switch_to_a_different_known_requisition(self):
        start = "https://jobs.lever.co/example/job-a"
        review = "https://jobs.lever.co/example/job-b"
        target = self._retarget(start, review, "lever:example:job-a")
        client = ScriptedCDP(review, {})
        with patch("chironjp.runner._target", return_value=target), \
             patch("chironjp.runner._CDP", return_value=client):
            with self.assertRaisesRegex(ValueError, "official requisition"):
                finish_review(
                    self.store, self.registry, attempt_id="att-one", review_path=self.review_path,
                )

    def test_unknown_greenhouse_route_invokes_required_field_gate(self):
        url = "https://job-boards.greenhouse.io/example/jobs/42"
        target = self._retarget(url, url, "greenhouse:example:42")
        responses = {
            browser_tools._FINAL_GUARD_JS: True,
            browser_tools._REVIEW_JS: {
                "url": url, "isReview": True, "sections": [], "attachments": [],
                "finalActions": ["Submit Application"],
            },
            browser_tools._OBSERVE_JS: {
                "url": url, "fields": [], "actions": ["Submit Application"],
                "validations": [],
            },
        }
        client = ScriptedCDP(url, responses)
        original_gate = browser_tools._greenhouse_form_ready
        with patch("chironjp.runner._target", return_value=target), \
             patch("chironjp.runner._CDP", return_value=client), \
             patch.object(browser_tools, "_greenhouse_form_ready", wraps=original_gate) as gate:
            finish_review(
                self.store, self.registry, attempt_id="att-one", review_path=self.review_path,
            )
        gate.assert_called_once()
        self.assertEqual(self.store.attempt_context("att-one")["ats_family"], "greenhouse")

    def test_unknown_workday_route_invokes_structured_history_and_questions(self):
        url = "https://example.wd1.myworkdayjobs.com/en-US/Example/job/42/apply/review"
        target = self._retarget(url, url, "url:" + url)
        profile = {
            "identity": {},
            "education": [
                {"id": "current-school", "school": "Example University", "degree": "BSc", "field": "Computing", "current": True, "start": "2024-09", "expected_end": "2028-05"},
                {"id": "prior-school", "school": "Prior College", "degree": "Diploma", "field": "Science", "current": False, "start": "2020-09", "completed_end": "2022-05"},
            ],
            "work_experience": [{
                "id": "role-one", "title": "Engineer", "employer": "Example Co",
                "location": "Remote", "current": True, "start": "2025-01",
                "role_description": "Built reliable systems.",
            }],
        }
        self.fixture.profile.write_text(json.dumps(profile), encoding="utf-8")
        with self.store.immediate() as connection:
            connection.execute(
                "UPDATE tailor_requests SET profile_sha256=? WHERE id='req-one'",
                (file_sha256(self.fixture.profile),),
            )
        responses = {
            browser_tools._FINAL_GUARD_JS: True,
            browser_tools._REVIEW_JS: {
                "url": url, "isReview": True, "sections": [], "attachments": [],
                "finalActions": ["Submit Application"],
            },
            _EMPLOYER_CONSTRAINTS_JS: {
                "education": {
                    "kind": "most_recent_only", "limit": 1,
                    "rendered_instruction": "Add only your most recent school or university.",
                },
            },
        }
        client = ScriptedCDP(url, responses)
        history = {
            "stage": "review", "complete": True,
            "constraints": responses[_EMPLOYER_CONSTRAINTS_JS],
            "excluded": [{
                "kind": "education", "canonical_id": "prior-school",
                "reason": "employer_requires_most_recent_only",
            }],
        }
        questions = {"stage": "review", "questions": []}
        with patch("chironjp.runner._target", return_value=target), \
             patch("chironjp.runner._CDP", return_value=client), \
             patch.object(browser_tools, "workday_history_readback", return_value=history) as history_read, \
             patch.object(browser_tools, "workday_question_readback", return_value=questions) as question_read:
            finish_review(
                self.store, self.registry, attempt_id="att-one", review_path=self.review_path,
            )
        history_read.assert_called_once()
        question_read.assert_called_once()
        self.assertEqual(
            history_read.call_args.kwargs["constraints"],
            responses[_EMPLOYER_CONSTRAINTS_JS],
        )
        self.assertEqual(self.store.attempt_context("att-one")["ats_family"], "workday")

    def test_employer_constraint_contract_rejects_unproven_scope_reduction(self):
        with self.assertRaisesRegex(ValueError, "could not prove"):
            _validated_employer_constraints({
                "education": {
                    "kind": "most_recent_only", "limit": 1,
                    "rendered_instruction": "Education is optional.",
                },
            })

    def test_concurrent_idempotent_claim_runs_only_one_operator(self):
        entered = threading.Event()
        release = threading.Event()
        results: list[dict[str, object]] = []

        def fake_run(_store, _registry, attempt_id, **_kwargs):
            entered.set()
            release.wait(5)
            return {"state": "fixture", "attempt_id": attempt_id}

        def first_call():
            results.append(dict(claim_and_run(
                self.store, self.registry, package_id="pkg-one", worker_id="worker-one",
            )))

        with patch("chironjp.runner.run_attempt", side_effect=fake_run) as invoked:
            thread = threading.Thread(target=first_call)
            thread.start()
            self.assertTrue(entered.wait(2))
            duplicate = claim_and_run(
                self.store, self.registry, package_id="pkg-one", worker_id="worker-one",
            )
            release.set()
            thread.join(5)
        self.assertEqual(duplicate["state"], "active")
        self.assertEqual(duplicate["attempt_id"], "att-one")
        self.assertEqual(invoked.call_count, 1)

    def test_orphaned_live_exact_workspace_is_not_relaunched(self):
        with patch("chironjp.runner._operator_process_running", return_value=True), \
             patch("chironjp.runner.run_attempt") as invoked:
            result = claim_and_run(
                self.store, self.registry, package_id="pkg-one", worker_id="worker-one",
            )
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["attempt_id"], "att-one")
        invoked.assert_not_called()

    def test_unfulfilled_worker_fails_attempt_and_uses_isolated_invocation_environment(self):
        captured = {}

        def run_process(_command, **kwargs):
            captured["command"] = list(_command)
            captured["cwd"] = kwargs["cwd"]
            captured.update(kwargs["env"])
            return SimpleNamespace(returncode=9)

        context = self.store.attempt_context("att-one")
        target = {"id": "target-one", "url": context["start_url"], "type": "page"}
        with patch("chironjp.runner.start_chromium"), \
             patch("chironjp.runner._ensure_application_target", return_value=target), \
             patch("chironjp.runner._preflight_browser_transport"), \
             patch("chironjp.runner.hermes_cli", return_value="/fixture/hermes"), \
             patch.dict("os.environ", {"BH_RUNTIME_DIR_SHARED": "1"}), \
             patch("chironjp.runner.subprocess.run", side_effect=run_process):
            result = run_attempt(self.store, self.registry, "att-one", timeout_seconds=3)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["failure"]["failure_code"], "worker_unfulfilled")
        brief = json.loads(
            (Path(result["workspace"]) / "run-brief.json").read_text(encoding="utf-8")
        )
        self.assertEqual(brief["review_contract"]["schema"], "chironjp-review-v1")
        self.assertEqual(
            set(brief["review_contract"]["top_level_keys"]),
            {
                "stage", "url", "target_id", "observed_resume_sha256", "rendered",
                "provisional", "final_actions", "submit_untouched", "final_guard_active",
            },
        )
        self.assertEqual(captured["HERMES_HOME"], str(self.worker.hermes_home))
        self.assertNotIn("--in", captured["command"])
        self.assertEqual(captured["cwd"], Path(result["workspace"]))
        self.assertRegex(captured["BU_NAME"], r"^chironjp_[0-9a-f]{32}$")
        self.assertNotIn("BH_RUNTIME_DIR_SHARED", captured)
        self.assertEqual(
            captured["BH_RUNTIME_DIR"],
            str(_browser_runtime_dir(
                self.registry.runtime_root, "worker-one", "app-one", "att-one",
            )),
        )
        self.assertEqual(
            captured["CHIRONJP_BROWSER_HARNESS"],
            str(self.registry.runtime_root / "browser-venv" / "bin" / "browser-harness"),
        )
        self.assertEqual(
            captured["PATH"].split(":", 1)[0],
            str(self.registry.runtime_root / "browser-venv" / "bin"),
        )
        connection = self.store.connect()
        try:
            application = connection.execute(
                "SELECT status,claimable,mission_worker_id FROM applications WHERE id='app-one'",
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(tuple(application), ("queued", 1, "worker-one"))

    def test_worker_timeout_has_terminal_failure_and_is_retryable(self):
        context = self.store.attempt_context("att-one")
        target = {"id": "target-one", "url": context["start_url"], "type": "page"}
        with patch("chironjp.runner.start_chromium"), \
             patch("chironjp.runner._ensure_application_target", return_value=target), \
             patch("chironjp.runner._preflight_browser_transport"), \
             patch("chironjp.runner.hermes_cli", return_value="/fixture/hermes"), \
             patch("chironjp.runner.subprocess.run", side_effect=subprocess.TimeoutExpired("hermes", 1)):
            result = run_attempt(self.store, self.registry, "att-one", timeout_seconds=1)
        self.assertEqual(result["failure"]["failure_code"], "worker_timeout")
        retried = self.store.claim_package("pkg-one", "worker-one")
        self.assertNotEqual(retried["id"], "att-one")
        retry_context = self.store.attempt_context(str(retried["id"]))
        self.assertEqual(retry_context["retry_target_id"], "target-one")
        prior_target = {
            "id": "target-one", "url": context["start_url"], "type": "page",
            "webSocketDebuggerUrl": "ws://prior",
        }
        with patch("chironjp.runner._target", return_value=prior_target), \
             patch("chironjp.runner._create_application_target") as no_create:
            resumed = _ensure_application_target(self.store, self.worker, retry_context)
        self.assertEqual(resumed["id"], "target-one")
        no_create.assert_not_called()
        self.assertEqual(
            self.store.attempt_context(str(retried["id"]))["designated_target_id"],
            "target-one",
        )


if __name__ == "__main__":
    unittest.main()
