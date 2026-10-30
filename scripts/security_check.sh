#!/usr/bin/env bash
# Sprint 6 (Member 6, items 6.15 / 6.16): the platform's security checks in one command; part of check_sprint.sh.
#   scripts/security_check.sh            # all checks; writes reports/security-<date>.md
#   scripts/security_check.sh --offline  # skip the dependency audits (they download the advisory databases)
exec uv run --no-project --python 3.11 "$(dirname "$0")/security_check.py" "$@"
