#!/bin/bash
set -e

# Set CLAUDE_BIN to the latest versioned binary (exported for web_cli.py)
CLAUDE_VERSIONS_DIR="/opt/claude/versions"
if [ -d "$CLAUDE_VERSIONS_DIR" ]; then
  CLAUDE_VERSION=$(ls "$CLAUDE_VERSIONS_DIR" | sort -V | tail -1)
  if [ -n "$CLAUDE_VERSION" ] && [ -f "${CLAUDE_VERSIONS_DIR}/${CLAUDE_VERSION}" ]; then
    export CLAUDE_BIN="${CLAUDE_VERSIONS_DIR}/${CLAUDE_VERSION}"
    echo "[entrypoint] Claude Code: ${CLAUDE_VERSION}"
  else
    echo "[entrypoint] WARNING: no claude binary found in ${CLAUDE_VERSIONS_DIR}"
  fi
else
  echo "[entrypoint] WARNING: ${CLAUDE_VERSIONS_DIR} not mounted"
fi

exec "$@"
