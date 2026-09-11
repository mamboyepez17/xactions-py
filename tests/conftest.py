"""Config común de tests: sin refresh GraphQL en red real."""

import os

os.environ.setdefault("XACTIONS_NO_GQL_REFRESH", "1")
