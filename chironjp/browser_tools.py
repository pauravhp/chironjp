"""Proven ATS page mechanics for the ChironJP browser worker.

This is a dependency-closed, sanitized extraction of the browser mechanics in
``chiron/browser_toolbox.py`` at the immutable Chiron revision documented in
``docs/browser.md``.  The helpers prepare and verify employer forms; they do not
offer an agent-driven final-action API.

Workday patterns adapted from yuyao-wang/Jobops commit
643f489936e07494941d58433da82826ed224ae8 (MIT); see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


# Browser Harness loads this file by spec without necessarily adding the bound
# workspace to sys.path. Preserve the documented stateless-helper import.
if __name__ == "browser_harness_agent_helpers":
    import os

    _workspace = Path(os.environ.get("BH_AGENT_WORKSPACE", ".")).resolve()
    if Path(__file__).resolve() == _workspace / "agent_helpers.py" and str(_workspace) not in sys.path:
        sys.path.insert(0, str(_workspace))


try:
    import browser_harness.helpers as _harness_helpers

    _ORIGINAL_CDP = getattr(_harness_helpers, "_chiron_original_cdp", _harness_helpers.cdp)
    _harness_helpers._chiron_original_cdp = _ORIGINAL_CDP
except ImportError:
    _ORIGINAL_CDP = None


def cdp(method, session_id=None, **params):
    """CDP transport with explicit frame-session routing and viewport checks."""
    if "sessionId" in params and not method.startswith("Target."):
        alias = params.pop("sessionId")
        if session_id is not None and session_id != alias:
            raise ValueError("conflicting CDP session_id and sessionId")
        session_id = alias
    if "targetId" in params and method.startswith(("Runtime.", "Page.", "DOM.", "Input.")):
        raise ValueError(
            "targetId does not route this CDP method. Use js(expression,target_id=FRAME_ID), "
            "switch_tab(PAGE_ID), or cdp(method,session_id=ATTACHED_SESSION)."
        )
    if _ORIGINAL_CDP is None:
        raise RuntimeError("CDP transport is only available inside browser_exec")
    expression = str(params.get("expression") or "")
    can_activate = (
        method == "Runtime.evaluate"
        and bool(re.search(r"(?:\.click\s*\(|\.submit\s*\(|\.requestSubmit\s*\(|dispatchEvent\s*\()", expression))
    ) or (
        method == "Input.dispatchMouseEvent" and params.get("type") == "mousePressed"
    ) or (
        method == "Input.dispatchKeyEvent"
        and params.get("type") in {"keyDown", "rawKeyDown"}
        and str(params.get("key") or params.get("code") or "") in {"Enter", "NumpadEnter", "Space"}
    )
    if can_activate:
        guarded = _ORIGINAL_CDP(
            "Runtime.evaluate",
            session_id=session_id,
            expression=_FINAL_GUARD_JS,
            returnByValue=True,
            awaitPromise=True,
        )
        installed = guarded.get("result", {}).get("value") is True and "exceptionDetails" not in guarded
        if not installed:
            raise RuntimeError(
                "No browser action dispatched: final-action guard is unavailable in the active document realm"
            )
    if method == "Input.dispatchMouseEvent" and params.get("type") == "mousePressed" and session_id is None:
        metrics = _ORIGINAL_CDP("Page.getLayoutMetrics")
        viewport = metrics["cssVisualViewport"]
        x, y = float(params["x"]), float(params["y"])
        width, height = viewport["clientWidth"], viewport["clientHeight"]
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(
                f"No mouse press dispatched: ({x}, {y}) is outside the current {width}×{height} viewport. "
                "Iframe-local or document coordinates are not viewport coordinates. Inspect the parent/frame geometry, "
                "scroll and remeasure, or focus the exact control and use trusted keyboard input; verify its rendered value."
            )
    return _ORIGINAL_CDP(method, session_id=session_id, **params)


_OBSERVE_JS = r"""(() => {
  const visible = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const norm = s => String(s || '').replace(/\s+/g, ' ').trim();
  const body = norm(document.body && document.body.innerText).slice(0, 30000);
  const controls = Array.from(document.querySelectorAll(
    'input,textarea,select,[role="combobox"],button[aria-haspopup="listbox"],[role="radio"],[role="checkbox"]'
  )).filter(e => (visible(e) || e.type === 'file') && !e.disabled && e.type !== 'hidden').slice(0, 180);
  const fields = controls.map((e, index) => {
    const aid = e.getAttribute('data-automation-id') || '';
    const id = e.id || '';
    const name = e.getAttribute('name') || '';
    let label = e.getAttribute('aria-label') || '';
    if ((e.type === 'radio' || e.type === 'checkbox' || e.getAttribute('role') === 'radio')) {
      const group = e.closest('fieldset,[role="radiogroup"],[data-automation-id*="question" i]');
      label = group && group.querySelector('legend,[data-automation-id="formLabel"]')?.textContent || label;
    }
    if (!label && e.labels && e.labels.length) label = Array.from(e.labels).map(x => x.innerText || x.textContent || '').join(' ');
    if (!label) label = e.closest('fieldset,[data-automation-id*="question" i],div')?.querySelector('legend,label,[data-automation-id="formLabel"]')?.textContent || '';
    const role = e.getAttribute('role') || '';
    const kind = role === 'combobox' || e.getAttribute('aria-haspopup') === 'listbox' ? 'combobox'
      : role === 'radio' ? 'radio' : role === 'checkbox' ? 'checkbox'
      : e.tagName === 'SELECT' ? 'select' : e.tagName === 'TEXTAREA' ? 'textarea'
      : String(e.getAttribute('type') || 'text').toLowerCase();
    const ref = aid ? `aid:${aid}` : id ? `id:${id}` : name ? `name:${name}` : `index:${index}`;
    const options = e.tagName === 'SELECT' ? Array.from(e.options).map(o => norm(o.textContent)).filter(Boolean).slice(0, 100) : [];
    const nativeSelected = e.tagName === 'SELECT' && e.selectedIndex >= 0 ? norm(e.options[e.selectedIndex].textContent) : '';
    const reactSelect = kind === 'combobox' ? e.closest('.select__control') : null;
    const selectShell = reactSelect || (kind === 'combobox' ? e.closest('.select-shell,[class*="container"], [data-automation-id*="select"]') : null);
    const renderedSelected = selectShell ? norm(selectShell.querySelector('.select__single-value,[class*="singleValue"],[data-automation-id="selectedItem"]')?.textContent) : '';
    const selected = nativeSelected || renderedSelected;
    return {ref, aid, id, name, label:norm(label).slice(0,500), kind,
      required:!!(e.required || e.getAttribute('aria-required') === 'true' || e.closest('[aria-required="true"]')),
      filled:kind === 'checkbox' || kind === 'radio' ? !!(e.checked || e.getAttribute('aria-checked') === 'true')
        : kind === 'file' ? !!(e.files && e.files.length) : reactSelect ? !!renderedSelected : !!String(e.value || selected).trim(),
      selected, options};
  });
  const ids = Array.from(document.querySelectorAll('[data-automation-id]')).map(e => e.getAttribute('data-automation-id')).filter(Boolean).slice(0,250);
  const actions = Array.from(document.querySelectorAll('button,a')).filter(visible).map(e => norm(e.innerText || e.getAttribute('aria-label'))).filter(Boolean).slice(0,100);
  const validations = Array.from(document.querySelectorAll('[role="alert"],[aria-live="assertive"],[data-automation-id*="error" i],.helper-text--error')).filter(visible).map(e => norm(e.innerText)).filter(Boolean).slice(0,30);
  const attachments = Array.from(document.querySelectorAll('[data-automation-id*="file" i],[data-automation-id*="attachment" i]')).filter(visible).map(e => norm(e.innerText)).filter(Boolean).slice(0,30);
  return {url:location.href, title:document.title, heading:norm(document.querySelector('h1,[role="heading"]')?.textContent), body,
    passwordFields:controls.filter(e => e.type === 'password').length,
    hasCaptcha:!!document.querySelector('iframe[src*="recaptcha" i],iframe[src*="hcaptcha" i],.g-recaptcha,.h-captcha,[data-sitekey]'),
    ids, fields, actions, validations, attachments};
})()"""


_REVIEW_JS = r"""(() => {
  const visible = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const norm = s => String(s || '').replace(/\s+/g, ' ').trim();
  const body = norm(document.body && document.body.innerText);
  const sections = Array.from(document.querySelectorAll('section,[data-automation-id*="review" i]')).filter(visible).slice(0,60).map(e => ({
    heading:norm(e.querySelector('h1,h2,h3,h4,[role="heading"]')?.textContent).slice(0,300),
    text:norm(e.innerText).slice(0,5000)
  })).filter(x => x.heading || x.text);
  const controls = Array.from(document.querySelectorAll('button,a,input[type="submit"],[role="button"]')).filter(visible);
  const finalActions = controls.filter(e => /^(submit|submit application|send|confirm)$/i.test(norm(e.innerText || e.value || e.getAttribute('aria-label')))
    || (e.id === 'fbqa_apply' && /^apply$/i.test(norm(e.innerText || e.value || e.getAttribute('aria-label')))))
    .map(e => norm(e.innerText || e.value || e.getAttribute('aria-label'))).filter(Boolean);
  const attachments = Array.from(document.querySelectorAll('[data-automation-id*="file" i],[data-automation-id*="attachment" i]')).filter(visible).map(e => norm(e.innerText)).filter(Boolean);
  const isReview = /(?:\/|#)review(?:\/|$|\?)/i.test(location.href)
    || !!document.querySelector('[data-automation-id="reviewPage"],[data-automation-id="reviewSubmit"],[data-automation-id="applyFlowReviewPage"]')
    || /current step \d+ of \d+ review review/i.test(body)
    || (location.hostname === 'job-boards.greenhouse.io' && finalActions.some(x => /^submit application$/i.test(x)));
  return {url:location.href, isReview, sections:sections.slice(0,60), attachments:[...new Set(attachments)].slice(0,30), finalActions:[...new Set(finalActions)]};
})()"""


_FINAL_GUARD_JS = r"""(() => {
  if (globalThis.__chironFinalGuardState?.version === 5
      && globalThis.__chironFinalGuardInstalled) {
    delete globalThis.__chironFinalGuardState.continuation;
    globalThis.__chironFinalGuardInstalled=true; return true;
  }
  if ([2,3,4].includes(globalThis.__chironFinalGuardState?.version)) {
    globalThis.__chironFinalGuardState.active=false;
    globalThis.__chironFinalGuardInstalled=false;
  }
  if (globalThis.__chironFinalGuardInstalled) return true;
  const guard=globalThis.__chironFinalGuardState?.version===5
    ? globalThis.__chironFinalGuardState : {version:5};
  if(!Object.getOwnPropertyDescriptor(guard,'active'))
    Object.defineProperty(guard,'active',{enumerable:true,configurable:false,get:()=>true});
  globalThis.__chironFinalGuardState=guard;
  const isFinalLabel = label => /^(submit|submit application|send|confirm)$/i.test(label);
  const finalControl = e => e?.closest?.('button,a,input[type="submit"],[role="button"]') || e;
  const isSuccessFactorsFinalApply = e => {
    const control=finalControl(e),label=finalLabel(control);
    return control?.id==='fbqa_apply' && /^apply$/i.test(label);
  };
  const isFinalControl = e => isFinalLabel(finalLabel(finalControl(e))) || isSuccessFactorsFinalApply(e);
  const isFinalForm = form => !!form && (isReview()
    || Array.from(form.querySelectorAll('button,a,input[type="submit"],[role="button"]')).some(isFinalControl));
  const isReview = () => /(?:\/|#)review(?:\/|$|\?)/i.test(location.href)
    || !!document.querySelector('[data-automation-id="reviewPage"],[data-automation-id="reviewSubmit"],[data-automation-id="applyFlowReviewPage"]')
    || /current step \d+ of \d+ review review/i.test(String(document.body?.innerText || '').replace(/\s+/g, ' '))
    || (location.hostname === 'job-boards.greenhouse.io' && Array.from(document.querySelectorAll('button,input[type="submit"],[role="button"]')).some(isFinalControl));
  const finalLabel = e => String((e && (e.innerText || e.value || e.getAttribute?.('aria-label'))) || '').replace(/\s+/g,' ').trim();
  const block = label => { globalThis.__chironBlockedFinalAction={label,at:new Date().toISOString()}; };
  const clickGuard=function __chironBlockedFinalActionClick(event) {
    if (!guard.active) return;
    const control = finalControl(event.target);
    const continuation=guard.continuation;
    if (continuation && !continuation.consumed && !event.isTrusted
        && control?.form===continuation.form && control.type==='submit') return;
    if (isFinalControl(control)) {
      event.preventDefault(); event.stopImmediatePropagation();
      block(finalLabel(control));
    }
  };
  const submitGuard=function __chironBlockedFinalActionSubmit(event) {
    const continuation=guard.continuation;
    if (continuation && event.target===continuation.form) {
      if (!continuation.consumed) { continuation.consumed=true; return; }
      event.preventDefault(); event.stopImmediatePropagation();
      block('repeated form submit'); return;
    }
    if (!guard.active) return;
    const submitter = event.submitter;
    if (isFinalForm(event.target) || isFinalControl(submitter)) { event.preventDefault(); event.stopImmediatePropagation(); block('form submit'); }
  };
  const cleanRealm=document.createElement('iframe');
  cleanRealm.hidden=true; (document.documentElement||document.body).appendChild(cleanRealm);
  const nativeAdd=cleanRealm.contentWindow.EventTarget.prototype.addEventListener;
  Reflect.apply(nativeAdd,document,['click',clickGuard,true]);
  Reflect.apply(nativeAdd,document,['submit',submitGuard,true]);
  cleanRealm.remove();
  const nativeSubmit=HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit=function(...args) {
    if (guard.active && isFinalForm(this)) { block('direct form submit'); return; }
    return Reflect.apply(nativeSubmit,this,args);
  };
  if(!Object.getOwnPropertyDescriptor(guard,'nativeSubmit'))
    Object.defineProperty(guard,'nativeSubmit',{value:nativeSubmit,enumerable:false,
      configurable:false,writable:false});
  globalThis.__chironFinalGuardInstalled = true;
  return true;
})()"""


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _install_final_guard(js: Callable[[str], Any]) -> bool:
    try:
        return bool(js(_FINAL_GUARD_JS))
    except Exception:
        return False


def _stage(raw: Mapping[str, Any]) -> str:
    text = _norm(raw.get("body"))
    url = _norm(raw.get("url")).replace("-", "").replace("_", "")
    ids = {_norm(value).replace(" ", "") for value in raw.get("ids", [])}
    if raw.get("hasCaptcha") or any(phrase in text for phrase in ("complete the captcha", "verify you are human", "captcha challenge")):
        return "captcha"
    if any(phrase in text for phrase in ("multi factor authentication", "two factor authentication", "authenticator app")):
        return "mfa"
    if any(phrase in text for phrase in ("verify your email", "email verification", "code sent to your email")) or ids & {"verificationcode", "emailverificationcode"}:
        return "email_verification"
    if any(phrase in text for phrase in ("account has been locked", "incorrect username or password", "unable to sign in")):
        return "account_locked"
    if "sign in with email" in text and int(raw.get("passwordFields") or 0) == 0:
        return "login_choice"
    if int(raw.get("passwordFields") or 0) == 1 and any(x in text for x in ("sign in", "log in", "forgot password")):
        return "login"
    if int(raw.get("passwordFields") or 0) >= 2 or "create an account" in text:
        return "register"
    if ids & {"reviewpage", "reviewsubmit", "applyflowreviewpage"} or re.search(r"current step \d+ of \d+ review review", text):
        return "review"
    routes = (
        ("autofillwithresume", "autofillWithResume"), ("myinformation", "myInformation"),
        ("myexperience", "myExperience"), ("applicationquestions", "applicationQuestions"),
        ("voluntarydisclosures", "voluntaryDisclosures"), ("selfidentify", "selfIdentify"),
        ("review", "review"),
    )
    for token, stage in routes:
        if token in url:
            return stage
    marker_groups = (
        ({"resumeupload", "fileuploadinputref", "autofillwithresume"}, "autofillWithResume"),
        ({"myinformation", "legalnamesectionfirstname"}, "myInformation"),
        ({"myexperience", "workexperiencesection"}, "myExperience"),
        ({"applicationquestions", "primaryquestionnairepage"}, "applicationQuestions"),
        ({"voluntarydisclosures"}, "voluntaryDisclosures"), ({"selfidentify"}, "selfIdentify"),
        ({"reviewpage", "reviewsubmit", "applyflowreviewpage"}, "review"),
    )
    for markers, stage in marker_groups:
        if ids & markers:
            return stage
    if any(_norm(x) in {"apply", "apply now"} for x in raw.get("actions", [])):
        return "job"
    return "other"


def workday_observe(js: Callable[[str], Any]) -> dict[str, Any]:
    guard = _install_final_guard(js)
    raw = js(_OBSERVE_JS) or {}
    fields = []
    for item in list(raw.get("fields") or [])[:180]:
        fields.append({key: item.get(key) for key in ("ref", "label", "kind", "required", "filled", "selected", "options")})
    return {
        "supported": True,
        "stage": _stage(raw),
        "url": str(raw.get("url", "")),
        "title": str(raw.get("title", ""))[:300],
        "heading": str(raw.get("heading", ""))[:500],
        "fields": fields,
        "validation": list(raw.get("validations") or [])[:30],
        "attachments": list(raw.get("attachments") or [])[:30],
        "final_guard_active": guard,
    }


_WORKDAY_HISTORY_LINES_JS = r"""(() => {
  const norm=s=>String(s||'').replace(/\u00a0/g,' ').trim();
  const lines=String(document.body?.innerText||'').split(/\n+/).map(norm).filter(Boolean);
  const review=!!document.querySelector('[data-automation-id="reviewPage"],[data-automation-id="reviewSubmit"],[data-automation-id="applyFlowReviewPage"]')
    || /current step \d+ of \d+ review review/i.test(lines.join(' '));
  const markers=lines.map((value,index)=>({value,index})).filter(x=>x.value==='My Experience');
  const start=markers.length ? markers[markers.length-1].index : -1;
  return {url:location.href,review,lines:start>=0?lines.slice(start):[]};
})()"""


_WORKDAY_REVIEW_QA_JS = r"""(() => {
  const norm=s=>String(s||'').replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
  const body=norm(document.body?.innerText||'');
  const review=!!document.querySelector('[data-automation-id="reviewPage"],[data-automation-id="reviewSubmit"],[data-automation-id="applyFlowReviewPage"]')
    || /current step \d+ of \d+ review review/i.test(body);
  const questions=[];
  for(const rich of document.querySelectorAll('[data-automation-id="richText"]')) {
    const labelRoot=rich.parentElement, container=labelRoot?.parentElement;
    const answerRoot=labelRoot?.nextElementSibling;
    const question=norm(rich.innerText), answer=norm(answerRoot?.innerText);
    const combined=norm(container?.innerText);
    if(!question||!answer||!combined.startsWith(question)||answer===question)continue;
    questions.push({question,answer});
  }
  return {url:location.href,review,questions};
})()"""


def _history_cards(lines: Sequence[str], prefix: str, end_labels: set[str]) -> list[list[str]]:
    marker = re.compile(rf"^{re.escape(prefix)}\s+(\d+)$", re.I)
    starts = [index for index, value in enumerate(lines) if marker.fullmatch(str(value).strip())]
    cards: list[list[str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        for index in range(start + 1, end):
            if str(lines[index]).strip() in end_labels:
                end = index
                break
        cards.append(list(lines[start:end]))
    return cards


def _history_field(card: Sequence[str], label: str, labels: set[str]) -> str:
    try:
        start = list(card).index(label) + 1
    except ValueError:
        return ""
    values: list[str] = []
    for value in card[start:]:
        if value in labels or re.fullmatch(r"(?:Work Experience|Education)\s+\d+", value, re.I):
            break
        values.append(str(value))
    return " ".join(values).strip()


def _history_text(value: Any) -> str:
    return " ".join(str(value or "").replace("’", "'").split()).casefold()


def _location_matches(rendered: Any, canonical: Any) -> bool:
    """Match the same Canadian location after Workday expands province names."""
    def normalized(value: Any) -> str:
        text = _history_text(value)
        replacements = {
            "british columbia": "bc", "quebec": "qc", "ontario": "on",
            "alberta": "ab", "manitoba": "mb", "saskatchewan": "sk",
            "nova scotia": "ns", "new brunswick": "nb",
            "newfoundland and labrador": "nl", "prince edward island": "pe",
        }
        for full, short in replacements.items():
            text = text.replace(full, short)
        text = re.sub(r"\bcanada\b", "", text)
        return " ".join(re.findall(r"[a-z0-9]+", text))

    return bool(normalized(canonical)) and normalized(rendered) == normalized(canonical)


def _description_matches(rendered: Any, canonical: Any) -> bool:
    """Allow a word-equivalent rendering when Workday rejects symbols."""
    def normalized(value: Any) -> str:
        text = re.sub(r"<\s*(\d+)", r"under \1", str(value or ""))
        text = re.sub(r">\s*(\d+)", r"over \1", text)
        text = re.sub(r"(\d+)\s*%", r"\1 percent", text)
        text = re.sub(r"(\d+)\s*\+", r"\1 plus", text)
        text = re.sub(r"[–—−]", "-", text)
        text = re.sub(r"\s*•\s*", " ", text)
        return _history_text(text)

    return normalized(rendered) == normalized(canonical)


def _history_date(value: Any) -> tuple[int | None, int | None]:
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:(\d{1,2})/)?(\d{4})", text)
    if match:
        return int(match.group(2)), int(match.group(1)) if match.group(1) else None
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def _date_matches(rendered: Any, canonical: Any, *, year_only: bool = False) -> bool:
    actual_year, actual_month = _history_date(rendered)
    expected_year, expected_month = _history_date(canonical)
    if actual_year is None or expected_year is None or actual_year != expected_year:
        return False
    return year_only or actual_month is None or expected_month is None or actual_month == expected_month


def _degree_matches(rendered: Any, canonical: Any) -> bool:
    actual, expected = _history_text(rendered), _history_text(canonical)
    if actual == expected:
        return True
    for family in ("master", "bachelor", "doctor", "associate"):
        if family in expected:
            return family in actual
    return False


def _field_of_study_matches(rendered: Any, canonical: Any) -> bool:
    actual, expected = _history_text(rendered), _history_text(canonical)
    if actual == expected:
        return True
    equivalents = {"computer science": {"computer and information science"}}
    return actual in equivalents.get(expected, set())


def workday_history_readback(
    js: Callable[[str], Any], profile: Mapping[str, Any] | None = None,
    constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile visible Workday history rows against canonical expectations."""
    raw = js(_WORKDAY_HISTORY_LINES_JS) or {}
    lines = [str(value).strip() for value in list(raw.get("lines") or []) if str(value).strip()]
    if raw.get("review") is not True or not lines:
        return {"supported": False, "stage": "other", "url": str(raw.get("url") or "")}
    starts = [index for index, value in enumerate(lines) if value in {"Work Experience", "Education"}]
    history_start = min(starts) if starts else -1
    history_end = len(lines)
    if history_start >= 0:
        for index in range(history_start + 1, len(lines)):
            if lines[index] in {
                "Certifications", "Languages", "Skills", "Resume/CV",
                "Resume / Transcript", "Resume and Additional Documents",
            }:
                history_end = index
                break
    history_lines = lines[history_start:history_end] if history_start >= 0 else []
    work_labels = {"Job Title", "Company", "Location", "I currently work here", "From", "To", "Role Description"}
    education_labels = {"School or University", "Degree", "Field of Study", "Overall Result (GPA)", "From", "To (Actual or Expected)"}
    work = [{
        "job_title": _history_field(card, "Job Title", work_labels),
        "company": _history_field(card, "Company", work_labels),
        "location": _history_field(card, "Location", work_labels),
        "currently_work_here": _history_field(card, "I currently work here", work_labels),
        "from": _history_field(card, "From", work_labels),
        "to": _history_field(card, "To", work_labels),
        "role_description": _history_field(card, "Role Description", work_labels),
    } for card in _history_cards(
        history_lines, "Work Experience", {"Projects", "Education", "Certifications", "Languages", "Skills"},
    )]
    education = [{
        "school": _history_field(card, "School or University", education_labels),
        "degree": _history_field(card, "Degree", education_labels),
        "field_of_study": _history_field(card, "Field of Study", education_labels),
        "gpa": _history_field(card, "Overall Result (GPA)", education_labels),
        "from": _history_field(card, "From", education_labels),
        "to": _history_field(card, "To (Actual or Expected)", education_labels),
    } for card in _history_cards(
        history_lines, "Education", {"Work Experience", "Certifications", "Languages", "Skills", "Resume/CV", "Resume / Transcript", "Resume and Additional Documents"},
    )]
    all_expected_work = list((profile or {}).get("work_experience") or [])
    expected_work: list[Mapping[str, Any]] = []
    expected_education = list((profile or {}).get("education") or [])
    applied_constraints: dict[str, Any] = {}
    excluded: list[dict[str, Any]] = []
    for index, row in enumerate(all_expected_work):
        if not isinstance(row, Mapping):
            continue
        if row.get("source_completeness") == "incomplete":
            excluded.append({
                "kind": "work_experience",
                "canonical_id": str(row.get("id") or f"work_{index + 1}"),
                "reason": "canonical_source_incomplete",
                "source_missing_fields": list(row.get("source_missing_fields") or []),
            })
        else:
            expected_work.append(row)
    education_constraint = (
        constraints.get("education")
        if isinstance(constraints, Mapping) and isinstance(constraints.get("education"), Mapping)
        else None
    )
    if education_constraint:
        instruction = str(education_constraint.get("rendered_instruction") or "").strip()
        normalized_instruction = _history_text(instruction)
        valid_most_recent_only = (
            education_constraint.get("kind") == "most_recent_only"
            and education_constraint.get("limit") == 1
            and "most recent school or university" in normalized_instruction
            and "add only" in normalized_instruction
        )
        if valid_most_recent_only and expected_education:
            applied_constraints["education"] = {
                "kind": "most_recent_only", "limit": 1, "rendered_instruction": instruction,
            }
            for index, row in enumerate(expected_education[1:], 2):
                excluded.append({
                    "kind": "education",
                    "canonical_id": str(row.get("id") or f"education_{index}"),
                    "reason": "employer_requires_most_recent_only",
                })
            expected_education = expected_education[:1]
    omissions: list[dict[str, Any]] = []
    matched_work: list[dict[str, Any]] = []
    used_work: set[int] = set()
    for index, expected in enumerate(expected_work):
        identifier = str(expected.get("id") or f"work_{index + 1}")
        candidates = [
            actual_index for actual_index, actual in enumerate(work)
            if actual_index not in used_work
            and _history_text(actual.get("company")) == _history_text(expected.get("employer"))
            and _history_text(actual.get("job_title")) == _history_text(expected.get("title"))
        ]
        if not candidates:
            candidates = [
                actual_index for actual_index, actual in enumerate(work)
                if actual_index not in used_work
                and (
                    _history_text(actual.get("company")) == _history_text(expected.get("employer"))
                    or _history_text(actual.get("job_title")) == _history_text(expected.get("title"))
                )
            ]
        if not candidates:
            omissions.append({"kind": "work_experience", "canonical_id": identifier, "reason": "record_missing"})
            continue
        actual_index = candidates[0]
        used_work.add(actual_index)
        actual = dict(work[actual_index])
        actual["canonical_id"] = identifier
        matched_work.append(actual)
        checks = {
            "job_title": _history_text(actual["job_title"]) == _history_text(expected.get("title")),
            "company": _history_text(actual["company"]) == _history_text(expected.get("employer")),
            "location": _location_matches(actual["location"], expected.get("location")),
            "currently_work_here": _history_text(actual["currently_work_here"]) == ("yes" if expected.get("current") else "no"),
            "from": _date_matches(actual["from"], expected.get("start")),
            "to": bool(expected.get("current")) and not actual["to"] or _date_matches(actual["to"], expected.get("end")),
            "role_description": (
                _description_matches(actual["role_description"], expected.get("role_description"))
                if expected.get("role_description") else _history_text(actual["role_description"]) in {"", "no response"}
            ),
        }
        for field, matched in checks.items():
            if not matched:
                omissions.append({"kind": "work_experience", "canonical_id": identifier, "field": field,
                                  "reason": "missing_or_mismatched", "rendered": actual.get(field, "")})
    extra_work = [dict(actual) for actual_index, actual in enumerate(work) if actual_index not in used_work]
    if extra_work:
        omissions.append({"kind": "work_experience", "reason": "unexpected_extra_records", "count": len(extra_work)})
    matched_education: list[dict[str, Any]] = []
    used_education: set[int] = set()
    for index, expected in enumerate(expected_education):
        identifier = str(expected.get("id") or f"education_{index + 1}")
        candidates = [
            actual_index for actual_index, actual in enumerate(education)
            if actual_index not in used_education
            and _history_text(actual.get("school")) == _history_text(expected.get("school"))
            and _degree_matches(actual.get("degree"), expected.get("degree"))
        ]
        if not candidates:
            candidates = [
                actual_index for actual_index, actual in enumerate(education)
                if actual_index not in used_education
                and (
                    _history_text(actual.get("school")) == _history_text(expected.get("school"))
                    or _degree_matches(actual.get("degree"), expected.get("degree"))
                )
            ]
        if not candidates:
            omissions.append({"kind": "education", "canonical_id": identifier, "reason": "record_missing"})
            continue
        actual_index = candidates[0]
        used_education.add(actual_index)
        actual = dict(education[actual_index])
        actual["canonical_id"] = identifier
        matched_education.append(actual)
        checks = {
            "school": _history_text(actual["school"]) == _history_text(expected.get("school")),
            "degree": _degree_matches(actual["degree"], expected.get("degree")),
            "field_of_study": _field_of_study_matches(actual["field_of_study"], expected.get("field")),
            "gpa": str(expected.get("gpa") or "").split("/")[0] in str(actual["gpa"] or ""),
            "from": _date_matches(actual["from"], expected.get("start"), year_only=True),
            "to": _date_matches(
                actual["to"],
                expected.get("expected_end") if expected.get("current") else expected.get("completed_end"),
                year_only=True,
            ),
        }
        for field, matched in checks.items():
            if not matched:
                omissions.append({"kind": "education", "canonical_id": identifier, "field": field,
                                  "reason": "missing_or_mismatched", "rendered": actual.get(field, "")})
    extra_education = [dict(actual) for actual_index, actual in enumerate(education) if actual_index not in used_education]
    if extra_education:
        omissions.append({"kind": "education", "reason": "unexpected_extra_records", "count": len(extra_education)})
    return {
        "supported": True,
        "stage": "review",
        "work_experience": matched_work + extra_work,
        "education": matched_education + extra_education,
        "constraints": applied_constraints,
        "excluded": excluded,
        "omissions": omissions,
        "complete": not omissions and len(matched_work) == len(expected_work)
        and len(matched_education) == len(expected_education),
    }


def workday_question_readback(js: Callable[[str], Any]) -> dict[str, Any]:
    """Bind each Workday Review question to its rendered sibling answer."""
    raw = js(_WORKDAY_REVIEW_QA_JS) or {}
    questions = [
        {
            "question": " ".join(str(item.get("question") or "").split()),
            "answer": " ".join(str(item.get("answer") or "").split()),
        }
        for item in list(raw.get("questions") or [])
        if isinstance(item, Mapping)
        and str(item.get("question") or "").strip()
        and str(item.get("answer") or "").strip()
    ]
    return {
        "supported": raw.get("review") is True,
        "stage": "review" if raw.get("review") is True else "other",
        "url": str(raw.get("url") or ""),
        "questions": questions,
    }


def _greenhouse_form_ready(raw: Mapping[str, Any]) -> bool:
    """Require every observable Greenhouse requirement before Review."""
    if list(raw.get("validations") or []):
        return False
    required = [item for item in list(raw.get("fields") or []) if item.get("required")]
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for item in required:
        ref = str(item.get("ref") or "")
        label = str(item.get("label") or "").strip()
        if ref.startswith("index:") and not label:
            continue
        kind = str(item.get("kind") or "").casefold()
        if kind in {"checkbox", "radio"}:
            group = _norm(label) or _norm(item.get("name")) or ref
            grouped.setdefault((kind, group), []).append(item)
        elif not item.get("filled"):
            return False
    return all(any(item.get("filled") for item in items) for items in grouped.values())


def ats_observe(js: Callable[[str], Any], ats_family: str = "auto") -> dict[str, Any]:
    """Install the universal final guard; inventory known ATS families compactly."""
    if not callable(js):
        raise TypeError(
            "Use ats_observe(js, ats_family), e.g. ats_observe(js, 'lever'). "
            "First argument is the js helper, not a target ID; select the target with switch_tab(target_id)."
        )
    family = str(ats_family).strip().casefold()
    guard = _install_final_guard(js)
    if family == "workday":
        return workday_observe(js)
    if family != "greenhouse":
        return {
            "supported": False, "stage": "other", "ats_family": family,
            "final_guard_active": guard,
        }
    raw = js(_OBSERVE_JS) or {}
    fields = [
        {key: item.get(key) for key in ("ref", "label", "kind", "required", "filled", "selected", "options")}
        for item in list(raw.get("fields") or [])[:180]
    ]
    actions = [str(value) for value in list(raw.get("actions") or [])[:100]]
    final_actions = [value for value in actions if _norm(value) in {"submit", "submit application", "send", "confirm"}]
    required_complete = _greenhouse_form_ready(raw)
    stage = "review" if final_actions and required_complete else _stage(raw)
    return {
        "supported": True,
        "ats_family": family,
        "stage": stage,
        "url": str(raw.get("url", "")),
        "title": str(raw.get("title", ""))[:300],
        "heading": str(raw.get("heading", ""))[:500],
        "fields": fields,
        "validation": list(raw.get("validations") or [])[:30],
        "attachments": list(raw.get("attachments") or [])[:30],
        "final_actions": final_actions,
        "required_complete": required_complete,
        "final_guard_active": guard,
    }


def _selector(ref: str) -> str | None:
    kind, separator, value = str(ref).partition(":")
    if not separator or kind not in {"aid", "id", "name"} or not value:
        return None
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f"#{escaped}" if kind == "id" else f'[{"data-automation-id" if kind == "aid" else "name"}="{escaped}"]'


def _readback(js: Callable[[str], Any], selector: str) -> Mapping[str, Any]:
    return js("""(() => { const e=document.querySelector(%s); if(!e) return {found:false};
      const selected=e.tagName==='SELECT' && e.selectedIndex>=0 ? e.options[e.selectedIndex] : null;
      const shell=e.getAttribute('role')==='combobox' ? e.closest('.select__control') : null;
      const rendered=shell?.querySelector('.select__single-value,[class*="singleValue"]')?.textContent||'';
      return {found:true,value:String(shell?rendered:e.value||''),text:String(shell?rendered:selected?selected.textContent||'':e.textContent||''),
      checked:!!(e.checked || e.getAttribute('aria-checked')==='true'),files:Array.from(e.files||[]).map(f=>({name:f.name,size:f.size}))}; })()""" % json.dumps(selector)) or {}


def trusted_batch_input(
    js: Callable[[str], Any],
    fill_input: Callable[[str, str], Any],
    assignments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fill text-like fields with Browser Use's trusted input helper."""
    filled: list[str] = []
    mismatches: list[str] = []
    unsupported: list[str] = []
    for assignment in assignments:
        ref = str(assignment.get("ref", ""))
        selector = _selector(ref)
        kind = str(assignment.get("kind", "text")).casefold()
        value = assignment.get("value")
        if selector is None or kind not in {"text", "email", "tel", "number", "textarea", "search", "url", "date"}:
            unsupported.append(ref)
            continue
        try:
            fill_input(selector, str(value))
            state = _readback(js, selector)
            if not state.get("found") or str(state.get("value", "")).replace("\r\n", "\n").strip() != str(value).replace("\r\n", "\n").strip():
                mismatches.append(ref)
            else:
                filled.append(ref)
        except Exception:
            mismatches.append(ref)
    return {"filled": filled, "mismatches": mismatches, "unsupported": unsupported}


def _click_ref(js: Callable[[str], Any], click_at_xy: Callable[[float, float], Any], ref: str) -> bool:
    selector = _selector(ref)
    if selector is None:
        return False
    return _click_selector(js, click_at_xy, selector)


def _click_selector(js, click_at_xy, selector):
    box = js("""(() => { const e=document.querySelector(%s); if(!e || e.disabled) return null;
      e.scrollIntoView({block:'center',inline:'center'}); const r=e.getBoundingClientRect();
      const x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);
      return r.width && r.height && x>=0 && y>=0 && x<innerWidth && y<innerHeight
        && (hit===e || e.contains(hit)) ? {x,y} : null; })()""" % json.dumps(selector))
    if not box:
        return False
    result = click_at_xy(float(box["x"]), float(box["y"]))
    return result is not False and not (isinstance(result, dict) and result.get("success") is False)


def exact_select(
    js: Callable[[str], Any],
    click_at_xy: Callable[[float, float], Any],
    ref: str,
    exact_value: str,
) -> dict[str, Any]:
    """Choose only an exact rendered option; unmatched variation returns control."""
    selector = _selector(ref)
    if selector is None:
        return {"selected": False, "reason": "unsupported_ref"}
    metadata = js("""(() => { const e=document.querySelector(%s); if(!e) return null;
      return {tag:e.tagName,role:e.getAttribute('role')||'',type:e.type||''}; })()""" % json.dumps(selector))
    if not metadata:
        return {"selected": False, "reason": "field_not_found"}
    target = _norm(exact_value)
    if metadata.get("type") in {"radio", "checkbox"} or metadata.get("role") in {"radio", "checkbox"}:
        match = js(r"""(() => { const seed=document.querySelector(%s); if(!seed) return null; const root=seed.closest('fieldset,[role="radiogroup"]')||document;
          const candidates=Array.from(root.querySelectorAll('input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]'));
          const norm=s=>String(s||'').replace(/\s+/g,' ').trim().toLowerCase(); const target=%s;
          const matches=candidates.filter(e=>{const label=e.getAttribute('aria-label')||(e.labels&&Array.from(e.labels).map(x=>x.textContent).join(' '))||e.value||''; return norm(label)===target||norm(e.value)===target;});
          if(matches.length!==1) return {count:matches.length}; const r=matches[0].getBoundingClientRect(); return {count:1,x:r.left+r.width/2,y:r.top+r.height/2}; })()""" % (json.dumps(selector), json.dumps(target)))
        if not match or match.get("count") != 1:
            return {"selected": False, "reason": "exact_option_not_unique"}
        click_at_xy(float(match["x"]), float(match["y"]))
        return {"selected": True, "value": exact_value}
    if not _click_ref(js, click_at_xy, ref):
        return {"selected": False, "reason": "cannot_open"}
    match = js(r"""(() => { const norm=s=>String(s||'').replace(/\s+/g,' ').trim().toLowerCase(); const target=%s;
      const nodes=Array.from(document.querySelectorAll('[role="option"],option,[data-automation-id="promptLeafNode"],[data-automation-id="menuItem"]'));
      const opts=[]; for(const node of nodes){
        if(node.matches('[data-automation-id="selectedItem"]')) continue;
        const row=node.closest('[data-automation-id="promptLeafNode"]')||node;
        const r=row.getBoundingClientRect();
        if((row.tagName==='OPTION'||r.width||r.height)&&!opts.includes(row)) opts.push(row);
      }
      const matches=opts.filter(e=>norm(e.textContent)===target||norm(e.getAttribute('data-value'))===target||norm(e.value)===target);
      if(matches.length!==1) return {count:matches.length}; const e=matches[0]; if(e.tagName==='OPTION') return {count:1,native:true,value:e.value};
      const action=e.querySelector?.('[data-automation-id="menuItem"],[role="option"]')||e;
      action.scrollIntoView({block:'center'}); const r=action.getBoundingClientRect(); return {count:1,x:r.left+r.width/2,y:r.top+r.height/2}; })()""" % json.dumps(target))
    if not match or match.get("count") != 1:
        return {"selected": False, "reason": "exact_option_not_unique"}
    if match.get("native"):
        changed = js(r"""(() => { const e=document.querySelector(%s); const target=%s; const norm=s=>String(s||'').replace(/\s+/g,' ').trim().toLowerCase();
          const matches=Array.from(e.options||[]).filter(o=>norm(o.textContent)===target||norm(o.value)===target); if(matches.length!==1)return false;
          e.value=matches[0].value;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return true; })()""" % (json.dumps(selector), json.dumps(target)))
        if not changed:
            return {"selected": False, "reason": "native_selection_failed"}
    else:
        click_at_xy(float(match["x"]), float(match["y"]))
    state = _readback(js, selector)
    observed = {_norm(state.get("value")), _norm(state.get("text"))}
    return {"selected": target in observed, "value": exact_value, "observed": list(observed)}


def upload_and_verify(
    js: Callable[[str], Any],
    cdp: Callable[..., Mapping[str, Any]],
    ref: str,
    path: str,
) -> dict[str, Any]:
    """Attach one exact package file through CDP and verify its browser bytes."""
    file_path = Path(path).expanduser().resolve()
    selector = _selector(ref)
    if selector is None or not file_path.is_file():
        return {"verified": False, "reason": "unsupported_ref_or_missing_file"}
    try:
        armed = js(r"""(() => {
          const selector=%s;
          if(globalThis.__chironUploadCapture)
            document.removeEventListener('change',globalThis.__chironUploadCapture,true);
          globalThis.__chironUploadProof=null;
          const capture=async event=>{
            const input=event.target;
            if(!input?.matches?.(selector)||!input.files||input.files.length!==1)return;
            document.removeEventListener('change',capture,true);
            globalThis.__chironUploadCapture=null;
            const file=input.files[0],bytes=new Uint8Array(await file.arrayBuffer());
            let binary='';
            for(let offset=0;offset<bytes.length;offset+=0x8000)
              binary+=String.fromCharCode(...bytes.subarray(offset,offset+0x8000));
            globalThis.__chironUploadProof={name:file.name,size:file.size,contentBase64:btoa(binary)};
          };
          globalThis.__chironUploadCapture=capture;
          document.addEventListener('change',capture,true);
          return true;
        })()""" % json.dumps(selector))
        if armed is not True:
            return {"verified": False, "reason": "upload_capture_unavailable"}
        document = cdp("DOM.getDocument", depth=-1, pierce=True)
        root = int(document["root"]["nodeId"])
        found = cdp("DOM.querySelector", nodeId=root, selector=selector)
        node_id = int(found.get("nodeId") or 0)
        if not node_id:
            return {"verified": False, "reason": "file_input_not_found"}
        cdp("DOM.setFileInputFiles", nodeId=node_id, files=[str(file_path)])
    except Exception:
        return {"verified": False, "reason": "trusted_upload_failed"}
    return verify_upload(js, ref, str(file_path))


def verify_upload(js: Callable[[str], Any], ref: str, path: str) -> dict[str, Any]:
    """Verify the currently attached File bytes against the package artifact."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        return {"verified": False, "reason": "package_file_missing"}
    expected = hashlib.sha256(file_path.read_bytes()).hexdigest()
    selector = _selector(ref)
    if selector is None:
        return {"verified": False, "reason": "unsupported_ref"}
    observed = js("""(async()=>{ for(let attempt=0;attempt<40;attempt++){
      const e=document.querySelector(%s),f=e?.files?.length===1?e.files[0]:null;
      if(f){ const bytes=new Uint8Array(await f.arrayBuffer()); let binary='';
        for(let offset=0;offset<bytes.length;offset+=0x8000) binary+=String.fromCharCode(...bytes.subarray(offset,offset+0x8000));
        return {name:f.name,size:f.size,contentBase64:btoa(binary)}; }
      if(globalThis.__chironUploadProof){ const proof=globalThis.__chironUploadProof;
        globalThis.__chironUploadProof=null; return proof; }
      await new Promise(resolve=>setTimeout(resolve,50)); }
      return null; })()""" % json.dumps(selector))
    if not observed:
        return {"verified": False, "expected_sha256": expected, "observed": None}
    try:
        observed_hash = hashlib.sha256(base64.b64decode(str(observed.pop("contentBase64")), validate=True)).hexdigest()
    except Exception:
        return {
            "verified": False,
            "expected_sha256": expected,
            "observed": {"name": observed.get("name"), "size": observed.get("size"), "sha256": None},
        }
    safe_observed = {"name": observed.get("name"), "size": observed.get("size"), "sha256": observed_hash}
    return {"verified": observed_hash == expected, "expected_sha256": expected, "observed": safe_observed}


def advance(js: Callable[[str], Any], click_at_xy: Callable[[float, float], Any]) -> dict[str, Any]:
    """Advance one proven non-final control while retaining the final guard."""
    if not _install_final_guard(js):
        return {"advanced": False, "reason": "final_guard_unavailable"}
    candidate = js(r"""(() => { const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
      const norm=s=>String(s||'').replace(/\s+/g,' ').trim(); const allowed=new Set(['next','continue','save and continue']);
      const candidates=Array.from(document.querySelectorAll('button,a')).filter(visible).filter(e=>allowed.has(norm(e.innerText||e.getAttribute('aria-label')).toLowerCase()));
      if(candidates.length!==1)return {count:candidates.length};const e=candidates[0],r=e.getBoundingClientRect();return {count:1,label:norm(e.innerText),x:r.left+r.width/2,y:r.top+r.height/2}; })()""")
    if not candidate or candidate.get("count") != 1:
        return {"advanced": False, "reason": "non_final_advance_not_unique"}
    click_at_xy(float(candidate["x"]), float(candidate["y"]))
    return {"advanced": True, "label": candidate.get("label")}


def review_readback(
    js: Callable[[str], Any], ats_family: str = "workday",
    profile: Mapping[str, Any] | None = None,
    constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read a rendered Review, retaining structured Workday validation."""
    family = str(ats_family).strip().casefold()
    guard = _install_final_guard(js)
    raw = js(_REVIEW_JS) or {}
    url = str(raw.get("url", ""))
    if not raw.get("isReview") and "review" not in url.casefold():
        return {"stage": "other", "url": url, "supported": False}
    if family == "greenhouse":
        observed = js(_OBSERVE_JS) or {}
        actions = {_norm(value) for value in list(observed.get("actions") or [])}
        if "submit application" not in actions or not _greenhouse_form_ready(observed):
            return {
                "stage": "application", "ats_family": family, "url": url,
                "supported": True, "required_complete": False,
                "final_guard_active": guard,
            }
    result = {
        "stage": "review",
        "ats_family": family,
        "url": url,
        "sections": list(raw.get("sections") or [])[:60],
        "attachments": list(raw.get("attachments") or [])[:30],
        "final_actions": list(raw.get("finalActions") or [])[:10],
        "submit_untouched": True,
        "final_guard_active": guard,
    }
    if family == "workday" and profile and (profile.get("work_experience") or profile.get("education")):
        history = workday_history_readback(js, profile, constraints=constraints)
        questions = workday_question_readback(js)
        result["structured_history"] = history
        result["question_answers"] = questions
        if history.get("complete") is not True or questions.get("stage") != "review":
            result.update({"stage": "application", "required_complete": False})
    return result
