from __future__ import annotations

from pathlib import Path

from telegram_bot_new.skill_library import build_skill_instruction, list_installed_skills, resolve_skill_id, resolve_skill_ids


def _write_demo_skill(root: Path) -> None:
    skill_dir = root / "demo-skill"
    rules_dir = skill_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: demo description
---

Use this skill for demo tasks.

- [rules/animations.md](rules/animations.md)
- [rules/audio.md](rules/audio.md)
""",
        encoding="utf-8",
    )
    (rules_dir / "animations.md").write_text("# Animations\nUse spring() and interpolate().\n", encoding="utf-8")
    (rules_dir / "audio.md").write_text("# Audio\nUse audio trimming APIs.\n", encoding="utf-8")


def test_list_installed_skills_and_resolve(tmp_path: Path, monkeypatch) -> None:
    _write_demo_skill(tmp_path)
    monkeypatch.setenv("BOT_SKILLS_DIR", str(tmp_path))

    skills = list_installed_skills()
    assert len(skills) == 1
    assert skills[0].skill_id == "demo-skill"
    assert "demo description" in skills[0].description
    assert resolve_skill_id("demo-skill") == "demo-skill"
    assert resolve_skill_ids(name_or_ids="demo-skill,demo-skill") == (["demo-skill"], [])


def test_build_skill_instruction_includes_rule_content(tmp_path: Path, monkeypatch) -> None:
    _write_demo_skill(tmp_path)
    monkeypatch.setenv("BOT_SKILLS_DIR", str(tmp_path))

    instruction = build_skill_instruction(skill_id="demo-skill", prompt="add animation to title")
    assert instruction is not None
    assert "[Skill:demo-skill]" in instruction
    assert "[Rule:rules/animations.md]" in instruction
    assert "spring()" in instruction


def test_build_skill_instruction_supports_multiple_skills(tmp_path: Path, monkeypatch) -> None:
    _write_demo_skill(tmp_path)
    other_dir = tmp_path / "audio-skill"
    rules_dir = other_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (other_dir / "SKILL.md").write_text(
        """---
name: audio-skill
description: audio tweaks
---

Use this skill for audio tasks.

- [rules/audio.md](rules/audio.md)
""",
        encoding="utf-8",
    )
    (rules_dir / "audio.md").write_text("# Audio\nNormalize volume.\n", encoding="utf-8")
    monkeypatch.setenv("BOT_SKILLS_DIR", str(tmp_path))

    instruction = build_skill_instruction(skill_id="demo-skill,audio-skill", prompt="add animation and audio")
    assert instruction is not None
    assert "[Skill:demo-skill]" in instruction
    assert "[Skill:audio-skill]" in instruction
    assert "Normalize volume." in instruction
