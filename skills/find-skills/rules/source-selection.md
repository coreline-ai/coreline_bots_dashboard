# Source Selection Rule

## Goal

Find candidate skills from `skills.sh` / Skills CLI and collect enough metadata to validate trustworthiness.

## Preferred discovery commands

- `npx skills find <query>`
- `npx skills add <owner/repo> --list` (list-only mode, no install)

## Required metadata per candidate

- Skill name and unique slug/id
- Latest version and release/update date
- Download count
- Popularity indicators (likes/stars/trending rank/reviews if available)
- Publisher/author identity
- Repository URL (official source)
- License
- Checksums/signatures (if provided)

## Selection policy

- Prefer candidates that expose:
  - clear source repository,
  - recent update history,
  - transparent changelog,
  - clear license.
- De-prioritize entries with missing author/source/license.
- Reject candidates with suspicious naming that imitates popular skills.

## Multi-source confirmation

Before installation, verify key fields (name/version/repo/publisher) from at least 2 data points:

1. `skills.sh` listing/detail page
2. Source repository release/tags (or package registry page if applicable)

If mismatch exists, mark as `metadata_mismatch` and block installation.
