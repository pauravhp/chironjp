"""Manifest-driven canonical resume composition and rendered validation.

The caller chooses IDs from a finite canonical bank. This module never invents,
rewrites, or semantically selects resume claims.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from .paths import REPO_ROOT, discover_executable, private_dir, private_file


DEFAULT_BANK_PATH = REPO_ROOT / "resume" / "bank.template.json"
DEFAULT_TEMPLATE_PATH = REPO_ROOT / "resume" / "template.tex"
DEFAULT_PROFILE_PATH = REPO_ROOT / "templates" / "config" / "canonical-profile-overrides.json"
COMPOSER_VERSION = 6
GEOMETRY_CHECK_VERSION = 1


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_bank(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported canonical resume bank version")
    return value


def _load_profile(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("canonical profile must be a JSON object")
    return value


def _tex(value: Any) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        "–": "--", "—": "---", "’": "'", "“": "``", "”": "''",
    }
    return "".join(replacements.get(char, char) for char in str(value))


def _tex_with_inline_links(value: Any, links: Sequence[Mapping[str, Any]]) -> str:
    text = str(value)
    spans: list[tuple[int, int, str, str]] = []
    for link in links:
        label = str(link.get("label") or "")
        url = str(link.get("url") or "")
        if not label or not re.fullmatch(r"https?://[^\s{}]+", url):
            raise ValueError("inline link requires a non-empty label and safe HTTP(S) URL")
        start = text.find(label)
        if start < 0 or text.find(label, start + len(label)) >= 0:
            raise ValueError(f"inline link label must occur exactly once: {label!r}")
        spans.append((start, start + len(label), label, url))
    rendered: list[str] = []
    cursor = 0
    for start, end, label, url in sorted(spans):
        if start < cursor:
            raise ValueError("inline link labels must not overlap")
        rendered.append(_tex(text[cursor:start]))
        rendered.append(f"\\href{{{url}}}{{\\underline{{{_tex(label)}}}}}")
        cursor = end
    rendered.append(_tex(text[cursor:]))
    return "".join(rendered)


def _safe_http_url(value: Any, *, field: str) -> str:
    url = str(value or "").strip()
    if url and not re.fullmatch(r"https?://[^\s{}]+", url):
        raise ValueError(f"{field} must be blank or a safe HTTP(S) URL")
    return url


def _contact_tex(profile: Mapping[str, Any]) -> str:
    identity = profile.get("identity", {})
    if not isinstance(identity, Mapping):
        identity = {}
    pieces: list[str] = []
    phone = str(identity.get("phone") or "").strip()
    if phone:
        pieces.append(_tex(phone))
    for field, label in (("linkedin_url", "LinkedIn"), ("website_url", "Website")):
        url = _safe_http_url(identity.get(field), field=f"identity.{field}")
        if url:
            display = re.sub(r"^https?://", "", url).rstrip("/") or label
            pieces.append(f"\\href{{{url}}}{{\\underline{{{_tex(display)}}}}}")
    return " ~$|$~ ".join(pieces)


def _month(value: Any) -> str:
    raw = str(value or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if not match:
        return raw
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return raw
    return f"{calendar.month_abbr[month]} {match.group(1)}"


def _education_tex(profile: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for item in profile.get("education", []):
        degree = str(item.get("degree") or "").strip()
        field = str(item.get("field") or "").strip()
        credential = " in ".join(value for value in (degree, field) if value)
        end_key = "expected_end" if bool(item.get("current")) else "completed_end"
        date_parts = [value for value in (_month(item.get("start")), _month(item.get(end_key))) if value]
        dates = " -- ".join(date_parts)
        raw_place = item.get("location")
        if isinstance(raw_place, Mapping):
            place = ", ".join(
                str(raw_place.get(key) or "").strip()
                for key in ("city", "region", "country")
                if str(raw_place.get(key) or "").strip()
            )
        else:
            place = str(raw_place or "").strip()
        lines.append(
            f"  \\resumeSubheading{{{_tex(item.get('school') or '')}}}{{{_tex(dates)}}}"
            f"{{{_tex(credential)}}}{{{_tex(place)}}}"
        )
    return "\n".join(lines)


def _skill_aliases(bank: Mapping[str, Any]) -> dict[str, str]:
    aliases = {
        str(value).casefold(): str(value)
        for values in bank.get("canonical_skills", {}).values()
        for value in values
    }
    for skill, evidence in bank.get("skill_evidence", {}).items():
        aliases[str(skill).casefold()] = str(skill)
        for alias in evidence.get("aliases", []):
            aliases[str(alias).casefold()] = str(skill)
    return aliases


def _skill_exclusions(bank: Mapping[str, Any]) -> dict[str, str]:
    exclusions: dict[str, str] = {}
    for skill, evidence in bank.get("skill_exclusions", {}).items():
        exclusions[str(skill).casefold()] = str(skill)
        for alias in evidence.get("aliases", []):
            exclusions[str(alias).casefold()] = str(skill)
    return exclusions


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9+#.]+", value.casefold())
        if len(token) > 1
    }


def _excluded_skill(
    term: str,
    aliases: Mapping[str, str],
    exclusions: Mapping[str, str],
) -> str | None:
    """Resolve exact or qualified denials without treating neighbors as facts."""
    folded = term.casefold().strip()
    if folded in aliases:
        return exclusions.get(folded)
    if folded in exclusions:
        return exclusions[folded]
    term_tokens = _tokens(term)
    for phrase, canonical in exclusions.items():
        phrase_tokens = _tokens(phrase)
        if len(phrase_tokens) >= 2 and phrase_tokens <= term_tokens:
            return canonical
    return None


def extract_technology_hints(bank: Mapping[str, Any], description: str) -> list[str]:
    """Return deterministic omission hints, never a semantic selection."""
    aliases = _skill_aliases(bank)
    hits: list[tuple[int, str]] = []
    for phrase, canonical in aliases.items():
        phrase_pattern = re.escape(phrase).replace(r"\ ", r"\s+")
        match = re.search(
            rf"(?<![\w+#]){phrase_pattern}(?![\w+#])",
            description,
            re.I,
        )
        if match:
            hits.append((match.start(), canonical))
    ordered: list[str] = []
    for _, canonical in sorted(hits, key=lambda item: (item[0], item[1])):
        if canonical not in ordered:
            ordered.append(canonical)
    return ordered


def tailor_contract(
    *,
    role: str,
    description: str,
    bank_path: str | Path = DEFAULT_BANK_PATH,
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> Mapping[str, Any]:
    """Expose the complete finite choice set; the caller selects from it."""
    bank_file, template_file, profile_file = Path(bank_path), Path(template_path), Path(profile_path)
    bank = _load_bank(bank_file)
    _load_profile(profile_file)
    summary = bank.get("canonical_summary", {})
    labels = [*summary.get("labels", {}).values(), summary.get("default_label")]
    return {
        "schema_version": 1,
        "composer_version": COMPOSER_VERSION,
        "role": role,
        "job_description_sha256": hashlib.sha256(description.encode()).hexdigest(),
        "summary_labels": list(dict.fromkeys(label for label in labels if label)),
        "fixed_experience_order": [str(item["id"]) for item in bank.get("experience", [])],
        "experiences": [{
            "id": item["id"],
            "minimum_bullets": item["minimum_bullets"],
            "target_bullets": item["preferred_bullets"],
            "bullets": [{
                "id": bullet["id"], "text": bullet["text"],
                "tags": bullet.get("tags", []),
                **({"inline_links": bullet["inline_links"]} if bullet.get("inline_links") else {}),
            } for bullet in item.get("bullets", [])],
        } for item in bank.get("experience", [])],
        "projects": list(bank.get("projects", [])),
        "leadership": dict(bank.get("leadership", {})),
        "awards": list(bank.get("awards", [])),
        "canonical_skills": dict(bank.get("canonical_skills", {})),
        "skill_sources": dict(bank.get("skill_sources", {})),
        "skill_evidence": dict(bank.get("skill_evidence", {})),
        "skill_exclusions": dict(bank.get("skill_exclusions", {})),
        "jd_technology_hints": extract_technology_hints(bank, description),
        "jd_analysis_required": (
            "Read the whole JD; name every technology or concept with an exact JD "
            "quote and canonical skill mapping, or null for owner confirmation. "
            "Hints are incomplete, not a vocabulary limit."
        ),
        "skills_line_budget": 4,
        "skills_target_count": "roughly 30 distinct known technologies, or whatever fits readably",
        "bank_path": str(bank_file.resolve()),
        "bank_sha256": file_sha256(bank_file),
        "template_path": str(template_file.resolve()),
        "template_sha256": file_sha256(template_file),
        "profile_path": str(profile_file.resolve()),
        "profile_sha256": file_sha256(profile_file),
    }


def _experience_tex(
    experience: Sequence[Mapping[str, Any]],
    selected: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    blocks: list[str] = []
    for entry in experience:
        blocks.append(
            f"  \\resumeSubheading{{{_tex(entry['employer'])}}}{{{_tex(entry['dates'])}}}"
            f"{{{_tex(entry['title'])}}}{{{_tex(entry['location'])}}}"
        )
        bullets = selected.get(str(entry["id"]), ())
        if bullets:
            blocks.append("  \\resumeItemListStart")
            blocks.extend(
                f"    \\resumeItem{{{_tex_with_inline_links(item['text'], item.get('inline_links') or [])}}}"
                for item in bullets
            )
            blocks.append("  \\resumeItemListEnd")
    return "\n".join(blocks)


def _project_rendering(project: Mapping[str, Any], variant_id: str | None) -> Mapping[str, Any]:
    variants = list(project.get("variants") or [])
    if not variants:
        return project
    selected_id = variant_id or str(project.get("default_variant") or "")
    selected = next((item for item in variants if str(item.get("id")) == selected_id), None)
    if selected is None:
        raise ValueError(f"unknown project variant {selected_id!r} for {project.get('id')!r}")
    rendered = {**dict(project), **{key: value for key, value in selected.items() if key != "id"}}
    rendered.pop("variants", None)
    rendered.pop("default_variant", None)
    return rendered


def _projects_tex(
    projects: Sequence[Mapping[str, Any]], project_variants: Mapping[str, str],
) -> str:
    blocks: list[str] = []
    for raw_project in projects:
        project = _project_rendering(raw_project, project_variants.get(str(raw_project["id"])))
        heading = (
            f"\\textbf{{{_tex(project['name'])}}} $|$ "
            f"\\emph{{{_tex(', '.join(project['technologies']))}}}"
        )
        bullets = list(project.get("bullets") or [project["text"]])
        links = list(project.get("links") or [])
        if not links and project.get("url"):
            links.append({"label": "Source", "url": project["url"]})
        if not project.get("links") and project.get("deployed_url"):
            links.append({"label": "Live", "url": project["deployed_url"]})
        link_tex = " ".join(
            f"[\\href{{{item['url']}}}{{\\underline{{{_tex(item['label'])}}}}}]"
            for item in links
        )
        blocks.extend((
            f"  \\resumeProjectHeading{{{heading}}}{{{_tex(project.get('date') or '')}}}",
            "  \\resumeItemListStart",
        ))
        for index, bullet in enumerate(bullets):
            suffix = f" \\hfill {link_tex}" if link_tex and index == len(bullets) - 1 else ""
            blocks.append(f"    \\resumeItem{{{_tex(bullet)}{suffix}}}")
        blocks.append("  \\resumeItemListEnd")
    return "\n".join(blocks)


def _skills_tex(groups: Mapping[str, Sequence[str]]) -> str:
    return " \\\\\n".join(
        f"  \\textbf{{{_tex(label)}}}{{: {_tex(', '.join(values))}}}"
        for label, values in groups.items()
    )


def _leadership_tex(
    entry: Mapping[str, Any],
    bullets: Sequence[Mapping[str, Any]],
    awards: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        f"  \\resumeSubheading{{{_tex(entry['employer'])}}}{{{_tex(entry['dates'])}}}"
        f"{{{_tex(entry['title'])}}}{{{_tex(entry['location'])}}}",
        "  \\resumeItemListStart",
        *(f"    \\resumeItem{{{_tex(item['text'])}}}" for item in bullets),
        "  \\resumeItemListEnd",
    ]
    for award in awards:
        lines.extend((
            f"  \\resumeProjectHeading{{\\textbf{{{_tex(award['title'])}}}}}{{}}",
            "  \\resumeItemListStart",
            f"    \\resumeItem{{{_tex(award['text'])}}}",
            "  \\resumeItemListEnd",
        ))
    return "\n".join(lines)


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    role: str,
    description: str,
    bank_path: str | Path = DEFAULT_BANK_PATH,
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> Mapping[str, Any]:
    """Validate an explicit selection and compose TeX without compiling it."""
    bank_file, template_file, profile_file = Path(bank_path), Path(template_path), Path(profile_path)
    bank = _load_bank(bank_file)
    profile = _load_profile(profile_file)
    errors: list[dict[str, str]] = []

    def error(code: str, path: str, detail: str) -> None:
        errors.append({"code": code, "path": path, "detail": detail})

    if manifest.get("schema_version") != 1:
        error("schema_version", "schema_version", "must equal 1")
    identity = profile.get("identity")
    if not isinstance(identity, Mapping) or not str(identity.get("full_legal_name") or "").strip():
        error("profile_identity", "profile.identity.full_legal_name", "must be populated")
    education = profile.get("education")
    if not isinstance(education, list) or not education:
        error("profile_education", "profile.education", "requires at least one canonical row")
    else:
        for index, item in enumerate(education):
            if not isinstance(item, Mapping) or any(
                not str(item.get(field) or "").strip()
                for field in ("school", "degree", "field", "start")
            ):
                error("profile_education", f"profile.education.{index}", "school, degree, field, and start are required; unknown location/end values remain blank")
    try:
        _contact_tex(profile)
    except ValueError as exc:
        error("profile_contact", "profile.identity", str(exc))
    resume_fields = {key: manifest.get(key) for key in ("summary_label", "skills")}
    if "seeking" in compact_json(resume_fields).casefold() or any(
        "seeking" in str(key).casefold() for key in manifest
    ):
        error("forbidden_seeking", "$", "a Seeking sentence or field is forbidden")
    summary = bank.get("canonical_summary", {})
    labels = set(summary.get("labels", {}).values()) | {summary.get("default_label")}
    label = manifest.get("summary_label")
    if label not in labels:
        error("summary_label", "summary_label", "must be one offered canonical label")

    experience = list(bank.get("experience", []))
    fixed_order = [str(item["id"]) for item in experience]
    if manifest.get("experience_order") != fixed_order:
        error("experience_order", "experience_order", f"must equal {fixed_order}")
    raw_bullets = manifest.get("experience_bullets")
    if not isinstance(raw_bullets, Mapping):
        error("experience_bullets", "experience_bullets", "must be an object")
        raw_bullets = {}
    selected: dict[str, list[Mapping[str, Any]]] = {}
    for entry in experience:
        entry_id = str(entry["id"])
        ids = raw_bullets.get(entry_id)
        if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
            error("experience_bullets", f"experience_bullets.{entry_id}", "must be a list of canonical IDs")
            ids = []
        if len(ids) != len(set(ids)):
            error("duplicate_bullet", f"experience_bullets.{entry_id}", "bullet IDs must be unique")
        available = {str(item["id"]): item for item in entry.get("bullets", [])}
        unknown = [value for value in ids if value not in available]
        if unknown:
            error("unknown_bullet", f"experience_bullets.{entry_id}", f"unknown IDs: {unknown}")
        minimum = int(entry.get("minimum_bullets", 0))
        if len(ids) < minimum or len(ids) > len(available):
            error("bullet_count", f"experience_bullets.{entry_id}", f"requires {minimum}..{len(available)} bullets")
        selected[entry_id] = [available[value] for value in ids if value in available]
    if set(raw_bullets) != set(fixed_order):
        error("experience_keys", "experience_bullets", f"keys must equal {fixed_order}")

    project_map = {str(item["id"]): item for item in bank.get("projects", [])}
    raw_projects = manifest.get("projects")
    if (
        not isinstance(raw_projects, list)
        or not all(isinstance(value, str) for value in raw_projects)
        or len(raw_projects) != 2
        or len(set(raw_projects)) != 2
    ):
        error("project_count", "projects", "requires exactly two distinct canonical project IDs")
        raw_projects = []
    unknown_projects = [value for value in raw_projects if value not in project_map]
    if unknown_projects:
        error("unknown_project", "projects", f"unknown IDs: {unknown_projects}")
    raw_project_variants = manifest.get("project_variants") or {}
    if not isinstance(raw_project_variants, Mapping):
        error("project_variants", "project_variants", "must be an object keyed by selected project ID")
        raw_project_variants = {}
    extra_variant_keys = [key for key in raw_project_variants if key not in raw_projects]
    if extra_variant_keys:
        error("project_variant_scope", "project_variants", f"variants supplied for unselected projects: {extra_variant_keys}")
    selected_project_variants: dict[str, str] = {}
    for project_id in raw_projects:
        project = project_map.get(project_id)
        if not project:
            continue
        variants = {str(item["id"]): item for item in project.get("variants") or []}
        chosen = raw_project_variants.get(project_id)
        if variants:
            if not isinstance(chosen, str) or chosen not in variants:
                error("project_variant", f"project_variants.{project_id}", f"choose exactly one canonical variant: {sorted(variants)}")
            else:
                selected_project_variants[project_id] = chosen
        elif chosen is not None:
            error("project_variant", f"project_variants.{project_id}", "project has no variants")

    leadership_entry = bank.get("leadership", {})
    leadership_map = {str(item["id"]): item for item in leadership_entry.get("bullets", [])}
    raw_leadership = manifest.get("leadership_bullets")
    if not isinstance(raw_leadership, list) or not all(isinstance(value, str) for value in raw_leadership):
        error("leadership_bullets", "leadership_bullets", "must be a list of canonical IDs")
        raw_leadership = []
    minimum_leadership = int(leadership_entry.get("minimum_bullets", 1))
    if not minimum_leadership <= len(raw_leadership) <= len(leadership_map) or len(set(raw_leadership)) != len(raw_leadership):
        error("leadership_count", "leadership_bullets", f"requires {minimum_leadership}..{len(leadership_map)} distinct bullets")
    unknown_leadership = [value for value in raw_leadership if value not in leadership_map]
    if unknown_leadership:
        error("unknown_leadership_bullet", "leadership_bullets", f"unknown IDs: {unknown_leadership}")

    award_map = {str(item["id"]): item for item in bank.get("awards", [])}
    required_awards = {key for key, item in award_map.items() if item.get("required")}
    raw_awards = manifest.get("awards")
    if not isinstance(raw_awards, list) or not all(isinstance(value, str) for value in raw_awards):
        error("awards", "awards", "must be a list of canonical award IDs")
        raw_awards = []
    if len(raw_awards) != len(set(raw_awards)):
        error("duplicate_award", "awards", "award IDs must be unique")
    unknown_awards = [value for value in raw_awards if value not in award_map]
    if unknown_awards:
        error("unknown_award", "awards", f"unknown IDs: {unknown_awards}")
    if not required_awards.issubset(set(raw_awards)):
        error("required_award", "awards", f"requires canonical awards: {sorted(required_awards)}")

    raw_skills = manifest.get("skills")
    aliases, exclusions = _skill_aliases(bank), _skill_exclusions(bank)
    skill_groups: dict[str, list[str]] = {}
    if (
        not isinstance(raw_skills, Mapping)
        or not 1 <= len(raw_skills) <= 4
        or any(not isinstance(key, str) or not key.strip() or len(key) > 48 for key in raw_skills)
    ):
        error("skill_groups", "skills", "choose one to four concise role-specific category labels")
        raw_skills = {}
    for group, values in raw_skills.items():
        if not isinstance(values, list) or not values or not all(isinstance(value, str) and value.strip() for value in values):
            error("skill_values", f"skills.{group}", "must be a list of non-empty strings")
            values = []
        skill_groups[str(group)] = list(values)
    selected_skills = [value for values in skill_groups.values() for value in values]
    canonical_selected = [aliases.get(value.casefold(), value) for value in selected_skills]
    if len(set(canonical_selected)) != len(selected_skills):
        error("duplicate_skill", "skills", "skills and aliases must be unique across categories")
    denied = [value for value in selected_skills if value.casefold() in exclusions]
    if denied:
        error("owner_denied_skill", "skills", f"owner-denied skills cannot be asserted: {denied}")
    extras = [value for value in selected_skills if value.casefold() not in aliases and value.casefold() not in exclusions]
    if extras:
        error("unsupported_skill", "skills", f"unconfirmed skills cannot be asserted: {extras}")

    analysis = manifest.get("jd_coverage")
    if not isinstance(analysis, list):
        error("jd_analysis_required", "jd_coverage", "requires whole-JD technology and concept analysis, even when empty")
        analysis = []
    coverage: dict[str, bool] = {}
    pending: list[dict[str, str]] = []
    folded_description = " ".join(description.split()).casefold()
    analyzed: set[str] = set()
    for index, item in enumerate(analysis):
        path = f"jd_coverage.{index}"
        if not isinstance(item, Mapping):
            error("jd_evidence", path, "requires term, exact jd_quote, skill or null, and reason")
            continue
        term = str(item.get("term") or "").strip()
        quote = str(item.get("jd_quote") or "").strip()
        skill = item.get("skill")
        reason = str(item.get("reason") or "").strip()
        if not term or not quote or " ".join(quote.split()).casefold() not in folded_description or not reason:
            error("jd_evidence", path, "term, exact JD quote, and mapping or confirmation reason are required")
            continue
        canonical_term = aliases.get(term.casefold(), term)
        if canonical_term.casefold() in analyzed:
            error("duplicate_jd_term", path, term)
        analyzed.add(canonical_term.casefold())
        known = aliases.get(term.casefold())
        excluded = _excluded_skill(term, aliases, exclusions)
        if excluded and skill is not None:
            error("owner_denied_skill", path, f"{term} is owner-denied; use skill null")
        if known and skill != known:
            error("jd_skill_mapping", path, f"{term} maps to confirmed {known}")
        if skill is None:
            if not excluded:
                pending.append({"technology": term, "jd_quote": quote, "reason": reason})
            coverage[term] = False
        elif not isinstance(skill, str) or skill.casefold() not in aliases:
            error("jd_skill_mapping", path, "mapped skill must be evidence-backed; otherwise use null")
        elif aliases[skill.casefold()] not in canonical_selected:
            error("missing_jd_technology", "skills", f"{term}: include {aliases[skill.casefold()]}")
        else:
            coverage[term] = True
    for hint in extract_technology_hints(bank, description):
        if hint.casefold() not in analyzed:
            error("missing_jd_analysis", "jd_coverage", f"address detected {hint} with JD evidence")
        if hint not in canonical_selected:
            error("missing_jd_technology", "skills", f"missing confirmed JD technology: {hint}")

    if errors:
        return {"schema_version": 1, "passed": False, "errors": errors, "source": None, "selection": None}

    projects = [project_map[value] for value in raw_projects]
    leadership = [leadership_map[value] for value in raw_leadership]
    awards = [award_map[value] for value in raw_awards]
    source = template_file.read_text(encoding="utf-8")
    placeholders = {
        "@@FULL_NAME@@", "@@CONTACT@@", "@@EDUCATION@@", "@@SUMMARY@@",
        "@@EXPERIENCE@@", "@@PROJECTS@@", "@@SKILLS@@", "@@LEADERSHIP@@",
    }
    missing = sorted(value for value in placeholders if value not in source)
    if missing:
        return {
            "schema_version": 1,
            "passed": False,
            "errors": [{"code": "template_placeholder", "path": str(template_file), "detail": f"missing placeholders: {missing}"}],
            "source": None,
            "selection": None,
        }
    source = source.replace("@@FULL_NAME@@", _tex(profile["identity"]["full_legal_name"]))
    source = source.replace("@@CONTACT@@", _contact_tex(profile))
    source = source.replace("@@EDUCATION@@", _education_tex(profile))
    source = source.replace("@@SUMMARY@@", _tex(f"{label} {summary['body']}"))
    source = source.replace("@@EXPERIENCE@@", _experience_tex(experience, selected))
    source = source.replace("@@PROJECTS@@", _projects_tex(projects, selected_project_variants))
    source = source.replace("@@SKILLS@@", _skills_tex(skill_groups))
    source = source.replace("@@LEADERSHIP@@", _leadership_tex(leadership_entry, leadership, awards))
    normalized = {
        **dict(manifest),
        "composer_version": COMPOSER_VERSION,
        "project_variants": selected_project_variants,
        "role": role,
        "job_description_sha256": hashlib.sha256(description.encode()).hexdigest(),
        "bank_sha256": file_sha256(bank_file),
        "template_sha256": file_sha256(template_file),
        "profile_sha256": file_sha256(profile_file),
        "jd_technologies": list(coverage),
        "technology_coverage": coverage,
        "owner_confirmation_needed": pending,
        "provisional_technologies": [],
    }
    return {"schema_version": 1, "passed": True, "errors": [], "source": source, "selection": normalized}


def inspect_pdf_geometry(
    pdf: str | Path,
    *,
    pdftotext: str | os.PathLike[str] | None = None,
) -> Mapping[str, Any]:
    """Measure page bounds, Skills lines, and rendered text intersections."""
    executable = discover_executable("pdftotext", explicit=pdftotext, env_var="CHIRONJP_PDFTOTEXT")
    if executable is None:
        raise ValueError("pdftotext is unavailable; set CHIRONJP_PDFTOTEXT or add it to PATH")
    path = Path(pdf)
    with tempfile.TemporaryDirectory(prefix="chironjp-geometry-") as raw:
        output = Path(raw) / "bbox.xhtml"
        result = subprocess.run(
            [str(executable), "-bbox-layout", str(path), str(output)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode or not output.is_file():
            raise ValueError(f"PDF geometry extraction failed: {result.stdout[-1000:]}")
        root = ET.parse(output).getroot()
    namespace = "{http://www.w3.org/1999/xhtml}"
    pages = list(root.iter(namespace + "page"))
    skills_lines: list[str] = []
    in_skills = False
    for line in root.iter(namespace + "line"):
        text = " ".join(word.text or "" for word in line.iter(namespace + "word"))
        if text.strip().casefold() == "technical skills":
            in_skills = True
        elif in_skills and text.strip().casefold().startswith("leadership"):
            in_skills = False
        elif in_skills and text.strip():
            skills_lines.append(text)
    words: list[dict[str, Any]] = []
    clipped: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages):
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        for word in page.iter(namespace + "word"):
            box = {
                "page": page_index + 1,
                "text": word.text or "",
                "x_min": float(word.attrib["xMin"]),
                "y_min": float(word.attrib["yMin"]),
                "x_max": float(word.attrib["xMax"]),
                "y_max": float(word.attrib["yMax"]),
            }
            words.append(box)
            if box["x_min"] < -0.01 or box["y_min"] < -0.01 or box["x_max"] > width + 0.01 or box["y_max"] > height + 0.01:
                clipped.append(box)
    adjacency: dict[int, set[int]] = {}
    pair_count = 0
    for left_index, left in enumerate(words):
        for right_index in range(left_index + 1, len(words)):
            right = words[right_index]
            if left["page"] != right["page"]:
                continue
            x_overlap = min(left["x_max"], right["x_max"]) - max(left["x_min"], right["x_min"])
            y_overlap = min(left["y_max"], right["y_max"]) - max(left["y_min"], right["y_min"])
            if x_overlap <= 0.01 or y_overlap <= 0.01:
                continue
            pair_count += 1
            adjacency.setdefault(left_index, set()).add(right_index)
            adjacency.setdefault(right_index, set()).add(left_index)
    components: list[dict[str, Any]] = []
    unseen = set(adjacency)
    while unseen:
        pending, members = [unseen.pop()], set()
        while pending:
            index = pending.pop()
            if index in members:
                continue
            members.add(index)
            for neighbor in adjacency.get(index, ()):
                unseen.discard(neighbor)
                if neighbor not in members:
                    pending.append(neighbor)
        boxes = [words[index] for index in sorted(members)]
        components.append({
            "page": boxes[0]["page"],
            "text": [box["text"] for box in boxes],
            "x_min": min(box["x_min"] for box in boxes),
            "y_min": min(box["y_min"] for box in boxes),
            "x_max": max(box["x_max"] for box in boxes),
            "y_max": max(box["y_max"] for box in boxes),
        })
    components.sort(key=lambda item: (item["page"], item["y_min"], item["x_min"]))
    regions: list[dict[str, Any]] = []
    for component in components:
        prior = regions[-1] if regions else None
        y_overlap = 0.0 if prior is None else min(prior["y_max"], component["y_max"]) - max(prior["y_min"], component["y_min"])
        x_gap = 1000.0 if prior is None else component["x_min"] - prior["x_max"]
        if prior is not None and prior["page"] == component["page"] and y_overlap > 0.01 and x_gap <= 12.0:
            prior["text"].extend(component["text"])
            for edge, operation in (("x_min", min), ("y_min", min), ("x_max", max), ("y_max", max)):
                prior[edge] = operation(prior[edge], component[edge])
        else:
            regions.append({**component, "text": list(component["text"])})
    return {
        "geometry_check_version": GEOMETRY_CHECK_VERSION,
        "page_count": len(pages),
        "word_count": len(words),
        "skills_line_count": len(skills_lines),
        "skills_lines": skills_lines,
        "intersecting_word_pair_count": pair_count,
        "intersection_component_count": len(components),
        "text_intersection_count": len(regions),
        "text_intersections": regions,
        "clipped_text_count": len(clipped),
        "clipped_text": clipped,
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(compact_json(value) + "\n", encoding="utf-8")
    private_file(path)


def render_agent_manifest(
    *,
    selection_path: str | Path,
    role: str,
    description: str,
    output_dir: str | Path,
    bank_path: str | Path = DEFAULT_BANK_PATH,
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    tectonic: str | os.PathLike[str] | None = None,
    pdftotext: str | os.PathLike[str] | None = None,
    pdftoppm: str | os.PathLike[str] | None = None,
) -> Mapping[str, Any]:
    """Render exactly one manifest and return hash-bound automated evidence.

    A passing report still requires a human or vision-capable agent to inspect
    the exact returned PNG and bind its hashes in a separate inspection record.
    """
    selection_file, bank_file, template_file, profile_file = (
        Path(selection_path), Path(bank_path), Path(template_path), Path(profile_path)
    )
    raw = selection_file.read_bytes()
    selection_input_sha256 = hashlib.sha256(raw).hexdigest()
    renderer_sha256 = file_sha256(Path(__file__))
    render_identity = hashlib.sha256(raw + compact_json({
        "bank": file_sha256(bank_file),
        "template": file_sha256(template_file),
        "profile": file_sha256(profile_file),
        "role": role,
        "description": description,
        "renderer": renderer_sha256,
    }).encode()).hexdigest()
    render_root = Path(output_dir) / "renders" / render_identity[:24]
    private_dir(render_root)
    validation_path = render_root / "validation.json"
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        report = {
            "schema_version": 1,
            "passed": False,
            "selection_input_sha256": selection_input_sha256,
            "errors": [{"code": "invalid_json", "path": "$", "detail": str(exc)}],
            "validation_path": str(validation_path),
            "vision_inspection_required": True,
        }
        _write_json(validation_path, report)
        return report
    if not isinstance(manifest, Mapping):
        manifest = {}
    composition = validate_manifest(
        manifest,
        role=role,
        description=description,
        bank_path=bank_file,
        template_path=template_file,
        profile_path=profile_file,
    )
    if not composition["passed"]:
        report = {
            "schema_version": 1,
            "passed": False,
            "selection_input_sha256": selection_input_sha256,
            "bank_sha256": file_sha256(bank_file),
            "template_sha256": file_sha256(template_file),
            "profile_sha256": file_sha256(profile_file),
            "renderer_sha256": renderer_sha256,
            "errors": composition["errors"],
            "validation_path": str(validation_path),
            "preview_path": None,
            "vision_inspection_required": True,
        }
        _write_json(validation_path, report)
        return report

    source_path = render_root / "resume.tex"
    selection_output = render_root / "selection.json"
    pdf_path = render_root / "resume.pdf"
    preview_stem, preview_path = render_root / "preview", render_root / "preview.png"
    log_path = render_root / "resume.log"
    source_path.write_text(str(composition["source"]), encoding="utf-8")
    private_file(source_path)
    _write_json(selection_output, composition["selection"])

    compiler = discover_executable("tectonic", explicit=tectonic, env_var="CHIRONJP_TECTONIC")
    text_tool = discover_executable("pdftotext", explicit=pdftotext, env_var="CHIRONJP_PDFTOTEXT")
    preview_tool = discover_executable("pdftoppm", explicit=pdftoppm, env_var="CHIRONJP_PDFTOPPM")
    errors: list[dict[str, Any]] = []
    geometry: Mapping[str, Any] = {}
    compiler_output = ""
    compiler_return_code: int | None = None
    overflow = False
    if compiler is None:
        errors.append({"code": "compiler_unavailable", "path": "resume.tex", "detail": "set CHIRONJP_TECTONIC or add tectonic to PATH"})
    else:
        env = dict(os.environ)
        env["SOURCE_DATE_EPOCH"] = "0"
        result = subprocess.run(
            [str(compiler), "--keep-logs", "--outdir", str(render_root), str(source_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
        compiler_return_code = result.returncode
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        compiler_output = result.stdout + "\n" + log
        overflow = bool(re.search(r"Overfull \\[hv]box", compiler_output))
        if result.returncode or not pdf_path.is_file():
            errors.append({"code": "compile_failed", "path": "resume.tex", "detail": compiler_output[-2000:]})
    if pdf_path.is_file():
        if text_tool is None:
            errors.append({"code": "geometry_unavailable", "path": "resume.pdf", "detail": "set CHIRONJP_PDFTOTEXT or add pdftotext to PATH"})
        else:
            geometry = inspect_pdf_geometry(pdf_path, pdftotext=text_tool)
            if int(geometry["page_count"]) != 1:
                errors.append({"code": "page_count", "path": "resume.pdf", "detail": f"expected 1 page, observed {geometry['page_count']}"})
            if int(geometry["word_count"]) == 0:
                errors.append({"code": "zero_text", "path": "resume.pdf", "detail": "no extractable text was rendered"})
            if int(geometry["skills_line_count"]) != 4:
                errors.append({"code": "skills_lines", "path": "resume.pdf", "detail": f"Skills must fill 4 readable lines, observed {geometry['skills_line_count']}", "lines": geometry["skills_lines"]})
            if int(geometry["clipped_text_count"]):
                errors.append({"code": "clipped_text", "path": "resume.pdf", "detail": f"{geometry['clipped_text_count']} words cross page bounds", "locations": geometry["clipped_text"]})
            if int(geometry["text_intersection_count"]):
                errors.append({"code": "text_intersections", "path": "resume.pdf", "detail": f"{geometry['text_intersection_count']} collision regions", "locations": geometry["text_intersections"]})
        if overflow:
            errors.append({"code": "tex_overflow", "path": "resume.tex", "detail": "TeX reported an overfull box"})
        if preview_tool is None:
            errors.append({"code": "preview_unavailable", "path": "resume.pdf", "detail": "set CHIRONJP_PDFTOPPM or add pdftoppm to PATH"})
        else:
            preview_result = subprocess.run(
                [str(preview_tool), "-png", "-singlefile", "-r", "180", str(pdf_path), str(preview_stem)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                check=False,
            )
            if preview_result.returncode or not preview_path.is_file():
                errors.append({"code": "preview_failed", "path": "resume.pdf", "detail": preview_result.stdout[-1000:]})
    for path in (pdf_path, preview_path, log_path):
        if path.is_file():
            private_file(path)
    report = {
        "schema_version": 1,
        "passed": not errors,
        "selection_input_sha256": selection_input_sha256,
        "selection_sha256": file_sha256(selection_output),
        "source_sha256": file_sha256(source_path),
        "resume_sha256": file_sha256(pdf_path) if pdf_path.is_file() else None,
        "preview_sha256": file_sha256(preview_path) if preview_path.is_file() else None,
        "bank_sha256": file_sha256(bank_file),
        "template_sha256": file_sha256(template_file),
        "profile_sha256": file_sha256(profile_file),
        "renderer_sha256": renderer_sha256,
        "selection_path": str(selection_output),
        "source_path": str(source_path),
        "resume_path": str(pdf_path) if pdf_path.is_file() else None,
        "preview_path": str(preview_path) if preview_path.is_file() else None,
        "validation_path": str(validation_path),
        "compiler_path": str(compiler) if compiler else None,
        "compiler_return_code": compiler_return_code,
        "compiler_evidence_sha256": hashlib.sha256(compiler_output.encode()).hexdigest(),
        "overflow": overflow,
        "skills_distinct_count": sum(len(values) for values in composition["selection"]["skills"].values()),
        "owner_confirmation_needed": composition["selection"].get("owner_confirmation_needed", []),
        "errors": errors,
        "vision_inspection_required": True,
        "vision_contract": {
            "selection_sha256": file_sha256(selection_output),
            "preview_sha256": file_sha256(preview_path) if preview_path.is_file() else None,
            "inspected_preview_path": str(preview_path) if preview_path.is_file() else None,
            "required_result_fields": ["schema_version", "passed", "obvious_defects", "selection_sha256", "preview_sha256", "inspected_preview_path"],
        },
        **geometry,
    }
    _write_json(validation_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and render a canonical Chiron resume manifest")
    parser.add_argument("command", choices=("contract", "check", "render"))
    parser.add_argument("--bank", type=Path, default=DEFAULT_BANK_PATH)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--role", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "contract":
        result = tailor_contract(role=args.role, description=args.description, bank_path=args.bank, template_path=args.template, profile_path=args.profile)
    else:
        if args.manifest is None:
            raise SystemExit("--manifest is required for check and render")
        raw = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.command == "check":
            result = validate_manifest(raw, role=args.role, description=args.description, bank_path=args.bank, template_path=args.template, profile_path=args.profile)
            result = {key: value for key, value in result.items() if key != "source"}
        else:
            if args.output_dir is None:
                raise SystemExit("--output-dir is required for render")
            result = render_agent_manifest(
                selection_path=args.manifest,
                role=args.role,
                description=args.description,
                output_dir=args.output_dir,
                bank_path=args.bank,
                template_path=args.template,
                profile_path=args.profile,
            )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
