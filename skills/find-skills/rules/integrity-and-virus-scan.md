# Integrity and Malware Scan Rule

## Goal

Verify downloaded artifacts are authentic and malware-free before install.

## Required process

1. Stage download in quarantine directory
- Example: `/tmp/skills-staging/<skill-id>/<version>/`
- Never install directly from download output.

2. Integrity verification
- Prefer publisher-provided checksum/signature.
- Compute hash locally (`sha256` at minimum).
- If expected checksum/signature is unavailable, mark `integrity_unverified` and block auto-install.

3. Malware scan
- Run at least one malware scanner over staged files.
- If available, run two independent scanners and compare outcomes.

4. Result handling
- Any positive detection -> reject.
- Scanner error/unavailable -> reject auto-install (manual override only).

## Evidence to record

- Download URL, timestamp
- Artifact filename/size
- SHA256 digest
- Scanner names/versions
- Scanner output summary
