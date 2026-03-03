from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class SkillInfo:
    skill_id: str
    name: str
    description: str
    path: Path
    entry_file: Path


def _skills_root() -> Path:
    configured = (os.getenv("BOT_SKILLS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "skills").resolve()


def _extract_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return ({}, text)
    end = text.find("\n---\n", 4)
    if end < 0:
        return ({}, text)
    raw = text[4:end]
    rest = text[end + 5 :]
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip()
    return (meta, rest)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def list_installed_skills() -> list[SkillInfo]:
    root = _skills_root()
    if not root.exists() or not root.is_dir():
        return []
    items: list[SkillInfo] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue
        raw = _read_text(skill_md)
        meta, _ = _extract_frontmatter(raw)
        name = str(meta.get("name") or child.name)
        description = str(meta.get("description") or "").strip()
        items.append(
            SkillInfo(
                skill_id=child.name,
                name=name,
                description=description,
                path=child,
                entry_file=skill_md,
            )
        )
    return items


def resolve_skill_id(name_or_id: str) -> str | None:
    resolved, _unknown = resolve_skill_ids(name_or_ids=name_or_id)
    if not resolved:
        return None
    return resolved[0]


def _normalize_skill_tokens(name_or_ids: str | Iterable[str]) -> list[str]:
    if isinstance(name_or_ids, str):
        raw_items = re.split(r"[,\s]+", name_or_ids)
    else:
        raw_items = [str(item or "") for item in name_or_ids]
    return [item.strip() for item in raw_items if str(item or "").strip()]


def resolve_skill_ids(*, name_or_ids: str | Iterable[str]) -> tuple[list[str], list[str]]:
    installed = list_installed_skills()
    if not installed:
        return ([], _normalize_skill_tokens(name_or_ids))

    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for skill in installed:
        by_id[skill.skill_id.lower()] = skill.skill_id
        by_name[skill.name.lower()] = skill.skill_id

    resolved: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for token in _normalize_skill_tokens(name_or_ids):
        key = token.lower()
        canonical = by_id.get(key) or by_name.get(key)
        if canonical is None:
            unknown.append(token)
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        resolved.append(canonical)
    return (resolved, unknown)


def _extract_rule_links(skill_body: str) -> list[str]:
    matches = re.findall(r"\((rules/[^)]+\.md)\)", skill_body, flags=re.IGNORECASE)
    seen: set[str] = set()
    ordered: list[str] = []
    for match in matches:
        normalized = match.strip().replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _score_rule_path(rule_path: str, prompt: str) -> int:
    lowered_prompt = prompt.lower()
    stem = Path(rule_path).stem.replace("-", " ").lower()
    score = 0
    for token in stem.split():
        if len(token) < 3:
            continue
        if token in lowered_prompt:
            score += 2
    if score == 0 and any(token in lowered_prompt for token in ("video", "animation", "react", "remotion")):
        score = 1
    return score


def build_skill_instruction(
    *,
    skill_id: str | Iterable[str] | None,
    prompt: str,
    max_chars: int = 14000,
) -> str | None:
    if not skill_id:
        return None

    resolved_ids, _unknown = resolve_skill_ids(name_or_ids=skill_id)
    if not resolved_ids:
        return None

    by_id = {row.skill_id: row for row in list_installed_skills()}
    sections: list[str] = []
    for resolved_id in resolved_ids:
        target = by_id.get(resolved_id)
        if target is None:
            continue

        raw_skill = _read_text(target.entry_file)
        _, skill_body = _extract_frontmatter(raw_skill)
        if not skill_body.strip():
            continue

        links = _extract_rule_links(skill_body)
        ranked = sorted(
            links,
            key=lambda path: _score_rule_path(path, prompt),
            reverse=True,
        )

        # Include only top matched rule files to keep prompt size bounded.
        selected_rule_paths = [path for path in ranked if _score_rule_path(path, prompt) > 0][:4]
        if not selected_rule_paths:
            selected_rule_paths = links[:2]

        chunks: list[str] = [
            f"[Skill:{target.name}]",
            skill_body.strip(),
        ]
        for rel_path in selected_rule_paths:
            rule_path = (target.path / rel_path).resolve()
            if not rule_path.exists() or not rule_path.is_file():
                continue
            content = _read_text(rule_path).strip()
            if not content:
                continue
            chunks.append(f"\n[Rule:{rel_path}]\n{content}")
        sections.append("\n\n".join(chunks).strip())

    if not sections:
        return None

    combined = "\n\n".join(sections).strip()
    if len(combined) > max_chars:
        return f"{combined[: max_chars - 3].rstrip()}..."
    return combined
