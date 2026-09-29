"""Shared test config: no real-network GraphQL refresh."""

import os

os.environ.setdefault("XACTIONS_NO_GQL_REFRESH", "1")
