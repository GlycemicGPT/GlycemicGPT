"""Shared safety guard for security scripts that register throwaway users.

The security scripts (``test-auth-flows.py``, ``fuzz-api.py``,
``test-data-isolation.py``) create throwaway accounts
(``sectest_*`` / ``fuzz_*`` / ``dyntest_*`` ``@example.com``) via the API. They
are meant to run ONLY against the ephemeral ``glycemicgpt-test`` stack (port
8001), which CI tears down -- and its volume with it -- after every run.

Pointed at the persistent dev stack (port 8000), they leak those users into the
dev database, where they accumulate across runs and eventually saturate the
schedulers' per-user discovery queries (e.g. the Medtronic Connect sync tick).
This guard aborts before the first registration when the target looks like a
persistent (non-ephemeral) stack, unless ``SECURITY_TEST_ALLOW_DEV=1`` is set
explicitly. When overriding, run ``scripts/security/cleanup-test-users.sh``
afterward to purge the leftovers.

Imported as a sibling module (``from _ephemeral_guard import ...``): the
security scripts are always run directly (``python scripts/security/x.py``),
never imported as a package, so the script's own directory is on
``sys.path[0]`` and the bare import resolves. Do not "fix" it into a relative
(``from .``) import -- the scripts are not a package.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

# Ports that belong to the persistent dev stack (API / web / Postgres). The
# ephemeral test stack runs the API on 8001, so any of these signals misuse.
# NOTE: this is a block-list of the one signal that actually distinguishes the
# stacks (8001 vs 8000) -- it catches the real mistake (API_URL pointed at the
# dev port), not every conceivable target. A reverse-proxied dev host on 80/443
# would slip through; that is an accepted limitation for a dev-only tool.
_PERSISTENT_PORTS = {8000, 3000, 5432}

_OVERRIDE_ENV = "SECURITY_TEST_ALLOW_DEV"


def assert_ephemeral_target(api_url: str) -> None:
    """Abort if ``api_url`` points at the persistent dev stack.

    No-ops when ``SECURITY_TEST_ALLOW_DEV=1`` is set, so an intentional dev run
    is still possible (paired with the cleanup script).
    """
    if os.environ.get(_OVERRIDE_ENV) == "1":
        return

    port = urlparse(api_url).port
    if port is not None and port in _PERSISTENT_PORTS:
        sys.exit(
            f"Refusing to register throwaway test users against {api_url!r}: "
            f"port {port} is the persistent dev stack. These scripts are for "
            "the ephemeral glycemicgpt-test stack (API on port 8001), which is "
            "torn down after use. Leaking users into the dev DB accumulates "
            "rows that saturate scheduler discovery queries.\n"
            f"To override intentionally: set {_OVERRIDE_ENV}=1 and run "
            "scripts/security/cleanup-test-users.sh afterward."
        )
