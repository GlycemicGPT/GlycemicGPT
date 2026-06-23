#!/usr/bin/env bash
# Planning-ID gate
# ----------------
# Fails when a PR's *added* lines introduce internal BMAD planning identifiers
# (`Story <n.n>`, `AC<nn>`, `locked decision N`, `LOCKED #N`) into committed
# source under `apps/` or `plugins/`. These belong in the gitignored planning
# artifacts -- never in shipped code, comments, docstrings, or test names.
#
# Usage:
#   scripts/ci/check-planning-ids.sh <base-ref> <head-ref>
#
# Scans only the ADDED lines of the `base...head` diff, so a pre-existing token
# in unchanged code can never fail an innocent PR -- only the PR that introduces
# one is flagged. Restricted to source extensions where the leak has recurred.
#
# Exit 0 = clean. Exit 1 = leaks found (the offending file + lines are printed).
set -euo pipefail

BASE_REF="${1:?usage: check-planning-ids.sh <base-ref> <head-ref>}"
HEAD_REF="${2:?usage: check-planning-ids.sh <base-ref> <head-ref>}"

# High-signal BMAD planning tokens. Diff-scoped, so a rare legitimate match in
# unchanged code never trips the gate; a contributor who hits a false positive
# simply rephrases the comment.
PATTERN='Story [0-9]+\.[0-9]+|\bAC[0-9]{1,2}\b|[Ll]ocked [Dd]ecision [0-9]|LOCKED #[0-9]'

# Source extensions where the leak has recurred (code/tests, not docs/config).
EXT_RE='\.(py|ts|tsx|js|jsx|kt|java|sh)$'

mapfile -t FILES < <(
  git diff --name-only --diff-filter=d "${BASE_REF}...${HEAD_REF}" -- 'apps/' 'plugins/' \
    | grep -E "${EXT_RE}" || true
)

found=0
findings=""
for f in "${FILES[@]}"; do
  [ -z "${f}" ] && continue
  # Added lines only ('+' lines, excluding the '+++' file header).
  hits=$(
    git diff "${BASE_REF}...${HEAD_REF}" -- "${f}" \
      | grep -E '^\+' | grep -vE '^\+\+\+' \
      | grep -E "${PATTERN}" || true
  )
  if [ -n "${hits}" ]; then
    found=1
    findings="${findings}${f}:"$'\n'"$(printf '%s\n' "${hits}" | sed 's/^+/    /')"$'\n'
  fi
done

if [ "${found}" -eq 1 ]; then
  echo "FAILED: internal planning identifiers found in committed source."
  echo "(Story <n.n> / AC<nn> / locked decision N belong in the gitignored"
  echo " planning artifacts, not shipped code.)"
  echo ""
  printf '%s' "${findings}"
  echo ""
  echo "Fix: remove the Story / AC / locked-decision tokens from the comments,"
  echo "docstrings, and test names -- keep the descriptive prose."
  exit 1
fi

echo "PASSED: no internal planning identifiers in the diff."
