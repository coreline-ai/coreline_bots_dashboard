---
name: find-skills
description: Discover and install skills from skills.sh using npx skills, with mandatory stability, security, integrity, and malware gates before any installation.
---

# Find Skills (skills.sh Integrated)

Use this skill when the user asks:
- "find a skill for X"
- "is there a skill that can do X"
- "install a skill for X"
- "how do I extend agent capability for X"

Primary source analyzed and integrated:
- `https://skills.sh/vercel-labs/skills/find-skills`
- Skills CLI: `npx skills`

This local version keeps the upstream discovery flow and adds strict enterprise safety gates.

## Unified workflow

1. Clarify task intent and keywords.
2. Discover candidates:
- `npx skills find <query>`
- Optional listing only: `npx skills add <owner/repo> --list`
3. Collect metadata from skills.sh + source repo.
4. Evaluate stability/popularity.
5. Evaluate security/integrity/malware.
6. Install only if all gates pass.
7. Run smoke checks and provide audit report.

If any gate fails, do **not** install.

## Mandatory rule order

Read and apply these files in order:

1. [rules/source-selection.md](rules/source-selection.md)
2. [rules/stability-gates.md](rules/stability-gates.md)
3. [rules/security-gates.md](rules/security-gates.md)
4. [rules/integrity-and-virus-scan.md](rules/integrity-and-virus-scan.md)
5. [rules/install-flow.md](rules/install-flow.md)
6. [rules/fallback-and-reporting.md](rules/fallback-and-reporting.md)

## Hard constraints

- Prefer official repository source linked by skills.sh.
- Never execute installation before security checks.
- Never install when evidence is missing/inconclusive.
- Always keep evidence: URL, version, checksums, scanner output, popularity signals.

## Project integration notes

- Local bot runtime loads skills from `./skills` (or `BOT_SKILLS_DIR`).
- After installation, verify with:
  - `/skills`
  - `/skill find-skills`
