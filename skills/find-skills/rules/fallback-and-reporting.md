# Fallback and Reporting Rule

## When direct search is blocked/unavailable

If `skills.sh` or `npx skills find` cannot be accessed (network block, rate limit, timeout):

1. Report the access limitation explicitly.
2. Do not bypass site protections aggressively.
3. Request/derive candidate identifiers from user input.
4. Validate candidates via official source repositories and registries.
5. Keep the same security and integrity gates.

## Report template (required)

For every installation attempt, provide:

- Candidate identity: name/version/source URL
- Popularity metrics: downloads + other signals
- Stability decision: pass/fail + score
- Integrity result: pass/fail + hash evidence
- Malware/security result: pass/fail + scan summary
- Final decision: installed/rejected/deferred
- If rejected: exact blocking reason and remediation steps

## Conservative default

When evidence is incomplete, decision must be `deferred` or `rejected`, not installed.
