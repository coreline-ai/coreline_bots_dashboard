# Safe Install Flow Rule

## Install sequence

1. Candidate discovery (metadata only, no install)
2. Candidate listing with `--list` when needed
3. Stability/popularity gate pass
4. Security + integrity + malware gate pass
5. Dry-run install in isolated workspace
6. Post-install smoke check
7. Promote to active skills directory

## Recommended command stages

- Search:
  - `npx skills find <query>`
- List skills in source repo only:
  - `npx skills add <owner/repo> --list`
- Install after all gates pass:
  - `npx skills add <owner/repo>@<skill> -g -y`

## Isolation requirements

- Use temporary isolated directory for dry-run.
- Do not overwrite existing production skill directly.
- Keep rollback path:
  - backup existing version,
  - install new version as staged,
  - switch only after smoke check success.

## Smoke checks

- Validate `SKILL.md` exists and is parseable.
- Validate linked rule files exist.
- Validate required entry points/metadata keys.
- Ensure no unexpected executable modifications outside target directory.

## Promotion policy

- Atomic move/swap after all checks pass.
- On failure, restore previous version and report reason.
