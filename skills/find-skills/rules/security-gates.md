# Security Gates

## Goal

Prevent installation of unsafe or supply-chain-compromised skills.

## Mandatory checks (all required)

1. Provenance check
- Confirm author/publisher consistency between listing and source.
- Validate repository ownership and history (no sudden ownership hijack patterns).

2. Static risk scan
- Inspect files for high-risk patterns:
  - obfuscated scripts,
  - hidden network download-and-execute flows,
  - suspicious shell invocation chains,
  - credential exfiltration patterns.

3. Dependency risk scan (if package manifest exists)
- Run ecosystem audit tools where possible.
- Flag critical/high CVEs as install blockers.

4. Permission and runtime behavior review
- Detect if the skill requires excessive privileges.
- Reject skills demanding broad filesystem/network access without clear justification.

## Auto-block conditions

- Known malicious indicators from scanner output
- Unsigned binaries from unknown source with no integrity metadata
- Obfuscated installer with no readable source
- Hardcoded secrets, token grabbers, or remote command payloads

