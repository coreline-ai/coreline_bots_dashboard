#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${ROOT_DIR}/skills"
INSTALLER="${HOME}/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py"
TARGET_NAME="remotion-best-practices"

if [[ ! -f "${INSTALLER}" ]]; then
  echo "skill-installer not found: ${INSTALLER}" >&2
  exit 1
fi

if [[ -d "${DEST_DIR}/${TARGET_NAME}" ]]; then
  echo "Destination already exists: ${DEST_DIR}/${TARGET_NAME}" >&2
  echo "Remove it first if you want to reinstall." >&2
  exit 1
fi

python3 "${INSTALLER}" \
  --repo remotion-dev/skills \
  --path skills/remotion \
  --dest "${DEST_DIR}" \
  --name "${TARGET_NAME}"

echo "Synced skill to ${DEST_DIR}/${TARGET_NAME}"
