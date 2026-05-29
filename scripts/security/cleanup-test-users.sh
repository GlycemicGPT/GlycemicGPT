#!/usr/bin/env bash
#
# Purge throwaway accounts left behind by the security scripts
# (test-auth-flows.py, fuzz-api.py, test-data-isolation.py). Those scripts are
# meant to run against the ephemeral glycemicgpt-test stack, but if they are
# ever pointed at the persistent dev stack (SECURITY_TEST_ALLOW_DEV=1) the
# users they create accumulate in the dev DB and saturate the schedulers'
# per-user discovery queries.
#
# Targets ONLY the known security-test email prefixes, so real users (and
# unrelated @example.com fixtures) are left untouched.
#
# Usage:
#   scripts/security/cleanup-test-users.sh
#   COMPOSE_PROJECT_NAME=glycemicgpt-test scripts/security/cleanup-test-users.sh
#
set -euo pipefail

DB_USER="${POSTGRES_USER:-glycemicgpt}"
DB_NAME="${POSTGRES_DB:-glycemicgpt}"

# Match each script's generated prefix exactly (see _make_*_email helpers):
#   sectest_<uuid>@example.com   (test-auth-flows.py)
#   fuzz_<uuid>@example.com       (fuzz-api.py)
#   dyntest_<uuid>@example.com    (test-data-isolation.py)
# The '_' after each prefix is a literal underscore, so escape it -- in a SQL
# LIKE pattern an unescaped '_' is a single-char wildcard.
SQL="DELETE FROM users WHERE
  email LIKE 'sectest\_%@example.com' ESCAPE '\'
  OR email LIKE 'fuzz\_%@example.com' ESCAPE '\'
  OR email LIKE 'dyntest\_%@example.com' ESCAPE '\';"

echo "Purging security-test users (sectest_/fuzz_/dyntest_) from ${DB_NAME}..."
docker compose exec -T db psql -U "${DB_USER}" -d "${DB_NAME}" -c "${SQL}"
echo "Done."
