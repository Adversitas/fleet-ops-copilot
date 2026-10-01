import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion import build_ontology


@pytest.fixture(scope="session", autouse=True)
def fresh_db():
    """Rebuild data/fleet.db from the raw sources once per test run."""
    build_ontology.build()
