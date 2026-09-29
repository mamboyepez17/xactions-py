"""Shared test config: no real-network GraphQL refresh, no writes to the real ~/.xactions."""

import os
import tempfile

os.environ.setdefault("XACTIONS_NO_GQL_REFRESH", "1")

# Module-level defaults (caps, drafts, watch state, GraphQL cache, tracking DB)
# are computed at import time from these variables, so they must be set before
# any test imports xactions. Otherwise the suite charges the developer's real
# daily write caps and eventually trips them.
_home = tempfile.mkdtemp(prefix="xactions-test-home-")
os.environ["XACTIONS_HOME"] = _home
os.environ["XACTIONS_DB"] = os.path.join(_home, "xactions.db")
