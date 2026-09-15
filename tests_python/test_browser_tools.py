from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from chironjp import browser_tools as toolbox


def test_switch_tab_reuses_exact_controller_session_without_reattaching():
    calls = []
    harness = SimpleNamespace(
        current_tab=lambda: {"targetId": "target-one"},
        activate_tab=lambda target: calls.append(("activate", target)),
        _send=lambda request: calls.append(("send", request)) or {"session_id": "session-one"},
    )
    with patch.object(toolbox, "_harness_helpers", harness):
        assert toolbox.switch_tab("target-one") == "session-one"
        assert toolbox.switch_tab({"target_id": "target-one"}, activate=True) == "session-one"
    assert calls == [
        ("send", {"meta": "session"}),
        ("activate", "target-one"),
        ("send", {"meta": "session"}),
    ]


def test_switch_tab_rejects_every_non_designated_target():
    harness = SimpleNamespace(
        current_tab=lambda: {"targetId": "target-one"},
        activate_tab=lambda _target: pytest.fail("must not activate another target"),
        _send=lambda _request: pytest.fail("must not read a session for another target"),
    )
    with patch.object(toolbox, "_harness_helpers", harness):
        with pytest.raises(RuntimeError, match="controller-bound"):
            toolbox.switch_tab("target-two")


def test_cdp_routes_frame_session_and_installs_guard_before_activation():
    calls = []

    def transport(method, session_id=None, **params):
        calls.append((method, session_id, params))
        if method == "Runtime.evaluate" and params.get("expression") == toolbox._FINAL_GUARD_JS:
            return {"result": {"value": True}}
        return {"result": {"value": "ok"}}

    with patch.object(toolbox, "_ORIGINAL_CDP", transport):
        toolbox.cdp(
            "Runtime.evaluate", session_id="frame-session",
            expression="document.querySelector('button').click()",
        )
    assert calls[0][1] == "frame-session"
    assert calls[0][2]["expression"] == toolbox._FINAL_GUARD_JS
    assert calls[1][1] == "frame-session"


def test_cdp_rejects_target_id_as_frame_routing():
    with patch.object(toolbox, "_ORIGINAL_CDP", lambda *_args, **_kwargs: {}):
        with pytest.raises(ValueError, match="targetId does not route"):
            toolbox.cdp("Runtime.evaluate", targetId="frame", expression="1")


def test_cdp_rejects_off_viewport_mouse_press_before_dispatch():
    calls = []

    def transport(method, session_id=None, **params):
        calls.append(method)
        if method == "Runtime.evaluate":
            return {"result": {"value": True}}
        if method == "Page.getLayoutMetrics":
            return {"cssVisualViewport": {"clientWidth": 800, "clientHeight": 500}}
        return {}

    with patch.object(toolbox, "_ORIGINAL_CDP", transport):
        with pytest.raises(ValueError, match="outside the current"):
            toolbox.cdp("Input.dispatchMouseEvent", type="mousePressed", x=20, y=900)
    assert calls == ["Runtime.evaluate", "Page.getLayoutMetrics"]


def test_guard_treats_apply_as_final_only_for_evidenced_successfactors_control():
    guard = toolbox._FINAL_GUARD_JS
    assert "control?.id==='fbqa_apply'" in guard
    assert "&& /^apply$/i.test(label)" in guard
    assert "isFinalLabel" in guard
    assert "apply now" not in guard.casefold()


def test_guard_fails_closed_for_review_and_final_forms():
    guard = toolbox._FINAL_GUARD_JS
    assert "isReview()" in guard
    assert "isFinalForm(event.target) || isFinalControl(submitter)" in guard
    assert "HTMLFormElement.prototype.submit" in guard
    assert "direct form submit" in guard


def test_observer_and_readback_use_rendered_react_select_value():
    assert ".select__single-value" in toolbox._OBSERVE_JS
    assert "renderedSelected" in toolbox._OBSERVE_JS
    scripts = []
    toolbox._readback(lambda script: scripts.append(script) or {"found": True}, "#choice")
    assert ".select__single-value" in scripts[0]


def test_exact_select_opens_with_scrolled_hit_test_and_verifies_readback():
    scripts = []
    responses = iter((
        {"tag": "DIV", "role": "combobox", "type": "text"},
        {"x": 10, "y": 20},
        {"count": 1, "x": 12, "y": 24},
        {"found": True, "value": "Canada", "text": "Canada"},
    ))

    def js(script):
        scripts.append(script)
        return next(responses)

    clicks = []
    result = toolbox.exact_select(js, lambda x, y: clicks.append((x, y)), "aid:country", "Canada")
    assert result["selected"] is True
    assert "scrollIntoView" in scripts[1]
    assert "elementFromPoint" in scripts[1]
    assert clicks == [(10.0, 20.0), (12.0, 24.0)]


def test_upload_captures_change_before_ats_clears_input_and_reads_bounded(tmp_path: Path):
    artifact = tmp_path / "resume.pdf"
    artifact.write_bytes(b"fictional resume")
    scripts = []

    def js(script):
        scripts.append(script)
        if "__chironUploadCapture" in script and "addEventListener" in script:
            return True
        return {
            "name": artifact.name,
            "size": artifact.stat().st_size,
            "contentBase64": base64.b64encode(artifact.read_bytes()).decode(),
        }

    calls = []

    def cdp(method, **params):
        calls.append((method, params))
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 1}}
        if method == "DOM.querySelector":
            return {"nodeId": 2}
        return {}

    result = toolbox.upload_and_verify(js, cdp, "aid:resumeUpload", str(artifact))
    assert result["verified"] is True
    assert calls[-1] == ("DOM.setFileInputFiles", {"nodeId": 2, "files": [str(artifact.resolve())]})
    assert "attempt<40" in scripts[-1]
    assert "__chironUploadProof" in scripts[-1]


def test_greenhouse_required_gate_blocks_incomplete_review():
    raw = {
        "url": "https://job-boards.greenhouse.io/example/jobs/42",
        "fields": [{"ref": "id:first_name", "label": "First Name", "kind": "text", "required": True, "filled": False}],
        "actions": ["Submit Application"], "validations": [], "ids": [], "body": "Application",
    }
    result = toolbox.ats_observe(lambda script: True if script == toolbox._FINAL_GUARD_JS else raw, "greenhouse")
    assert result["stage"] != "review"
    assert result["required_complete"] is False


def test_greenhouse_required_group_needs_one_checked_choice():
    raw = {
        "fields": [
            {"ref": "name:choice", "name": "choice", "label": "Selection", "kind": "radio", "required": True, "filled": False},
            {"ref": "name:choice", "name": "choice", "label": "Selection", "kind": "radio", "required": True, "filled": True},
        ],
        "validations": [],
    }
    assert toolbox._greenhouse_form_ready(raw) is True


def test_workday_review_includes_structured_history_questions_and_constraints():
    profile = {
        "work_experience": [{
            "id": "fictional_role", "title": "Software Engineer", "employer": "Example Labs",
            "location": "Toronto, ON", "current": True, "start": "2025-01",
            "role_description": "Built reliable systems.",
        }],
        "education": [],
    }
    responses = iter((
        True,
        {"url": "https://tenant.example/apply/review", "isReview": True, "sections": [], "attachments": ["resume.pdf"], "finalActions": ["Submit"]},
        {"url": "https://tenant.example/apply/review", "review": True, "lines": [
            "My Experience", "Work Experience", "Work Experience 1", "Job Title", "Software Engineer",
            "Company", "Example Labs", "Location", "Toronto, ON", "I currently work here", "Yes",
            "From", "01/2025", "To", "Role Description", "Built reliable systems.", "Education", "No Response",
        ]},
        {"url": "https://tenant.example/apply/review", "review": True,
         "questions": [{"question": "Authorized question", "answer": "Authorized answer"}]},
    ))
    result = toolbox.review_readback(lambda _script: next(responses), "workday", profile, constraints={})
    assert result["stage"] == "review"
    assert result["structured_history"]["complete"] is True
    assert result["question_answers"]["questions"] == [
        {"question": "Authorized question", "answer": "Authorized answer"}
    ]
    assert result["submit_untouched"] is True


def test_workday_review_demotes_when_structured_history_is_missing():
    profile = {"work_experience": [{
        "id": "fictional_role", "title": "Engineer", "employer": "Example Labs",
        "location": "Toronto, ON", "current": True, "start": "2025-01",
    }]}
    responses = iter((
        True,
        {"url": "https://tenant.example/apply/review", "isReview": True, "sections": [], "attachments": [], "finalActions": ["Submit"]},
        {"url": "https://tenant.example/apply/review", "review": True,
         "lines": ["My Experience", "Work Experience", "No Response", "Education", "No Response"]},
        {"url": "https://tenant.example/apply/review", "review": True, "questions": []},
    ))
    result = toolbox.review_readback(lambda _script: next(responses), "workday", profile)
    assert result["stage"] == "application"
    assert result["required_complete"] is False
    assert result["structured_history"]["omissions"][0]["canonical_id"] == "fictional_role"


def test_workday_education_uses_completed_or_expected_end_from_canonical_schema():
    profile = {"education": [
        {
            "id": "completed_program", "school": "Example College",
            "degree": "Bachelor of Science", "field": "Computer Science",
            "gpa": "3.8/4.0", "start": "2020-09", "current": False,
            "completed_end": "2024-06", "expected_end": "2099-12",
        },
        {
            "id": "current_program", "school": "Example University",
            "degree": "Master of Science", "field": "Computer Science",
            "gpa": "3.9/4.0", "start": "2025-09", "current": True,
            "completed_end": "1999-01", "expected_end": "2027-08",
        },
    ]}
    raw = {
        "url": "https://tenant.example/apply/review", "review": True,
        "lines": [
            "My Experience", "Work Experience", "No Response", "Education",
            "Education 1", "School or University", "Example College",
            "Degree", "Bachelor's Degree", "Field of Study", "Computer Science",
            "Overall Result (GPA)", "3.8", "From", "2020",
            "To (Actual or Expected)", "2024",
            "Education 2", "School or University", "Example University",
            "Degree", "Master's Degree", "Field of Study", "Computer Science",
            "Overall Result (GPA)", "3.9", "From", "2025",
            "To (Actual or Expected)", "2027", "Languages",
        ],
    }
    result = toolbox.workday_history_readback(lambda _script: raw, profile)
    assert result["complete"] is True
    assert result["omissions"] == []


def test_advance_never_treats_generic_apply_as_navigation():
    responses = iter((True, {"count": 0}))
    result = toolbox.advance(lambda _script: next(responses), lambda *_args: pytest.fail("must not click"))
    assert result == {"advanced": False, "reason": "non_final_advance_not_unique"}


def test_agent_module_has_no_final_click_or_guard_disarm_api():
    assert not hasattr(toolbox, "final_submit_once")
    assert not hasattr(toolbox, "_disarm_final_guard_for_authorized_action")
