#!/usr/bin/env bash
# Install a git pre-commit hook that runs the fast checks (run this yourself inside your git clone).
# Usage: scripts/install_git_hook.sh [member-number]     e.g. scripts/install_git_hook.sh 3
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
member="${1:-}"
hook="$root/.git/hooks/pre-commit"
args="--fast"
[ -n "$member" ] && args="$args --member $member --git-staged"
cat > "$hook" <<HOOK
#!/usr/bin/env bash
# installed by scripts/install_git_hook.sh — skip once with: git commit --no-verify
exec "$root/scripts/precommit.sh" $args
HOOK
chmod +x "$hook"
echo "pre-commit hook installed: $hook (runs: scripts/precommit.sh $args)"
